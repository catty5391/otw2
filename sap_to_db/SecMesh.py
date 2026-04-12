"""
SecMesh: A module to mesh the cross-section with triangular fibers

Author: Yexiang Yan
Email: yexiang_yan@outlook.com
WeChat: yx592715024
"""

import matplotlib.collections
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
import numpy as np
import pygmsh
from numpy.typing import ArrayLike
from shapely.geometry import Polygon


class sec_base:
    """
    A class for generating fiber-based OpenSees sections based on triangular cells.
    """

    def __init__(self):
        """
        None
        """

        self.outline = None  # 截面外轮廓线
        self.holes = []  # 将开口初始化为一个空列表
        # 保存所有钢筋的信息
        self.rebar_coords = []  # 钢筋坐标
        self.rebar_areas = []  # 钢筋面积
        # 保存所有的网格划分对象
        self.mesh_obj = []

        # 默认颜色
        self.colors = ['#0099e5', '#ffb900', '#6a67ce', '#00a98f']
        self.color_rebar = '#be0027'

    def add_outline(self, points: ArrayLike):
        """
        param points:  Coordinates for section profile, List-like, [(x1, y1), (x2, y2),...,(xn,yn)].
        clockwise, the beginning and end do not need to be closed.
        It can be defined by the corner points of the section, with a straight line segment between points.
        Curves need to be subdivided.
        """

        self.outline = Polygon(points)
        # points = list(self.outline.exterior.coords)
        # x, y = self.outline.exterior.xy

    def add_outline_circle(self, center=(0, 0), radius=1):
        xo, yo = center
        alpha = np.linspace(0, 2 * np.pi, 24, endpoint=False)
        xcoords = xo + radius * np.cos(alpha)
        ycoords = yo + radius * np.sin(alpha)
        points = [(x, y) for x, y in zip(xcoords, ycoords)]
        self.outline = Polygon(points)

    def add_hole(self, points: ArrayLike):
        self.holes.append(Polygon(points))

    def add_rebar_outline(self, dia, gap, d):
        # 偏移获得最外层钢筋线的坐标
        outline_rebar = self.outline.buffer(
            -d - dia / 2, cap_style=3, join_style=2)
        x, y = outline_rebar.exterior.xy
        # 根据间距重新划分钢筋点
        extern_rebar_points = lines_subdivide(x, y, gap)  # 最外层钢筋点
        for rebar_xy in extern_rebar_points:
            self.rebar_coords.append(rebar_xy)
            self.rebar_areas.append(np.pi / 4 * dia ** 2)

    def add_rebar_hole(self, dia, gap, d):
        # 最内层钢筋点，仅在 holes 定义的情况下才定义
        if self.holes:  # 如果不是空列表
            for hole_line in self.holes:
                # 对开口的轮廓进行偏移，以获得最内层钢筋线
                inner_rebar_line = hole_line.buffer(
                    d + dia / 2, cap_style=3, join_style=2)
                x, y = inner_rebar_line.exterior.xy
                # 根据间距重新划分钢筋点
                rebar_xy = lines_subdivide(x, y, gap)
                for xy in rebar_xy:
                    self.rebar_coords.append(xy)
                    self.rebar_areas.append(np.pi / 4 * dia ** 2)

    def add_rebar_line(self, points, dia, gap):
        # 处理除最外层与最内层之外的额外的钢筋
        rebar_lines = Polygon(points)
        x, y = rebar_lines.exterior.xy
        # 根据间距重新划分钢筋点
        rebar_xy = lines_subdivide(x, y, gap)
        for xy in rebar_xy:
            self.rebar_coords.append(xy)
            self.rebar_areas.append(np.pi / 4 * dia ** 2)

    def set_colors(self, colors):
        self.colors = colors

    def centring(self):
        # 将截面移动到形心位置
        _, _, sec_property = mesh_geom(self.mesh_obj)
        for mesh in self.mesh_obj:
            vertices = mesh.points - np.array(sec_property['center'])  # 将原点转移到形心位置
            mesh.points = vertices
        if len(self.rebar_coords) > 0:
            self.rebar_coords = np.array(self.rebar_coords)
            self.rebar_areas = np.array(self.rebar_areas)
            # 将原点转移到形心位置
            self.rebar_coords -= np.array(sec_property['center'])

    def rotate(self, theta=0):
        # 顺时针转动截面
        # 先求截面形心
        self.rebar_coords = np.array(self.rebar_coords)
        theta = theta / 180 * np.pi  # 转换成弧度制
        self.centring()
        for mesh in self.mesh_obj:
            vertices = mesh.points
            x = vertices[:, 0]
            y = vertices[:, 1]
            x_rot, y_rot = sec_rotation(x, y, theta)  # 将各坐标转动theta
            mesh.points[:, 0] = x_rot
            mesh.points[:, 1] = y_rot
        if len(self.rebar_coords) > 0:
            # 将原点转移到形心位置
            self.rebar_coords[:, 0], self.rebar_coords[:, 1] = \
                sec_rotation(
                    self.rebar_coords[:, 0], self.rebar_coords[:, 1], theta)

    def sec_props(self):
        _, _, sec_property = mesh_geom(self.mesh_obj)
        return sec_property

    def ops_cmds_py(self, secTag: int, matTags: ArrayLike, GJ: float):
        """
        生成opensees纤维命令
        :param secTag: 截面号
        :param matTags: 材料号，列表样
        :param GJ: 扭转常数
        :return: None
        """
        import openseespy.opensees as ops

        fiber_center, fiber_area, sec_property = mesh_geom(self.mesh_obj)
        fiber_center.append(np.array(self.rebar_coords))
        fiber_area.append(np.array(self.rebar_areas))

        # if len(matTags) != len(fiber_center):
        #     raise ValueError("matTags 必须与截面子区域数相同！此外，若有钢筋，钢筋材料号放在最后")

        ops.section('Fiber', secTag, '-GJ', GJ)
        i = 0
        for centers, areas in zip(fiber_center, fiber_area):
            for center, area in zip(centers, areas):
                ops.fiber(center[0], center[1], area, matTags[i])
            i += 1

    def ops_cmds_tcl(self, output_dir: str, secTag: int, matTag: int):
        """
        生成opensees纤维命令
        :param output_dir: 输出目录＋文件名
        :param secTag: 截面号
        :param matTags: 材料号，列表样
        :param GJ: 扭转常数
        :return: None
        """

        fiber_center, fiber_area, sec_property = mesh_geom(self.mesh_obj)
        fiber_center.append(np.array(self.rebar_coords))
        fiber_area.append(np.array(self.rebar_areas))

        # if len(matTags) != len(fiber_center):
        #     raise ValueError("matTags 必须与截面子区域数相同！此外，若有钢筋，钢筋材料号放在最后")

        with open(output_dir, "a") as output:
            temp = "{"
            output.write(f'section Fiber {secTag} -GJ 10000 {temp}\n')
            i = 0
            for centers, areas in zip(fiber_center, fiber_area):
                for center, area in zip(centers, areas):
                    output.write(f'    fiber {center[0]:.10f} {center[1]:.10f} {area:.10f} {matTag}\n')
                i += 1
            output.write('}\n')

    def mesh_view(self, fill=True, show_mesh_order=True):
        """
        :param fill: 是否填充多边形，否则画线框
        :param show_mesh_order: 是否显示网格绘制的次序，材料号应与该顺序一致
        """

        # matplotlib 绘图
        fig, ax = plt.subplots(figsize=(8, 8))
        # ax.set_facecolor("#efefef")
        # 显示划分图
        for i, mesh in enumerate(self.mesh_obj):
            vertices = mesh.points
            faces = mesh.cells_dict['triangle']  # 每个三角形顶点的号
            faces = faces.astype(np.int64)
            if not fill:
                x = vertices[:, 0]
                y = vertices[:, 1]
                ax.triplot(x, y, triangles=faces, color=self.colors[i],
                           lw=1, zorder=0)
                if show_mesh_order:
                    ax.scatter([], [], label=f"mesh #{i + 1}", color=self.colors[i])  # 仅用作图例
            else:
                x = vertices[:, 0]
                y = vertices[:, 1]
                ax.triplot(x, y, triangles=faces, lw=1, color='black')
                patches = [plt.Polygon(vertices[face_link, :2])
                           for face_link in faces]
                coll = matplotlib.collections.PatchCollection(patches,
                                                              facecolors=self.colors[i],
                                                              edgecolors='black')
                ax.add_collection(coll)
                if show_mesh_order:
                    ax.scatter([], [], label=f"mesh #{i + 1}", color=self.colors[i])  # 仅用作图例

        patches = [plt.Circle((rebar_xy[0], rebar_xy[1]), np.sqrt(area / np.pi))
                   for rebar_xy, area in zip(self.rebar_coords, self.rebar_areas)]
        coll = matplotlib.collections.PatchCollection(
            patches, facecolors=self.color_rebar)
        ax.add_collection(coll)
        if show_mesh_order:
            ax.scatter([], [], label=f"mesh #{len(self.mesh_obj) + 1}", color=self.color_rebar)  # 仅用作图例
        ax.set_aspect('equal')
        ax.set_title('section fiber mesh', fontsize=20)
        plt.xticks(fontsize=15)
        plt.yticks(fontsize=15)
        ax.legend(fontsize=18, shadow=True, markerscale=3,
                  title="mesh order", title_fontsize=20)
        plt.show()


