"""Focused tests for the soft-refresh progress reconciliation hook."""

from types import SimpleNamespace

from larix_nexus.ui.tree_operations import soft_refresh_and_restore_view


class _SoftRefreshOwner:
    def __init__(self, *, project_id=None, load_error=None):
        self.tree = SimpleNamespace(currentItem=lambda: None)
        self._project_id = project_id
        self._load_error = load_error
        self.reconcile_scheduled = 0

    def current_project_id(self):
        return self._project_id

    def load_tree_for_project(self, _project_id, *, expanded_folder_ids):
        assert expanded_folder_ids == set()
        if self._load_error is not None:
            raise self._load_error

    def _schedule_orphaned_generic_progress_reconcile(self):
        self.reconcile_scheduled += 1


def test_soft_refresh_schedules_reconcile_on_normal_path():
    owner = _SoftRefreshOwner()

    soft_refresh_and_restore_view(owner)

    assert owner.reconcile_scheduled == 1


def test_soft_refresh_schedules_reconcile_when_refresh_raises():
    owner = _SoftRefreshOwner(project_id="project", load_error=RuntimeError("refresh failed"))

    soft_refresh_and_restore_view(owner)

    assert owner.reconcile_scheduled == 1
