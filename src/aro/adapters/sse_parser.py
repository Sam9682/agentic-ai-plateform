"""Pure Server-Sent Events (SSE) parser (Task 9).

SHAI's HTTP transport streams responses as SSE. This module reassembles SSE
events from arbitrary byte/text chunks per the W3C event-stream grammar:

* a line ``field: value`` contributes to the current event;
* a blank line dispatches the accumulated event;
* multiple ``data:`` lines are joined with ``\n``;
* lines beginning with ``:`` are comments (ignored).

Kept pure so the HTTP adapter's stream handling is unit-tested without a server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, List, Optional


@dataclass
class SSEEvent:
    event: Optional[str] = None
    data: str = ""
    id: Optional[str] = None


class SSEParser:
    """Incremental SSE parser. Feed text chunks; yields complete events."""

    def __init__(self) -> None:
        self._buf = ""
        self._event: Optional[str] = None
        self._data_lines: List[str] = []
        self._id: Optional[str] = None

    def feed(self, chunk: str) -> Iterator[SSEEvent]:
        self._buf += chunk
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.rstrip("\r")
            if line == "":
                event = self._dispatch()
                if event is not None:
                    yield event
                continue
            if line.startswith(":"):
                continue  # comment
            field_name, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field_name == "event":
                self._event = value
            elif field_name == "data":
                self._data_lines.append(value)
            elif field_name == "id":
                self._id = value
            # unknown fields are ignored per spec

    def _dispatch(self) -> Optional[SSEEvent]:
        if not self._data_lines and self._event is None and self._id is None:
            return None
        event = SSEEvent(
            event=self._event,
            data="\n".join(self._data_lines),
            id=self._id,
        )
        self._event = None
        self._data_lines = []
        self._id = None
        return event
