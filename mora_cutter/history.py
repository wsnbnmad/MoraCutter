from __future__ import annotations

from collections import deque
from copy import deepcopy
from typing import Any
import time


class History:
    def __init__(self, capacity: int = 100):
        self.undo_stack: deque[Any] = deque(maxlen=capacity)
        self.redo_stack: deque[Any] = deque(maxlen=capacity)
        self._last_key: str | None = None
        self._last_recorded_at = 0.0

    def record(self, state: Any, coalesce_key: str | None = None) -> None:
        now = time.monotonic()
        if coalesce_key and coalesce_key == self._last_key and now - self._last_recorded_at < 1.0:
            self._last_recorded_at = now
            return
        self.undo_stack.append(deepcopy(state))
        self.redo_stack.clear()
        self._last_key = coalesce_key
        self._last_recorded_at = now

    def undo(self, current: Any) -> Any | None:
        if not self.undo_stack:
            return None
        self._last_key = None
        self.redo_stack.append(deepcopy(current))
        return self.undo_stack.pop()

    def redo(self, current: Any) -> Any | None:
        if not self.redo_stack:
            return None
        self._last_key = None
        self.undo_stack.append(deepcopy(current))
        return self.redo_stack.pop()
