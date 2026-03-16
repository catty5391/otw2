import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401


class TowerElementSelector:
    def __init__(
        self,
        node_file,
        element_file,
        node_cols=(1, 2, 3, 4),      # node, x, y, z
        element_cols=(2, 3, 4),      # eleTag, node1, node2
        axis_ranges=None,            # {"x": (-80, 80), "y": (-80, 80), "z": (-80, 80)}
        title="Tower Element Selector"
    ):
        self.node_file = node_file
        self.element_file = element_file
        self.node_cols = node_cols
        self.element_cols = element_cols
        self.axis_ranges = axis_ranges
        self.title = title

        self.node_df = None
        self.element_df = None
        self.node_coord_dict = {}
        self.element_records = []

        self.selected_tags = set()
        self.confirmed = False

        self.fig = None
        self.ax = None
        self.info_text = None
        self.mid_scatter = None

    def _load_data(self):
        node_raw = pd.read_csv(
            self.node_file,
            sep=r"\s+",
            header=None,
            comment="#",
            engine="python"
        )
        self.node_df = node_raw.iloc[:, list(self.node_cols)].copy()
        self.node_df.columns = ["node", "x", "y", "z"]
        self.node_df["node"] = self.node_df["node"].astype(int)
        self.node_df["x"] = self.node_df["x"].astype(float)
        self.node_df["y"] = self.node_df["y"].astype(float)
        self.node_df["z"] = self.node_df["z"].astype(float)

        ele_raw = pd.read_csv(
            self.element_file,
            sep=r"\s+",
            header=None,
            comment="#",
            engine="python"
        )
        self.element_df = ele_raw.iloc[:, list(self.element_cols)].copy()
        self.element_df.columns = ["eleTag", "node1", "node2"]
        self.element_df["eleTag"] = self.element_df["eleTag"].astype(int)
        self.element_df["node1"] = self.element_df["node1"].astype(int)
        self.element_df["node2"] = self.element_df["node2"].astype(int)

        self.node_coord_dict = {
            int(row["node"]): (float(row["x"]), float(row["y"]), float(row["z"]))
            for _, row in self.node_df.iterrows()
        }

        self.element_records = []
        for _, row in self.element_df.iterrows():
            eleTag = int(row["eleTag"])
            node1 = int(row["node1"])
            node2 = int(row["node2"])

            if node1 not in self.node_coord_dict or node2 not in self.node_coord_dict:
                continue

            x1, y1, z1 = self.node_coord_dict[node1]
            x2, y2, z2 = self.node_coord_dict[node2]

            self.element_records.append({
                "eleTag": eleTag,
                "node1": node1,
                "node2": node2,
                "x1": x1, "y1": y1, "z1": z1,
                "x2": x2, "y2": y2, "z2": z2,
                "xm": (x1 + x2) / 2.0,
                "ym": (y1 + y2) / 2.0,
                "zm": (z1 + z2) / 2.0,
            })

    def _draw(self):
        self.ax.clear()

        # 画杆件
        for rec in self.element_records:
            color = "red" if rec["eleTag"] in self.selected_tags else "lightgray"
            lw = 2.5 if rec["eleTag"] in self.selected_tags else 0.8
            self.ax.plot(
                [rec["x1"], rec["x2"]],
                [rec["y1"], rec["y2"]],
                [rec["z1"], rec["z2"]],
                color=color,
                linewidth=lw
            )

        # 画节点（可选）
        self.ax.scatter(
            self.node_df["x"],
            self.node_df["y"],
            self.node_df["z"],
            s=4,
            c="tab:blue",
            alpha=0.5
        )

        # 画杆件中点，供点击选择
        mid_x = [rec["xm"] for rec in self.element_records]
        mid_y = [rec["ym"] for rec in self.element_records]
        mid_z = [rec["zm"] for rec in self.element_records]
        mid_c = [
            "red" if rec["eleTag"] in self.selected_tags else "blue"
            for rec in self.element_records
        ]

        self.mid_scatter = self.ax.scatter(
            mid_x, mid_y, mid_z,
            s=25,
            c=mid_c,
            picker=True,
            depthshade=False
        )

        self.ax.set_title(self.title)
        self.ax.set_xlabel("X")
        self.ax.set_ylabel("Y")
        self.ax.set_zlabel("Z")

        if self.axis_ranges:
            if "x" in self.axis_ranges:
                self.ax.set_xlim(*self.axis_ranges["x"])
            if "y" in self.axis_ranges:
                self.ax.set_ylim(*self.axis_ranges["y"])
            if "z" in self.axis_ranges:
                self.ax.set_zlim(*self.axis_ranges["z"])

        selected_list = sorted(self.selected_tags)
        info = f"Selected ({len(selected_list)}): {selected_list}"
        if self.info_text is not None:
            self.info_text.set_text(info)

        self.fig.canvas.draw_idle()

    def _on_pick(self, event):
        if event.artist != self.mid_scatter:
            return
        if not event.ind:
            return

        idx = int(event.ind[0])
        eleTag = self.element_records[idx]["eleTag"]

        if eleTag in self.selected_tags:
            self.selected_tags.remove(eleTag)
        else:
            self.selected_tags.add(eleTag)

        self._draw()

    def _on_clear(self, event):
        self.selected_tags.clear()
        self._draw()

    def _on_confirm(self, event):
        self.confirmed = True
        plt.close(self.fig)

    def select(self):
        self._load_data()

        self.fig = plt.figure(figsize=(11, 8))
        self.ax = self.fig.add_subplot(111, projection="3d")
        plt.subplots_adjust(bottom=0.15)

        self.info_text = self.fig.text(
            0.02, 0.02,
            "Selected (0): []",
            fontsize=10
        )

        ax_clear = plt.axes([0.72, 0.03, 0.10, 0.05])
        ax_confirm = plt.axes([0.84, 0.03, 0.12, 0.05])

        btn_clear = Button(ax_clear, "Clear")
        btn_confirm = Button(ax_confirm, "Confirm")

        btn_clear.on_clicked(self._on_clear)
        btn_confirm.on_clicked(self._on_confirm)

        self.fig.canvas.mpl_connect("pick_event", self._on_pick)

        self._draw()
        plt.show()

        return sorted(self.selected_tags)


def select_tower_elements(
    node_file,
    element_file,
    node_cols=(1, 2, 3, 4),
    element_cols=(2, 3, 4),
    axis_ranges=None,
    title="Tower Element Selector"
):
    selector = TowerElementSelector(
        node_file=node_file,
        element_file=element_file,
        node_cols=node_cols,
        element_cols=element_cols,
        axis_ranges=axis_ranges,
        title=title
    )
    return selector.select()


if __name__ == "__main__":
    node_file = "./Src/Node.tcl"
    element_file = "./Src/Element.tcl"
    selected_elements = select_tower_elements(node_file, element_file)
    print("Selected Element Tags:", selected_elements)