class SecPlain(sec_base):

    def __init__(self):
        super(SecPlain, self).__init__()

    def mesh(self, mesh_size=None):
        """
        """

        if not self.holes:  # 如果开口为空列表，即没有开口
            with pygmsh.geo.Geometry() as geom:
                geom.add_polygon(
                    list(self.outline.exterior.coords)[:-1],
                    mesh_size=mesh_size
                )
                mesh_core = geom.generate_mesh()
        # 如果有开口，则为核心区的纤维减去开口部分
        else:
            with pygmsh.occ.Geometry() as geom:
                geom_extern = geom.add_polygon(
                    list(self.outline.exterior.coords)[:-1],
                    mesh_size=mesh_size,
                )
                geom_holes = [
                    geom.add_polygon(list(hole_line.exterior.coords)[:-1], mesh_size=mesh_size)
                    for hole_line in self.holes]  # 注意可能有多个开口，所以这里holes是一个列表
                if len(self.holes) == 1:  # 如果只有一个开口，直接减去就可以
                    geom.boolean_difference(geom_extern, geom_holes[0])
                    mesh_core = geom.generate_mesh()
                else:  # 多个开口，先将开口联合，再减去
                    geom.boolean_difference(
                        geom_extern, geom.boolean_union(geom_holes))
                    mesh_core = geom.generate_mesh()
        self.mesh_obj.append(mesh_core)

        self.rebar_coords = np.array(self.rebar_coords)
        self.rebar_areas = np.array(self.rebar_areas)


