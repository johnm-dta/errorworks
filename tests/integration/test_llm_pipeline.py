"""Integration tests for the ChaosLLM pipeline: preset -> config -> server -> HTTP."""

from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from errorworks.llm.config import load_config
from errorworks.llm.server import create_app
from tests.integration.conftest import CHAT_BODY, assert_rate_near

pytestmark = pytest.mark.integration

_TEST_TOKEN = "test-admin-token"


def _make_client(*, preset: str | None = None, config_file: Path | None = None) -> TestClient:
    """Build a TestClient from preset/config_file using the full load pipeline."""
    config = load_config(
        preset=preset,
        config_file=config_file,
        cli_overrides={"server": {"admin_token": _TEST_TOKEN}},
    )
    app = create_app(config)
    return TestClient(app, raise_server_exceptions=False)


_ADMIN_HEADERS = {"Authorization": f"Bearer {_TEST_TOKEN}"}


def test_silent_preset_returns_200() -> None:
    """Silent preset should produce zero errors."""
    client = _make_client(preset="silent")
    statuses = [client.post("/v1/chat/completions", json=CHAT_BODY).status_code for _ in range(50)]
    assert all(s == 200 for s in statuses), f"Expected all 200s, got non-200 codes: {[s for s in statuses if s != 200]}"


def test_gentle_preset_injects_errors() -> None:
    """Gentle preset sums to 2% errors; verify within tolerance over 500 requests."""
    client = _make_client(preset="gentle")
    n = 500
    errors = sum(1 for _ in range(n) if client.post("/v1/chat/completions", json=CHAT_BODY).status_code != 200)
    assert_rate_near(errors, n, expected_pct=2.0, tolerance_pct=4.0)


def test_stress_extreme_injects_heavily() -> None:
    """Stress-extreme preset should produce >30% errors."""
    client = _make_client(preset="stress_extreme")
    n = 100
    errors = sum(1 for _ in range(n) if client.post("/v1/chat/completions", json=CHAT_BODY).status_code != 200)
    assert errors > 30, f"Expected >30% errors, got {errors}/{n}"


def test_preset_plus_config_file_merge(tmp_path: Path) -> None:
    """Silent preset merged with a YAML overlay that sets rate_limit_pct=100 -> all 429."""
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text(yaml.dump({"error_injection": {"rate_limit_pct": 100.0}}))

    config = load_config(preset="silent", config_file=overlay)
    app = create_app(config)
    client = TestClient(app, raise_server_exceptions=False)

    statuses = [client.post("/v1/chat/completions", json=CHAT_BODY).status_code for _ in range(10)]
    assert all(s == 429 for s in statuses), f"Expected all 429s, got: {statuses}"


def test_metrics_recorded_after_requests() -> None:
    """After sending requests, /admin/stats should reflect them."""
    client = _make_client(preset="silent")
    for _ in range(10):
        client.post("/v1/chat/completions", json=CHAT_BODY)

    resp = client.get("/admin/stats", headers=_ADMIN_HEADERS)
    assert resp.status_code == 200
    stats = resp.json()
    assert isinstance(stats, dict)
    assert stats.get("total_requests", 0) >= 10


def test_config_reload_endpoint() -> None:
    """POST /admin/config should update error injection at runtime."""
    client = _make_client(preset="silent")

    # Baseline: silent preset returns 200
    assert client.post("/v1/chat/completions", json=CHAT_BODY).status_code == 200

    # Reload config to inject 100% rate-limit errors
    reload_resp = client.post("/admin/config", json={"error_injection": {"rate_limit_pct": 100.0}}, headers=_ADMIN_HEADERS)
    assert reload_resp.status_code == 200
    body = reload_resp.json()
    assert body["status"] == "updated"

    # Next request should be 429
    assert client.post("/v1/chat/completions", json=CHAT_BODY).status_code == 429


def test_azure_endpoint_compatibility() -> None:
    """Azure-style deployment endpoint should work identically to the OpenAI path."""
    client = _make_client(preset="silent")
    resp = client.post("/openai/deployments/gpt-4/chat/completions", json=CHAT_BODY)
    assert resp.status_code == 200
    data = resp.json()
    assert "choices" in data


def test_response_contains_choices() -> None:
    """Successful completion response should contain a non-empty choices list."""
    client = _make_client(preset="silent")
    resp = client.post("/v1/chat/completions", json=CHAT_BODY)
    assert resp.status_code == 200
    data = resp.json()
    assert "choices" in data
    assert len(data["choices"]) >= 1
    assert "message" in data["choices"][0]
