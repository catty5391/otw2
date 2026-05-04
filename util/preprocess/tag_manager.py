from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class TagManager:
    """统一管理不同类型的 OpenSees tag，避免后续增量建模时重复。

    支持两种初始化方式：
    1. 不传 `existing_tags`，从默认起始值开始分配；
    2. 传入已有 tag，后续分配会自动从当前最大 tag 之后继续。

    示例：
    `TagManager()`
    `TagManager([1, 2, 3])`
    `TagManager({"node": tower_nodes, "element": tower_elements})`
    """

    def __init__(
        self,
        existing_tags: dict[str, Any] | Iterable[int] | int | None = None,
        start_tag: int | dict[str, int] = 1,
    ) -> None:
        self._used_tags: dict[str, set[int]] = {}
        self._next_tags: dict[str, int] = {}
        self._start_tag = start_tag
        if existing_tags is not None:
            self.initialize(existing_tags)

    def _get_start_tag(self, namespace: str) -> int:
        if isinstance(self._start_tag, dict):
            return int(self._start_tag.get(namespace, 1))
        return int(self._start_tag)

    def _ensure_namespace(self, namespace: str) -> None:
        if namespace in self._used_tags:
            return
        self._used_tags[namespace] = set()
        self._next_tags[namespace] = self._get_start_tag(namespace)

    @staticmethod
    def _coerce_tag_values(tags: Any) -> list[int]:
        if tags is None:
            return []
        if isinstance(tags, int):
            return [int(tags)]
        if isinstance(tags, str):
            raise TypeError("tag 不能使用字符串，请传入 int 或 int 可迭代对象。")
        return [int(tag) for tag in tags]

    def _normalize_existing_tags(
        self,
        existing_tags: dict[str, Any] | Iterable[int] | int,
    ) -> dict[str, list[int]]:
        if isinstance(existing_tags, dict):
            return {
                str(namespace): self._coerce_tag_values(tags)
                for namespace, tags in existing_tags.items()
            }
        return {"default": self._coerce_tag_values(existing_tags)}

    def initialize(self, existing_tags: dict[str, Any] | Iterable[int] | int) -> None:
        normalized = self._normalize_existing_tags(existing_tags)
        for namespace, tags in normalized.items():
            self._ensure_namespace(namespace)
            for tag in tags:
                self.register(tag, namespace=namespace)

    def register(self, tag: int, namespace: str = "default") -> int:
        self._ensure_namespace(namespace)
        tag = int(tag)
        if tag in self._used_tags[namespace]:
            raise ValueError(f"{namespace} tag 已存在: {tag}")
        self._used_tags[namespace].add(tag)
        if tag >= self._next_tags[namespace]:
            self._next_tags[namespace] = tag + 1
        return tag

    def register_many(self, tags: Iterable[int], namespace: str = "default") -> list[int]:
        registered: list[int] = []
        for tag in tags:
            registered.append(self.register(tag, namespace=namespace))
        return registered

    def get_next_tag(self, namespace: str = "default") -> int:
        self._ensure_namespace(namespace)
        tag = self._next_tags[namespace]
        while tag in self._used_tags[namespace]:
            tag += 1
        self._used_tags[namespace].add(tag)
        self._next_tags[namespace] = tag + 1
        return tag

    def get_next_tags(self, count: int, namespace: str = "default") -> list[int]:
        if int(count) < 1:
            raise ValueError("count 必须大于 0。")
        return [self.get_next_tag(namespace=namespace) for _ in range(int(count))]

    def peek_next_tag(self, namespace: str = "default") -> int:
        self._ensure_namespace(namespace)
        tag = self._next_tags[namespace]
        while tag in self._used_tags[namespace]:
            tag += 1
        return tag

    def has_tag(self, tag: int, namespace: str = "default") -> bool:
        self._ensure_namespace(namespace)
        return int(tag) in self._used_tags[namespace]

    def get_used_tags(self, namespace: str = "default") -> list[int]:
        self._ensure_namespace(namespace)
        return sorted(self._used_tags[namespace])

    def clear(self, namespace: str | None = None) -> None:
        if namespace is None:
            self._used_tags.clear()
            self._next_tags.clear()
            return
        self._used_tags.pop(namespace, None)
        self._next_tags.pop(namespace, None)

    def reset(
        self,
        existing_tags: dict[str, Any] | Iterable[int] | int | None = None,
        start_tag: int | dict[str, int] | None = None,
    ) -> None:
        self.clear()
        if start_tag is not None:
            self._start_tag = start_tag
        if existing_tags is not None:
            self.initialize(existing_tags)

    def summary(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for namespace in sorted(self._used_tags):
            result[namespace] = {
                "next_tag": self.peek_next_tag(namespace),
                "used_tags": sorted(self._used_tags[namespace]),
            }
        return result


if __name__ == "__main__":
    from pathlib import Path
    import sys 
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.append(str(PROJECT_ROOT))
    # 示例用法
    tm = TagManager()
    import openseespy.opensees as ops
    from model import OpenSeesModel

    model = OpenSeesModel("/home/panqiheng/OTW/Source/Z30103A6.s2k")
    model.model_tower()
    node = model.node_map.values()
    for n in node:
        tm.register(n.get("node_tag"), namespace="node")

    print(tm.get_next_tag(namespace="node"))