class SecRC(sec_base):
    def __init__(self):
        super().__init__()
        self.cover_d = None
        self.cover_line = None

    def add_cover(self, d):
        """
        :param d: thickness of cover
        """
        self.cover_d = d
        self.cover_line = self.outline.buffer(-d, cap_style=3, join_style=2)

    def add_rebar_outline(self, dia, gap, d):
        sec_base.add_rebar_outline(self, dia, gap, d)

    def mesh(self, mesh_size):
        with pygmsh.occ.Geometry() as geom:
            # 以下进行cover混凝土划分，方式为 整体截面-核心区混凝土部分
            geom_extern = geom.add_polygon(
                list(self.outline.exterior.coords)[:-1],
                mesh_size=mesh_size)
            geom_cover = geom.add_polygon(
                list(self.cover_line.exterior.coords)[:-1],
                mesh_size=mesh_size)
            geom.boolean_difference(geom_extern, geom_cover)
            mesh_cover = geom.generate_mesh()
        if not self.holes:  # 如果开口为空列表，即没有开口
            with pygmsh.geo.Geometry() as geom:
                geom.add_polygon(
                    list(self.cover_line.exterior.coords)[:-1],
                    mesh_size=mesh_size
                )
                mesh_core = geom.generate_mesh()
        # 如果有开口，则为核心区的纤维减去开口部分
        else:
            with pygmsh.occ.Geometry() as geom:
                geom_extern = geom.add_polygon(
                    list(self.cover_line.exterior.coords)[:-1],
                    mesh_size=mesh_size,
                )
                geom_holes = [
                    geom.add_polygon(list(hole_line.exterior.coords)[:-1], mesh_size=mesh_size)
                    for hole_line in self.holes]  # 注意可能有多个开口，所以这里holes是一个列表
                if len(self.holes) == 1:  # 如果只有一个开口，直接减去就可以
                    geom.boolean_difference(geom_extern, geom_holes[0])
                    mesh_core = geom.generate_mesh()
                else:  # 多个开口，先将开口联合，再减去
                    geom.boolean_difference(
                        geom_extern, geom.boolean_union(geom_holes))
                    mesh_core = geom.generate_mesh()

        self.mesh_obj.extend([mesh_cover, mesh_core])
        self.rebar_coords = np.array(self.rebar_coords)
        self.rebar_areas = np.array(self.rebar_areas)


