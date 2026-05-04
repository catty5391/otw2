from __future__ import annotations


class ForceControl:
    """只统一管理全局 timeSeriesTag 和 patternTag。"""

    def __init__(self, start_time_series_tag: int = 1, start_pattern_tag: int = 1):
        self._next_time_series_tag = int(start_time_series_tag)
        self._next_pattern_tag = int(start_pattern_tag)
        self.time_series_records: dict[str, int] = {}
        self.pattern_records: dict[str, int] = {}

    @property
    def next_time_series_tag(self) -> int:
        return self._next_time_series_tag

    @property
    def next_pattern_tag(self) -> int:
        return self._next_pattern_tag

    def _ensure_unique_name(self, name: str, records: dict[str, int], label: str) -> None:
        if name in records:
            raise ValueError(f"{label} 名称已存在: {name}")

    def _ensure_unique_tag(self, tag: int, records: dict[str, int], label: str) -> None:
        if tag in records.values():
            raise ValueError(f"{label} tag 已存在: {tag}")

    def get_next_time_series_tag(self, name: str | None = None) -> int:
        tag = self._next_time_series_tag
        self._next_time_series_tag += 1
        if name is not None:
            self.register_time_series(name=name, tag=tag)
        return tag

    def get_next_pattern_tag(self, name: str | None = None) -> int:
        tag = self._next_pattern_tag
        self._next_pattern_tag += 1
        if name is not None:
            self.register_pattern(name=name, tag=tag)
        return tag

    def get_next_tag_pair(
        self,
        time_series_name: str | None = None,
        pattern_name: str | None = None,
    ) -> tuple[int, int]:
        ts_tag = self.get_next_time_series_tag(name=time_series_name)
        pattern_tag = self.get_next_pattern_tag(name=pattern_name)
        return ts_tag, pattern_tag

    def register_time_series(self, name: str, tag: int) -> int:
        tag = int(tag)
        self._ensure_unique_name(name, self.time_series_records, "timeSeries")
        self._ensure_unique_tag(tag, self.time_series_records, "timeSeries")
        self.time_series_records[name] = tag
        if tag >= self._next_time_series_tag:
            self._next_time_series_tag = tag + 1
        return tag

    def register_pattern(self, name: str, tag: int) -> int:
        tag = int(tag)
        self._ensure_unique_name(name, self.pattern_records, "pattern")
        self._ensure_unique_tag(tag, self.pattern_records, "pattern")
        self.pattern_records[name] = tag
        if tag >= self._next_pattern_tag:
            self._next_pattern_tag = tag + 1
        return tag

    def get_time_series_tag(self, name: str) -> int:
        if name not in self.time_series_records:
            raise KeyError(f"未找到 timeSeries: {name}")
        return self.time_series_records[name]

    def get_pattern_tag(self, name: str) -> int:
        if name not in self.pattern_records:
            raise KeyError(f"未找到 pattern: {name}")
        return self.pattern_records[name]

    def has_time_series(self, name: str) -> bool:
        return name in self.time_series_records

    def has_pattern(self, name: str) -> bool:
        return name in self.pattern_records

    def clear_records(self) -> None:
        self.time_series_records.clear()
        self.pattern_records.clear()

    def reset(
        self,
        start_time_series_tag: int | None = None,
        start_pattern_tag: int | None = None,
        clear_records: bool = True,
    ) -> None:
        if start_time_series_tag is not None:
            self._next_time_series_tag = int(start_time_series_tag)
        if start_pattern_tag is not None:
            self._next_pattern_tag = int(start_pattern_tag)
        if clear_records:
            self.clear_records()

    def summary(self) -> dict[str, dict[str, int]]:
        return {
            "time_series": dict(self.time_series_records),
            "patterns": dict(self.pattern_records),
        }
