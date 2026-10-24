"""Exploratory TMQ axial + elastic bending/torsion whole-tower beam network.

One straight Corotational dispBeamColumn per physical member, no extra bow.
Not a calibrated angle-steel model: P/My/Mz/T are uncoupled; I23 is omitted.
"""
from dataclasses import replace
import math

from model.tower_model import OpenSeesModel
from initial_imperfection_material.material import MemberProperties, EquivalentImperfectionMaterial
from initial_imperfection_material.tian_ma_qu.cases import literature_cases
from initial_imperfection_material.tian_ma_qu.section_adapter import AxialSectionMaterial, CopyRegistry
from initial_imperfection_material.tian_ma_qu.opensees_adapter import register_model


class OpenSeesModelWithTianMaQu(OpenSeesModel):
    def __init__(self, *args, axial_mode="tmq", coefficient_case="p102_row_a",
                 imperfection_ratio=.001, **kwargs):
        super().__init__(*args, **kwargs)
        if axial_mode not in {"tmq", "elastic"}:
            raise ValueError("axial_mode must be tmq or elastic")
        if not math.isfinite(imperfection_ratio) or imperfection_ratio <= 0:
            raise ValueError("imperfection_ratio must be positive")
        cases = {c.key: c for c in literature_cases()}
        self.template = cases[coefficient_case].parameters
        self.coefficient_case = coefficient_case
        self.axial_mode = axial_mode
        self.imperfection_ratio = imperfection_ratio
        self.registries, self.member_parameters, self.native_metadata = {}, {}, None

    def element(self):
        basics = {self._parse_key_values(line)["Material"]: self._parse_key_values(line)
                  for line in self._table_lines("MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES")}
        steels = {self._parse_key_values(line)["Material"]: self._parse_key_values(line)
                  for line in self._table_lines("MATERIAL PROPERTIES 03A - STEEL DATA")}
        sections = self._frame_section_properties()
        assignments = self._element_section_assignments()
        rows, parameter_rows = [], []
        for tag, item in sorted(self._parse_element_connectivity().items()):
            ni, nj = self.node_map[item["node_i"]], self.node_map[item["node_j"]]
            length = math.dist(tuple(ni[k] for k in "xyz"), tuple(nj[k] for k in "xyz"))
            name = assignments[tag]["section_name"]
            sec = sections[name]
            steel = sec["material_name"]
            E, fy, area = float(basics[steel]["E1"]), float(steels[steel]["Fy"]) * 1e6, float(sec["area"])
            i22, i33, i23 = (float(sec[k]) for k in ("i22", "i33", "i23"))
            weak = .5 * (i22 + i33 - math.sqrt((i22-i33)**2 + 4*i23*i23))
            leg, thickness = self._l_section_dimensions(name)
            member = MemberProperties.from_equal_angle(name=name, length=length, leg_width=leg,
                thickness=thickness, area=area, inertia_weak=weak, elastic_modulus=E,
                yield_strength=fy, steel_hardening_ratio=self.steel01_b)
            # First-fiber-yield Perry estimate, NOT a calibrated ultimate capacity.
            peak = EquivalentImperfectionMaterial._perry_peak_load(member, self.imperfection_ratio)
            p = replace(self.template, elastic_modulus=E, yield_stress=fy,
                        phi=peak/(area*fy), rho=self.steel01_b,
                        provenance=f"tower S2K E/fy/A/L; Perry first-yield phi K=1 e0/L={self.imperfection_ratio}; "
                                   f"{self.coefficient_case} tube cyclic coefficients transferred UNVALIDATED")
            tags = [self.tag_manager.get_next_tag(namespace="material") for _ in range(4)]
            if self.axial_mode == "tmq":
                registry = CopyRegistry()
                self.registries[tag] = registry
                self.native_metadata = register_model(tags[0], AxialSectionMaterial(p, area, registry))
            else:
                self.ops.uniaxialMaterial("Elastic", tags[0], E*area)
            for mat_tag, stiffness in zip(tags[1:], (E*i33, E*i22, E/2.6*float(sec["tors_const"]))):
                self.ops.uniaxialMaterial("Elastic", mat_tag, stiffness)
            section_tag = self.tag_manager.get_next_tag(namespace="section")
            self.ops.section("Aggregator", section_tag, tags[0], "P", tags[1], "Mz", tags[2], "My", tags[3], "T")
            transf = self.tag_manager.get_next_tag(namespace="transf")
            vec = self._geom_transf_vector(ni, nj)
            self.ops.geomTransf("Corotational", transf, *vec)
            integration = self.tag_manager.get_next_tag(namespace="integration")
            self.ops.beamIntegration("Legendre", integration, section_tag, 3)
            self.ops.element("dispBeamColumn", tag, item["node_i"], item["node_j"], transf, integration)
            row = dict(tower_id=self.tower_id, element_tag=tag, original_element_tag=tag,
                       local_element_tag=item.get("local_element_tag"), frame_name=item.get("frame_name", ""),
                       node_i=item["node_i"], node_j=item["node_j"], section_name=name, material_name=steel,
                       mat_tag=tags[0], section_tag=section_tag, transf_tag=transf, integration_tag=integration,
                       integration_type="Legendre", num_intgr_pts=3, length=length, area=area,
                       ops_type="dispBeamColumn-tmq-axial" if self.axial_mode == "tmq" else "dispBeamColumn-elastic-control")
            self.element_map[tag] = row
            self.section_tag_map[section_tag] = {"section_tag": section_tag, "element_tag": tag}
            self.transf_map[tag] = {"transf_tag": transf, "element_tag": tag, **dict(zip(("vec_x", "vec_y", "vec_z"), vec))}
            self.integration_map[integration] = {"integration_tag": integration, "section_tag": section_tag}
            parameter_row = dict(element_tag=tag, section_name=name, material_name=steel,
                                 length_m=length, area_m2=area, weak_inertia_m4=weak,
                                 slenderness_K1=member.slenderness_ratio, perry_first_yield_N=peak, **p.to_dict())
            self.member_parameters[tag] = parameter_row
            self.material_tag_map[tags[0]] = parameter_row
            parameter_rows.append(parameter_row)
            rows.append(row)
        self._write_csv(self.output_dir / "elements.csv", rows, list(rows[0]))
        self._write_csv(self.output_dir / "tmq_member_parameters.csv", parameter_rows, list(parameter_rows[0]))
        return self.element_map

    def model_tower(self):
        self.node()
        self.fix()
        self.mass()
        self.element()
        return {"nodes": self.node_map, "elements": self.element_map, "materials": self.material_tag_map}

    def committed_member_states(self):
        """Uniform axial strain in this dispBeamColumn: require all three copies.

        Record one representative only after verifying P states agree. This is
        not a fiber-strain measure and not an integration-point damage index.
        """
        result = []
        for tag, registry in self.registries.items():
            copies = registry.committed()
            if len(copies) != 3:
                raise RuntimeError(f"member {tag}: expected 3 active copies, got {len(copies)}")
            states = [m.material.get_state() for m in copies]
            first = states[0]
            if any(abs(s["strain"]-first["strain"]) > 1e-12 or
                   abs(s["stress"]-first["stress"]) > .001 or s["stage"] != first["stage"] for s in states[1:]):
                raise RuntimeError(f"member {tag}: axial integration states disagree")
            p = self.member_parameters[tag]
            result.append(dict(element_tag=tag, strain=first["strain"], stress_Pa=first["stress"],
                force_N=first["stress"]*p["area_m2"], stage=first["stage"],
                buckling_count=first["buckling_count"], min_strain=first["min_strain"], max_strain=first["max_strain"],
                tension_yield_ever=copies[0].tension_yield_ever,
                external_work_J=first["external_work_density"]*p["area_m2"]*p["length_m"], active_copies=3))
        return result
