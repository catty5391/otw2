import openseespy.opensees as ops
import math
import numpy as np


def build_transmission_line_formfinding():
    ops.wipe()

    # ============================================================
    # 1. 基本参数
    # ============================================================
    L = 300.0          # 档距，m
    H1 = 30.0          # 左侧挂点高度，m
    H2 = 30.0          # 右侧挂点高度，m

    n_seg = 60         # 导线离散段数
    n_node = n_seg + 1

    A = 4.0e-4         # 导线截面面积，m2
    E = 7.0e10         # 弹性模量，Pa
    rho = 2700.0       # 材料密度，kg/m3
    g = 9.81           # 重力加速度，m/s2

    T0 = 20000.0       # 初始水平张力，N
    init_stress = T0 / A

    # 给初始几何一个很小的下挠扰动，避免完全直线构型数值上过于理想
    initial_sag = 0.1  # m

    # ============================================================
    # 2. 建立三维模型
    # ============================================================
    ops.model("basic", "-ndm", 3, "-ndf", 3)

    # ============================================================
    # 3. 定义材料
    # ============================================================
    # 基础弹性材料
    ops.uniaxialMaterial("Elastic", 1, E)

    # 带初始应力的材料
    # 注意：这里的 init_stress 是初始应力，不是初始张力
    ops.uniaxialMaterial("InitStressMaterial", 2, 1, init_stress)

    # ============================================================
    # 4. 建立节点
    # ============================================================
    node_tags = []

    for i in range(n_node):
        x = L * i / n_seg
        y = 0.0

        # 两端高度线性插值
        z_linear = H1 + (H2 - H1) * i / n_seg

        # 初始给一个很小的抛物线下挠
        xi = i / n_seg
        z = z_linear - 4.0 * initial_sag * xi * (1.0 - xi)

        tag = i + 1
        ops.node(tag, x, y, z)
        node_tags.append(tag)

    # ============================================================
    # 5. 边界条件
    # ============================================================
    # 两端挂点固定
    ops.fix(1, 1, 1, 1)
    ops.fix(n_node, 1, 1, 1)

    # ============================================================
    # 6. 建立 corotTruss 单元
    # ============================================================
    # corotTruss 适合大位移、小应变的索 / 杆问题
    ele_tags = []

    for i in range(n_seg):
        ele_tag = i + 1
        i_node = i + 1
        j_node = i + 2

        ops.element(
            "corotTruss",
            ele_tag,
            i_node,
            j_node,
            A,
            2,
            "-rho",
            rho,
            "-cMass",
            1
        )

        ele_tags.append(ele_tag)

    # ============================================================
    # 7. 设置节点质量
    # ============================================================
    # 动态松弛法需要质量。这里按导线线密度等效到节点。
    # 线密度 = rho * A
    mass_per_length = rho * A

    for i in range(n_node):
        if i == 0:
            trib_length = L / n_seg / 2.0
        elif i == n_node - 1:
            trib_length = L / n_seg / 2.0
        else:
            trib_length = L / n_seg

        m = mass_per_length * trib_length
        ops.mass(i + 1, m, m, m)

    # ============================================================
    # 8. 施加重力荷载
    # ============================================================
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)

    for i in range(n_node):
        node_tag = i + 1

        if i == 0:
            trib_length = L / n_seg / 2.0
        elif i == n_node - 1:
            trib_length = L / n_seg / 2.0
        else:
            trib_length = L / n_seg

        weight = mass_per_length * trib_length * g

        # 全局 Z 方向向下
        ops.load(node_tag, 0.0, 0.0, -weight)

    # ============================================================
    # 9. 动态松弛分析设置
    # ============================================================
    ops.constraints("Plain")
    ops.numberer("RCM")
    ops.system("BandGeneral")

    # 收敛测试
    ops.test("NormDispIncr", 1.0e-8, 50)

    # 非线性算法
    ops.algorithm("Newton")

    # Newmark 平均加速度法
    ops.integrator("Newmark", 0.5, 0.25)

    ops.analysis("Transient")

    # Rayleigh 阻尼
    # 动态松弛的关键是较大的阻尼，使振动逐渐衰减到平衡位置
    alpha_m = 1.0
    beta_k = 0.0
    beta_k_init = 0.0
    beta_k_comm = 0.0
    ops.rayleigh(alpha_m, beta_k, beta_k_init, beta_k_comm)

    # ============================================================
    # 10. 开始动态松弛迭代
    # ============================================================
    dt = 0.02
    max_steps = 20000

    tol_vel = 1.0e-5
    tol_disp_change = 1.0e-7

    last_coords = {}

    for node in node_tags:
        last_coords[node] = np.array(ops.nodeCoord(node), dtype=float) + np.array(ops.nodeDisp(node), dtype=float)

    converged = False

    for step in range(max_steps):
        ok = ops.analyze(1, dt)

        if ok != 0:
            print(f"分析在 step = {step} 不收敛，尝试减小时间步长。")
            ok = ops.analyze(1, dt * 0.5)

            if ok != 0:
                print("减小时间步后仍不收敛，分析终止。")
                break

        # 每隔一定步数检查一次速度和位移变化
        if step % 100 == 0:
            max_vel = 0.0
            max_disp_change = 0.0

            for node in node_tags:
                vel = np.array(ops.nodeVel(node), dtype=float)
                max_vel = max(max_vel, np.linalg.norm(vel))

                current_coord = np.array(ops.nodeCoord(node), dtype=float) + np.array(ops.nodeDisp(node), dtype=float)
                disp_change = np.linalg.norm(current_coord - last_coords[node])
                max_disp_change = max(max_disp_change, disp_change)

                last_coords[node] = current_coord

            print(
                f"step = {step:6d}, "
                f"max_vel = {max_vel:.4e}, "
                f"max_coord_change = {max_disp_change:.4e}"
            )

            if max_vel < tol_vel and max_disp_change < tol_disp_change:
                converged = True
                print("动态松弛找形收敛。")
                break

    if not converged:
        print("达到最大步数，未完全满足收敛准则。")

    # ============================================================
    # 11. 输出找形后的节点坐标
    # ============================================================
    final_coords = []

    print("\n找形后的导线节点坐标：")
    print("nodeTag, X, Y, Z")

    for node in node_tags:
        coord = np.array(ops.nodeCoord(node), dtype=float)
        disp = np.array(ops.nodeDisp(node), dtype=float)
        final_coord = coord + disp

        final_coords.append(final_coord)

        print(
            f"{node:4d}, "
            f"{final_coord[0]:12.6f}, "
            f"{final_coord[1]:12.6f}, "
            f"{final_coord[2]:12.6f}"
        )

    # ============================================================
    # 12. 计算最终弧垂
    # ============================================================
    z_values = [p[2] for p in final_coords]
    min_z = min(z_values)

    support_z_min = min(H1, H2)
    sag = support_z_min - min_z

    print(f"\n最终最大弧垂约为：{sag:.6f} m")

    return final_coords


if __name__ == "__main__":
    final_shape = build_transmission_line_formfinding()