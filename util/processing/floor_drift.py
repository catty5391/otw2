import json
import re
from statistics import fmean

import openseespy.opensees as ops


class CorrectedStoryDriftTracker:
    """
    逐步统计修正层间位移角：
    gamma(i->i+1) = (Uy(i+1) - Uy(i)) / H(i->i+1) - Rx(i)

    说明：
    1. Uy 取每层参考点的 y 向平均位移（dof=2）
    2. Rx 取每层参考点的绕 x 轴平均转角位移（dof=4）
    3. floor_i -> floor_(i+1) 的修正项减去 floor_i 的平均 Rx
    """

    def __init__(self, node_floor_json_path):
        self.node_floor_json_path = node_floor_json_path
        self.floor_to_nodes = self._load_floor_nodes(node_floor_json_path)
        self.floor_order = self._sorted_floor_keys(self.floor_to_nodes)
        self.history = []  # 每步: [gamma_0_1, gamma_1_2, ...]
        self.not_corrected_history = []  # 每步: [gamma_not_corr_0_1, gamma_not_corr_1_2, ...]

        if len(self.floor_order) < 2:
            raise ValueError("至少需要两个楼层才能计算层间位移角。")

    @staticmethod
    def _load_floor_nodes(json_path):
        # 从 JSON 文件加载楼层节点配置，返回 {floor_name: [node_tags]} 字典
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict) or not data:
            raise ValueError("楼层节点配置必须是非空字典。")

        cleaned = {}
        for floor, nodes in data.items():
            if not isinstance(nodes, list) or len(nodes) == 0:
                raise ValueError(f"{floor} 的节点列表为空或格式错误。")
            cleaned[floor] = [int(n) for n in nodes]
        return cleaned

    @staticmethod
    def _sorted_floor_keys(floor_to_nodes):
        # 根据楼层名称排序，假设格式为 "floorX"，X 为整数。
        def floor_index(name):
            m = re.fullmatch(r"floor(\d+)", str(name))
            if not m:
                raise ValueError(f"楼层名格式错误: {name}，应类似 floor0/floor1。")
            return int(m.group(1))

        return sorted(floor_to_nodes.keys(), key=floor_index)

    @staticmethod
    def _mean(values):
        if len(values) == 0:
            raise ValueError("平均值输入为空。")
        return fmean(values)

    def _avg_floor_disp(self, floor_key, dof):
        vals = [ops.nodeDisp(node_tag, dof) for node_tag in self.floor_to_nodes[floor_key]]
        return self._mean(vals)

    def _avg_floor_z(self, floor_key):
        # ndm=3 时，第3个坐标为 z
        vals = [ops.nodeCoord(node_tag, 3) for node_tag in self.floor_to_nodes[floor_key]]
        return self._mean(vals)

    def capture_step(self):
        """
        在当前分析步收敛后调用一次。
        返回当前步所有修正层间位移角列表：
        [floor0-floor1, floor1-floor2, ...]
        """
        # 每层平均 y 位移与平均 x 转角
        avg_uy = {f: self._avg_floor_disp(f, 2) for f in self.floor_order}
        avg_rx = {f: self._avg_floor_disp(f, 4) for f in self.floor_order}
        avg_z = {f: self._avg_floor_z(f) for f in self.floor_order}

        step_drifts = []
        step_drifts_not_corr = []
        for i in range(len(self.floor_order) - 1):
            lower = self.floor_order[i]
            upper = self.floor_order[i + 1]

            h = avg_z[upper] - avg_z[lower]
            if abs(h) < 1e-12:
                raise ZeroDivisionError(f"{lower}->{upper} 层高接近0，无法计算。")
            gamma_not_corr = (avg_uy[upper] - avg_uy[lower]) / h
            gamma_corr = (avg_uy[upper] - avg_uy[lower]) / h + avg_rx[lower]
            step_drifts.append(gamma_corr)
            step_drifts_not_corr.append(gamma_not_corr)

        self.history.append(step_drifts)
        self.not_corrected_history.append(step_drifts_not_corr)
        return step_drifts

    def get_history(self):
        """
        返回所有分析步的修正层间位移角：
        [
          [step1 的各层间位移角],
          [step2 的各层间位移角],
          ...
        ]
        """
        return self.history
    
    def get_not_corrected_history(self):
        """
        返回所有分析步的未修正层间位移角：
        [
          [step1 的各层间位移角],
          [step2 的各层间位移角],
          ...
        ]
        """
        return self.not_corrected_history

    def get_story_labels(self):
        """
        返回层间标签顺序，与 capture_step 的列表一一对应。
        例如: ["floor0-floor1", "floor1-floor2", ...]
        """
        labels = []
        for i in range(len(self.floor_order) - 1):
            labels.append(f"{self.floor_order[i]}-{self.floor_order[i + 1]}")
        return labels