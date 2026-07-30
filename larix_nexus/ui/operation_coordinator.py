"""Single-owner coordination for filesystem/network operations."""

from __future__ import annotations

from collections.abc import Callable


class FileOperationCoordinator:
    """Own at most one user or automatic file operation at a time."""

    def __init__(self, on_deferred_auto_ready: Callable[[], None] | None = None):
        self._active: str | None = None
        self._auto_pending = False
        self._on_deferred_auto_ready = on_deferred_auto_ready

    @property
    def active_operation(self) -> str | None:
        return self._active

    @property
    def auto_pending(self) -> bool:
        return self._auto_pending

    def is_busy(self) -> bool:
        return self._active is not None

    def try_acquire_user(self, operation: str) -> bool:
        if self._active is not None:
            return False
        self._active = str(operation)
        return True

    def try_acquire_auto(self) -> bool:
        if self._active is not None:
            self._auto_pending = True
            return False
        self._active = "sync"
        self._auto_pending = False
        return True

    def release(self, operation: str | None = None) -> bool:
        if self._active is None:
            return False
        if operation is not None and self._active != operation:
            return False
        self._active = None
        if self._auto_pending:
            self._auto_pending = False
            callback = self._on_deferred_auto_ready
            if callback is not None:
                callback()
        return True

    def cancel_pending_auto(self) -> None:
        self._auto_pending = False