class SecSRC(SecRC, sec_base):
    def __init__(self):
        super(SecSRC, self).__init__()
        self.bones = []

    def add_steel_bone(self, points):
        self.bones.append(Polygon(points))

    def mesh(self, mesh_size):
        with pygmsh.occ.Geometry() as geom:
            # 以下进行cover混凝土划分，方式为 整体截面-核心区混凝土部分
            geom_extern = geom.add_polygon(
                list(self.outline.exterior.coords)[:-1],
                mesh_size=mesh_size)
            geom_cover = geom.add_polygon(
                list(self.cover_line.exterior.coords)[:-1],
                mesh_size=mesh_size)
            geom.boolean_difference(geom_extern, geom_cover)
            mesh_cover = geom.generate_mesh()
        # 设置核心混凝土
        with pygmsh.occ.Geometry() as geom:
            geom_extern = geom.add_polygon(
                list(self.cover_line.exterior.coords)[:-1],
                mesh_size=mesh_size,
            )
            geom_bones = [
                geom.add_polygon(list(bone_line.exterior.coords)[:-1], mesh_size=mesh_size)
                for bone_line in self.bones]  # 注意可能有多个开口，所以这里holes是一个列表
            if len(self.bones) == 1:  # 如果只有一个开口，直接减去就可以
                geom.boolean_difference(geom_extern, geom_bones[0])
                mesh_core = geom.generate_mesh()
            else:  # 多个开口，先将开口联合，再减去
                geom.boolean_difference(
                    geom_extern, geom.boolean_union(geom_bones))
                mesh_core = geom.generate_mesh()
        # 钢骨部分
        with pygmsh.occ.Geometry() as geom:
            geom_bones = [
                geom.add_polygon(list(bone_line.exterior.coords)[:-1], mesh_size=mesh_size)
                for bone_line in self.bones]
            if len(self.bones) == 1:  # 如果只有一个
                mesh_bones = geom.generate_mesh()
            else:
                geom.boolean_union(geom_bones)
                mesh_bones = geom.generate_mesh()
        self.mesh_obj.extend([mesh_cover, mesh_core] + [mesh_bones])
        self.rebar_coords = np.array(self.rebar_coords)
        self.rebar_areas = np.array(self.rebar_areas)


