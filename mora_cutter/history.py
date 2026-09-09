from __future__ import annotations

from collections import deque
from copy import deepcopy
from typing import Any


class History:
    def __init__(self, capacity: int = 100):
        self.undo_stack: deque[Any] = deque(maxlen=capacity)
        self.redo_stack: deque[Any] = deque(maxlen=capacity)

    def record(self, state: Any) -> None:
        self.undo_stack.append(deepcopy(state))
        self.redo_stack.clear()

    def undo(self, current: Any) -> Any | None:
        if not self.undo_stack:
            return None
        self.redo_stack.append(deepcopy(current))
        return self.undo_stack.pop()

    def redo(self, current: Any) -> Any | None:
        if not self.redo_stack:
            return None
        self.undo_stack.append(deepcopy(current))
        return self.redo_stack.pop()

