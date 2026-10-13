"""
Test setup: point every runtime directory and the SQLite database at a
temporary folder BEFORE the app is imported, then give each test a
FastAPI TestClient plus a helper that uploads a DataFrame as a CSV.

Run from the `backend/` directory:

    python -m pytest -q
"""
import io
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="pivot-tests-")
for _name, _sub in (
    ("UPLOAD_DIR", "uploads"),
    ("REPORTS_DIR", "reports"),
    ("LOG_DIR", "logs"),
):
    os.environ[_name] = os.path.join(_TMP, _sub)
os.environ["DB_PATH"] = os.path.join(_TMP, "data", "pivot.db")
os.environ["USERS_CSV_PATH"] = os.path.join(_TMP, "Users.csv")
os.environ["DISTRIBUTION_LISTS_CSV_PATH"] = os.path.join(_TMP, "DistributionLists.csv")
os.environ.pop("APP_AUTH_USERNAME", None)
os.environ.pop("APP_AUTH_PASSWORD", None)

# The app resolves templates / static files relative to backend/.
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_BACKEND)
sys.path.insert(0, _BACKEND)

import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def upload(client):
    """Upload a DataFrame as CSV and return the new dataset id."""
    def _upload(df: pd.DataFrame, name: str = "data.csv") -> int:
        buf = io.BytesIO()
        df.to_csv(buf, index=False)
        res = client.post(
            "/api/upload",
            files={"file": (name, buf.getvalue(), "text/csv")},
        )
        assert res.status_code == 200, res.text
        return res.json()["dataset_id"]
    return _upload
