import math

import numpy as np
import openseespy.opensees as ops
left_hang_node = [0, 0, 36]
right_hang_node = [0, 500, 36]
EA = 8.222e7
g = 29.751e3
separate = 100
initial_stress = 52.85e6
probe_load = -10.0

# Keep the same initial geometry in both cases so we can isolate the effect of
# the material initial stress from the effect of the starting shape.
shape_reference_force = initial_stress

# Use A = 1.0 so the truss axial stiffness remains EA and the InitStressMaterial
# value can be compared directly with the previous script's numeric input.
area = 1.0
elastic_modulus = EA / area

def initial_line(x):
    x0 = left_hang_node[1]
    y0 = left_hang_node[2]
    tan_beta = (y0 - right_hang_node[2]) / (x0 - right_hang_node[1])
    cos_beta = 1 / math.sqrt(1 + tan_beta**2)
    span = right_hang_node[1] - left_hang_node[1]
    return y0 + (x - x0) * tan_beta - g * (x - x0) * (span - (x - x0)) / (
        2 * shape_reference_force * cos_beta
    )

def create_nodes():
    node_tags = []
    x_coords = np.linspace(left_hang_node[1], right_hang_node[1], num=separate)
    z_coords = initial_line(x_coords)

    for index, (x_coord, z_coord) in enumerate(zip(x_coords, z_coords), start=1):
        ops.node(index, float(x_coord), float(z_coord))
        node_tags.append(index)
    return node_tags

def create_elements(node_tags, use_initial_stress):
    ops.uniaxialMaterial("Elastic", 1, elastic_modulus)
    if use_initial_stress:
        ops.uniaxialMaterial("InitStressMaterial", 2, 1, initial_stress)
        material_tag = 2
    else:
        material_tag = 1

    element_tags = []
    for index in range(len(node_tags) - 1):
        element_tag = index + 1
        ops.element(
            "corotTruss",
            element_tag,
            node_tags[index],
            node_tags[index + 1],
            area,
            material_tag,
        )
        element_tags.append(element_tag)
    return element_tags

def element_axial_force(element_tag):
    for query in (("axialForce",), ("forces",), ("localForce",)):
        try:
            return query[0], ops.eleResponse(element_tag, *query)
        except Exception:
            continue
    return "unavailable", None

def run_case(use_initial_stress):
    ops.wipe()
    ops.model("basic", "-ndm", 2, "-ndf", 2)
    node_tags = create_nodes()
    element_tags = create_elements(node_tags, use_initial_stress)

    ops.fix(node_tags[0], 1, 1)
    ops.fix(node_tags[-1], 1, 1)

    mid_node = node_tags[len(node_tags)//2]
    mid_ele = element_tags[len(element_tags)//2]
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    ops.load(mid_node, 0.0, probe_load)

    ops.constraints("Plain")
    ops.numberer("RCM")
    ops.system("BandGeneral")
    ops.test("NormUnbalance", 1.0e-6, 100, 2)
    ops.algorithm("Newton")
    ops.integrator("LoadControl", 1.0)
    ops.analysis("Static")

    ok = ops.analyze(1)

    mid_coord = ops.nodeCoord(mid_node)
    mid_disp = ops.nodeDisp(mid_node)
    axial_query, axial_force = element_axial_force(mid_ele)

    ops.reactions()

    label = "with initial stress" if use_initial_stress else "without initial stress"
    print(f"\n--- {label} ---")
    print("analyze ok =", ok)
    print("mid coord =", mid_coord)
    print("mid disp =", mid_disp)
    print(
        "mid deformed coord =",
        [mid_coord[i] + mid_disp[i] for i in range(len(mid_coord))],
    )
    print(f"mid element {axial_query} =", axial_force)
    print("left reaction =", ops.nodeReaction(node_tags[0]))
    print("right reaction =", ops.nodeReaction(node_tags[-1]))

if __name__ == "__main__":
    run_case(use_initial_stress=False)
    run_case(use_initial_stress=True)
