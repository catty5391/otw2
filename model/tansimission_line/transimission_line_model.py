from pathlib import Path
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))


from model import OpenSeesModel
from util import TagManager
from pathlib import Path
import json


class TransmissionLineModel(OpenSeesModel):
    def __init__(self, name, path):
        super().__init__(path)
        self.base_dir = Path(__file__).resolve().parents[1]
        self.transmission_line_config_path = self.base_dir / ".config" / "transmission_line.json"
        self._read_transmission_line_json()
        self._register_tag()


    def _register_tag(self):
        self.tag_manager = TagManager()
        # 注册已经使用过的tag，方便后续添加时，不会和之前tag冲突
        # 1. node注册
        for node in self.node_map.values():
            self.tag_manager.register(node.get("node_tag"), "node")
        for element in self.element_map.values():
            self.tag_manager.register(element.get("element_tag"), "element")
        for material in self.material_tag_map.values():
            self.tag_manager.register(material.get("mat_tag"), "material")
        for section in self.section_tag_map.values():
            self.tag_manager.register(section.get("section_tag"), "section")
    
    def _read_transmission_line_json(self):
        self.transmission_line_config = json.loads(self.transmission_line_config_path.read_text("utf-8"))


    def build_one_line(self, name: str):
        node_entity = self.transmission_line_config.get(name)
        if node_entity is None:
            raise ValueError(f"Line {name} not found in transmission_line_config")
        node_to_hang = node_entity.get("node_to_hang")
        EA = node_entity.get("material")[0]
        EI = node_entity.get("material")[1]
        GJ = node_entity.get("material")[2]
        initial_stress = node_entity.get("material")[3]


    def build_all_line(self):
        pass

    def test(self):
        print(self.transmission_line_config.get("line1"))
        print(self.transmission_line_config.get("line3"))

if __name__ == "__main__":
    model = TransmissionLineModel("TransmissionLine", "/home/panqiheng/OTW/Source/Z30103A6.s2k")
    model.model_tower()
    model.test()