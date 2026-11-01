import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update({
    "ENVIRONMENT": "test",
    "DATABASE_URL": f"sqlite:///{_tmp}/test.db",
    "SECRET_KEY": "test-secret-key-that-is-long-enough-1234567890",
    "ANTHROPIC_API_KEY": "",
    "REDIS_URL": "",
    "GLOBAL_RATE_LIMIT_PER_MINUTE": "100000",
    "WIDGET_MESSAGES_PER_MINUTE": "1000",
    "WIDGET_CONVERSATIONS_PER_HOUR": "1000",
    "STRIPE_WEBHOOK_SECRET": "whsec_test_secret",
    "STRIPE_PRICE_STARTER": "price_starter",
    "STRIPE_PRICE_GROWTH": "price_growth",
    "STRIPE_PRICE_PRO": "price_pro",
    "PLATFORM_ADMIN_EMAILS": "founder@example.com",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.rate_limit import limiter  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "Correct-Horse-42!"
ALL_DAY = {str(d): [["00:00", "23:59"]] for d in range(7)}


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    limiter.reset()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.headers.update({"X-Requested-With": "XMLHttpRequest"})
        yield c


def register(client, email="alice@example.com", business="Alice Salon", tz="America/New_York", invite_token=None):
    body = {"email": email, "password": PASSWORD, "full_name": email.split("@")[0].title(), "timezone": tz}
    if invite_token:
        body["invite_token"] = invite_token
    else:
        body["business_name"] = business
    r = client.post("/api/v1/auth/register", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def h(token_out, org_id=None) -> dict:
    headers = {"Authorization": f"Bearer {token_out['access_token']}"}
    if org_id:
        headers["X-Org-Id"] = org_id
    return headers


def open_all_day(client, headers, **overrides):
    cfg = client.get("/api/v1/assistant", headers=headers).json()
    for k in ("widget_key", "updated_at"):
        cfg.pop(k)
    cfg.update(hours=ALL_DAY, min_notice_minutes=0, **overrides)
    r = client.put("/api/v1/assistant", json=cfg, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()
