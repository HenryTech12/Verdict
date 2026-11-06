import os
import tempfile

# Must be set before the app is imported so tests never touch a developer's real database or API keys.
_tmp = tempfile.mkdtemp(prefix="verdict-tests-")
os.environ.update({"DATABASE_URL": f"sqlite:///{_tmp}/test.db", "AUTO_SEED": "false", "PAYPAL_MODE": "mock", "LLM_PROVIDER": "mock", "STAGE_DELAY_MS": "0", "API_TOKEN": "verdict-demo-token"})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

AUTH = {"Authorization": "Bearer verdict-demo-token"}


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as test_client:
        test_client.headers.update(AUTH)
        yield test_client


def run_case(client: TestClient, case: str) -> dict:
    response = client.post(f"/sim/dispute?case={case}")
    assert response.status_code == 201, response.text
    return client.get(f"/disputes/{response.json()['dispute_id']}").json()
