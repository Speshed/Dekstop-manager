from pathlib import Path
from uuid import uuid4

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    """Avoid restricted-host cleanup of pytest's inaccessible basetemp root."""
    factory = getattr(session.config, "_tmp_path_factory", None)
    if factory is not None:
        factory._basetemp = None


@pytest.fixture
def tmp_path(request):
    """Workspace-local replacement for pytest's temp fixture on restricted Windows hosts."""
    root = Path(request.config.rootpath) / "larix_nexus" / "tests" / ".runtime" / "cases"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"test-{uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        for child in path.iterdir():
            if child.is_dir():
                for nested in child.rglob("*"):
                    if nested.is_file():
                        nested.unlink()
                for nested in sorted(child.rglob("*"), reverse=True):
                    if nested.is_dir():
                        nested.rmdir()
                child.rmdir()
            else:
                child.unlink()
        path.rmdir()
