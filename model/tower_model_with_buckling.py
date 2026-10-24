from __future__ import annotations

import math
from typing import Any

try:
    from .tower_model import OpenSeesModel, TagManager
except ImportError:  # pragma: no cover
    from tower_model import OpenSeesModel, TagManager


class OpenSeesModelWithBuckling(OpenSeesModel):
    """Tower model variant that splits every frame member into segments.

    The original SAP ids are kept as local ids. Actual OpenSees tags are
    allocated through the shared :class:`TagManager`, so multiple tower instances
    can be placed in one domain without node/element/material collisions.
    """

    def __init__(
        self,
        *args: Any,
        random_disp_ratio: float = 0.01,
        member_divisions: int = 4,
        imperfection_seed: int | None = None,
        **kwargs: Any,
    ) -> None:
        if int(member_divisions) < 2:
            raise ValueError("member_divisions 必须大于等于 2。")
        super().__init__(*args, **kwargs)
        self.random_disp_ratio = float(random_disp_ratio)
        self.member_divisions = int(member_divisions)
        self.imperfection_seed = imperfection_seed
        if imperfection_seed is None:
            self._imperfection_random = None
        else:
            import random

            self._imperfection_random = random.Random(int(imperfection_seed))
        self._frame_element_tag_namespace = "source_element"
        self.split_node_map: dict[int, dict[str, Any]] = {}
        self.segmented_connectivity_map: dict[int, dict[str, Any]] = {}
        self.element_segment_map: dict[int, list[int]] = {}

    def _allocate_node_tag(self) -> int:
        node_tag = self.tag_manager.get_next_tag(namespace="node")
        while node_tag in self.node_map:
            node_tag = self.tag_manager.get_next_tag(namespace="node")
        return node_tag

    def _write_current_nodes(self) -> None:
        rows = [
            {
                "tower_id": record.get("tower_id", self.tower_id),
                "node_tag": int(node_tag),
                "local_node_tag": record.get("local_node_tag", ""),
                "x": float(record["x"]),
                "y": float(record["y"]),
                "z": float(record["z"]),
            }
            for node_tag, record in sorted(self.node_map.items())
        ]
        self._write_csv(
            self.output_dir / "nodes.csv",
            rows,
            ["tower_id", "node_tag", "local_node_tag", "x", "y", "z"],
        )

    # 计算element上分割点坐标
    def _get_breakpoint_coord(
        self,
        node_i: dict[str, Any],
        node_j: dict[str, Any],
        num: int,
        imperfection_vector: tuple[float, float, float] | None = None,
    ):
        node_i_x = node_i["x"]
        node_i_y = node_i["y"]
        node_i_z = node_i["z"]
        node_j_x = node_j["x"]
        node_j_y = node_j["y"]
        node_j_z = node_j["z"]
        ratio = num / self.member_divisions
        x = float(node_i_x) + (float(node_j_x) - float(node_i_x)) * ratio
        y = float(node_i_y) + (float(node_j_y) - float(node_i_y)) * ratio
        z = float(node_i_z) + (float(node_j_z) - float(node_i_z)) * ratio
        # 所有内部节点沿同一横向方向组成半正弦初弯曲。这样改变
        # member_divisions 只改变离散精度，不会改变缺陷峰值位置和形状。
        if imperfection_vector is None:
            imperfection_vector = self._add_rand_disp(
                x,
                y,
                z,
                node_i_x,
                node_i_y,
                node_i_z,
                node_j_x,
                node_j_y,
                node_j_z,
            )
        shape_factor = math.sin(math.pi * ratio)
        x += imperfection_vector[0] * shape_factor
        y += imperfection_vector[1] * shape_factor
        z += imperfection_vector[2] * shape_factor
        return x, y, z
    
    def _add_rand_disp(
        self,
        x, y, z,
        node_i_x, node_i_y, node_i_z,
        node_j_x, node_j_y, node_j_z,
    ):
        import random
        import math

        
        # 杆件方向向量
        vx = node_j_x - node_i_x
        vy = node_j_y - node_i_y
        vz = node_j_z - node_i_z

        length = math.sqrt(vx ** 2 + vy ** 2 + vz ** 2)
        disp = length * self.random_disp_ratio
        if length == 0:
            raise ValueError("杆件两端节点重合，无法确定杆件方向。")

        # 杆件方向单位向量
        ux = vx / length
        uy = vy / length
        uz = vz / length

        # 选一个不与杆件方向平行的辅助向量
        # 如果杆件不接近 z 轴，就用 z 轴作为辅助向量
        if abs(uz) < 0.9:
            ax, ay, az = 0.0, 0.0, 1.0
        else:
            ax, ay, az = 1.0, 0.0, 0.0

        # e1 = u × a
        e1x = uy * az - uz * ay
        e1y = uz * ax - ux * az
        e1z = ux * ay - uy * ax

        e1_len = math.sqrt(e1x ** 2 + e1y ** 2 + e1z ** 2)

        e1x /= e1_len
        e1y /= e1_len
        e1z /= e1_len

        # e2 = u × e1
        e2x = uy * e1z - uz * e1y
        e2y = uz * e1x - ux * e1z
        e2z = ux * e1y - uy * e1x

        # 在垂直于杆件的平面内随机取一个方向
        generator = self._imperfection_random or random
        theta = generator.uniform(0, 2 * math.pi)

        disp_x = disp * (math.cos(theta) * e1x + math.sin(theta) * e2x)
        disp_y = disp * (math.cos(theta) * e1y + math.sin(theta) * e2y)
        disp_z = disp * (math.cos(theta) * e1z + math.sin(theta) * e2z)

        return disp_x, disp_y, disp_z

    def _build_segmented_connectivity(self) -> dict[int, dict[str, Any]]:
        self._ensure_model_builder()
        ops = self.ops
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
            imperfection_vector = self._add_rand_disp(
                0.5 * (float(node_i["x"]) + float(node_j["x"])),
                0.5 * (float(node_i["y"]) + float(node_j["y"])),
                0.5 * (float(node_i["z"]) + float(node_j["z"])),
                node_i["x"],
                node_i["y"],
                node_i["z"],
                node_j["x"],
                node_j["y"],
                node_j["z"],
            )

            for station_index in range(1, self.member_divisions):
                ratio = station_index / self.member_divisions
                node_tag = self._allocate_node_tag()
                x, y, z = self._get_breakpoint_coord(
                    node_i,
                    node_j,
                    station_index,
                    imperfection_vector,
                )
                ops.node(node_tag, x, y, z)
                node_record = {
                    "tower_id": self.tower_id,
                    "node_tag": node_tag,
                    "local_node_tag": "",
                    "x": x,
                    "y": y,
                    "z": z,
                    "original_element_tag": original_ele_tag,
                    "original_frame_name": item.get("frame_name", ""),
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
                    "tower_id": self.tower_id,
                    "element_tag": element_tag,
                    "original_element_tag": original_ele_tag,
                    "original_frame_name": item.get("frame_name", ""),
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
                "tower_id",
                "node_tag",
                "local_node_tag",
                "x",
                "y",
                "z",
                "original_element_tag",
                "original_frame_name",
                "station_index",
                "station_ratio",
            ],
        )
        self._write_csv(
            self.output_dir / "element_segments.csv",
            segment_rows,
            [
                "tower_id",
                "element_tag",
                "original_element_tag",
                "original_frame_name",
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
        ops = self.ops

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
            ops.uniaxialMaterial("Steel02", tag, fy, e0, self.steel01_b, 20, 0.925, 0.15, 0.0005, 0.01, 0.0005, 0.01)
            record = {
                "mat_tag": tag,
                "material_name": name,
                "fy": fy,
                "e0": e0,
                "g": g,
                "nu": nu,
                "density": density,
                "b": self.steel01_b,
                "ops_type": "Steel02",
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

        ops = self.ops
        for section_name, material_name in unique_sections:
            section_tag = self.tag_manager.get_next_tag(namespace="section")
            if material_name not in self.material_name_to_tag and "Q" in section_name:
                material_name = f"Q{section_name.split('Q')[-1]}"
            mat_tag = self.material_name_to_tag[material_name]
            section_prop = section_properties.get(section_name, {})
            gj = self.material_tag_map[mat_tag]["g"] * section_prop.get("tors_const", 0.0)
            ops.section("Fiber", section_tag, "-GJ", gj if gj > 0 else 1.0)

            # 使用 OpenSeesPy 自带 rect patch 划分等边 L 角钢截面。长肢方向使用
            # long_edge_segments，厚度方向使用 short_edge_segments，并保持
            # (zJ-zI)/(yJ-yI) 为正以生成正的 fiber area。
            fibers, sec_prop = self._l_section_rect_patches(section_name, mat_tag)
            for patch in sec_prop["patches"]:
                ops.patch(
                    "rect",
                    mat_tag,
                    patch["num_y"],
                    patch["num_z"],
                    patch["y_i"],
                    patch["z_i"],
                    patch["y_j"],
                    patch["z_j"],
                )

            section_record = {
                "section_tag": section_tag,
                "section_name": section_name,
                "material_name": material_name,
                "mat_tag": mat_tag,
                "shape": section_prop.get("shape", "Angle"),
                "long_edge_segments": self.long_edge_segments,
                "short_edge_segments": self.short_edge_segments,
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
            for fiber in fibers:
                fiber_record = {
                    "section_tag": section_tag,
                    "fiber_id": fiber_id,
                    "y": fiber["y"],
                    "z": fiber["z"],
                    "area": fiber["area"],
                    "mat_tag": fiber["mat_tag"],
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
                "long_edge_segments",
                "short_edge_segments",
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
        ops = self.ops
        connectivity = self._build_segmented_connectivity()

        rows: list[dict[str, Any]] = []
        self.transf_map = {}
        for element_tag, item in connectivity.items():
            node_i = self.node_map[item["node_i"]]
            node_j = self.node_map[item["node_j"]]
            vec_x, vec_y, vec_z = self._geom_transf_vector(node_i, node_j)
            transf_tag = self.tag_manager.get_next_tag(namespace="transf")
            ops.geomTransf("Corotational", transf_tag, vec_x, vec_y, vec_z)
            record = {
                "tower_id": self.tower_id,
                "transf_tag": transf_tag,
                "element_tag": element_tag,
                "original_element_tag": item["original_element_tag"],
                "original_frame_name": item.get("original_frame_name", ""),
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
                "tower_id",
                "transf_tag",
                "element_tag",
                "original_element_tag",
                "original_frame_name",
                "segment_index",
                "vec_x",
                "vec_y",
                "vec_z",
            ],
        )
        return self.transf_map

    def element(self) -> dict[int, dict[str, Any]]:
        self._ensure_model_builder()
        ops = self.ops
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
            original_frame_name = item.get("original_frame_name", assign.get("frame_name", ""))
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
                "tower_id": self.tower_id,
                "integration_tag": integration_tag,
                "element_tag": element_tag,
                "original_element_tag": original_ele_tag,
                "original_frame_name": original_frame_name,
                "segment_index": item["segment_index"],
                "integration_type": self.beam_integration_type,
                "section_tag": section_tag,
                "num_intgr_pts": self.num_intgr_pts,
            }
            self.integration_map[integration_tag] = integration_record
            integration_rows.append(integration_record)
            record = {
                "tower_id": self.tower_id,
                "element_tag": element_tag,
                "original_element_tag": original_ele_tag,
                "original_frame_name": original_frame_name,
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
                "tower_id",
                "integration_tag",
                "element_tag",
                "original_element_tag",
                "original_frame_name",
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
                "tower_id",
                "element_tag",
                "original_element_tag",
                "original_frame_name",
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
            "frame_tags": self.frame_name_to_element_tag,
            "tag_maps": self.tag_maps(),
            "tower_id": self.tower_id,
            "origin": self.origin,
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
                    "original_frame_name": row.get("original_frame_name", ""),
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
        resolved_tag = self.resolve_element_tag(original_element_tag)
        segment_tags = self.element_segment_map.get(resolved_tag, [])
        return [self.element_map[tag] for tag in segment_tags]


OpenSeesBucklingModel = OpenSeesModelWithBuckling
TowerModelWithBuckling = OpenSeesModelWithBuckling

if __name__ == "__main__":
    model = TowerModelWithBuckling("Source/Z30103A6.s2k")
    model.model_tower()
    
