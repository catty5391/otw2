from __future__ import annotations

import csv
import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]

try:
    import openseespy.opensees as ops
except ImportError as exc:  # pragma: no cover
    raise ImportError("当前环境未安装 openseespy，无法执行塔线体系建模。") from exc

try:
    from model.tower_model import OpenSeesModel, TagManager
    from model.tower_model_with_buckling import OpenSeesModelWithBuckling
except ImportError:  # pragma: no cover
    tower_model_path = PROJECT_ROOT / "model" / "tower_model.py"
    spec = importlib.util.spec_from_file_location("otw_tower_model", tower_model_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 OpenSeesModel: {tower_model_path}")
    tower_model_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tower_model_module)
    OpenSeesModel = tower_model_module.OpenSeesModel
    TagManager = tower_model_module.TagManager

    buckling_path = PROJECT_ROOT / "model" / "tower_model_with_buckling.py"
    spec = importlib.util.spec_from_file_location("otw_tower_model_with_buckling", buckling_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 OpenSeesModelWithBuckling: {buckling_path}")
    buckling_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(buckling_module)
    OpenSeesModelWithBuckling = buckling_module.OpenSeesModelWithBuckling


class TowerLineSystemModel:
    """Build towers, V-shaped insulator strings, and transmission lines from config."""

    DEFAULT_CONFIG_PATH = PROJECT_ROOT / "model" / ".config" / "tower_line_with_insulators.json"

    def __init__(
        self,
        config_path: str | Path | None = None,
        *,
        output_dir: str | Path | None = None,
        wipe: bool = True,
    ) -> None:
        self.config_path = Path(config_path) if config_path is not None else self.DEFAULT_CONFIG_PATH
        self.output_dir = Path(output_dir) if output_dir is not None else PROJECT_ROOT / "model" / ".output" / "tower_line_system"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.config = self._read_config()
        self.tag_manager = self._make_tag_manager()
        self.ops = ops
        if wipe:
            self.ops.wipe()

        self.towers: dict[str, OpenSeesModel] = {}
        self.insulator_map: dict[str, dict[str, Any]] = {}
        self.transmission_line_map: dict[str, dict[str, Any]] = {}
        self.node_map: dict[int, dict[str, Any]] = {}
        self.element_map: dict[int, dict[str, Any]] = {}
        self.material_tag_map: dict[int, dict[str, Any]] = {}
        self.section_tag_map: dict[int, dict[str, Any]] = {}
        self.fix_map: dict[int, dict[str, Any]] = {}
        self.mass_map: dict[int, dict[str, Any]] = {}

    def _read_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"未找到塔线体系配置: {self.config_path}")
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError(f"配置文件必须是 JSON object: {self.config_path}")
        return config

    @staticmethod
    def _make_tag_manager() -> TagManager:
        return TagManager(
            start_tag={
                "node": 1,
                "material": 1,
                "section": 1,
                "transf": 1,
                "integration": 1,
                "element": 1,
                "source_element": 1,
                "timeSeries": 1,
                "pattern": 1,
            }
        )

    @staticmethod
    def _as_float(value: Any, name: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} 必须是数值，当前值为 {value!r}") from exc
        if not math.isfinite(number):
            raise ValueError(f"{name} 必须是有限数值，当前值为 {value!r}")
        return number

    @staticmethod
    def _items(config_value: Any) -> list[tuple[str, dict[str, Any]]]:
        if config_value is None:
            return []
        if isinstance(config_value, dict):
            return [(str(name), value) for name, value in config_value.items()]
        if isinstance(config_value, list):
            result = []
            for index, value in enumerate(config_value, start=1):
                if not isinstance(value, dict):
                    raise ValueError("列表配置项必须是 JSON object")
                name = value.get("id", value.get("name", f"item_{index}"))
                result.append((str(name), value))
            return result
        raise ValueError("配置段必须是 object 或 list")

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            if rows:
                writer.writerows(rows)

    def _merge_tower_maps(self, tower: OpenSeesModel) -> None:
        self.node_map.update(tower.node_map)
        self.element_map.update(tower.element_map)
        self.material_tag_map.update(tower.material_tag_map)
        self.section_tag_map.update(tower.section_tag_map)
        self.fix_map.update(tower.fix_map)
        self.mass_map.update(tower.mass_map)

    def build(self) -> dict[str, Any]:
        self.build_towers()
        self.build_insulators()
        self.build_transmission_lines()
        self._write_outputs()
        return {
            "towers": self.towers,
            "insulators": self.insulator_map,
            "transmission_lines": self.transmission_line_map,
            "nodes": self.node_map,
            "elements": self.element_map,
            "materials": self.material_tag_map,
            "sections": self.section_tag_map,
            "tag_summary": self.tag_manager.summary(),
        }

    def build_towers(self) -> dict[str, OpenSeesModel]:
        for tower_id, tower_config in self._items(self.config.get("towers")):
            model_type = str(tower_config.get("model", tower_config.get("type", "normal"))).lower()
            model_cls = OpenSeesModelWithBuckling if model_type in {"buckling", "with_buckling"} else OpenSeesModel
            s2k_path = Path(tower_config.get("s2k_path", tower_config.get("path", "Source/Z30103A6.s2k")))
            if not s2k_path.is_absolute():
                s2k_path = PROJECT_ROOT / s2k_path
            origin = tower_config.get("origin", [0.0, 0.0, 0.0])
            tower_output_dir = self.output_dir / "towers" / tower_id
            extra_kwargs: dict[str, Any] = {}
            if model_cls is OpenSeesModelWithBuckling:
                for key in ("random_disp_ratio", "member_divisions"):
                    if key in tower_config:
                        extra_kwargs[key] = tower_config[key]
            tower = model_cls(
                s2k_path,
                tower_id=tower_id,
                origin=origin,
                tag_manager=self.tag_manager,
                output_dir=tower_output_dir,
                **extra_kwargs,
            )
            tower.model_tower()
            self.towers[tower_id] = tower
            self._merge_tower_maps(tower)
        return self.towers

    def _resolve_point(self, point: Any, name: str) -> tuple[int | None, np.ndarray, bool, dict[str, Any]]:
        if isinstance(point, str):
            if point in self.insulator_map:
                record = self.insulator_map[point]
                return int(record["lower_node_tag"]), np.array(record["lower_coord"], dtype=float), True, {"kind": "insulator", "id": point}
            raise ValueError(f"{name} 引用了未知点: {point}")
        if isinstance(point, (int, float)):
            tag = int(point)
            if tag not in self.node_map:
                raise KeyError(f"{name} 引用了不存在的全局节点 {tag}")
            record = self.node_map[tag]
            return tag, np.array([record["x"], record["y"], record["z"]], dtype=float), True, {"kind": "node", "node_tag": tag}
        if isinstance(point, (list, tuple)) and len(point) == 3:
            coord = np.array([self._as_float(value, name) for value in point], dtype=float)
            return None, coord, False, {"kind": "coord"}
        if not isinstance(point, dict):
            raise ValueError(f"{name} 需为 tower/local_node、insulator/lower、node 或 coord 引用")

        if "coord" in point:
            coord = np.array([self._as_float(value, f"{name}.coord") for value in point["coord"]], dtype=float)
            return None, coord, False, {"kind": "coord"}

        insulator_id = point.get("insulator") or point.get("insulator_id")
        if insulator_id is not None:
            insulator_id = str(insulator_id)
            if insulator_id not in self.insulator_map:
                raise KeyError(f"{name} 引用了未知绝缘子串 {insulator_id}")
            record = self.insulator_map[insulator_id]
            point_name = str(point.get("point", "lower"))
            if point_name != "lower":
                raise ValueError(f"{name}.point 当前仅支持 lower")
            return int(record["lower_node_tag"]), np.array(record["lower_coord"], dtype=float), True, {
                "kind": "insulator",
                "id": insulator_id,
                "point": point_name,
            }

        tower_id = point.get("tower") or point.get("tower_id")
        local_node = point.get("local_node", point.get("node"))
        if tower_id is not None and local_node is not None:
            tower_id = str(tower_id)
            if tower_id not in self.towers:
                raise KeyError(f"{name} 引用了未知塔 {tower_id}")
            tower = self.towers[tower_id]
            node_tag = tower.resolve_node_tag(int(local_node))
            coord = np.array(tower.get_node_coord(int(local_node), prefer_ops=True), dtype=float)
            return node_tag, coord, True, {
                "kind": "tower_node",
                "tower_id": tower_id,
                "local_node": int(local_node),
                "node_tag": node_tag,
            }

        node_tag = point.get("node_tag")
        if node_tag is not None:
            node_tag = int(node_tag)
            if node_tag not in self.node_map:
                raise KeyError(f"{name} 引用了不存在的全局节点 {node_tag}")
            record = self.node_map[node_tag]
            return node_tag, np.array([record["x"], record["y"], record["z"]], dtype=float), True, {
                "kind": "node",
                "node_tag": node_tag,
            }
        raise ValueError(f"{name} 点引用缺少必要字段")

    def _lower_coord_from_config(
        self,
        insulator_id: str,
        insulator_config: dict[str, Any],
        upper_coords: list[np.ndarray],
    ) -> np.ndarray:
        lower = insulator_config.get("lower_point", insulator_config.get("lower"))
        if lower is None:
            raise ValueError(f"{insulator_id}.lower_point 必须配置 coord 或 offset_from_upper_midpoint")
        if isinstance(lower, dict) and "coord" in lower:
            return np.array([self._as_float(value, f"{insulator_id}.lower_point.coord") for value in lower["coord"]], dtype=float)
        if isinstance(lower, dict):
            offset = lower.get("offset_from_upper_midpoint", lower.get("offset"))
            if offset is not None:
                offset_vector = np.array([self._as_float(value, f"{insulator_id}.lower_point.offset") for value in offset], dtype=float)
                return 0.5 * (upper_coords[0] + upper_coords[1]) + offset_vector
        if isinstance(lower, (list, tuple)) and len(lower) == 3:
            return np.array([self._as_float(value, f"{insulator_id}.lower_point") for value in lower], dtype=float)
        raise ValueError(f"{insulator_id}.lower_point 格式不支持")

    def _create_node(
        self,
        coord: np.ndarray,
        record: dict[str, Any],
        *,
        fix_rotations: bool = True,
        mass: float = 0.0,
    ) -> int:
        node_tag = self.tag_manager.get_next_tag(namespace="node")
        self.ops.node(node_tag, float(coord[0]), float(coord[1]), float(coord[2]))
        node_record = {
            "node_tag": node_tag,
            "x": float(coord[0]),
            "y": float(coord[1]),
            "z": float(coord[2]),
            **record,
        }
        self.node_map[node_tag] = node_record
        if fix_rotations:
            self.ops.fix(node_tag, 0, 0, 0, 1, 1, 1)
            self.fix_map[node_tag] = {
                "node_tag": node_tag,
                "ux": 0,
                "uy": 0,
                "uz": 0,
                "rx": 1,
                "ry": 1,
                "rz": 1,
                **{k: v for k, v in record.items() if k in {"component", "insulator_id", "line_id"}},
            }
        if mass != 0.0:
            self.ops.mass(node_tag, mass, mass, mass, 0.0, 0.0, 0.0)
            self.mass_map[node_tag] = {
                "node_tag": node_tag,
                "mx": mass,
                "my": mass,
                "mz": mass,
                "mrx": 0.0,
                "mry": 0.0,
                "mrz": 0.0,
            }
        return node_tag

    def build_insulators(self) -> dict[str, dict[str, Any]]:
        for insulator_id, insulator_config in self._items(self.config.get("insulators")):
            upper_points = insulator_config.get("upper_points", insulator_config.get("upper_nodes"))
            if not isinstance(upper_points, list) or len(upper_points) != 2:
                raise ValueError(f"{insulator_id}.upper_points 必须配置两个上挂点")
            upper_resolved = [
                self._resolve_point(point, f"{insulator_id}.upper_points[{index}]")
                for index, point in enumerate(upper_points)
            ]
            upper_node_tags = [int(item[0]) for item in upper_resolved if item[0] is not None]
            upper_coords = [item[1] for item in upper_resolved]
            if len(upper_node_tags) != 2:
                raise ValueError(f"{insulator_id} 的两个上挂点必须是已有节点")

            lower_coord = self._lower_coord_from_config(insulator_id, insulator_config, upper_coords)
            material = insulator_config.get("material", {})
            ea = self._as_float(material.get("EA", material.get("ea", 1.0e8)), f"{insulator_id}.material.EA")
            area = self._as_float(material.get("area", material.get("A", 1.0)), f"{insulator_id}.material.area")
            mass = self._as_float(material.get("mass", 0.0), f"{insulator_id}.material.mass")
            e_modulus = ea / area if area != 0.0 else ea

            lower_node_tag = self._create_node(
                lower_coord,
                {
                    "component": "insulator_lower",
                    "insulator_id": insulator_id,
                    "tower_id": insulator_config.get("tower_id", insulator_config.get("tower", "")),
                    "side": insulator_config.get("side", ""),
                },
                fix_rotations=True,
                mass=mass,
            )
            mat_tag = self.tag_manager.get_next_tag(namespace="material")
            self.ops.uniaxialMaterial("Elastic", mat_tag, e_modulus)
            self.material_tag_map[mat_tag] = {
                "mat_tag": mat_tag,
                "component": "insulator",
                "insulator_id": insulator_id,
                "ops_type": "Elastic",
                "EA": ea,
                "area": area,
                "E": e_modulus,
            }

            element_tags: list[int] = []
            for leg_index, upper_node_tag in enumerate(upper_node_tags, start=1):
                element_tag = self.tag_manager.get_next_tag(namespace="element")
                self.ops.element("corotTruss", element_tag, upper_node_tag, lower_node_tag, area, mat_tag)
                record = {
                    "element_tag": element_tag,
                    "component": "insulator",
                    "insulator_id": insulator_id,
                    "leg_index": leg_index,
                    "node_i": upper_node_tag,
                    "node_j": lower_node_tag,
                    "mat_tag": mat_tag,
                    "area": area,
                    "ops_type": "corotTruss",
                }
                self.element_map[element_tag] = record
                element_tags.append(element_tag)

            self.insulator_map[insulator_id] = {
                "insulator_id": insulator_id,
                "tower_id": insulator_config.get("tower_id", insulator_config.get("tower", "")),
                "side": insulator_config.get("side", ""),
                "upper_node_tags": upper_node_tags,
                "lower_node_tag": lower_node_tag,
                "lower_coord": [float(value) for value in lower_coord],
                "element_tags": element_tags,
                "mat_tag": mat_tag,
                "EA": ea,
                "area": area,
            }
        return self.insulator_map

    def _line_material(self, line_id: str, line_config: dict[str, Any], span: float, n_seg: int) -> dict[str, float]:
        material = line_config.get("material", {})
        ea = self._as_float(material.get("EA", material.get("ea", 2.8e7)), f"{line_id}.material.EA")
        area = self._as_float(material.get("area", material.get("A", 1.0)), f"{line_id}.material.area")
        eiy = self._as_float(material.get("EIy", material.get("EI", material.get("ei", 0.0))), f"{line_id}.material.EIy")
        eiz = self._as_float(material.get("EIz", material.get("EI", material.get("ei", 0.0))), f"{line_id}.material.EIz")
        gj = self._as_float(material.get("GJ", material.get("gj", 0.0)), f"{line_id}.material.GJ")
        initial_force = material.get("initial_force", material.get("T0"))
        if initial_force is None:
            initial_stress = self._as_float(material.get("initial_stress", material.get("stress", 0.0)), f"{line_id}.material.initial_stress")
            initial_force_value = initial_stress * area
        else:
            initial_force_value = self._as_float(initial_force, f"{line_id}.material.initial_force")
            initial_stress = initial_force_value / area if area != 0.0 else initial_force_value
        element_length = span / n_seg
        fallback_nonaxial = max(1.0e-8 * ea * element_length**2, 1.0e-12)
        return {
            "EA": ea,
            "area": area,
            "EIy": eiy if eiy > 0.0 else fallback_nonaxial,
            "EIz": eiz if eiz > 0.0 else fallback_nonaxial,
            "GJ": gj if gj > 0.0 else fallback_nonaxial,
            "initial_force": initial_force_value,
            "initial_stress": initial_stress,
        }

    def _create_line_section(self, line_id: str, material: dict[str, float]) -> int:
        axial_mat = self.tag_manager.get_next_tag(namespace="material")
        eiy_mat = self.tag_manager.get_next_tag(namespace="material")
        eiz_mat = self.tag_manager.get_next_tag(namespace="material")
        torsion_mat = self.tag_manager.get_next_tag(namespace="material")
        init_mat = self.tag_manager.get_next_tag(namespace="material")
        section_tag = self.tag_manager.get_next_tag(namespace="section")
        self.ops.uniaxialMaterial("Elastic", axial_mat, material["EA"])
        self.ops.uniaxialMaterial("Elastic", eiy_mat, material["EIy"])
        self.ops.uniaxialMaterial("Elastic", eiz_mat, material["EIz"])
        self.ops.uniaxialMaterial("Elastic", torsion_mat, material["GJ"])
        self.ops.uniaxialMaterial("InitStressMaterial", init_mat, axial_mat, material["initial_force"])
        self.ops.section("Aggregator", section_tag, init_mat, "P", eiz_mat, "Mz", eiy_mat, "My", torsion_mat, "T")
        for mat_tag, component, stiffness in (
            (axial_mat, "P_base", material["EA"]),
            (eiy_mat, "My", material["EIy"]),
            (eiz_mat, "Mz", material["EIz"]),
            (torsion_mat, "T", material["GJ"]),
            (init_mat, "P", material["initial_force"]),
        ):
            self.material_tag_map[mat_tag] = {
                "mat_tag": mat_tag,
                "component": "transmission_line",
                "line_id": line_id,
                "line_component": component,
                "stiffness": stiffness,
            }
        self.section_tag_map[section_tag] = {
            "section_tag": section_tag,
            "component": "transmission_line",
            "line_id": line_id,
            "ops_type": "Aggregator",
            "axial_mat_tag": axial_mat,
            "init_mat_tag": init_mat,
            "eiy_mat_tag": eiy_mat,
            "eiz_mat_tag": eiz_mat,
            "torsion_mat_tag": torsion_mat,
            **material,
        }
        return section_tag

    @staticmethod
    def _line_coordinates(start: np.ndarray, end: np.ndarray, n_seg: int, initial_sag: float) -> np.ndarray:
        coords = []
        for index in range(n_seg + 1):
            xi = index / n_seg
            coord = start + (end - start) * xi
            coord = coord.astype(float, copy=True)
            coord[2] -= 4.0 * initial_sag * xi * (1.0 - xi)
            coords.append(coord)
        return np.array(coords, dtype=float)

    def build_transmission_lines(self) -> dict[str, dict[str, Any]]:
        for line_id, line_config in self._items(self.config.get("transmission_lines", self.config.get("lines"))):
            points = line_config.get("node_to_hang", line_config.get("endpoints"))
            if not isinstance(points, list) or len(points) != 2:
                raise ValueError(f"{line_id}.node_to_hang/endpoints 必须配置两个端点")
            left_tag, start, left_exists, left_ref = self._resolve_point(points[0], f"{line_id}.endpoints[0]")
            right_tag, end, right_exists, right_ref = self._resolve_point(points[1], f"{line_id}.endpoints[1]")
            n_seg = int(line_config.get("n_seg", line_config.get("segments", 60)))
            if n_seg < 1:
                raise ValueError(f"{line_id}.n_seg 必须大于 0")
            initial_sag = self._as_float(line_config.get("initial_sag", line_config.get("sag", 0.0)), f"{line_id}.initial_sag")
            q_g = self._as_float(line_config.get("q_g", line_config.get("weight_per_length", 0.0)), f"{line_id}.q_g")
            gravity = self._as_float(line_config.get("gravity", 9.81), f"{line_id}.gravity")
            span = float(np.linalg.norm(end - start))
            if span <= 0.0:
                raise ValueError(f"{line_id} 两端点重合")
            material = self._line_material(line_id, line_config, span, n_seg)
            section_tag = self._create_line_section(line_id, material)

            coords = self._line_coordinates(start, end, n_seg, initial_sag)
            node_tags: list[int] = []
            for index, coord in enumerate(coords):
                if index == 0 and left_exists and left_tag is not None:
                    node_tag = left_tag
                elif index == n_seg and right_exists and right_tag is not None:
                    node_tag = right_tag
                else:
                    node_tag = self._create_node(
                        coord,
                        {"component": "transmission_line_node", "line_id": line_id, "local_index": index},
                        fix_rotations=True,
                    )
                node_tags.append(node_tag)

            element_tags: list[int] = []
            for index in range(n_seg):
                element_tag = self.tag_manager.get_next_tag(namespace="element")
                self.ops.element("corotTrussSection", element_tag, node_tags[index], node_tags[index + 1], section_tag)
                record = {
                    "element_tag": element_tag,
                    "component": "transmission_line",
                    "line_id": line_id,
                    "local_index": index,
                    "node_i": node_tags[index],
                    "node_j": node_tags[index + 1],
                    "section_tag": section_tag,
                    "ops_type": "corotTrussSection",
                }
                self.element_map[element_tag] = record
                element_tags.append(element_tag)

            if q_g != 0.0:
                time_series_tag = self.tag_manager.get_next_tag(namespace="timeSeries")
                pattern_tag = self.tag_manager.get_next_tag(namespace="pattern")
                self.ops.timeSeries("Linear", time_series_tag)
                self.ops.pattern("Plain", pattern_tag, time_series_tag)
                dx = span / n_seg
                for index, node_tag in enumerate(node_tags):
                    trib_length = dx / 2.0 if index in (0, n_seg) else dx
                    weight = q_g * trib_length
                    self.ops.load(node_tag, 0.0, 0.0, -weight, 0.0, 0.0, 0.0)
                    mass = weight / gravity if gravity != 0.0 else 0.0
                    if mass != 0.0 and node_tag not in self.mass_map:
                        self.ops.mass(node_tag, mass, mass, mass, 0.0, 0.0, 0.0)
                        self.mass_map[node_tag] = {
                            "node_tag": node_tag,
                            "mx": mass,
                            "my": mass,
                            "mz": mass,
                            "mrx": 0.0,
                            "mry": 0.0,
                            "mrz": 0.0,
                        }

            self.transmission_line_map[line_id] = {
                "line_id": line_id,
                "node_tags": node_tags,
                "element_tags": element_tags,
                "section_tag": section_tag,
                "span": span,
                "n_seg": n_seg,
                "initial_sag": initial_sag,
                "q_g": q_g,
                "left_ref": left_ref,
                "right_ref": right_ref,
                "material": material,
            }
        return self.transmission_line_map

    def _write_outputs(self) -> None:
        self._write_csv(
            self.output_dir / "system_nodes.csv",
            list(self.node_map.values()),
            sorted({key for row in self.node_map.values() for key in row}),
        )
        self._write_csv(
            self.output_dir / "system_elements.csv",
            list(self.element_map.values()),
            sorted({key for row in self.element_map.values() for key in row}),
        )
        self._write_csv(
            self.output_dir / "insulators.csv",
            list(self.insulator_map.values()),
            sorted({key for row in self.insulator_map.values() for key in row}) if self.insulator_map else ["insulator_id"],
        )
        self._write_csv(
            self.output_dir / "transmission_lines.csv",
            list(self.transmission_line_map.values()),
            sorted({key for row in self.transmission_line_map.values() for key in row}) if self.transmission_line_map else ["line_id"],
        )

    def write_plot_html(self, path: str | Path | None = None, *, auto_open: bool = False) -> Path:
        from util.postprocess.plot_model import PlotModel

        html_path = Path(path) if path is not None else self.output_dir / "tower_line_system.html"
        return PlotModel(self).write_html(
            html_path,
            title="Tower-Line System With V Insulators",
            show_nodes=True,
            show_elements=True,
            element_hover="midpoint",
            node_size=2,
            element_width=2,
            width=1200,
            height=850,
            auto_open=auto_open,
        )


TowerLineModel = TowerLineSystemModel
