"""Bounded-memory reading of a top-level states array in gzip JSON evidence.

Archives remain unchanged. This avoids loading all detailed sections when a
postprocessor needs only original-point forces from every nth committed state.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Iterator, TextIO


class _JsonStream:
    def __init__(self, stream: TextIO, *, chunk_size: int = 65536, max_value_chars: int = 64 * 1024 * 1024):
        self.stream, self.chunk_size, self.max_value_chars = stream, chunk_size, max_value_chars
        self.buffer, self.position, self.eof = "", 0, False
        self.decoder = json.JSONDecoder()

    def fill(self) -> None:
        self.buffer = self.buffer[self.position:]
        self.position = 0
        chunk = self.stream.read(self.chunk_size)
        self.eof = not chunk
        self.buffer += chunk
        if len(self.buffer) > self.max_value_chars:
            raise ValueError("Archive JSON value exceeds the bounded streaming limit")

    def peek(self) -> str:
        while True:
            while self.position < len(self.buffer) and self.buffer[self.position].isspace():
                self.position += 1
            if self.position < len(self.buffer):
                return self.buffer[self.position]
            if self.eof:
                raise ValueError("Truncated state archive")
            self.fill()

    def expect(self, character: str) -> None:
        if self.peek() != character:
            raise ValueError(f"Invalid state archive; expected {character!r}")
        self.position += 1

    def value(self) -> Any:
        self.peek()
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer, self.position)
                # A scalar number could continue beyond the current chunk.
                needs_more = end == len(self.buffer) or self.buffer[end] not in ",]}: \t\r\n"
                if needs_more:
                    if self.eof and end != len(self.buffer):
                        raise ValueError("Invalid delimiter in state archive JSON")
                    if not self.eof:
                        self.fill()
                        continue
                self.position = end
                return value
            except json.JSONDecodeError as error:
                if self.eof:
                    raise ValueError("Malformed or truncated state archive JSON") from error
                self.fill()


def iter_archive_states(path: str | Path, *, chunk_size: int = 65536) -> Iterator[dict[str, Any]]:
    """Yield top-level states one at a time; do not scan nested key strings.

The remaining top-level tail is intentionally not parsed. Run/case completion
and checksums must be validated by the caller's artifact-manifest gate.
"""
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        reader = _JsonStream(stream, chunk_size=chunk_size)
        reader.expect("{")
        while reader.peek() != "}":
            key = reader.value()
            if not isinstance(key, str):
                raise ValueError("Archive object key is not a string")
            reader.expect(":")
            if key == "states":
                reader.expect("[")
                if reader.peek() == "]":
                    return
                while True:
                    state = reader.value()
                    if not isinstance(state, dict):
                        raise ValueError("An archived state must be a JSON object")
                    yield state
                    if reader.peek() == "]":
                        return
                    reader.expect(",")
            reader.value()
            if reader.peek() == "}":
                break
            reader.expect(",")
        raise ValueError("Archive has no top-level states array")
