from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]

from model.conductor_properties import resolve_conductor_mass, tributary_lengths

try:
    from model import OpenSeesModel
except ImportError:  # pragma: no cover
    model_path = PROJECT_ROOT / "model" / "tower_model.py"
    spec = importlib.util.spec_from_file_location("otw_tower_model", model_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 OpenSeesModel: {model_path}")
    model_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model_module)
    OpenSeesModel = model_module.OpenSeesModel

try:
    from util.preprocess.tag_manager import TagManager
except ImportError:  # pragma: no cover
    tag_manager_path = PROJECT_ROOT / "util" / "preprocess" / "tag_manager.py"
    spec = importlib.util.spec_from_file_location("otw_tag_manager", tag_manager_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 TagManager: {tag_manager_path}")
    tag_manager_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tag_manager_module)
    TagManager = tag_manager_module.TagManager


class TransmissionLineModel(OpenSeesModel):
    """Build transmission-line cable elements on top of the tower model.

    The class keeps the notebook workflow available for standalone form-finding,
    but the normal tower-coupled path is ``model_tower()`` followed by
    ``build_one_line()`` or ``build_all_line()``. End nodes listed by tag in the
    line config are reused as tower hanging points; only internal cable nodes are
    created.
    """

    DEFAULT_CONFIG_PATH = PROJECT_ROOT / "model" / ".config" / "transmission_line.json"

    def __init__(
        self,
        name: str,
        path: str | Path,
        transmission_line_config_path: str | Path | None = None,
        line_output_dir: str | Path | None = None,
        **tower_kwargs: Any,
    ) -> None:
        super().__init__(path, **tower_kwargs)
        self.name = name
        self.transmission_line_config_path = (
            Path(transmission_line_config_path)
            if transmission_line_config_path is not None
            else self.DEFAULT_CONFIG_PATH
        )
        self.line_output_dir = (
            Path(line_output_dir)
            if line_output_dir is not None
            else self.output_dir / "transimission_line"
        )
        self.line_output_dir.mkdir(parents=True, exist_ok=True)

        self.transmission_line_config: dict[str, Any] = {}
        self.transmission_line_map: dict[str, dict[str, Any]] = {}
        self.transmission_line_node_map: dict[int, dict[str, Any]] = {}
        self.transmission_line_element_map: dict[int, dict[str, Any]] = {}
        self.transmission_line_section_map: dict[int, dict[str, Any]] = {}
        self.transmission_line_material_map: dict[int, dict[str, Any]] = {}
        self.transmission_line_load_map: dict[int, dict[str, Any]] = {}

        self._read_transmission_line_json()
        self._register_tag()

    def _read_transmission_line_json(self) -> dict[str, Any]:
        if not self.transmission_line_config_path.exists():
            self.transmission_line_config = {}
            return self.transmission_line_config
        config = json.loads(self.transmission_line_config_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError(f"导线配置必须是 JSON object: {self.transmission_line_config_path}")
        self.transmission_line_config = config
        return self.transmission_line_config

    def reload_transmission_line_config(self) -> dict[str, Any]:
        return self._read_transmission_line_json()

    def _safe_register(self, tag: int | None, namespace: str) -> None:
        if tag is None:
            return
        tag = int(tag)
        if not self.tag_manager.has_tag(tag, namespace=namespace):
            self.tag_manager.register(tag, namespace=namespace)

    def _register_tag(self) -> None:
        """Synchronize the incremental line tag manager with the tower maps."""

        self.tag_manager = TagManager()
        for node in self.node_map.values():
            self._safe_register(node.get("node_tag"), "node")
        for element in self.element_map.values():
            self._safe_register(element.get("element_tag"), "element")
        for material in self.material_tag_map.values():
            self._safe_register(material.get("mat_tag"), "material")
        for section in self.section_tag_map.values():
            self._safe_register(section.get("section_tag"), "section")
        for section in self.transmission_line_section_map.values():
            self._safe_register(section.get("section_tag"), "section")
        for material in self.transmission_line_material_map.values():
            self._safe_register(material.get("mat_tag"), "material")
        for node in self.transmission_line_node_map.values():
            self._safe_register(node.get("node_tag"), "node")
        for element in self.transmission_line_element_map.values():
            self._safe_register(element.get("element_tag"), "element")

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
    def _first_value(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
        for key in keys:
            if key in data:
                return data[key]
        return default

    def _parse_line_material(self, line_name: str, line_config: dict[str, Any]) -> dict[str, float]:
        material = line_config.get("material", {})
        if isinstance(material, dict):
            ea = self._first_value(material, "EA", "ea", "axial_stiffness", "axial")
            ei = self._first_value(material, "EI", "ei", "bending_stiffness", "EIz", "EIz")
            eiy = self._first_value(material, "EIy", "eiy", default=ei)
            eiz = self._first_value(material, "EIz", "eiz", default=ei)
            gj = self._first_value(material, "GJ", "gj", "torsional_stiffness", "torsion")
            area = self._first_value(material, "A", "area", default=line_config.get("A", line_config.get("area")))
            initial_force = self._first_value(material, "initial_force", "init_force", "T0", "tension")
            initial_stress = self._first_value(material, "initial_stress", "init_stress", "stress")
        elif isinstance(material, (list, tuple)) and len(material) >= 4:
            ea, ei, gj = material[0], material[1], material[2]
            eiy = eiz = ei
            area = line_config.get("A", line_config.get("area"))
            initial_force = None
            initial_stress = material[3]
        else:
            raise ValueError(
                f"{line_name}.material 需要 dict 或 [EA, EI, GJ, initial_stress/force] 格式。"
            )

        ea_value = self._as_float(ea, f"{line_name}.material.EA")
        eiy_value = self._as_float(eiy, f"{line_name}.material.EIy")
        eiz_value = self._as_float(eiz, f"{line_name}.material.EIz")
        gj_value = self._as_float(gj, f"{line_name}.material.GJ")
        area_value = None if area is None else self._as_float(area, f"{line_name}.area")

        if initial_force is not None:
            initial_force_value = self._as_float(initial_force, f"{line_name}.material.initial_force")
            initial_stress_value = initial_force_value / area_value if area_value else initial_force_value
        else:
            initial_stress_value = self._as_float(initial_stress, f"{line_name}.material.initial_stress")
            initial_force_value = initial_stress_value * area_value if area_value else initial_stress_value

        return {
            "EA": ea_value,
            "EIy": eiy_value,
            "EIz": eiz_value,
            "GJ": gj_value,
            "area": area_value or 1.0,
            "initial_stress": initial_stress_value,
            "initial_force": initial_force_value,
        }

    def _line_config(self, name: str) -> dict[str, Any]:
        if name not in self.transmission_line_config:
            raise ValueError(f"Line {name} not found in {self.transmission_line_config_path}")
        line_config = self.transmission_line_config[name]
        if not isinstance(line_config, dict):
            raise ValueError(f"Line {name} 的配置必须是 JSON object")
        return line_config

    def _segment_count(self, line_name: str, line_config: dict[str, Any]) -> int:
        value = self._first_value(line_config, "n_seg", "segments", "separate", "sepearte", default=60)
        try:
            n_seg = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{line_name}.n_seg/sepearte 必须是正整数，当前值为 {value!r}") from exc
        if n_seg < 1:
            raise ValueError(f"{line_name}.n_seg/sepearte 必须大于 0")
        return n_seg

    def _node_exists_in_ops(self, node_tag: int) -> bool:
        try:
            return int(node_tag) in {int(tag) for tag in self.ops.getNodeTags()}
        except Exception:
            return False

    def _resolve_hang_point(self, point: Any, endpoint_name: str) -> tuple[int | None, np.ndarray, bool]:
        if isinstance(point, dict):
            node_tag = self._first_value(point, "node", "node_tag", "tag")
            coord = self._first_value(point, "coord", "coords", "coordinate")
            if node_tag is not None:
                tag = int(node_tag)
                if coord is None:
                    return tag, np.array(self.get_node_coord(tag, prefer_ops=True), dtype=float), self._node_exists_in_ops(tag)
                return tag, np.array([self._as_float(v, endpoint_name) for v in coord], dtype=float), self._node_exists_in_ops(tag)
            if coord is not None:
                return None, np.array([self._as_float(v, endpoint_name) for v in coord], dtype=float), False
        if isinstance(point, int) or (isinstance(point, str) and point.lstrip("+-").isdigit()):
            tag = int(point)
            return tag, np.array(self.get_node_coord(tag, prefer_ops=True), dtype=float), self._node_exists_in_ops(tag)
        if isinstance(point, (list, tuple)) and len(point) == 3:
            return None, np.array([self._as_float(v, endpoint_name) for v in point], dtype=float), False
        raise ValueError(f"{endpoint_name} 需为塔节点 tag、三维坐标或包含 node/coord 的 dict，当前为 {point!r}")

    def _resolve_hang_points(self, line_name: str, line_config: dict[str, Any]) -> tuple[list[int | None], np.ndarray, np.ndarray, list[bool]]:
        node_to_hang = line_config.get("node_to_hang")
        if not isinstance(node_to_hang, (list, tuple)) or len(node_to_hang) != 2:
            raise ValueError(f"{line_name}.node_to_hang 必须包含两个挂点")
        left_tag, left_coord, left_exists = self._resolve_hang_point(node_to_hang[0], f"{line_name}.node_to_hang[0]")
        right_tag, right_coord, right_exists = self._resolve_hang_point(node_to_hang[1], f"{line_name}.node_to_hang[1]")
        return [left_tag, right_tag], left_coord, right_coord, [left_exists, right_exists]

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

    def _create_node_if_needed(
        self,
        node_tag: int | None,
        coord: np.ndarray,
        exists_in_ops: bool,
        fixity: tuple[int, int, int, int, int, int] | None,
    ) -> int:
        tag = int(node_tag) if node_tag is not None else self.tag_manager.get_next_tag(namespace="node")
        if exists_in_ops:
            self._safe_register(tag, "node")
            return tag
        self._safe_register(tag, "node")
        self.ops.node(tag, float(coord[0]), float(coord[1]), float(coord[2]))
        self.node_map[tag] = {"node_tag": tag, "x": float(coord[0]), "y": float(coord[1]), "z": float(coord[2])}
        if fixity is not None:
            self.ops.fix(tag, *fixity)
            self.fix_map[tag] = {
                "node_tag": tag,
                "ux": fixity[0],
                "uy": fixity[1],
                "uz": fixity[2],
                "rx": fixity[3],
                "ry": fixity[4],
                "rz": fixity[5],
            }
        return tag

    def _add_node_mass(self, node_tag: int, translational_mass: float) -> None:
        if translational_mass == 0.0:
            return
        old = self.mass_map.get(int(node_tag), {})
        mx = float(old.get("mx", 0.0)) + translational_mass
        my = float(old.get("my", 0.0)) + translational_mass
        mz = float(old.get("mz", 0.0)) + translational_mass
        mrx = float(old.get("mrx", 0.0))
        mry = float(old.get("mry", 0.0))
        mrz = float(old.get("mrz", 0.0))
        self.ops.mass(int(node_tag), mx, my, mz, mrx, mry, mrz)
        self.mass_map[int(node_tag)] = {
            **old,
            "node_tag": int(node_tag),
            "mx": mx,
            "my": my,
            "mz": mz,
            "mrx": mrx,
            "mry": mry,
            "mrz": mrz,
        }

    def _create_line_section(self, line_name: str, material: dict[str, float], span: float, n_seg: int) -> dict[str, Any]:
        element_length = span / n_seg
        fallback_nonaxial = max(1.0e-8 * material["EA"] * element_length**2, 1.0e-12)
        eiy = material["EIy"] if material["EIy"] > 0.0 else fallback_nonaxial
        eiz = material["EIz"] if material["EIz"] > 0.0 else fallback_nonaxial
        gj = material["GJ"] if material["GJ"] > 0.0 else fallback_nonaxial

        axial_mat = self.tag_manager.get_next_tag(namespace="material")
        eiy_mat = self.tag_manager.get_next_tag(namespace="material")
        eiz_mat = self.tag_manager.get_next_tag(namespace="material")
        torsion_mat = self.tag_manager.get_next_tag(namespace="material")
        init_mat = self.tag_manager.get_next_tag(namespace="material")
        section_tag = self.tag_manager.get_next_tag(namespace="section")

        self.ops.uniaxialMaterial("Elastic", axial_mat, material["EA"])
        self.ops.uniaxialMaterial("Elastic", eiy_mat, eiy)
        self.ops.uniaxialMaterial("Elastic", eiz_mat, eiz)
        self.ops.uniaxialMaterial("Elastic", torsion_mat, gj)
        self.ops.uniaxialMaterial("InitStressMaterial", init_mat, axial_mat, material["initial_force"])
        self.ops.section("Aggregator", section_tag, init_mat, "P", eiz_mat, "Mz", eiy_mat, "My", torsion_mat, "T")

        material_records = [
            (axial_mat, "Elastic", "P_base", material["EA"]),
            (eiy_mat, "Elastic", "My", eiy),
            (eiz_mat, "Elastic", "Mz", eiz),
            (torsion_mat, "Elastic", "T", gj),
            (init_mat, "InitStressMaterial", "P", material["initial_force"]),
        ]
        for mat_tag, ops_type, component, stiffness in material_records:
            record = {
                "mat_tag": mat_tag,
                "line_name": line_name,
                "ops_type": ops_type,
                "component": component,
                "stiffness": stiffness,
                "initial_force": material["initial_force"] if ops_type == "InitStressMaterial" else 0.0,
            }
            self.transmission_line_material_map[mat_tag] = record
            self.material_tag_map[mat_tag] = record

        section_record = {
            "section_tag": section_tag,
            "line_name": line_name,
            "ops_type": "Aggregator",
            "axial_mat_tag": axial_mat,
            "init_mat_tag": init_mat,
            "eiy_mat_tag": eiy_mat,
            "eiz_mat_tag": eiz_mat,
            "torsion_mat_tag": torsion_mat,
            "EA": material["EA"],
            "EIy": eiy,
            "EIz": eiz,
            "GJ": gj,
            "area": material["area"],
            "initial_stress": material["initial_stress"],
            "initial_force": material["initial_force"],
        }
        self.transmission_line_section_map[section_tag] = section_record
        self.section_tag_map[section_tag] = section_record
        return section_record

    def _write_transmission_line_outputs(self) -> None:
        self._write_csv(
            self.line_output_dir / "line_nodes.csv",
            list(self.transmission_line_node_map.values()),
            ["line_name", "local_index", "node_tag", "x", "y", "z", "is_support"],
        )
        self._write_csv(
            self.line_output_dir / "line_elements.csv",
            list(self.transmission_line_element_map.values()),
            ["line_name", "local_index", "element_tag", "node_i", "node_j", "section_tag", "ops_type"],
        )
        self._write_csv(
            self.line_output_dir / "line_sections.csv",
            list(self.transmission_line_section_map.values()),
            [
                "section_tag",
                "line_name",
                "ops_type",
                "axial_mat_tag",
                "init_mat_tag",
                "eiy_mat_tag",
                "eiz_mat_tag",
                "torsion_mat_tag",
                "EA",
                "EIy",
                "EIz",
                "GJ",
                "area",
                "initial_stress",
                "initial_force",
            ],
        )
        self._write_csv(
            self.line_output_dir / "line_materials.csv",
            list(self.transmission_line_material_map.values()),
            ["mat_tag", "line_name", "ops_type", "component", "stiffness", "initial_force"],
        )
        self._write_csv(
            self.line_output_dir / "line_loads.csv",
            list(self.transmission_line_load_map.values()),
            ["line_name", "node_tag", "pattern_tag", "time_series_tag", "fx", "fy", "fz", "mx", "my", "mz"],
        )

    def build_one_line(
        self,
        name: str,
        *,
        apply_self_weight: bool = True,
        add_mass: bool = True,
        analyze: bool = False,
        n_steps: int = 100,
        verbose: bool = False,
    ) -> dict[str, Any]:
        """Append one transmission line to the current OpenSees model."""

        self._ensure_model_builder(ndm=3, ndf=6)
        self._register_tag()

        line_config = self._line_config(name)
        material = self._parse_line_material(name, line_config)
        support_tags, start, end, support_exists = self._resolve_hang_points(name, line_config)
        n_seg = self._segment_count(name, line_config)
        initial_sag = self._as_float(
            self._first_value(line_config, "initial_sag", "sag_guess", "sag", default=0.0),
            f"{name}.initial_sag",
        )
        gravity = self._as_float(line_config.get("gravity", 9.81), f"{name}.gravity")
        conductor_mass = resolve_conductor_mass(line_config, gravity=gravity)
        mass_per_length = conductor_mass.mass_per_length
        q_g = conductor_mass.weight_per_length
        span = float(np.linalg.norm(end - start))
        if span <= 0.0:
            raise ValueError(f"{name} 两个挂点重合，无法建立导线。")

        coords = self._line_coordinates(start, end, n_seg, initial_sag)
        line_node_tags: list[int] = []
        for index, coord in enumerate(coords):
            if index == 0:
                tag = self._create_node_if_needed(support_tags[0], coord, support_exists[0], (1, 1, 1, 1, 1, 1))
                is_support = True
            elif index == n_seg:
                tag = self._create_node_if_needed(support_tags[1], coord, support_exists[1], (1, 1, 1, 1, 1, 1))
                is_support = True
            else:
                tag = self._create_node_if_needed(None, coord, False, (0, 0, 0, 1, 1, 1))
                is_support = False
            line_node_tags.append(tag)
            record = {
                "line_name": name,
                "local_index": index,
                "node_tag": tag,
                "x": float(coord[0]),
                "y": float(coord[1]),
                "z": float(coord[2]),
                "is_support": int(is_support),
            }
            self.transmission_line_node_map[tag] = record
            self.node_map.setdefault(tag, {"node_tag": tag, "x": float(coord[0]), "y": float(coord[1]), "z": float(coord[2])})

        section_record = self._create_line_section(name, material, span, n_seg)
        section_tag = int(section_record["section_tag"])
        line_element_tags: list[int] = []
        for index in range(n_seg):
            ele_tag = self.tag_manager.get_next_tag(namespace="element")
            node_i = line_node_tags[index]
            node_j = line_node_tags[index + 1]
            self.ops.element("corotTrussSection", ele_tag, node_i, node_j, section_tag)
            record = {
                "line_name": name,
                "local_index": index,
                "element_tag": ele_tag,
                "node_i": node_i,
                "node_j": node_j,
                "section_tag": section_tag,
                "ops_type": "corotTrussSection",
            }
            self.transmission_line_element_map[ele_tag] = record
            self.element_map[ele_tag] = record
            line_element_tags.append(ele_tag)

        pattern_tag = None
        time_series_tag = None
        if apply_self_weight and q_g != 0.0:
            time_series_tag = self.tag_manager.get_next_tag(namespace="timeSeries")
            pattern_tag = self.tag_manager.get_next_tag(namespace="pattern")
            self.ops.timeSeries("Linear", time_series_tag)
            self.ops.pattern("Plain", pattern_tag, time_series_tag)

        node_tributary_lengths = tributary_lengths(coords)
        for node_tag, trib_length in zip(line_node_tags, node_tributary_lengths):
            if add_mass and mass_per_length != 0.0:
                self._add_node_mass(node_tag, mass_per_length * trib_length)
            if pattern_tag is not None and time_series_tag is not None:
                weight = q_g * trib_length
                self.ops.load(node_tag, 0.0, 0.0, -weight, 0.0, 0.0, 0.0)
                self.transmission_line_load_map[len(self.transmission_line_load_map) + 1] = {
                    "line_name": name,
                    "node_tag": node_tag,
                    "pattern_tag": pattern_tag,
                    "time_series_tag": time_series_tag,
                    "fx": 0.0,
                    "fy": 0.0,
                    "fz": -weight,
                    "mx": 0.0,
                    "my": 0.0,
                    "mz": 0.0,
                }

        line_record = {
            "line_name": name,
            "support_node_tags": [line_node_tags[0], line_node_tags[-1]],
            "node_tags": line_node_tags,
            "element_tags": line_element_tags,
            "section_tag": section_tag,
            "span": span,
            "n_seg": n_seg,
            "initial_sag": initial_sag,
            "q_g": q_g,
            "mass_per_length": mass_per_length,
            "conductor": conductor_mass.to_dict(),
            "conductor_length": sum(node_tributary_lengths),
            "total_conductor_mass": mass_per_length * sum(node_tributary_lengths),
            "material": material,
            "pattern_tag": pattern_tag,
            "time_series_tag": time_series_tag,
        }
        self.transmission_line_map[name] = line_record
        self._write_transmission_line_outputs()

        if analyze:
            line_record["analysis_success"] = self.run_static_analysis(n_steps=n_steps, verbose=verbose)
        return line_record

    def build_all_line(self, **kwargs: Any) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        for line_name in self.transmission_line_config:
            results[line_name] = self.build_one_line(line_name, **kwargs)
        return results

    def model_with_transmission_lines(self, **line_kwargs: Any) -> dict[str, Any]:
        tower_result = self.model_tower()
        line_result = self.build_all_line(**line_kwargs)
        return {
            **tower_result,
            "transmission_lines": line_result,
            "transmission_line_nodes": self.transmission_line_node_map,
            "transmission_line_elements": self.transmission_line_element_map,
            "tag_summary": self.tag_manager.summary(),
        }

    def run_static_analysis(self, n_steps: int = 100, verbose: bool = False) -> bool:
        ops = self.ops
        ops.wipeAnalysis()
        ops.constraints("Plain")
        ops.numberer("RCM")
        ops.system("BandGeneral")
        ops.test("NormDispIncr", 1.0e-8, 50)
        ops.algorithm("Newton")
        ops.integrator("LoadControl", 1.0 / int(n_steps))
        ops.analysis("Static")

        ok_total = 0
        for step in range(int(n_steps)):
            ok = ops.analyze(1)
            if ok != 0:
                if verbose:
                    print(f"常规 Newton 不收敛，step = {step + 1}，尝试减小荷载步。")
                ops.integrator("LoadControl", 1.0 / int(n_steps) / 10.0)
                ok = ops.analyze(10)
                ops.integrator("LoadControl", 1.0 / int(n_steps))
                if ok != 0:
                    ok_total = ok
                    break
        return ok_total == 0

    @staticmethod
    def calculate_sag_relative_to_chord(final_coords: np.ndarray, h1: float, h2: float, span: float) -> float:
        max_sag = -1.0e30
        for point in np.asarray(final_coords, dtype=float):
            x = point[0]
            z = point[2]
            chord_z = h1 + (h2 - h1) * x / span
            max_sag = max(max_sag, chord_z - z)
        return float(max_sag)

    @staticmethod
    def run_static_formfinding_with_init_stress(
        init_stress: float,
        L: float = 300.0,
        H1: float = 30.0,
        H2: float = 30.0,
        A: float = 4.0e-4,
        E: float = 7.0e10,
        q_g: float = 15.0,
        g: float = 9.81,
        n_seg: int = 60,
        initial_sag: float = 0.2,
        nonaxial_stiffness_ratio: float = 1.0e-8,
        n_steps: int = 100,
        verbose: bool = False,
        mass_per_length: float | None = None,
    ) -> tuple[float, np.ndarray, np.ndarray, bool]:
        """Standalone notebook form-finding routine.

        This method wipes the current OpenSees domain, so use it before building
        a coupled tower model or in a separate process.
        """

        import openseespy.opensees as ops

        ops.wipe()
        ops.model("basic", "-ndm", 3, "-ndf", 6)
        n_node = int(n_seg) + 1
        ea = E * A
        init_force = init_stress * A
        element_length = L / n_seg
        nonaxial_stiffness = max(nonaxial_stiffness_ratio * ea * element_length**2, 1.0e-12)

        ops.uniaxialMaterial("Elastic", 1, ea)
        ops.uniaxialMaterial("Elastic", 2, nonaxial_stiffness)
        ops.uniaxialMaterial("Elastic", 3, nonaxial_stiffness)
        ops.uniaxialMaterial("Elastic", 5, nonaxial_stiffness)
        ops.uniaxialMaterial("InitStressMaterial", 4, 1, init_force)
        ops.section("Aggregator", 1, 4, "P", 2, "Mz", 3, "My", 5, "T")

        initial_coords = []
        for index in range(n_node):
            xi = index / n_seg
            x = L * xi
            z_linear = H1 + (H2 - H1) * xi
            z = z_linear - 4.0 * initial_sag * xi * (1.0 - xi)
            ops.node(index + 1, x, 0.0, z)
            initial_coords.append((x, 0.0, z))

        if g <= 0.0:
            raise ValueError("g 必须大于 0。")
        if mass_per_length is None:
            resolved_mass_per_length = q_g / g
        else:
            resolved_mass_per_length = float(mass_per_length)
            if resolved_mass_per_length < 0.0 or not math.isfinite(resolved_mass_per_length):
                raise ValueError("mass_per_length 必须是非负有限数值。")
            q_g = resolved_mass_per_length * g
        node_tributary_lengths = tributary_lengths(initial_coords)
        for index, trib_length in enumerate(node_tributary_lengths):
            node_tag = index + 1
            node_mass = resolved_mass_per_length * trib_length
            ops.mass(node_tag, node_mass, node_mass, node_mass, 0.0, 0.0, 0.0)

        for node in range(1, n_node + 1):
            if node in (1, n_node):
                ops.fix(node, 1, 1, 1, 1, 1, 1)
            else:
                ops.fix(node, 0, 0, 0, 1, 1, 1)

        for index in range(n_seg):
            ops.element("corotTrussSection", index + 1, index + 1, index + 2, 1)

        ops.timeSeries("Linear", 1)
        ops.pattern("Plain", 1, 1)
        for index, trib_length in enumerate(node_tributary_lengths):
            node_tag = index + 1
            ops.load(node_tag, 0.0, 0.0, -q_g * trib_length, 0.0, 0.0, 0.0)

        ops.constraints("Plain")
        ops.numberer("RCM")
        ops.system("BandGeneral")
        ops.test("NormDispIncr", 1.0e-8, 50)
        ops.algorithm("Newton")
        ops.integrator("LoadControl", 1.0 / n_steps)
        ops.analysis("Static")

        ok_total = 0
        for step in range(n_steps):
            ok = ops.analyze(1)
            if ok != 0:
                if verbose:
                    print(f"常规 Newton 不收敛，step = {step + 1}，尝试减小荷载步。")
                ops.integrator("LoadControl", 1.0 / n_steps / 10.0)
                ok = ops.analyze(10)
                ops.integrator("LoadControl", 1.0 / n_steps)
                if ok != 0:
                    ok_total = ok
                    if verbose:
                        print(f"静力分析失败，init_stress = {init_stress:.6e}")
                    break

        final_coords = []
        for node in range(1, n_node + 1):
            coord = np.array(ops.nodeCoord(node), dtype=float)
            disp = np.array(ops.nodeDisp(node), dtype=float)
            final_coords.append(coord + disp[: coord.size])
        final_coords_array = np.array(final_coords, dtype=float)
        sag_final = TransmissionLineModel.calculate_sag_relative_to_chord(final_coords_array, H1, H2, L)

        axial_forces = []
        for element in range(1, n_seg + 1):
            try:
                response = ops.eleResponse(element, "axialForce")
                axial_forces.append(response[0] if isinstance(response, (list, tuple)) and response else np.nan)
            except Exception:
                axial_forces.append(np.nan)

        return sag_final, final_coords_array, np.array(axial_forces, dtype=float), ok_total == 0

    @classmethod
    def formfind_by_target_sag_static(
        cls,
        sag_target: float,
        sigma_low: float,
        sigma_high: float,
        tol_sag: float = 1.0e-3,
        max_iter: int = 40,
        verbose: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        sag_low, _, _, success_low = cls.run_static_formfinding_with_init_stress(sigma_low, **kwargs)
        sag_high, _, _, success_high = cls.run_static_formfinding_with_init_stress(sigma_high, **kwargs)
        if not success_low:
            raise RuntimeError("sigma_low 对应的静力分析失败，请调整 sigma_low 或分析参数。")
        if not success_high:
            raise RuntimeError("sigma_high 对应的静力分析失败，请调整 sigma_high 或分析参数。")
        if not (sag_low >= sag_target >= sag_high):
            raise ValueError(
                "当前 sigma_low 和 sigma_high 没有包络目标弧垂。通常需要满足 sag_low >= sag_target >= sag_high。"
            )

        history: list[dict[str, Any]] = []
        best_result: dict[str, Any] | None = None
        for iteration in range(1, int(max_iter) + 1):
            sigma_mid = 0.5 * (sigma_low + sigma_high)
            sag_mid, coords_mid, axial_mid, success_mid = cls.run_static_formfinding_with_init_stress(
                sigma_mid,
                **kwargs,
            )
            error = sag_mid - sag_target
            history.append(
                {
                    "iteration": iteration,
                    "init_stress": sigma_mid,
                    "sag": sag_mid,
                    "error": error,
                    "success": success_mid,
                }
            )
            if verbose:
                print(
                    f"{iteration:6d} | {sigma_mid / 1e6:16.6f} | {sag_mid:12.6f} | "
                    f"{error:12.6e} | {str(success_mid):>8s}"
                )
            if not success_mid:
                raise RuntimeError(f"二分过程中静力分析失败，iteration = {iteration}")
            best_result = {
                "init_stress": sigma_mid,
                "sag": sag_mid,
                "error": error,
                "final_coords": coords_mid,
                "axial_forces": axial_mid,
                "success": success_mid,
                "iteration": iteration,
                "history": history,
            }
            if abs(error) < tol_sag:
                return best_result
            if sag_mid > sag_target:
                sigma_low = sigma_mid
            else:
                sigma_high = sigma_mid
        if best_result is None:
            raise RuntimeError("未得到有效找形结果。")
        return best_result

    def run_modal_analysis(self, num_modes: int = 6) -> dict[str, Any]:
        ops = self.ops
        ops.wipeAnalysis()
        try:
            eigenvalues = np.array(ops.eigen(num_modes), dtype=float)
        except Exception:
            eigenvalues = np.array(ops.eigen("-fullGenLapack", num_modes), dtype=float)
        omega = np.full_like(eigenvalues, np.nan, dtype=float)
        positive = eigenvalues > 0.0
        omega[positive] = np.sqrt(eigenvalues[positive])
        frequencies = omega / (2.0 * np.pi)
        periods = np.full_like(frequencies, np.inf, dtype=float)
        valid_freq = frequencies > 0.0
        periods[valid_freq] = 1.0 / frequencies[valid_freq]

        node_tags = sorted(int(tag) for tag in ops.getNodeTags())
        mode_shapes = np.zeros((len(eigenvalues), len(node_tags), 3), dtype=float)
        for mode_index in range(len(eigenvalues)):
            mode_tag = mode_index + 1
            for node_index, node_tag in enumerate(node_tags):
                eigenvector = np.array(ops.nodeEigenvector(node_tag, mode_tag), dtype=float)
                mode_shapes[mode_index, node_index, :] = eigenvector[:3]
            scale = np.max(np.linalg.norm(mode_shapes[mode_index], axis=1))
            if scale > 0.0:
                mode_shapes[mode_index] /= scale
        return {
            "eigenvalues": eigenvalues,
            "omega": omega,
            "frequencies": frequencies,
            "periods": periods,
            "mode_shapes": mode_shapes,
            "node_tags": node_tags,
        }


# Backward-compatible spellings kept because the directory/file name uses
# ``transimission`` in the existing project.
TransimissionLineModel = TransmissionLineModel
transimission = TransmissionLineModel


if __name__ == "__main__":
    model = TransmissionLineModel("TransmissionLine", "/home/panqiheng/OTW/Source/Z30103A6.s2k")
    model.model_tower()
    print(model.build_all_line())
