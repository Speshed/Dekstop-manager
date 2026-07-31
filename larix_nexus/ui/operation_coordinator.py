"""Single-owner coordination for filesystem/network operations."""

from __future__ import annotations

from collections.abc import Callable
import logging


_LOG = logging.getLogger(__name__)


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

    def _log(self, event: str, operation: str | None, previous: str | None,
             source: str, *, current: str | None = None) -> None:
        _LOG.debug(
            "file-operation %s operation=%r previous=%r current=%r source=%s",
            event,
            operation,
            previous,
            self._active if current is None else current,
            source,
        )

    def try_acquire_user(self, operation: str, source: str = "user") -> bool:
        previous = self._active
        if self._active is not None:
            self._log("acquire-rejected", str(operation), previous, source)
            return False
        self._active = str(operation)
        self._log("acquire", self._active, previous, source)
        return True

    def try_acquire_auto(self, source: str = "auto_sync") -> bool:
        previous = self._active
        if self._active is not None:
            self._auto_pending = True
            self._log("auto-acquire-deferred", "sync", previous, source)
            return False
        self._active = "sync"
        self._auto_pending = False
        self._log("acquire", self._active, previous, source)
        return True

    def release(self, operation: str | None = None, source: str = "release") -> bool:
        previous = self._active
        if self._active is None:
            self._log("release-ignored", operation, previous, source)
            return False
        if operation is not None and self._active != operation:
            self._log("release-ignored-owner-mismatch", operation, previous, source)
            return False
        self._active = None
        self._log("release", operation or previous, previous, source)
        if self._auto_pending:
            self._auto_pending = False
            callback = self._on_deferred_auto_ready
            if callback is not None:
                callback()
        return True

    def cancel_pending_auto(self) -> None:
        self._auto_pending = False
