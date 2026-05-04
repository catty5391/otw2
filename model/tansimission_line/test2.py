# -*- coding: utf-8 -*-
import math
import openseespy.opensees as ops
import matplotlib.pyplot as plt


def _safe_scalar(x):
    """把 eleResponse 之类的返回值统一转成标量"""
    if isinstance(x, (list, tuple)):
        return float(x[0])
    return float(x)


def run_form_finding(
    init_stress,          # 初始应力，单位 Pa
    L=300.0,              # 档距，m
    n_seg=20,             # 单元数
    A=3.0e-4,             # 导线截面积，m^2
    E=1.60e11,            # 弹性模量，Pa
    w=12.0,               # 导线自重线荷载，N/m
    y_left=0.0,           # 左挂点标高
    y_right=0.0           # 右挂点标高
):
    """
    单次找形：
    给定一个初始应力 init_stress，施加自重后求平衡形态。
    返回：
        sag        : 中跨弧垂（相对于两端连线），m
        avg_N      : 平均轴力，N
        xs, ys     : 平衡后节点坐标
    """
    ops.wipe()
    ops.model('basic', '-ndm', 2, '-ndf', 2)

    dx = L / n_seg

    # -----------------------------
    # 1) 建立节点：初始几何先取两端直线
    # -----------------------------
    for i in range(n_seg + 1):
        x = i * dx
        y = y_left + (y_right - y_left) * x / L
        ops.node(i + 1, x, y)

    # 两端挂点固定
    ops.fix(1, 1, 1)
    ops.fix(n_seg + 1, 1, 1)

    # -----------------------------
    # 2) 材料：Elastic + InitStressMaterial
    # -----------------------------
    mat_elastic = 1
    mat_init = 2
    ops.uniaxialMaterial('Elastic', mat_elastic, E)
    ops.uniaxialMaterial('InitStressMaterial', mat_init, mat_elastic, init_stress)

    # -----------------------------
    # 3) 单元：corotTruss
    # -----------------------------
    for e in range(1, n_seg + 1):
        ops.element('corotTruss', e, e, e + 1, A, mat_init)

    # -----------------------------
    # 4) 自重：等效成节点竖向荷载
    #    每个内部节点承担一段左半 + 一段右半 => w*dx
    #    两端节点承担半段 => w*dx/2
    # -----------------------------
    ops.timeSeries('Linear', 1)
    ops.pattern('Plain', 1, 1)

    for i in range(1, n_seg + 2):
        tributary = dx if (1 < i < n_seg + 1) else dx / 2.0
        p = -w * tributary
        ops.load(i, 0.0, p)

    # -----------------------------
    # 5) 静力分析
    # -----------------------------
    ops.constraints('Plain')
    ops.numberer('RCM')
    ops.system('BandGeneral')
    ops.test('NormDispIncr', 1.0e-10, 100, 0)
    ops.algorithm('Newton')
    ops.integrator('LoadControl', 0.05)   # 20步加载完成
    ops.analysis('Static')

    ok = 0
    for _ in range(20):
        ok = ops.analyze(1)
        if ok != 0:
            # 简单回退策略
            ops.test('NormDispIncr', 1.0e-8, 200, 0)
            ops.algorithm('ModifiedNewton')
            ok = ops.analyze(1)
            ops.algorithm('Newton')
            if ok != 0:
                raise RuntimeError("分析未收敛，请调整初始应力、分段数或步长。")

    # -----------------------------
    # 6) 读取平衡后坐标
    # -----------------------------
    xs, ys = [], []
    for nd in range(1, n_seg + 2):
        x0, y0 = ops.nodeCoord(nd)
        ux, uy = ops.nodeDisp(nd)
        xs.append(x0 + ux)
        ys.append(y0 + uy)

    # -----------------------------
    # 7) 计算弧垂（相对两端连线）
    #    这里取中点节点，也可改成全节点最大下挠
    # -----------------------------
    mid_node = n_seg // 2 + 1
    x_mid = xs[mid_node - 1]
    y_mid = ys[mid_node - 1]

    # 两端连线在 mid 处的标高
    y_chord_mid = ys[0] + (ys[-1] - ys[0]) * (x_mid - xs[0]) / (xs[-1] - xs[0])

    # 弧垂取向下为正
    sag = y_chord_mid - y_mid

    # -----------------------------
    # 8) 读取平均轴力
    # -----------------------------
    Ns = []
    for e in range(1, n_seg + 1):
        N = _safe_scalar(ops.eleResponse(e, 'axialForce'))
        Ns.append(N)
    avg_N = sum(Ns) / len(Ns)

    return sag, avg_N, xs, ys