class SecSTC(sec_base):
    def __init__(self):
        super(SecSTC, self).__init__()
        self.tube_line = None
        self.tube_d = None

    def add_steel_tube(self, d):
        self.tube_d = d
        self.tube_line = self.outline.buffer(-d, cap_style=3, join_style=2)

    def add_rebar_tube(self, dia, gap, d):
        sec_base.add_rebar_outline(self, dia, gap, d)

    def mesh(self, mesh_size):
        with pygmsh.occ.Geometry() as geom:
            # 以下进行cover混凝土划分，方式为 整体截面-核心区混凝土部分
            geom_extern = geom.add_polygon(
                list(self.outline.exterior.coords)[:-1],
                mesh_size=mesh_size)
            geom_tube = geom.add_polygon(
                list(self.tube_line.exterior.coords)[:-1],
                mesh_size=mesh_size)
            geom.boolean_difference(geom_extern, geom_tube)
            mesh_tube = geom.generate_mesh()
        # 设置核心混凝土
        with pygmsh.occ.Geometry() as geom:
            geom.add_polygon(
                list(self.tube_line.exterior.coords)[:-1],
                mesh_size=mesh_size,
            )
            mesh_core = geom.generate_mesh()
        self.mesh_obj.extend([mesh_tube, mesh_core])
        self.rebar_coords = np.array(self.rebar_coords)
        self.rebar_areas = np.array(self.rebar_areas)


