from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any


class OpenSeesModel:
    """Parse SAP2000 `.s2k` data and build an OpenSeesPy model with queryable mappings."""

    def __init__(
        self,
        s2k_path: str | Path,
        num_intgr_pts: int = 8,
        long_edge_segments: int = 8,
        short_edge_segments: int = 2,
        steel01_b: float = 0.05,
        beam_integration_type: str = "Legendre",
        output_dir: str | Path | None = None,
        node_to_fix_path: str | Path | None = None,
    ) -> None:
        self.s2k_path = Path(s2k_path)
        self.base_dir = Path(__file__).resolve().parent
        self.output_dir = Path(output_dir) if output_dir else self.base_dir / ".output"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.node_to_fix_path = (
            Path(node_to_fix_path)
            if node_to_fix_path
            else self.base_dir / ".config" / "node_to_fix.json"
        )
        self.num_intgr_pts = num_intgr_pts
        self.long_edge_segments = self._positive_segment_count(long_edge_segments, "long_edge_segments")
        self.short_edge_segments = self._positive_segment_count(short_edge_segments, "short_edge_segments")
        self.steel01_b = steel01_b
        self.beam_integration_type = beam_integration_type
        self._lines = self.s2k_path.read_text(encoding="utf-8").splitlines()
        self._model_built = False

        # 这些映射既服务当前建模，也会被落盘后供后续分析阶段直接复用。
        self.node_map: dict[int, dict[str, Any]] = {}
        self.fix_map: dict[int, dict[str, Any]] = {}
        self.mass_map: dict[int, dict[str, Any]] = {}
        self.material_name_to_tag: dict[str, int] = {}
        self.material_tag_map: dict[int, dict[str, Any]] = {}
        self.section_name_to_tag: dict[str, int] = {}
        self.section_tag_map: dict[int, dict[str, Any]] = {}
        self.section_fiber_map: dict[int, list[dict[str, Any]]] = {}
        self.integration_map: dict[int, dict[str, Any]] = {}
        self.element_map: dict[int, dict[str, Any]] = {}
        self.transf_map: dict[int, dict[str, Any]] = {}


        try:
            import openseespy.opensees as ops
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "当前环境未安装 openseespy，无法执行建模命令。请先安装 openseespy 后再调用建模函数。"
            ) from exc
        self.ops = ops

    @staticmethod
    def _section_mesh_tools():
        try:
            from .SecMesh import SecPlain, mesh_geom
        except ImportError:
            try:  # pragma: no cover
                from SecMesh import SecPlain, mesh_geom
            except ImportError as exc:  # pragma: no cover
                raise ImportError(
                    "截面纤维划分依赖 SecMesh 及其相关库，请确认 matplotlib、pygmsh、shapely 等依赖已安装。"
                ) from exc
        return SecPlain, mesh_geom

    def _ensure_model_builder(self, ndm: int = 3, ndf: int = 6) -> None:
        if self._model_built:
            return
        ops = self.ops
        ops.model("basic", "-ndm", ndm, "-ndf", ndf)
        self._model_built = True

    @staticmethod
    def _parse_key_values(line: str) -> dict[str, str]:
        matches = re.findall(r'([A-Za-z0-9_]+)=(".*?"|\S+)', line)
        parsed: dict[str, str] = {}
        for key, value in matches:
            parsed[key] = value.strip('"')
        return parsed

    def _table_lines(self, table_name: str) -> list[str]:
        marker = f'TABLE:  "{table_name}"'
        start = -1
        for index, line in enumerate(self._lines):
            if marker in line:
                start = index + 1
                break
        if start < 0:
            raise ValueError(f"在 {self.s2k_path} 中未找到表格: {table_name}")

        records: list[str] = []
        current = ""
        for line in self._lines[start:]:
            stripped = line.strip()
            if line.startswith("TABLE:") or stripped == "END TABLE DATA":
                break
            if not stripped:
                if current:
                    records.append(current.strip())
                    current = ""
                continue
            # SAP2000 的长记录会用 "_" 续行，这里先拼回单条记录再做键值解析。
            if stripped.endswith("_"):
                current += stripped[:-1] + " "
            else:
                current += stripped
                records.append(current.strip())
                current = ""
        if current:
            records.append(current.strip())
        return records

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            if rows:
                writer.writerows(rows)

    @staticmethod
    def _read_csv_rows(path: Path) -> list[dict[str, str]]:
        if not path.exists():
            return []
        with path.open("r", newline="", encoding="utf-8") as file:
            return list(csv.DictReader(file))

    def initialize_model(self, ndm: int = 3, ndf: int = 6) -> None:
        self._ensure_model_builder(ndm=ndm, ndf=ndf)

    def node(self) -> dict[int, dict[str, Any]]:
        self._ensure_model_builder()
        ops = self.ops
        rows: list[dict[str, Any]] = []
        self.node_map = {}
        for line in self._table_lines("JOINT COORDINATES"):
            data = self._parse_key_values(line)
            node_tag = int(data["Joint"])
            x = float(data["GlobalX"])
            y = float(data["GlobalY"])
            z = float(data["GlobalZ"])
            ops.node(node_tag, x, y, z)
            record = {"node_tag": node_tag, "x": x, "y": y, "z": z}
            self.node_map[node_tag] = record
            rows.append(record)
        # 保留一份节点坐标映射，后续几何变换和结果查询都会用到。
        self._write_csv(self.output_dir / "nodes.csv", rows, ["node_tag", "x", "y", "z"])
        return self.node_map

    def _load_node_to_fix(self) -> dict[int, list[int]]:
        if not self.node_to_fix_path.exists():
            return {}
        config = json.loads(self.node_to_fix_path.read_text(encoding="utf-8"))
        if isinstance(config, dict) and all(isinstance(value, list) for value in config.values()):
            return {int(tag): [int(item) for item in dofs] for tag, dofs in config.items()}
        if isinstance(config, list):
            return {int(tag): [1, 1, 1, 1, 1, 1] for tag in config}
        node_tags = config.get("node_tags", config.get("nodes", []))
        dofs = [int(item) for item in config.get("fixity", config.get("dofs", [1, 1, 1, 1, 1, 1]))]
        return {int(tag): dofs[:] for tag in node_tags}

    def fix(self, node_tags: list[int] | None = None, dofs: list[int] | tuple[int, ...] | None = None) -> dict[int, dict[str, Any]]:
        self._ensure_model_builder()
        ops = self.ops
        if not self.node_map:
            self.node()
        default_fix_map = self._load_node_to_fix()

        rows: list[dict[str, Any]] = []
        self.fix_map = {}
        if node_tags is not None:
            fixity = list(dofs) if dofs is not None else [1, 1, 1, 1, 1, 1]
            fix_assignments = {int(node_tag): fixity[:] for node_tag in node_tags}
        elif dofs is not None:
            fixity = list(dofs)
            fix_assignments = {node_tag: fixity[:] for node_tag in default_fix_map}
        else:
            fix_assignments = default_fix_map

        for node_tag, fixity in fix_assignments.items():
            ops.fix(int(node_tag), *fixity)
            record = {
                "node_tag": int(node_tag),
                "ux": fixity[0],
                "uy": fixity[1],
                "uz": fixity[2],
                "rx": fixity[3],
                "ry": fixity[4],
                "rz": fixity[5],
            }
            self.fix_map[int(node_tag)] = record
            rows.append(record)
        self._write_csv(
            self.output_dir / "fixes.csv",
            rows,
            ["node_tag", "ux", "uy", "uz", "rx", "ry", "rz"],
        )
        return self.fix_map

    def mass(self) -> dict[int, dict[str, Any]]:
        self._ensure_model_builder()
        ops = self.ops
        rows: list[dict[str, Any]] = []
        self.mass_map = {}
        for line in self._table_lines("ASSEMBLED JOINT MASSES"):
            data = self._parse_key_values(line)
            node_tag = int(data["Joint"])
            mx = float(data["U1"])
            my = float(data["U2"])
            mz = float(data["U3"])
            ops.mass(node_tag, mx, my, mz, 0.0, 0.0, 0.0)
            record = {
                "node_tag": node_tag,
                "mx": mx,
                "my": my,
                "mz": mz,
                "mrx": 0.0,
                "mry": 0.0,
                "mrz": 0.0,
            }
            self.mass_map[node_tag] = record
            rows.append(record)
        self._write_csv(
            self.output_dir / "masses.csv",
            rows,
            ["node_tag", "mx", "my", "mz", "mrx", "mry", "mrz"],
        )
        return self.mass_map

    def material(self) -> dict[int, dict[str, Any]]:
        self._ensure_model_builder()
        ops = self.ops

        # SAP 把钢材基本力学参数和屈服信息拆在两张表里，这里合并后再生成 OpenSees 材料。
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
        for tag, steel_data in enumerate(steel_records, start=1):
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

    @staticmethod
    def _l_section_dimensions(section_name: str) -> tuple[float, float]:
        match = re.fullmatch(r"L(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)Q[\w.-]+", section_name)
        if not match:
            raise ValueError(f"当前仅支持角钢截面，无法识别截面名: {section_name}")
        length = float(match.group(1)) * 0.001
        thickness = float(match.group(2)) * 0.001
        return length, thickness

    @classmethod
    def _l_section_outline(cls, section_name: str) -> list[tuple[float, float]]:
        length, thickness = cls._l_section_dimensions(section_name)
        return [
            (0.0, 0.0),
            (length, 0.0),
            (length, thickness),
            (thickness, thickness),
            (thickness, length),
            (0.0, length),
        ]

    @staticmethod
    def _l_section_centroid(length: float, thickness: float) -> tuple[float, float]:
        area = 2 * length * thickness - thickness**2
        centroid = (
            length * thickness * (length / 2)
            + thickness * (length - thickness) * (thickness / 2)
        ) / area
        return centroid, centroid

    @staticmethod
    def _positive_segment_count(value: int, name: str) -> int:
        segments = int(value)
        if segments <= 0:
            raise ValueError(f"{name} 必须为正整数")
        return segments

    @staticmethod
    def _rect_patch_fibers(
        y_i: float,
        z_i: float,
        y_j: float,
        z_j: float,
        num_y: int,
        num_z: int,
        mat_tag: int,
    ) -> list[dict[str, Any]]:
        dy = (y_j - y_i) / num_y
        dz = (z_j - z_i) / num_z
        area = dy * dz
        fibers: list[dict[str, Any]] = []
        for i in range(num_y):
            y = y_i + (i + 0.5) * dy
            for j in range(num_z):
                z = z_i + (j + 0.5) * dz
                fibers.append({"y": y, "z": z, "area": area, "mat_tag": mat_tag})
        return fibers

    def _l_section_rect_patches(
        self,
        section_name: str,
        mat_tag: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        length, thickness = self._l_section_dimensions(section_name)
        centroid_y, centroid_z = self._l_section_centroid(length, thickness)
        long_div = self.long_edge_segments
        short_div = self.short_edge_segments

        # 角钢截面由角部方块、水平肢、竖直肢三个矩形 patch 组成。
        # 长肢方向使用 long_edge_segments，厚度方向使用 short_edge_segments；
        # 角部方块为短边区域，两个方向均使用 short_edge_segments。
        # OpenSees 的 rect patch 要求 (zJ-zI)/(yJ-yI) 为正；这里所有坐标均按
        # yI < yJ 且 zI < zJ 传入，保证生成正的 fiber area。
        patches = [
            {
                "num_y": short_div,
                "num_z": short_div,
                "y_i": -centroid_y,
                "z_i": -centroid_z,
                "y_j": thickness - centroid_y,
                "z_j": thickness - centroid_z,
            },
            {
                "num_y": long_div,
                "num_z": short_div,
                "y_i": thickness - centroid_y,
                "z_i": -centroid_z,
                "y_j": length - centroid_y,
                "z_j": thickness - centroid_z,
            },
            {
                "num_y": short_div,
                "num_z": long_div,
                "y_i": -centroid_y,
                "z_i": thickness - centroid_z,
                "y_j": thickness - centroid_y,
                "z_j": length - centroid_z,
            },
        ]

        area = 2 * length * thickness - thickness**2
        fibers: list[dict[str, Any]] = []
        for patch in patches:
            fibers.extend(
                self._rect_patch_fibers(
                    patch["y_i"],
                    patch["z_i"],
                    patch["y_j"],
                    patch["z_j"],
                    patch["num_y"],
                    patch["num_z"],
                    mat_tag,
                )
            )
        sec_prop = {"area": area, "center": (0.0, 0.0, 0.0), "patches": patches}
        return fibers, sec_prop

    def _frame_section_properties(self) -> dict[str, dict[str, Any]]:
        properties: dict[str, dict[str, Any]] = {}
        for line in self._table_lines("FRAME SECTION PROPERTIES 01 - GENERAL"):
            data = self._parse_key_values(line)
            name = data.get("SectionName")
            if not name:
                continue
            properties[name] = {
                "section_name": name,
                "material_name": data.get("Material", ""),
                "shape": data.get("Shape", ""),
                "area": float(data.get("Area", 0.0)),
                "tors_const": float(data.get("TorsConst", 0.0)),
            }
        return properties

    def _element_section_assignments(self) -> dict[int, dict[str, Any]]:
        assignments: dict[int, dict[str, Any]] = {}
        for line in self._table_lines("FRAME SECTION ASSIGNMENTS"):
            data = self._parse_key_values(line)
            ele_tag = int(data["Frame"])
            section_name = data.get("AnalSect", "")
            material_name = self._parse_key_values(line).get("MatProp", "")
            if not material_name and "Q" in section_name:
                material_name = f"Q{section_name.split('Q')[-1]}"
            assignments[ele_tag] = {
                "element_tag": ele_tag,
                "section_name": section_name,
                "material_name": material_name,
            }
        return assignments

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

        for sec_tag, (section_name, material_name) in enumerate(unique_sections, start=1):
            if material_name not in self.material_name_to_tag and "Q" in section_name:
                material_name = f"Q{section_name.split('Q')[-1]}"
            mat_tag = self.material_name_to_tag[material_name]
            section_prop = section_properties.get(section_name, {})
            gj = self.material_tag_map[mat_tag]["g"] * section_prop.get("tors_const", 0.0)
            self.ops.section("Fiber", sec_tag, "-GJ", gj if gj > 0 else 1.0)

            # 使用 OpenSeesPy 自带 rect patch 划分等边 L 角钢截面。几何先从外角点
            # 平移到形心坐标系，再拆为角部方块、水平肢、竖直肢三个不重叠矩形。
            fibers, sec_prop = self._l_section_rect_patches(section_name, mat_tag)
            for patch in sec_prop["patches"]:
                self.ops.patch(
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
                "section_tag": sec_tag,
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
            self.section_name_to_tag[section_name] = sec_tag
            self.section_tag_map[sec_tag] = section_record
            self.section_fiber_map[sec_tag] = []
            rows.append(section_record)

            fiber_id = 1
            # 单独导出纤维坐标和面积，后续截面响应提取时可直接按 section_tag 查询。
            for fiber in fibers:
                fiber_record = {
                    "section_tag": sec_tag,
                    "fiber_id": fiber_id,
                    "y": fiber["y"],
                    "z": fiber["z"],
                    "area": fiber["area"],
                    "mat_tag": fiber["mat_tag"],
                }
                self.section_fiber_map[sec_tag].append(fiber_record)
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

    @staticmethod
    def _geom_transf_vector(i_coord: dict[str, Any], j_coord: dict[str, Any], degree: float = 0.0) -> tuple[float, float, float]:
        from math import cos, pi, sin, sqrt

        dx = i_coord["x"] - j_coord["x"]
        dy = i_coord["y"] - j_coord["y"]
        dz = i_coord["z"] - j_coord["z"]
        lx, ly, lz = dx, dy, dz
        # 局部 x 轴沿杆件方向；当杆件竖直时，参考轴改用全局 x 轴以避免叉乘退化。
        if dx == 0.0 and dy == 0.0:
            ref_y = (1.0, 0.0, 0.0)
            loc_z = (
                ly * ref_y[2] - lz * ref_y[1],
                lz * ref_y[0] - lx * ref_y[2],
                lx * ref_y[1] - ly * ref_y[0],
            )
        else:
            global_z = (0.0, 0.0, 1.0)
            loc_z = (
                ly * global_z[2] - lz * global_z[1],
                lz * global_z[0] - lx * global_z[2],
                lx * global_z[1] - ly * global_z[0],
            )
        rot = degree / 180.0 * pi
        cross_xz = (
            ly * loc_z[2] - lz * loc_z[1],
            lz * loc_z[0] - lx * loc_z[2],
            lx * loc_z[1] - ly * loc_z[0],
        )
        loc_z_rot = tuple(loc_z[i] * cos(rot) + cross_xz[i] * sin(rot) for i in range(3))
        norm = sqrt(sum(item * item for item in loc_z_rot))
        return tuple(item / norm for item in loc_z_rot)

    def geomtransf(self) -> dict[int, dict[str, Any]]:
        self._ensure_model_builder()
        ops = self.ops
        if not self.node_map:
            self.node()
        if not self.element_map:
            raw_elements = self._parse_element_connectivity()
        else:
            raw_elements = {
                tag: {"element_tag": tag, "node_i": item["node_i"], "node_j": item["node_j"]}
                for tag, item in self.element_map.items()
            }

        rows: list[dict[str, Any]] = []
        self.transf_map = {}
        for ele_tag, item in raw_elements.items():
            node_i = self.node_map[item["node_i"]]
            node_j = self.node_map[item["node_j"]]
            vec_x, vec_y, vec_z = self._geom_transf_vector(node_i, node_j)
            ops.geomTransf("Corotational", ele_tag, vec_x, vec_y, vec_z)
            record = {
                "transf_tag": ele_tag,
                "element_tag": ele_tag,
                "vec_x": vec_x,
                "vec_y": vec_y,
                "vec_z": vec_z,
            }
            self.transf_map[ele_tag] = record
            rows.append(record)
        self._write_csv(
            self.output_dir / "geomtransf.csv",
            rows,
            ["transf_tag", "element_tag", "vec_x", "vec_y", "vec_z"],
        )
        return self.transf_map

    def _parse_element_connectivity(self) -> dict[int, dict[str, Any]]:
        connectivity: dict[int, dict[str, Any]] = {}
        for line in self._table_lines("CONNECTIVITY - FRAME"):
            data = self._parse_key_values(line)
            ele_tag = int(data["Frame"])
            connectivity[ele_tag] = {
                "element_tag": ele_tag,
                "node_i": int(data["JointI"]),
                "node_j": int(data["JointJ"]),
            }
        return connectivity

    def element(self) -> dict[int, dict[str, Any]]:
        self._ensure_model_builder()
        ops = self.ops
        if not self.section_name_to_tag:
            self.section()
        if not self.transf_map:
            self.geomtransf()

        connectivity = self._parse_element_connectivity()
        assignments = self._element_section_assignments()
        rows: list[dict[str, Any]] = []
        integration_rows: list[dict[str, Any]] = []
        self.integration_map = {}
        self.element_map = {}

        for ele_tag, item in connectivity.items():
            assign = assignments[ele_tag]
            section_tag = self.section_name_to_tag[assign["section_name"]]
            transf_tag = ele_tag
            integration_tag = ele_tag
            # 这里保持与原 Tcl 流程一致：单元号同时复用为几何变换号和积分号，便于追踪。
            ops.beamIntegration(
                self.beam_integration_type,
                integration_tag,
                section_tag,
                self.num_intgr_pts,
            )
            ops.element(
                "dispBeamColumn",
                ele_tag,
                item["node_i"],
                item["node_j"],
                transf_tag,
                integration_tag,
            )
            integration_record = {
                "integration_tag": integration_tag,
                "element_tag": ele_tag,
                "integration_type": self.beam_integration_type,
                "section_tag": section_tag,
                "num_intgr_pts": self.num_intgr_pts,
            }
            self.integration_map[integration_tag] = integration_record
            integration_rows.append(integration_record)
            record = {
                "element_tag": ele_tag,
                "node_i": item["node_i"],
                "node_j": item["node_j"],
                "num_intgr_pts": self.num_intgr_pts,
                "section_tag": section_tag,
                "section_name": assign["section_name"],
                "material_name": assign["material_name"],
                "mat_tag": self.section_tag_map[section_tag]["mat_tag"],
                "transf_tag": transf_tag,
                "integration_tag": integration_tag,
                "integration_type": self.beam_integration_type,
            }
            self.element_map[ele_tag] = record
            rows.append(record)

        self._write_csv(
            self.output_dir / "beam_integrations.csv",
            integration_rows,
            [
                "integration_tag",
                "element_tag",
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
                "node_i",
                "node_j",
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
            "fixes": self.fix_map,
            "masses": self.mass_map,
            "materials": self.material_tag_map,
            "sections": self.section_tag_map,
            "geomtransf": self.transf_map,
            "integrations": self.integration_map,
            "elements": self.element_map,
        }

    def modeltower(self) -> dict[str, Any]:
        return self.model_tower()

    def get_node_coord(self, node_tag: int, prefer_ops: bool = False) -> tuple[float, float, float]:
        if prefer_ops:
            try:
                # 如果模型还在 OpenSees 内存中，优先直接从 ops 里取实时坐标。
                coord = self.ops.nodeCoord(int(node_tag))
                return float(coord[0]), float(coord[1]), float(coord[2])
            except Exception:
                pass
        record = self.get_node_record(node_tag)
        return float(record["x"]), float(record["y"]), float(record["z"])

    def get_node_record(self, node_tag: int) -> dict[str, Any]:
        if int(node_tag) in self.node_map:
            return self.node_map[int(node_tag)]
        rows = self._read_csv_rows(self.output_dir / "nodes.csv")
        for row in rows:
            if int(row["node_tag"]) == int(node_tag):
                return {
                    "node_tag": int(row["node_tag"]),
                    "x": float(row["x"]),
                    "y": float(row["y"]),
                    "z": float(row["z"]),
                }
        raise KeyError(f"未找到节点 {node_tag}")

    def get_element_record(self, element_tag: int) -> dict[str, Any]:
        if int(element_tag) in self.element_map:
            return self.element_map[int(element_tag)]
        rows = self._read_csv_rows(self.output_dir / "elements.csv")
        for row in rows:
            if int(row["element_tag"]) == int(element_tag):
                return {
                    "element_tag": int(row["element_tag"]),
                    "node_i": int(row["node_i"]),
                    "node_j": int(row["node_j"]),
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

    def get_section_record(self, section_tag: int | None = None, section_name: str | None = None) -> dict[str, Any]:
        if section_tag is not None and int(section_tag) in self.section_tag_map:
            return self.section_tag_map[int(section_tag)]
        if section_name is not None and section_name in self.section_name_to_tag:
            return self.section_tag_map[self.section_name_to_tag[section_name]]

        rows = self._read_csv_rows(self.output_dir / "sections.csv")
        for row in rows:
            if section_tag is not None and int(row["section_tag"]) == int(section_tag):
                return {
                    "section_tag": int(row["section_tag"]),
                    "section_name": row["section_name"],
                    "material_name": row["material_name"],
                    "mat_tag": int(row["mat_tag"]),
                    "shape": row["shape"],
                    "long_edge_segments": int(row.get("long_edge_segments", self.long_edge_segments)),
                    "short_edge_segments": int(row.get("short_edge_segments", self.short_edge_segments)),
                    "area": float(row["area"]),
                    "centroid_y": float(row["centroid_y"]),
                    "centroid_z": float(row["centroid_z"]),
                    "gj": float(row["gj"]),
                }
            if section_name is not None and row["section_name"] == section_name:
                return {
                    "section_tag": int(row["section_tag"]),
                    "section_name": row["section_name"],
                    "material_name": row["material_name"],
                    "mat_tag": int(row["mat_tag"]),
                    "shape": row["shape"],
                    "long_edge_segments": int(row.get("long_edge_segments", self.long_edge_segments)),
                    "short_edge_segments": int(row.get("short_edge_segments", self.short_edge_segments)),
                    "area": float(row["area"]),
                    "centroid_y": float(row["centroid_y"]),
                    "centroid_z": float(row["centroid_z"]),
                    "gj": float(row["gj"]),
                }
        key = section_tag if section_tag is not None else section_name
        raise KeyError(f"未找到截面 {key}")

    def get_section_fibers(self, section_tag: int) -> list[dict[str, Any]]:
        if int(section_tag) in self.section_fiber_map:
            return self.section_fiber_map[int(section_tag)]
        rows = self._read_csv_rows(self.output_dir / "section_fibers.csv")
        result: list[dict[str, Any]] = []
        for row in rows:
            if int(row["section_tag"]) == int(section_tag):
                result.append(
                    {
                        "section_tag": int(row["section_tag"]),
                        "fiber_id": int(row["fiber_id"]),
                        "y": float(row["y"]),
                        "z": float(row["z"]),
                        "area": float(row["area"]),
                        "mat_tag": int(row["mat_tag"]),
                    }
                )
        return result

    def get_material_record(self, mat_tag: int | None = None, material_name: str | None = None) -> dict[str, Any]:
        if mat_tag is not None and int(mat_tag) in self.material_tag_map:
            return self.material_tag_map[int(mat_tag)]
        if material_name is not None and material_name in self.material_name_to_tag:
            return self.material_tag_map[self.material_name_to_tag[material_name]]

        rows = self._read_csv_rows(self.output_dir / "materials.csv")
        for row in rows:
            if mat_tag is not None and int(row["mat_tag"]) == int(mat_tag):
                return {
                    "mat_tag": int(row["mat_tag"]),
                    "material_name": row["material_name"],
                    "fy": float(row["fy"]),
                    "e0": float(row["e0"]),
                    "g": float(row["g"]),
                    "nu": float(row["nu"]),
                    "density": float(row["density"]),
                    "b": float(row["b"]),
                    "ops_type": row["ops_type"],
                }
            if material_name is not None and row["material_name"] == material_name:
                return {
                    "mat_tag": int(row["mat_tag"]),
                    "material_name": row["material_name"],
                    "fy": float(row["fy"]),
                    "e0": float(row["e0"]),
                    "g": float(row["g"]),
                    "nu": float(row["nu"]),
                    "density": float(row["density"]),
                    "b": float(row["b"]),
                    "ops_type": row["ops_type"],
                }
        key = mat_tag if mat_tag is not None else material_name
        raise KeyError(f"未找到材料 {key}")
