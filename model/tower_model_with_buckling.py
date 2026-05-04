from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

try:
    from .tower_model import OpenSeesModel
except ImportError:  # pragma: no cover
    from tower_model import OpenSeesModel


def _load_tag_manager() -> Any:
    tag_manager_path = Path(__file__).resolve().parents[1] / "util" / "preprocess" / "tag_manager.py"
    spec = importlib.util.spec_from_file_location("otw_preprocess_tag_manager", tag_manager_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 TagManager: {tag_manager_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TagManager


TagManager = _load_tag_manager()


class OpenSeesModelWithBuckling(OpenSeesModel):
    """Tower model variant that splits every frame member into four segments.

    Original SAP node tags are preserved. Generated intermediate node tags use
    the next available node number, while all other OpenSees tags are allocated
    through :class:`TagManager`.
    """

    def __init__(
        self,
        *args: Any,
        member_divisions: int = 4,
        **kwargs: Any,
    ) -> None:
        if int(member_divisions) < 2:
            raise ValueError("member_divisions 必须大于等于 2。")
        super().__init__(*args, **kwargs)
        self.member_divisions = int(member_divisions)
        self.tag_manager = TagManager(
            start_tag={
                "material": 1,
                "section": 1,
                "transf": 1,
                "integration": 1,
                "element": 1,
            }
        )
        self.split_node_map: dict[int, dict[str, Any]] = {}
        self.segmented_connectivity_map: dict[int, dict[str, Any]] = {}
        self.element_segment_map: dict[int, list[int]] = {}
        self._next_generated_node_tag: int | None = None

    def _allocate_node_tag(self) -> int:
        # Node tags are intentionally kept outside TagManager per buckling model
        # convention: SAP node ids remain stable and generated nodes continue
        # after the largest existing node id.
        if self._next_generated_node_tag is None:
            self._next_generated_node_tag = max(self.node_map, default=0) + 1
        while self._next_generated_node_tag in self.node_map:
            self._next_generated_node_tag += 1
        node_tag = self._next_generated_node_tag
        self._next_generated_node_tag += 1
        return node_tag

    def _write_current_nodes(self) -> None:
        rows = [
            {
                "node_tag": int(node_tag),
                "x": float(record["x"]),
                "y": float(record["y"]),
                "z": float(record["z"]),
            }
            for node_tag, record in sorted(self.node_map.items())
        ]
        self._write_csv(self.output_dir / "nodes.csv", rows, ["node_tag", "x", "y", "z"])

    def _build_segmented_connectivity(self) -> dict[int, dict[str, Any]]:
        self._ensure_model_builder()
        ops = self._ops()
        if not self.node_map:
            self.node()
        if self.segmented_connectivity_map:
            return self.segmented_connectivity_map

        connectivity = self._parse_element_connectivity()
        self.split_node_map = {}
        self.element_segment_map = {}
        split_node_rows: list[dict[str, Any]] = []
        segment_rows: list[dict[str, Any]] = []

        for original_ele_tag, item in connectivity.items():
            node_i_tag = int(item["node_i"])
            node_j_tag = int(item["node_j"])
            node_i = self.node_map[node_i_tag]
            node_j = self.node_map[node_j_tag]
            segment_nodes = [node_i_tag]

            for station_index in range(1, self.member_divisions):
                ratio = station_index / self.member_divisions
                node_tag = self._allocate_node_tag()
                x = float(node_i["x"]) + (float(node_j["x"]) - float(node_i["x"])) * ratio
                y = float(node_i["y"]) + (float(node_j["y"]) - float(node_i["y"])) * ratio
                z = float(node_i["z"]) + (float(node_j["z"]) - float(node_i["z"])) * ratio
                ops.node(node_tag, x, y, z)
                node_record = {
                    "node_tag": node_tag,
                    "x": x,
                    "y": y,
                    "z": z,
                    "original_element_tag": original_ele_tag,
                    "station_index": station_index,
                    "station_ratio": ratio,
                }
                self.node_map[node_tag] = node_record
                self.split_node_map[node_tag] = node_record
                split_node_rows.append(node_record)
                segment_nodes.append(node_tag)
            segment_nodes.append(node_j_tag)

            self.element_segment_map[original_ele_tag] = []
            for segment_index in range(1, self.member_divisions + 1):
                element_tag = self.tag_manager.get_next_tag(namespace="element")
                segment_record = {
                    "element_tag": element_tag,
                    "original_element_tag": original_ele_tag,
                    "segment_index": segment_index,
                    "node_i": segment_nodes[segment_index - 1],
                    "node_j": segment_nodes[segment_index],
                    "parent_node_i": node_i_tag,
                    "parent_node_j": node_j_tag,
                }
                self.segmented_connectivity_map[element_tag] = segment_record
                self.element_segment_map[original_ele_tag].append(element_tag)
                segment_rows.append(segment_record)

        self._write_current_nodes()
        self._write_csv(
            self.output_dir / "split_nodes.csv",
            split_node_rows,
            [
                "node_tag",
                "x",
                "y",
                "z",
                "original_element_tag",
                "station_index",
                "station_ratio",
            ],
        )
        self._write_csv(
            self.output_dir / "element_segments.csv",
            segment_rows,
            [
                "element_tag",
                "original_element_tag",
                "segment_index",
                "node_i",
                "node_j",
                "parent_node_i",
                "parent_node_j",
            ],
        )
        return self.segmented_connectivity_map

    def material(self) -> dict[int, dict[str, Any]]:
        self._ensure_model_builder()
        ops = self._ops()

        basic_records = {
            self._parse_key_values(line)["Material"]: self._parse_key_values(line)
            for line in self._table_lines("MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES")
        }
        steel_records = [
            self._parse_key_values(line)
            for line in self._table_lines("MATERIAL PROPERTIES 03A - STEEL DATA")
        ]

        rows: list[dict[str, Any]] = []
        self.material_name_to_tag = {}
        self.material_tag_map = {}
        for steel_data in steel_records:
            tag = self.tag_manager.get_next_tag(namespace="material")
            name = steel_data["Material"]
            basic = basic_records.get(name, {})
            fy = float(steel_data["Fy"]) * 1e6
            e0 = float(basic.get("E1", 2.1e11))
            g = float(basic.get("G12", e0 / (2 * (1 + float(basic.get("U12", 0.3))))))
            nu = float(basic.get("U12", 0.3))
            density = float(basic.get("UnitMass", 0.0))
            ops.uniaxialMaterial("Steel01", tag, fy, e0, self.steel01_b)
            record = {
                "mat_tag": tag,
                "material_name": name,
                "fy": fy,
                "e0": e0,
                "g": g,
                "nu": nu,
                "density": density,
                "b": self.steel01_b,
                "ops_type": "Steel01",
            }
            self.material_name_to_tag[name] = tag
            self.material_tag_map[tag] = record
            rows.append(record)
        self._write_csv(
            self.output_dir / "materials.csv",
            rows,
            ["mat_tag", "material_name", "fy", "e0", "g", "nu", "density", "b", "ops_type"],
        )
        return self.material_tag_map

    def section(self) -> dict[int, dict[str, Any]]:
        self._ensure_model_builder()
        if not self.material_tag_map:
            self.material()
        SecPlain, mesh_geom = self._section_mesh_tools()

        section_properties = self._frame_section_properties()
        assignments = self._element_section_assignments()
        unique_sections: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for assignment in assignments.values():
            key = (assignment["section_name"], assignment["material_name"])
            if key not in seen:
                unique_sections.append(key)
                seen.add(key)

        rows: list[dict[str, Any]] = []
        fiber_rows: list[dict[str, Any]] = []
        self.section_name_to_tag = {}
        self.section_tag_map = {}
        self.section_fiber_map = {}

        ops = self._ops()
        for section_name, material_name in unique_sections:
            section_tag = self.tag_manager.get_next_tag(namespace="section")
            if material_name not in self.material_name_to_tag and "Q" in section_name:
                material_name = f"Q{section_name.split('Q')[-1]}"
            mat_tag = self.material_name_to_tag[material_name]
            section_prop = section_properties.get(section_name, {})
            outline = self._l_section_outline(section_name)
            sec = SecPlain()
            sec.add_outline(outline)
            sec.mesh(mesh_size=self.mesh_size)
            sec.centring()
            gj = self.material_tag_map[mat_tag]["g"] * section_prop.get("tors_const", 0.0)
            ops.section("Fiber", section_tag, "-GJ", gj if gj > 0 else 1.0)
            fiber_centers, fiber_areas, sec_prop = mesh_geom(sec.mesh_obj)
            for centers, areas in zip(fiber_centers, fiber_areas):
                for center, area in zip(centers, areas):
                    ops.fiber(center[0], center[1], area, mat_tag)

            section_record = {
                "section_tag": section_tag,
                "section_name": section_name,
                "material_name": material_name,
                "mat_tag": mat_tag,
                "shape": section_prop.get("shape", "Angle"),
                "mesh_size": self.mesh_size,
                "area": sec_prop["area"],
                "centroid_y": sec_prop["center"][0],
                "centroid_z": sec_prop["center"][1],
                "gj": gj if gj > 0 else 1.0,
            }
            self.section_name_to_tag[section_name] = section_tag
            self.section_tag_map[section_tag] = section_record
            self.section_fiber_map[section_tag] = []
            rows.append(section_record)

            fiber_id = 1
            for centers, areas in zip(fiber_centers, fiber_areas):
                for center, area in zip(centers, areas):
                    fiber_record = {
                        "section_tag": section_tag,
                        "fiber_id": fiber_id,
                        "y": center[0],
                        "z": center[1],
                        "area": area,
                        "mat_tag": mat_tag,
                    }
                    self.section_fiber_map[section_tag].append(fiber_record)
                    fiber_rows.append(fiber_record)
                    fiber_id += 1

        self._write_csv(
            self.output_dir / "sections.csv",
            rows,
            [
                "section_tag",
                "section_name",
                "material_name",
                "mat_tag",
                "shape",
                "mesh_size",
                "area",
                "centroid_y",
                "centroid_z",
                "gj",
            ],
        )
        self._write_csv(
            self.output_dir / "section_fibers.csv",
            fiber_rows,
            ["section_tag", "fiber_id", "y", "z", "area", "mat_tag"],
        )
        return self.section_tag_map

    def geomtransf(self) -> dict[int, dict[str, Any]]:
        self._ensure_model_builder()
        ops = self._ops()
        connectivity = self._build_segmented_connectivity()

        rows: list[dict[str, Any]] = []
        self.transf_map = {}
        for element_tag, item in connectivity.items():
            node_i = self.node_map[item["node_i"]]
            node_j = self.node_map[item["node_j"]]
            vec_x, vec_y, vec_z = self._geom_transf_vector(node_i, node_j)
            transf_tag = self.tag_manager.get_next_tag(namespace="transf")
            ops.geomTransf("Linear", transf_tag, vec_x, vec_y, vec_z)
            record = {
                "transf_tag": transf_tag,
                "element_tag": element_tag,
                "original_element_tag": item["original_element_tag"],
                "segment_index": item["segment_index"],
                "vec_x": vec_x,
                "vec_y": vec_y,
                "vec_z": vec_z,
            }
            self.transf_map[element_tag] = record
            rows.append(record)
        self._write_csv(
            self.output_dir / "geomtransf.csv",
            rows,
            [
                "transf_tag",
                "element_tag",
                "original_element_tag",
                "segment_index",
                "vec_x",
                "vec_y",
                "vec_z",
            ],
        )
        return self.transf_map

    def element(self) -> dict[int, dict[str, Any]]:
        self._ensure_model_builder()
        ops = self._ops()
        if not self.section_name_to_tag:
            self.section()
        if not self.transf_map:
            self.geomtransf()

        connectivity = self._build_segmented_connectivity()
        assignments = self._element_section_assignments()
        rows: list[dict[str, Any]] = []
        integration_rows: list[dict[str, Any]] = []
        self.integration_map = {}
        self.element_map = {}

        for element_tag, item in connectivity.items():
            original_ele_tag = int(item["original_element_tag"])
            assign = assignments[original_ele_tag]
            section_tag = self.section_name_to_tag[assign["section_name"]]
            transf_tag = self.transf_map[element_tag]["transf_tag"]
            integration_tag = self.tag_manager.get_next_tag(namespace="integration")
            ops.beamIntegration(
                self.beam_integration_type,
                integration_tag,
                section_tag,
                self.num_intgr_pts,
            )
            ops.element(
                "dispBeamColumn",
                element_tag,
                item["node_i"],
                item["node_j"],
                transf_tag,
                integration_tag,
            )
            integration_record = {
                "integration_tag": integration_tag,
                "element_tag": element_tag,
                "original_element_tag": original_ele_tag,
                "segment_index": item["segment_index"],
                "integration_type": self.beam_integration_type,
                "section_tag": section_tag,
                "num_intgr_pts": self.num_intgr_pts,
            }
            self.integration_map[integration_tag] = integration_record
            integration_rows.append(integration_record)
            record = {
                "element_tag": element_tag,
                "original_element_tag": original_ele_tag,
                "segment_index": item["segment_index"],
                "node_i": item["node_i"],
                "node_j": item["node_j"],
                "parent_node_i": item["parent_node_i"],
                "parent_node_j": item["parent_node_j"],
                "num_intgr_pts": self.num_intgr_pts,
                "section_tag": section_tag,
                "section_name": assign["section_name"],
                "material_name": assign["material_name"],
                "mat_tag": self.section_tag_map[section_tag]["mat_tag"],
                "transf_tag": transf_tag,
                "integration_tag": integration_tag,
                "integration_type": self.beam_integration_type,
            }
            self.element_map[element_tag] = record
            rows.append(record)

        self._write_csv(
            self.output_dir / "beam_integrations.csv",
            integration_rows,
            [
                "integration_tag",
                "element_tag",
                "original_element_tag",
                "segment_index",
                "integration_type",
                "section_tag",
                "num_intgr_pts",
            ],
        )
        self._write_csv(
            self.output_dir / "elements.csv",
            rows,
            [
                "element_tag",
                "original_element_tag",
                "segment_index",
                "node_i",
                "node_j",
                "parent_node_i",
                "parent_node_j",
                "num_intgr_pts",
                "section_tag",
                "section_name",
                "material_name",
                "mat_tag",
                "transf_tag",
                "integration_tag",
                "integration_type",
            ],
        )
        return self.element_map

    def model_tower(self) -> dict[str, Any]:
        self.node()
        self.fix()
        self.mass()
        self.material()
        self.section()
        self.geomtransf()
        self.element()
        return {
            "nodes": self.node_map,
            "split_nodes": self.split_node_map,
            "fixes": self.fix_map,
            "masses": self.mass_map,
            "materials": self.material_tag_map,
            "sections": self.section_tag_map,
            "geomtransf": self.transf_map,
            "integrations": self.integration_map,
            "elements": self.element_map,
            "element_segments": self.element_segment_map,
            "tag_summary": self.tag_manager.summary(),
        }

    def get_element_record(self, element_tag: int) -> dict[str, Any]:
        if int(element_tag) in self.element_map:
            return self.element_map[int(element_tag)]
        rows = self._read_csv_rows(self.output_dir / "elements.csv")
        for row in rows:
            if int(row["element_tag"]) == int(element_tag):
                return {
                    "element_tag": int(row["element_tag"]),
                    "original_element_tag": int(row.get("original_element_tag", row["element_tag"])),
                    "segment_index": int(row.get("segment_index", 1)),
                    "node_i": int(row["node_i"]),
                    "node_j": int(row["node_j"]),
                    "parent_node_i": int(row.get("parent_node_i", row["node_i"])),
                    "parent_node_j": int(row.get("parent_node_j", row["node_j"])),
                    "num_intgr_pts": int(row["num_intgr_pts"]),
                    "section_tag": int(row["section_tag"]),
                    "section_name": row["section_name"],
                    "material_name": row["material_name"],
                    "mat_tag": int(row["mat_tag"]),
                    "transf_tag": int(row["transf_tag"]),
                    "integration_tag": int(row["integration_tag"]),
                    "integration_type": row["integration_type"],
                }
        raise KeyError(f"未找到单元 {element_tag}")

    def get_original_element_segments(self, original_element_tag: int) -> list[dict[str, Any]]:
        if not self.element_map:
            self.element()
        segment_tags = self.element_segment_map.get(int(original_element_tag), [])
        return [self.element_map[tag] for tag in segment_tags]


OpenSeesBucklingModel = OpenSeesModelWithBuckling
TowerModelWithBuckling = OpenSeesModelWithBuckling

if __name__ == "__main__":
    model = TowerModelWithBuckling("Source/Z30103A6.s2k")
    model.model_tower()