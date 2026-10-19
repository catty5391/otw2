from __future__ import annotations

import csv
import argparse
import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence


LOCAL_FORCE_COMPONENTS = (
    "p_i",
    "vy_i",
    "vz_i",
    "t_i",
    "my_i",
    "mz_i",
    "p_j",
    "vy_j",
    "vz_j",
    "t_j",
    "my_j",
    "mz_j",
)


class TowerInternalForceHistory:
    """Read and export a recorded full-tower local-force history."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        if not self.database_path.exists():
            raise FileNotFoundError(f"未找到内力数据库: {self.database_path}")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _selection_where(
        *,
        start_time: float | None,
        end_time: float | None,
        element_tags: Sequence[int] | None,
        tower_ids: Sequence[str] | None,
        alias: str = "h",
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if start_time is not None:
            clauses.append(f"{alias}.time >= ?")
            parameters.append(float(start_time))
        if end_time is not None:
            clauses.append(f"{alias}.time <= ?")
            parameters.append(float(end_time))
        if start_time is not None and end_time is not None and start_time > end_time:
            raise ValueError("start_time 不能大于 end_time。")
        if element_tags:
            placeholders = ",".join("?" for _ in element_tags)
            clauses.append(f"{alias}.element_tag IN ({placeholders})")
            parameters.extend(int(tag) for tag in element_tags)
        if tower_ids:
            placeholders = ",".join("?" for _ in tower_ids)
            clauses.append(f"e.tower_id IN ({placeholders})")
            parameters.extend(str(tower_id) for tower_id in tower_ids)
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), parameters

    def time_range(self) -> tuple[float, float] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT MIN(time) AS start_time, MAX(time) AS end_time FROM force_history"
            ).fetchone()
        if row is None or row["start_time"] is None:
            return None
        return float(row["start_time"]), float(row["end_time"])

    def recorded_times(self) -> list[float]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT time FROM force_history ORDER BY time"
            ).fetchall()
        return [float(row["time"]) for row in rows]

    def element_metadata(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM elements ORDER BY element_tag").fetchall()
        return [dict(row) for row in rows]

    def iter_history(
        self,
        *,
        start_time: float | None = None,
        end_time: float | None = None,
        element_tags: Sequence[int] | None = None,
        tower_ids: Sequence[str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        where, parameters = self._selection_where(
            start_time=start_time,
            end_time=end_time,
            element_tags=element_tags,
            tower_ids=tower_ids,
        )
        query = (
            "SELECT h.*, e.tower_id, e.local_element_tag, e.original_element_tag, "
            "e.segment_index, e.frame_name, e.node_i, e.node_j, e.section_name "
            "FROM force_history h JOIN elements e USING(element_tag)"
            f"{where} ORDER BY h.time, h.element_tag"
        )
        connection = self._connect()
        try:
            for row in connection.execute(query, parameters):
                yield dict(row)
        finally:
            connection.close()

    def nearest_recorded_time(self, requested_time: float) -> float:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT time FROM force_history GROUP BY time ORDER BY ABS(time - ?) LIMIT 1",
                (float(requested_time),),
            ).fetchone()
        if row is None:
            raise ValueError("内力数据库中没有记录。")
        return float(row["time"])

    def snapshot(
        self,
        requested_time: float,
        *,
        element_tags: Sequence[int] | None = None,
        tower_ids: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        actual_time = self.nearest_recorded_time(requested_time)
        return list(
            self.iter_history(
                start_time=actual_time,
                end_time=actual_time,
                element_tags=element_tags,
                tower_ids=tower_ids,
            )
        )

    def envelope(
        self,
        *,
        start_time: float | None = None,
        end_time: float | None = None,
        element_tags: Sequence[int] | None = None,
        tower_ids: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        where, parameters = self._selection_where(
            start_time=start_time,
            end_time=end_time,
            element_tags=element_tags,
            tower_ids=tower_ids,
        )
        maxima = ", ".join(
            f"MAX(ABS(h.{component})) AS {component}_abs_max"
            for component in LOCAL_FORCE_COMPONENTS
        )
        query = (
            "SELECT h.element_tag, e.tower_id, e.local_element_tag, e.original_element_tag, "
            "e.segment_index, e.frame_name, e.node_i, e.node_j, e.section_name, "
            f"MIN(h.time) AS start_time, MAX(h.time) AS end_time, {maxima} "
            "FROM force_history h JOIN elements e USING(element_tag)"
            f"{where} GROUP BY h.element_tag ORDER BY h.element_tag"
        )
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _write_rows(path: str | Path, rows: Iterable[dict[str, Any]]) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        iterator = iter(rows)
        first = next(iterator, None)
        with output_path.open("w", encoding="utf-8", newline="") as file:
            if first is None:
                return output_path
            writer = csv.DictWriter(file, fieldnames=list(first))
            writer.writeheader()
            writer.writerow(first)
            writer.writerows(iterator)
        return output_path

    def export_history_csv(
        self,
        path: str | Path,
        *,
        start_time: float | None = None,
        end_time: float | None = None,
        element_tags: Sequence[int] | None = None,
        tower_ids: Sequence[str] | None = None,
    ) -> Path:
        return self._write_rows(
            path,
            self.iter_history(
                start_time=start_time,
                end_time=end_time,
                element_tags=element_tags,
                tower_ids=tower_ids,
            ),
        )

    def export_snapshot_csv(
        self,
        path: str | Path,
        requested_time: float,
        **filters: Any,
    ) -> Path:
        return self._write_rows(path, self.snapshot(requested_time, **filters))

    def export_envelope_csv(
        self,
        path: str | Path,
        **filters: Any,
    ) -> Path:
        return self._write_rows(path, self.envelope(**filters))


class TowerInternalForceRecorder:
    """Record all tower beam local end forces into an indexed SQLite file.

    Local force order for a 3D beam-column element is:
    ``P, Vy, Vz, T, My, Mz`` at end I followed by the same six values at end J.
    Non-tower components such as insulators and conductors are excluded.
    """

    def __init__(
        self,
        model: Any,
        database_path: str | Path,
        *,
        overwrite: bool = False,
        record_every: int = 1,
        commit_every: int = 10,
        strict: bool = True,
    ) -> None:
        self.model = model
        self.ops = model.ops
        self.database_path = Path(database_path)
        self.record_every = self._positive_int(record_every, "record_every")
        self.commit_every = self._positive_int(commit_every, "commit_every")
        self.strict = bool(strict)
        self.element_records = self._tower_elements(getattr(model, "element_map", {}))
        if not self.element_records:
            raise ValueError("模型中没有可记录的塔身单元。")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        if self.database_path.exists() and not overwrite:
            raise FileExistsError(
                f"内力数据库已存在: {self.database_path}；如需覆盖请设置 overwrite=True。"
            )
        if self.database_path.exists():
            self.database_path.unlink()
        self.connection = sqlite3.connect(self.database_path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self._sample_count = 0
        self._next_step = 0
        self._closed = False
        self._create_schema()
        self._write_element_metadata()

    @staticmethod
    def _positive_int(value: Any, name: str) -> int:
        number = int(value)
        if number < 1 or float(value) != number:
            raise ValueError(f"{name} 必须是正整数。")
        return number

    @staticmethod
    def _tower_elements(raw_elements: Any) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        excluded = {"insulator", "transmission_line", "conductor", "line"}
        for key, raw in (raw_elements or {}).items():
            record = dict(raw)
            component = str(record.get("component", "")).lower()
            if component in excluded:
                continue
            tag = int(record.get("element_tag", key))
            result[tag] = {**record, "element_tag": tag}
        return result

    def _create_schema(self) -> None:
        force_columns = ",\n".join(f"{name} REAL" for name in LOCAL_FORCE_COMPONENTS)
        self.connection.executescript(
            f"""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE elements (
                element_tag INTEGER PRIMARY KEY,
                tower_id TEXT,
                local_element_tag INTEGER,
                original_element_tag INTEGER,
                segment_index INTEGER,
                frame_name TEXT,
                node_i INTEGER,
                node_j INTEGER,
                section_name TEXT
            );
            CREATE TABLE force_history (
                step INTEGER NOT NULL,
                time REAL NOT NULL,
                element_tag INTEGER NOT NULL,
                {force_columns},
                PRIMARY KEY (step, element_tag),
                FOREIGN KEY (element_tag) REFERENCES elements(element_tag)
            );
            CREATE INDEX idx_force_history_time ON force_history(time);
            CREATE INDEX idx_force_history_element_time ON force_history(element_tag, time);
            """
        )
        metadata = {
            "format": "otw2.tower_internal_force.v1",
            "coordinate_system": "element_local",
            "force_components": list(LOCAL_FORCE_COMPONENTS),
            "units": {"force": "N", "moment": "N*m", "time": "OpenSees model time"},
            "record_every": self.record_every,
        }
        self.connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            [(key, json.dumps(value, ensure_ascii=False)) for key, value in metadata.items()],
        )

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        return None if value in (None, "") else int(value)

    def _write_element_metadata(self) -> None:
        rows = []
        for tag, record in sorted(self.element_records.items()):
            rows.append(
                (
                    tag,
                    str(record.get("tower_id", "")),
                    self._optional_int(record.get("local_element_tag")),
                    self._optional_int(record.get("original_element_tag")),
                    self._optional_int(record.get("segment_index")),
                    str(record.get("frame_name", record.get("original_frame_name", ""))),
                    self._optional_int(record.get("node_i")),
                    self._optional_int(record.get("node_j")),
                    str(record.get("section_name", "")),
                )
            )
        self.connection.executemany(
            "INSERT INTO elements VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
        )
        self.connection.commit()

    def capture(self, *, step: int | None = None, time: float | None = None) -> int:
        if self._closed:
            raise RuntimeError("内力记录器已经关闭。")
        resolved_step = self._next_step if step is None else int(step)
        self._next_step = max(self._next_step, resolved_step + 1)
        if resolved_step % self.record_every != 0:
            return 0
        resolved_time = float(self.ops.getTime() if time is None else time)
        if not math.isfinite(resolved_time):
            raise ValueError("记录时间必须是有限数值。")

        rows = []
        failures = []
        for element_tag in sorted(self.element_records):
            try:
                response = tuple(float(value) for value in self.ops.eleResponse(element_tag, "localForce"))
            except Exception as exc:  # pragma: no cover - depends on OpenSees element type
                failures.append((element_tag, str(exc)))
                if self.strict:
                    continue
                response = tuple(math.nan for _ in LOCAL_FORCE_COMPONENTS)
            if len(response) != len(LOCAL_FORCE_COMPONENTS):
                failures.append((element_tag, f"localForce 返回 {len(response)} 个分量"))
                if self.strict:
                    continue
                response = tuple(math.nan for _ in LOCAL_FORCE_COMPONENTS)
            rows.append((resolved_step, resolved_time, element_tag, *response))

        if failures and self.strict:
            tag, reason = failures[0]
            raise RuntimeError(
                f"无法记录完整塔身内力，单元 {tag}: {reason}；失败单元数={len(failures)}。"
            )
        placeholders = ",".join("?" for _ in range(3 + len(LOCAL_FORCE_COMPONENTS)))
        self.connection.executemany(
            f"INSERT OR REPLACE INTO force_history VALUES ({placeholders})", rows
        )
        self._sample_count += 1
        if self._sample_count % self.commit_every == 0:
            self.connection.commit()
        return len(rows)

    def flush(self) -> None:
        if not self._closed:
            self.connection.commit()

    def close(self) -> TowerInternalForceHistory:
        if not self._closed:
            self.connection.commit()
            self.connection.close()
            self._closed = True
        return TowerInternalForceHistory(self.database_path)

    def __enter__(self) -> "TowerInternalForceRecorder":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="查询并导出全塔单元内力时程数据库。")
    parser.add_argument("database", type=Path, help="tower_internal_forces.sqlite 路径")
    parser.add_argument("output", type=Path, help="输出 CSV 路径")
    parser.add_argument(
        "--mode",
        choices=("history", "snapshot", "envelope"),
        default="history",
        help="导出时程、指定时刻空间分布或时间段包络。",
    )
    parser.add_argument("--start", type=float, help="起始模型时间。")
    parser.add_argument("--end", type=float, help="结束模型时间。")
    parser.add_argument("--time", type=float, help="snapshot 模式请求时刻。")
    parser.add_argument("--element", type=int, action="append", dest="element_tags")
    parser.add_argument("--tower", action="append", dest="tower_ids")
    args = parser.parse_args()

    history = TowerInternalForceHistory(args.database)
    filters = {"element_tags": args.element_tags, "tower_ids": args.tower_ids}
    if args.mode == "snapshot":
        if args.time is None:
            parser.error("snapshot 模式必须提供 --time。")
        actual_time = history.nearest_recorded_time(args.time)
        path = history.export_snapshot_csv(args.output, args.time, **filters)
        print(f"已导出 {actual_time:g} 时刻的全塔内力分布: {path.resolve()}")
    elif args.mode == "envelope":
        path = history.export_envelope_csv(
            args.output,
            start_time=args.start,
            end_time=args.end,
            **filters,
        )
        print(f"已导出内力包络: {path.resolve()}")
    else:
        path = history.export_history_csv(
            args.output,
            start_time=args.start,
            end_time=args.end,
            **filters,
        )
        print(f"已导出内力时程: {path.resolve()}")


if __name__ == "__main__":
    main()