def lines_subdivide(x, y, gap):
    """
    The polylines consisting of coordinates x and y are divided by the gap.
    """
    x_new = []
    y_new = []
    for i in range(len(x) - 1):
        x1, y1 = x[i], y[i]
        x2, y2 = x[i + 1], y[i + 1]
        length = np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
        n = int(length // gap + 1)
        x_new.extend(np.linspace(
            x1, x2, n + 1, endpoint=True)[:-1].tolist())
        y_new.extend(np.linspace(
            y1, y2, n + 1, endpoint=True)[:-1].tolist())
    new_line = np.column_stack((x_new, y_new, np.zeros(len(x_new))))
    return new_line


def sec_rotation(x, y, theta):
    """
    Rotate the section coordinates counterclockwise by theta
    """
    x_new = x * np.cos(theta) + y * np.sin(theta)
    y_new = -x * np.sin(theta) + y * np.cos(theta)
    return x_new, y_new


def mesh_geom(mesh_list):
    """
    用来计算mesh的几何性质，包括面积，惯性矩等
    :param mesh_list:  一个包含pygmsh生成的mesh的列表，即可以包含多个mesh
    :return:
    """
    fiber_center = []
    fiber_area = []
    for mesh in mesh_list:
        vertices = mesh.points
        faces = mesh.cells_dict['triangle']
        num = faces.shape[0]
        center_points = np.zeros((num, 3))  # 每个三角纤维的中点坐标
        areas = np.zeros(num)  # 每个三角纤维的面积
        for i, face in enumerate(faces):
            tag1, tag2, tag3 = face
            x1, y1 = vertices[tag1, :2]
            x2, y2 = vertices[tag2, :2]
            x3, y3 = vertices[tag3, :2]
            center_points[i] = (x1 + x2 + x3) / 3, (y1 + y2 + y3) / 3, 0
            areas[i] = 0.5 * np.abs(x2 * y3 + x1 * y2 + x3 * y1 - x3 * y2 - x2 * y1 - x1 * y3)
        fiber_center.append(center_points)
        fiber_area.append(areas)
    Centers = np.vstack(fiber_center)
    Areas = np.hstack(fiber_area)
    # 求总面积
    A = np.sum(Areas)
    # 求形心坐标
    yo = np.sum(Centers[:, 0] * Areas) / A
    zo = np.sum(Centers[:, 1] * Areas) / A
    # 求截面惯性矩
    Iy = np.sum(Centers[:, 1] ** 2 * Areas)
    Iz = np.sum(Centers[:, 0] ** 2 * Areas)
    # 回转半径
    ry = np.sqrt(Iy / A)
    rz = np.sqrt(Iz / A)
    # 极惯性矩
    Ip = Iy + Iz
    # 惯性积
    Iyz = np.sum(Centers[:, 0] * Centers[:, 1] * Areas)
    sec_property = dict(area=A, center=(yo, zo, 0), Iy=Iy,
                        Iz=Iz, ry=ry, rz=rz, Ip=Ip, Iyz=Iyz)
    return fiber_center, fiber_area, sec_property


def ops_sec_vis(ele_tag, sec_num=1, rebar_d=None, color=None):
    """
    ele_tag: 要显示截面的所属单元号；
    sec_num: 显示单元上的哪个积分点截面，从i段到j段从1开始编号；
    rebar_d: 钢筋直径，若想突出显示钢筋，请传入一个标量或列表等，列表则表示有多种钢筋直径。
    color: 显示颜色，默认为渐变颜色，其值按与截面中心点的距离变化。
    """
    import openseespy.opensees as ops
    # 利用eleResponse()命令提取出纤维数据
    FiberData = ops.eleResponse(ele_tag, 'section', 'fiberData', sec_num)
    # FiberData从第1列至第5列分别为："yCoord", "zCoord", "area", "stress", "strain"
    FiberData = np.array(FiberData).reshape((-1, 5))  # 变形为5列数组
    ylocs, zlocs, areas = FiberData[:, 0], FiberData[:, 1], FiberData[:, 2]
    # 如下提取出边界与坐标中心
    ymin, ymax = np.min(ylocs), np.max(ylocs)
    zmin, zmax = np.min(zlocs), np.max(zlocs)
    ymean, zmean = np.mean(ylocs), np.mean(zlocs)

    # matplotlib 绘图
    plt.style.use('fivethirtyeight')
    # plt.style.use('ggplot')
    fig, ax = plt.subplots(figsize=(8, 8))
    patches = [plt.Circle((yloc, zloc), np.sqrt(area / np.pi))
               for yloc, zloc, area in zip(ylocs, zlocs, areas)]
    coll = matplotlib.collections.PatchCollection(patches, alpha=0.75)
    if color is None:
        colors = (ylocs - ymean) ** 2 + (zlocs - zmean) ** 2
        coll.set_array(colors)
    else:
        coll.set_color(color)
    ax.add_collection(coll)

    # 如果包含钢筋
    if rebar_d is not None:
        rebar_d = np.atleast_1d(rebar_d)
        for d in rebar_d:
            rebar_area = np.pi * d ** 2 / 4
            idx = np.argwhere(np.abs(areas - rebar_area) < 1e-6)
            rebar_ys = ylocs[idx]
            rebar_zs = zlocs[idx]
            rebar_areas = areas[idx]
            patches_rebar = [plt.Circle((yloc, zloc), np.sqrt(area / np.pi))
                             for yloc, zloc, area in zip(rebar_ys, rebar_zs, rebar_areas)]
            coll_rebar = matplotlib.collections.PatchCollection(patches_rebar, color='black', alpha=1)
            ax.add_collection(coll_rebar)
    ax.set_aspect('equal')
    ax.set_xlim(ymin * 1.5, ymax * 1.5)
    ax.set_ylim(zmin * 1.5, zmax * 1.5)
    ax.set_xlabel('y', fontsize=20)
    ax.set_ylabel('z', fontsize=20)
    plt.xticks(fontsize=12)
    plt.yticks(fontsize=12)
    plt.show()


if __name__ == '__main__':
    # case 1, 单一材料截面
    line = [[0, 0], [1, 0], [2, 1], [1, 2], [0, 1], [0, 0]]
    holes = [[(0.5, 0.5), (1.0, 0.5), (1, 1), (0.5, 1)],
             [(0.5, 0.5), (1.0, 0.5), (1, 1), (0.5, 1)]]
    h = SecPlain()
    h.add_outline(line)
    h.add_rebar_outline(dia=0.032, gap=0.15, d=0.1)
    for hole in holes:
        h.add_hole(hole)
    h.add_rebar_hole(dia=0.032, gap=0.15, d=0.1)
    h.mesh(mesh_size=0.1)
    h.rotate(theta=90)
    h.centring()
    h.mesh_view()

    # Case 2  单一材料截面，圆形截面
    h = SecPlain()
    lines = []
    r = 1.2
    for angle in np.linspace(0, 2 * np.pi, 24, endpoint=False):
        lines.append((r * np.cos(angle), r * np.sin(angle)))
    lines2 = []
    r = 0.6
    for angle in np.linspace(0, 2 * np.pi, 24, endpoint=False):
        lines2.append((r * np.cos(angle), r * np.sin(angle)))
    h.add_outline(lines)
    h.add_rebar_outline(dia=0.032, gap=0.15, d=0.1)
    h.add_hole(lines2)
    h.mesh(mesh_size=0.2)
    # h.centring()
    h.mesh_view()

    # Case    RC 截面
    lines = [(-4, 4), (-2, 4), (-2, 2), (2, 2), (2, 4), (4, 4),
             (4, -4), (2, -4), (2, -2), (-2, -2), (-2, -4), (-4, -4)]
    holes = [[(-3, 1), (-2, 1), (-2, -1), (-3, -1)],
             [(3, 1), (2, 1), (2, -1), (3, -1)]]
    h = SecRC()
    h.add_outline(lines)
    h.add_cover(d=0.1)
    h.add_rebar_outline(dia=0.06, gap=0.15, d=0.1)
    for hole in holes:
        h.add_hole(hole)
    h.add_rebar_hole(dia=0.06, gap=0.15, d=0.1)
    h.mesh(mesh_size=0.4)
    h.rotate(theta=0)
    h.centring()
    h.mesh_view()

    # 钢骨混凝土截面
    lines = []
    r = 4
    for angle in np.linspace(0, 2 * np.pi, 6, endpoint=False):
        lines.append((r * np.cos(angle), r * np.sin(angle)))
    bones = [[(-2, 1), (-1, 1), (-1, -1), (-2, -1)],
             [(2, 1), (1, 1), (1, -1), (2, -1)]]
    h = SecSRC()
    h.add_outline(lines)
    h.add_cover(d=0.1)
    h.add_rebar_outline(dia=0.06, gap=0.15, d=0.1)
    for bone in bones:
        h.add_steel_bone(bone)
    h.mesh(mesh_size=0.4)
    h.rotate(theta=0)
    h.centring()
    h.mesh_view()

    # 钢骨混凝土截面
    lines = [(-2, 2), (2, 2), (2, -2), (-2, -2)]
    bone = []
    r = 1
    for angle in np.linspace(0, 2 * np.pi, 24, endpoint=False):
        bone.append((r * np.cos(angle), r * np.sin(angle)))
    h = SecSRC()
    h.add_outline(lines)
    h.add_cover(d=0.1)
    h.add_rebar_outline(dia=0.06, gap=0.15, d=0.1)
    h.add_steel_bone(bone)
    h.mesh(mesh_size=0.2)
    h.rotate(theta=0)
    h.centring()
    h.mesh_view()

    # 钢管混凝土截面
    lines = []
    r = 1
    for angle in np.linspace(0, 2 * np.pi, 24, endpoint=False):
        lines.append((r * np.cos(angle), r * np.sin(angle)))
    h = SecSTC()
    h.add_outline(lines)
    h.add_steel_tube(d=0.02)
    h.add_rebar_tube(dia=0.06, gap=0.15, d=0.02)
    h.mesh(mesh_size=0.2)
    h.rotate(theta=0)
    h.centring()
    h.mesh_view()
