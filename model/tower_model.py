from __future__ import annotations

import csv
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

try:
    from util.preprocess.tag_manager import TagManager
except ImportError:  # pragma: no cover
    tag_manager_path = Path(__file__).resolve().parents[1] / "util" / "preprocess" / "tag_manager.py"
    spec = importlib.util.spec_from_file_location("otw_preprocess_tag_manager", tag_manager_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 TagManager: {tag_manager_path}")
    tag_manager_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tag_manager_module)
    TagManager = tag_manager_module.TagManager


class OpenSeesModel:
    """Parse SAP2000 `.s2k` data and build an OpenSeesPy model with queryable mappings."""

    _WIND_AREA_BANDS: tuple[dict[str, Any], ...] = (
        {"z_min": 0.0, "z_max": 3.2, "boundary_pair": (3.2, 3.2), "y_limit": -3.2, "y_inclusive": False},
        {"z_min": 3.2, "z_max": 6.8, "boundary_pair": (6.8, 6.8), "y_limit": -2.9, "y_inclusive": False},
        {"z_min": 6.8, "z_max": 9.0, "boundary_pair": (9.0, 9.0), "y_limit": -2.7, "y_inclusive": True},
        {"z_min": 9.0, "z_max": 13.2, "boundary_pair": (13.2, 13.2), "y_limit": -2.49, "y_inclusive": True},
        {"z_min": 13.2, "z_max": 17.4, "boundary_pair": (17.4, 17.4), "y_limit": -2.28, "y_inclusive": True},
        {"z_min": 17.4, "z_max": 21.6, "boundary_pair": (21.6, 21.6), "y_limit": -2.07, "y_inclusive": True},
        {"z_min": 21.6, "z_max": 24.0, "boundary_pair": (24.0, 24.0), "y_limit": -1.95, "y_inclusive": True},
        {"z_min": 24.0, "z_max": 27.0, "boundary_pair": (27.0, 27.0), "y_limit": -1.95, "y_inclusive": True},
        {"z_min": 27.0, "z_max": 30.0, "boundary_pair": (27.0, 30.0), "y_limit": -1.95, "y_inclusive": True},
        {"z_min": 30.0, "z_max": 33.0, "boundary_pair": (33.0, 33.0), "y_limit": -1.95, "y_inclusive": True},
        {"z_min": 33.0, "z_max": 36.4, "boundary_pair": (36.4, 36.4), "y_limit": -0.85, "y_inclusive": True},
        {"z_min": 37.0, "z_max": 39.6, "boundary_pair": (39.6, 39.6), "y_limit": -0.5, "y_inclusive": True},
    )

    def __init__(
        self,
        s2k_path: str | Path,
        num_intgr_pts: int = 6,
        long_edge_segments: int = 8,
        short_edge_segments: int = 1,
        steel01_b: float = 0.03,
        beam_integration_type: str = "Legendre",
        output_dir: str | Path | None = None,
        node_to_fix_path: str | Path | None = None,
        tower_id: str | None = None,
        origin: tuple[float, float, float] | list[float] | None = None,
        tag_manager: TagManager | None = None,
    ) -> None:
        self.s2k_path = Path(s2k_path)
        self.tower_id = str(tower_id) if tower_id is not None else self.s2k_path.stem
        self.origin = self._coerce_origin(origin)
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
        self._lines = self.s2k_path.read_text(encoding="gbk").splitlines()
        self._model_built = False
        self.tag_manager = tag_manager if tag_manager is not None else TagManager(
            start_tag={
                "node": 1,
                "material": 1,
                "section": 1,
                "transf": 1,
                "integration": 1,
                "element": 1,
                "source_element": 1,
            }
        )
        self._frame_element_tag_namespace = "element"
        self._element_tags_initialized = False

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
        self.wind_projected_area_map: dict[int, dict[str, Any]] = {}
        self.wind_area_by_band: dict[int, float] = {}
        self.frame_name_to_element_tag: dict[str, int] = {}
        self.element_tag_to_frame_name: dict[int, str] = {}
        self.node_local_to_global_tag: dict[int, int] = {}
        self.node_global_to_local_tag: dict[int, int] = {}
        self.material_local_to_global_tag: dict[int, int] = {}
        self.material_global_to_local_tag: dict[int, int] = {}
        self.section_local_to_global_tag: dict[int, int] = {}
        self.section_global_to_local_tag: dict[int, int] = {}
        self.element_local_to_global_tag: dict[int, int] = {}
        self.element_global_to_local_tag: dict[int, int] = {}


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

    @staticmethod
    def _coerce_origin(origin: tuple[float, float, float] | list[float] | None) -> tuple[float, float, float]:
        if origin is None:
            return 0.0, 0.0, 0.0
        if len(origin) != 3:
            raise ValueError("origin 必须为三维坐标 (x, y, z)。")
        return float(origin[0]), float(origin[1]), float(origin[2])

    def _apply_origin(self, x: float, y: float, z: float) -> tuple[float, float, float]:
        ox, oy, oz = self.origin
        return float(x) + ox, float(y) + oy, float(z) + oz

    def _global_source_tag(
        self,
        local_tag: int,
        namespace: str,
        local_to_global: dict[int, int],
        global_to_local: dict[int, int],
    ) -> int:
        local_tag = int(local_tag)
        if local_tag in local_to_global:
            return local_to_global[local_tag]
        if self.tag_manager.has_tag(local_tag, namespace=namespace):
            global_tag = self.tag_manager.get_next_tag(namespace=namespace)
        else:
            global_tag = self.tag_manager.register(local_tag, namespace=namespace)
        local_to_global[local_tag] = global_tag
        global_to_local[global_tag] = local_tag
        return global_tag

    def _preferred_tag(self, preferred_tag: int, namespace: str) -> int:
        preferred_tag = int(preferred_tag)
        if self.tag_manager.has_tag(preferred_tag, namespace=namespace):
            return self.tag_manager.get_next_tag(namespace=namespace)
        return self.tag_manager.register(preferred_tag, namespace=namespace)

    def _global_node_tag(self, local_node_tag: int) -> int:
        return self._global_source_tag(
            local_node_tag,
            "node",
            self.node_local_to_global_tag,
            self.node_global_to_local_tag,
        )

    def _global_material_tag(self, local_mat_tag: int) -> int:
        return self._global_source_tag(
            local_mat_tag,
            "material",
            self.material_local_to_global_tag,
            self.material_global_to_local_tag,
        )

    def _global_section_tag(self, local_section_tag: int) -> int:
        return self._global_source_tag(
            local_section_tag,
            "section",
            self.section_local_to_global_tag,
            self.section_global_to_local_tag,
        )

    def _global_element_tag(self, local_element_tag: int, namespace: str | None = None) -> int:
        return self._global_source_tag(
            local_element_tag,
            namespace or self._frame_element_tag_namespace,
            self.element_local_to_global_tag,
            self.element_global_to_local_tag,
        )

    def resolve_node_tag(self, node_tag: int) -> int:
        node_tag = int(node_tag)
        return self.node_local_to_global_tag.get(node_tag, node_tag)

    def resolve_element_tag(self, element_tag: int) -> int:
        element_tag = int(element_tag)
        return self.element_local_to_global_tag.get(element_tag, element_tag)

    def tag_maps(self) -> dict[str, dict[int, int]]:
        return {
            "nodes": dict(self.node_local_to_global_tag),
            "materials": dict(self.material_local_to_global_tag),
            "sections": dict(self.section_local_to_global_tag),
            "elements": dict(self.element_local_to_global_tag),
        }

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

    @staticmethod
    def _numeric_frame_tag(frame_name: str) -> int | None:
        frame_name = str(frame_name).strip()
        if frame_name.lstrip("+-").isdigit():
            return int(frame_name)
        return None

    def _frame_names_from_table(self, table_name: str) -> list[str]:
        try:
            lines = self._table_lines(table_name)
        except ValueError:
            return []
        frame_names: list[str] = []
        for line in lines:
            data = self._parse_key_values(line)
            if "Frame" in data:
                frame_names.append(str(data["Frame"]))
        return frame_names

    def _register_frame_element_tag(self, frame_name: str) -> int:
        frame_name = str(frame_name)
        if frame_name in self.frame_name_to_element_tag:
            return self.frame_name_to_element_tag[frame_name]

        namespace = self._frame_element_tag_namespace
        numeric_tag = self._numeric_frame_tag(frame_name)
        if numeric_tag is None:
            element_tag = self.tag_manager.get_next_tag(namespace=namespace)
        else:
            element_tag = self._global_element_tag(numeric_tag, namespace=namespace)

        if element_tag in self.element_tag_to_frame_name:
            existing_frame = self.element_tag_to_frame_name[element_tag]
            raise ValueError(
                f"Frame {frame_name} 分配得到的 {namespace} tag {element_tag} 已被 Frame {existing_frame} 使用。"
            )
        self.frame_name_to_element_tag[frame_name] = element_tag
        self.element_tag_to_frame_name[element_tag] = frame_name
        return element_tag

    def _initialize_element_tags(self) -> None:
        if self._element_tags_initialized:
            return

        frame_names: list[str] = []
        seen: set[str] = set()
        for table_name in ("CONNECTIVITY - FRAME", "FRAME SECTION ASSIGNMENTS"):
            for frame_name in self._frame_names_from_table(table_name):
                if frame_name not in seen:
                    frame_names.append(frame_name)
                    seen.add(frame_name)

        numeric_frames = [frame_name for frame_name in frame_names if self._numeric_frame_tag(frame_name) is not None]
        named_frames = [frame_name for frame_name in frame_names if self._numeric_frame_tag(frame_name) is None]
        for frame_name in numeric_frames + named_frames:
            self._register_frame_element_tag(frame_name)
        self._element_tags_initialized = True

    def _element_tag_for_frame(self, frame_name: str) -> int:
        self._initialize_element_tags()
        return self._register_frame_element_tag(frame_name)

    def initialize_model(self, ndm: int = 3, ndf: int = 6) -> None:
        self._ensure_model_builder(ndm=ndm, ndf=ndf)

    def _parse_node_coordinates(self) -> dict[int, dict[str, Any]]:
        node_records: dict[int, dict[str, Any]] = {}
        for line in self._table_lines("JOINT COORDINATES"):
            data = self._parse_key_values(line)
            local_node_tag = int(data["Joint"])
            node_tag = self._global_node_tag(local_node_tag)
            x, y, z = self._apply_origin(
                float(data["GlobalX"]),
                float(data["GlobalY"]),
                float(data["GlobalZ"]),
            )
            node_records[node_tag] = {
                "tower_id": self.tower_id,
                "node_tag": node_tag,
                "local_node_tag": local_node_tag,
                "x": x,
                "y": y,
                "z": z,
            }
        return node_records

    def node(self) -> dict[int, dict[str, Any]]:
        self._ensure_model_builder()
        ops = self.ops
        rows: list[dict[str, Any]] = []
        self.node_map = {}
        for node_tag, record in self._parse_node_coordinates().items():
            x = float(record["x"])
            y = float(record["y"])
            z = float(record["z"])
            ops.node(node_tag, x, y, z)
            self.node_map[node_tag] = record
            rows.append(record)
        # 保留一份节点坐标映射，后续几何变换和结果查询都会用到。
        self._write_csv(
            self.output_dir / "nodes.csv",
            rows,
            ["tower_id", "node_tag", "local_node_tag", "x", "y", "z"],
        )
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

        for input_node_tag, fixity in fix_assignments.items():
            node_tag = self.resolve_node_tag(input_node_tag)
            ops.fix(node_tag, *fixity)
            record = {
                "tower_id": self.tower_id,
                "node_tag": node_tag,
                "local_node_tag": self.node_global_to_local_tag.get(node_tag, int(input_node_tag)),
                "ux": fixity[0],
                "uy": fixity[1],
                "uz": fixity[2],
                "rx": fixity[3],
                "ry": fixity[4],
                "rz": fixity[5],
            }
            self.fix_map[node_tag] = record
            rows.append(record)
        self._write_csv(
            self.output_dir / "fixes.csv",
            rows,
            ["tower_id", "node_tag", "local_node_tag", "ux", "uy", "uz", "rx", "ry", "rz"],
        )
        return self.fix_map

    def mass(self) -> dict[int, dict[str, Any]]:
        self._ensure_model_builder()
        ops = self.ops
        rows: list[dict[str, Any]] = []
        self.mass_map = {}
        for line in self._table_lines("ASSEMBLED JOINT MASSES"):
            data = self._parse_key_values(line)
            local_node_tag = int(data["Joint"])
            node_tag = self.resolve_node_tag(local_node_tag)
            mx = float(data["U1"])
            my = float(data["U2"])
            mz = float(data["U3"])
            ops.mass(node_tag, mx, my, mz, 0.0, 0.0, 0.0)
            record = {
                "tower_id": self.tower_id,
                "node_tag": node_tag,
                "local_node_tag": local_node_tag,
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
            ["tower_id", "node_tag", "local_node_tag", "mx", "my", "mz", "mrx", "mry", "mrz"],
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
        for local_mat_tag, steel_data in enumerate(steel_records, start=1):
            tag = self._global_material_tag(local_mat_tag)
            name = steel_data["Material"]
            basic = basic_records.get(name, {})
            fy = float(steel_data["Fy"]) * 1e6
            e0 = float(basic.get("E1", 2.1e11))
            g = float(basic.get("G12", e0 / (2 * (1 + float(basic.get("U12", 0.3))))))
            nu = float(basic.get("U12", 0.3))
            density = float(basic.get("UnitMass", 0.0))
            ops.uniaxialMaterial("Steel01", tag, fy, e0, self.steel01_b)
            record = {
                "tower_id": self.tower_id,
                "mat_tag": tag,
                "local_mat_tag": local_mat_tag,
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
            ["tower_id", "mat_tag", "local_mat_tag", "material_name", "fy", "e0", "g", "nu", "density", "b", "ops_type"],
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
                "i22": float(data.get("I22", 0.0)),
                "i33": float(data.get("I33", 0.0)),
                "i23": float(data.get("I23", 0.0)),
            }
        return properties

    def _element_section_assignments(self) -> dict[int, dict[str, Any]]:
        assignments: dict[int, dict[str, Any]] = {}
        for line in self._table_lines("FRAME SECTION ASSIGNMENTS"):
            data = self._parse_key_values(line)
            frame_name = str(data["Frame"])
            ele_tag = self._element_tag_for_frame(frame_name)
            section_name = data.get("AnalSect", "")
            material_name = self._parse_key_values(line).get("MatProp", "")
            if not material_name and "Q" in section_name:
                material_name = f"Q{section_name.split('Q')[-1]}"
            assignments[ele_tag] = {
                "element_tag": ele_tag,
                "frame_name": frame_name,
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

        for local_section_tag, (section_name, material_name) in enumerate(unique_sections, start=1):
            sec_tag = self._global_section_tag(local_section_tag)
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
                "tower_id": self.tower_id,
                "section_tag": sec_tag,
                "local_section_tag": local_section_tag,
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
                "tower_id",
                "section_tag",
                "local_section_tag",
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
                tag: {
                    "element_tag": tag,
                    "frame_name": item.get("frame_name", self.element_tag_to_frame_name.get(tag, "")),
                    "node_i": item["node_i"],
                    "node_j": item["node_j"],
                }
                for tag, item in self.element_map.items()
            }

        rows: list[dict[str, Any]] = []
        self.transf_map = {}
        for ele_tag, item in raw_elements.items():
            node_i = self.node_map[item["node_i"]]
            node_j = self.node_map[item["node_j"]]
            vec_x, vec_y, vec_z = self._geom_transf_vector(node_i, node_j)
            transf_tag = self._preferred_tag(ele_tag, "transf")
            ops.geomTransf("Linear", transf_tag, vec_x, vec_y, vec_z)
            record = {
                "tower_id": self.tower_id,
                "transf_tag": transf_tag,
                "element_tag": ele_tag,
                "frame_name": item.get("frame_name", self.element_tag_to_frame_name.get(ele_tag, "")),
                "vec_x": vec_x,
                "vec_y": vec_y,
                "vec_z": vec_z,
            }
            self.transf_map[ele_tag] = record
            rows.append(record)
        self._write_csv(
            self.output_dir / "geomtransf.csv",
            rows,
            ["tower_id", "transf_tag", "element_tag", "frame_name", "vec_x", "vec_y", "vec_z"],
        )
        return self.transf_map

    @staticmethod
    def _vector_dot(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
        return sum(first[index] * second[index] for index in range(3))

    @staticmethod
    def _vector_cross(first: tuple[float, float, float], second: tuple[float, float, float]) -> tuple[float, float, float]:
        return (
            first[1] * second[2] - first[2] * second[1],
            first[2] * second[0] - first[0] * second[2],
            first[0] * second[1] - first[1] * second[0],
        )

    @staticmethod
    def _vector_norm(vector: tuple[float, float, float]) -> float:
        from math import sqrt

        return sqrt(sum(component * component for component in vector))

    @classmethod
    def _absolute_cosine(cls, first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
        denominator = cls._vector_norm(first) * cls._vector_norm(second)
        if denominator == 0.0:
            return 0.0
        return abs(cls._vector_dot(first, second) / denominator)

    @staticmethod
    def _close(value: float, target: float, tolerance: float = 1e-9) -> bool:
        return abs(value - target) <= tolerance

    @classmethod
    def _matches_boundary_pair(cls, z_i: float, z_j: float, pair: tuple[float, float]) -> bool:
        return (
            cls._close(z_i, pair[0]) and cls._close(z_j, pair[1])
        ) or (
            cls._close(z_i, pair[1]) and cls._close(z_j, pair[0])
        )

    @classmethod
    def _is_in_wind_area_band(
        cls,
        node_i: dict[str, Any],
        node_j: dict[str, Any],
        band: dict[str, Any],
    ) -> bool:
        z_i = float(node_i["z"])
        z_j = float(node_j["z"])
        y_i = float(node_i["y"])
        y_j = float(node_j["y"])
        z_min = float(band["z_min"])
        z_max = float(band["z_max"])
        y_limit = float(band["y_limit"])
        boundary_pair = band["boundary_pair"]

        has_node_inside_band = z_min < z_i < z_max or z_min < z_j < z_max
        has_boundary_pair = cls._matches_boundary_pair(z_i, z_j, boundary_pair)
        if not (has_node_inside_band or has_boundary_pair):
            return False

        if bool(band["y_inclusive"]):
            return y_i <= y_limit and y_j <= y_limit
        return y_i < y_limit and y_j < y_limit

    def _l_section_projected_area(
        self,
        node_i: dict[str, Any],
        node_j: dict[str, Any],
        section_name: str,
        theta: float,
    ) -> float:
        from math import cos, sin

        x_i, y_i, z_i = float(node_i["x"]), float(node_i["y"]), float(node_i["z"])
        x_j, y_j, z_j = float(node_j["x"]), float(node_j["y"]), float(node_j["z"])
        member_vector = (x_j - x_i, y_j - y_i, z_j - z_i)
        member_length = self._vector_norm(member_vector)
        leg_width, _ = self._l_section_dimensions(section_name)
        local_z_vector = self._geom_transf_vector(node_i, node_j)
        wind_vector = (sin(theta), cos(theta), 0.0)
        second_face_vector = self._vector_cross(local_z_vector, member_vector)
        projected_width = (
            self._absolute_cosine(wind_vector, local_z_vector)
            + self._absolute_cosine(wind_vector, second_face_vector)
        )
        return member_length * leg_width * projected_width

    def element_wind_projected_areas(self, theta: float = 0.0) -> dict[int, dict[str, Any]]:
        """Return projected wind areas for original SAP frame members.

        The calculation intentionally uses the original S2K frame connectivity
        instead of ``self.element_map`` so buckling-model segment elements do
        not multiply the exposed area.
        """

        node_records = self.node_map if self.node_map else self._parse_node_coordinates()

        connectivity = self._parse_element_connectivity()
        assignments = self._element_section_assignments()
        area_map: dict[int, dict[str, Any]] = {}

        for ele_tag, item in connectivity.items():
            node_i = node_records[int(item["node_i"])]
            node_j = node_records[int(item["node_j"])]
            section_name = assignments[ele_tag]["section_name"]
            projected_area = self._l_section_projected_area(node_i, node_j, section_name, theta)
            band_indices = [
                index
                for index, band in enumerate(self._WIND_AREA_BANDS)
                if self._is_in_wind_area_band(node_i, node_j, band)
            ]
            area_map[ele_tag] = {
                "element_tag": ele_tag,
                "frame_name": item.get("frame_name", assignments[ele_tag].get("frame_name", "")),
                "node_i": int(item["node_i"]),
                "node_j": int(item["node_j"]),
                "section_name": section_name,
                "projected_area": projected_area,
                "band_indices": band_indices,
            }

        self.wind_projected_area_map = area_map
        return area_map

    def get_area(self, theta: float = 0.0) -> dict[int, float]:
        area_by_band = {index: 0.0 for index in range(len(self._WIND_AREA_BANDS))}
        for area_record in self.element_wind_projected_areas(theta=theta).values():
            for band_index in area_record["band_indices"]:
                area_by_band[int(band_index)] += float(area_record["projected_area"])
        self.wind_area_by_band = area_by_band
        return area_by_band

    def _parse_element_connectivity(self) -> dict[int, dict[str, Any]]:
        connectivity: dict[int, dict[str, Any]] = {}
        for line in self._table_lines("CONNECTIVITY - FRAME"):
            data = self._parse_key_values(line)
            frame_name = str(data["Frame"])
            ele_tag = self._element_tag_for_frame(frame_name)
            local_node_i = int(data["JointI"])
            local_node_j = int(data["JointJ"])
            connectivity[ele_tag] = {
                "tower_id": self.tower_id,
                "element_tag": ele_tag,
                "local_element_tag": self.element_global_to_local_tag.get(ele_tag),
                "frame_name": frame_name,
                "node_i": self._global_node_tag(local_node_i),
                "node_j": self._global_node_tag(local_node_j),
                "local_node_i": local_node_i,
                "local_node_j": local_node_j,
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
            transf_tag = self.transf_map[ele_tag]["transf_tag"]
            integration_tag = self._preferred_tag(ele_tag, "integration")
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
                "frame_name": item.get("frame_name", assign.get("frame_name", "")),
                "integration_type": self.beam_integration_type,
                "section_tag": section_tag,
                "num_intgr_pts": self.num_intgr_pts,
            }
            self.integration_map[integration_tag] = integration_record
            integration_rows.append(integration_record)
            record = {
                "tower_id": self.tower_id,
                "element_tag": ele_tag,
                "local_element_tag": item.get("local_element_tag"),
                "frame_name": item.get("frame_name", assign.get("frame_name", "")),
                "node_i": item["node_i"],
                "node_j": item["node_j"],
                "local_node_i": item.get("local_node_i"),
                "local_node_j": item.get("local_node_j"),
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
                "frame_name",
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
                "local_element_tag",
                "frame_name",
                "node_i",
                "node_j",
                "local_node_i",
                "local_node_j",
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
            "frame_tags": self.frame_name_to_element_tag,
            "tag_maps": self.tag_maps(),
            "tower_id": self.tower_id,
            "origin": self.origin,
            "tag_summary": self.tag_manager.summary(),
        }

    def modeltower(self) -> dict[str, Any]:
        return self.model_tower()

    def get_node_coord(self, node_tag: int, prefer_ops: bool = False) -> tuple[float, float, float]:
        resolved_tag = self.resolve_node_tag(node_tag)
        if prefer_ops:
            try:
                # 如果模型还在 OpenSees 内存中，优先直接从 ops 里取实时坐标。
                coord = self.ops.nodeCoord(resolved_tag)
                return float(coord[0]), float(coord[1]), float(coord[2])
            except Exception:
                pass
        record = self.get_node_record(node_tag)
        return float(record["x"]), float(record["y"]), float(record["z"])

    def get_node_record(self, node_tag: int) -> dict[str, Any]:
        resolved_tag = self.resolve_node_tag(node_tag)
        if resolved_tag in self.node_map:
            return self.node_map[resolved_tag]
        rows = self._read_csv_rows(self.output_dir / "nodes.csv")
        for row in rows:
            if int(row["node_tag"]) == resolved_tag or int(row.get("local_node_tag", row["node_tag"])) == int(node_tag):
                return {
                    "tower_id": row.get("tower_id", self.tower_id),
                    "node_tag": int(row["node_tag"]),
                    "local_node_tag": int(row.get("local_node_tag", row["node_tag"])),
                    "x": float(row["x"]),
                    "y": float(row["y"]),
                    "z": float(row["z"]),
                }
        raise KeyError(f"未找到节点 {node_tag}")

    def get_element_record(self, element_tag: int) -> dict[str, Any]:
        resolved_tag = self.resolve_element_tag(element_tag)
        if resolved_tag in self.element_map:
            return self.element_map[resolved_tag]
        rows = self._read_csv_rows(self.output_dir / "elements.csv")
        for row in rows:
            if int(row["element_tag"]) == resolved_tag or int(row.get("local_element_tag") or row["element_tag"]) == int(element_tag):
                return {
                    "tower_id": row.get("tower_id", self.tower_id),
                    "element_tag": int(row["element_tag"]),
                    "local_element_tag": int(row.get("local_element_tag") or row["element_tag"]),
                    "frame_name": row.get("frame_name", self.element_tag_to_frame_name.get(int(row["element_tag"]), "")),
                    "node_i": int(row["node_i"]),
                    "node_j": int(row["node_j"]),
                    "local_node_i": int(row.get("local_node_i") or row["node_i"]),
                    "local_node_j": int(row.get("local_node_j") or row["node_j"]),
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
if __name__ == "__main__":
    
    model = OpenSeesModel("Source/Z30103A6.s2k")
    model.model_tower()
    print(model.get_area())
