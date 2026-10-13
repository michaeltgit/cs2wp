"""API contract tests on an empty local store (no demos, no model)."""


import numpy as np
import pytest
from fastapi.testclient import TestClient

from cs2wp_api.app import app
from cs2wp_api.util import clean


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/healthz").json()
    assert r == {"ok": True, "storage": "local", "bus": "inprocess", "db": "sqlite"}


def test_empty_lists(client):
    assert client.get("/api/demos").json() == []
    s = client.get("/api/status").json()
    assert s["summary"]["maps"] == 0 and s["matches"] == []
    assert client.get("/api/models").json() == {"active": None, "versions": {}}


def test_only_model_switching_changes_anything(client):
    """Adding/deleting/reprocessing demos, training, Kalshi linking and HLTV results are backend
    commands; the web API exposes none of them."""
    assert client.post("/api/models/v404/activate").status_code == 404
    for method, path in [("post", "/api/upload"), ("post", "/api/train"), ("delete", "/api/demos/x"),
                         ("post", "/api/demos/x/reprocess"), ("post", "/api/demos/x/kalshi"),
                         ("post", "/api/demos/x/kalshi/auto"), ("post", "/api/hltv/results"), ("get", "/api/auth")]:
        assert getattr(client, method)(path).status_code in (404, 405), path


def test_cors_allows_dev_frontend(client):
    r = client.options("/api/demos", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_unknown_demo_404s(client):
    assert client.get("/api/demos/nope").status_code == 404
    assert client.get("/api/demos/nope/kalshi").status_code == 404


def test_live_socket_reports_errors(client):
    with client.websocket_connect("/ws/live/nope/1") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "error"


def test_clean_makes_json_safe():
    assert clean({"a": np.float32("nan"), "b": [np.int64(3), np.bool_(True)], "c": float("inf")}) == \
        {"a": None, "b": [3, True], "c": None}