def find_init_stress_by_target_sag(
    target_sag,           # 目标弧垂，m
    sigma_lo=1.0e6,       # 初始应力下界，Pa
    sigma_hi=3.0e8,       # 初始应力上界，Pa
    tol=1.0e-3,           # 弧垂容差，m
    max_iter=40,
    **kwargs
):
    """
    用二分法寻找满足目标弧垂的初始应力
    规律：初始应力越大，导线越紧，弧垂越小
    """

    # 先自动扩展区间，保证把 target_sag 夹在中间
    sag_lo, _, _, _ = run_form_finding(sigma_lo, **kwargs)
    sag_hi, _, _, _ = run_form_finding(sigma_hi, **kwargs)

    # 希望 sag_lo > target_sag > sag_hi
    # 若不满足，自动扩展
    count = 0
    while sag_lo < target_sag and count < 20:
        sigma_lo *= 0.5
        sag_lo, _, _, _ = run_form_finding(sigma_lo, **kwargs)
        count += 1

    count = 0
    while sag_hi > target_sag and count < 20:
        sigma_hi *= 2.0
        sag_hi, _, _, _ = run_form_finding(sigma_hi, **kwargs)
        count += 1

    if not (sag_lo >= target_sag >= sag_hi):
        raise RuntimeError(
            f"未能找到合适的初始应力包络区间：\n"
            f"sigma_lo={sigma_lo:.3e}, sag_lo={sag_lo:.6f}\n"
            f"sigma_hi={sigma_hi:.3e}, sag_hi={sag_hi:.6f}\n"
            f"请手动调整上下界。"
        )

    best = None
    for it in range(1, max_iter + 1):
        sigma_mid = 0.5 * (sigma_lo + sigma_hi)
        sag_mid, avg_N, xs, ys = run_form_finding(sigma_mid, **kwargs)

        best = (sigma_mid, sag_mid, avg_N, xs, ys)

        err = sag_mid - target_sag
        print(
            f"iter={it:02d}, sigma0={sigma_mid:.6e} Pa, "
            f"sag={sag_mid:.6f} m, err={err:+.6f} m, avgN={avg_N:.3f} N"
        )

        if abs(err) <= tol:
            break

        # sag_mid 偏大 -> 线太松 -> 需要增大初始应力
        if sag_mid > target_sag:
            sigma_lo = sigma_mid
        else:
            sigma_hi = sigma_mid

    return best


if __name__ == "__main__":
    # -----------------------------
    # 示例参数
    # -----------------------------
    L = 300.0          # 档距 m
    n_seg = 24
    A = 3.0e-4         # 截面积 m^2
    E = 1.60e11        # 弹模 Pa
    w = 12.0           # 自重 N/m
    target_sag = 8.0   # 目标弧垂 m

    sigma0, sag, avg_N, xs, ys = find_init_stress_by_target_sag(
        target_sag=target_sag,
        sigma_lo=5.0e6,
        sigma_hi=2.0e8,
        tol=1.0e-4,
        max_iter=30,
        L=L,
        n_seg=n_seg,
        A=A,
        E=E,
        w=w,
        y_left=0.0,
        y_right=0.0
    )

    print("\n====== 最终结果 ======")
    print(f"初始应力 sigma0 = {sigma0:.6e} Pa")
    print(f"对应初始张力 T0 = sigma0 * A = {sigma0 * A:.3f} N")
    print(f"平衡弧垂 sag = {sag:.6f} m")
    print(f"平均轴力 avgN = {avg_N:.3f} N")

    # 绘图
    plt.figure(figsize=(9, 4))
    plt.plot(xs, ys, '-o', ms=4, label='equilibrium shape')
    plt.plot([xs[0], xs[-1]], [ys[0], ys[-1]], '--', label='support chord')
    plt.xlabel('x (m)')
    plt.ylabel('y (m)')
    plt.title('Conductor Form Finding by Initial Stress Method')
    plt.grid(True, ls='--', alpha=0.4)
    plt.legend()
    plt.tight_layout()
    plt.show()