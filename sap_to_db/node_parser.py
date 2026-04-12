import os
import re
import pandas as pd
from Search_keyword import SearchKeyword


class NodeParser:
    def __init__(self, path):
        self.path = path
        self.keyword = "JOINT COORDINATES"

    def startline(self):
        obj = SearchKeyword(self.path, self.keyword)
        return obj.search()

    @staticmethod
    def parse_kv_line(line: str):
        """
        将一行类似：
        Joint=1 GlobalX=0 GlobalY=0 GlobalZ=10
        或
        Joint=1 XorR=0 Y=0 Z=10
        解析为字典
        """
        pairs = re.findall(r'(\S+?)=("[^"]*"|\S+)', line)
        data = {}
        for k, v in pairs:
            data[k] = v.strip('"')
        return data

    def dataframe(self):
        start_line, lines = self.startline()

        if start_line == -1:
            raise ValueError("缺少 JOINT COORDINATES 节点信息")

        rows = []

        for line in lines[start_line:]:
            if line.isspace():
                break

            line = line.strip()
            if not line:
                break

            data = self.parse_kv_line(line)

            # 根据 s2k 文件实际字段名做兼容
            node_id = data.get("Joint") or data.get("JointID") or data.get("N")
            x = data.get("GlobalX") or data.get("XorR") or data.get("X")
            y = data.get("GlobalY") or data.get("Y")
            z = data.get("GlobalZ") or data.get("Z")

            if node_id is None or x is None or y is None or z is None:
                continue

            rows.append({
                "node_id": int(node_id),
                "x": float(x),
                "y": float(y),
                "z": float(z),
                "group_name": None,
                "story_name": None,
                "remark": None,
            })

        node_df = pd.DataFrame(rows)

        if node_df.empty:
            raise ValueError("节点段已找到，但未解析出有效节点数据")

        # 防止重复节点
        node_df = node_df.drop_duplicates(subset=["node_id"]).sort_values("node_id").reset_index(drop=True)

        return node_df