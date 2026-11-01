import os
import tempfile
from pathlib import Path
import pytest

_temp_dir = tempfile.mkdtemp()
_test_db = Path(_temp_dir) / "test_platform.db"
_test_storage = Path(_temp_dir) / "data"

os.environ["DATABASE_URL"] = f"sqlite:///{_test_db}"
os.environ["STORAGE_DIR"] = str(_test_storage)

@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    try:
        from app.database import session as db_session
        db_session.engine.dispose()
    except Exception:
        pass
