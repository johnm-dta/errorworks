"""Integration tests for the ChaosWeb pipeline: preset -> config -> server -> HTTP."""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from errorworks.web.config import load_config
from errorworks.web.server import create_app
from tests.integration.conftest import assert_rate_near

_TEST_TOKEN = "test-admin-token"
_ADMIN_HEADERS = {"Authorization": f"Bearer {_TEST_TOKEN}"}


@pytest.mark.integration
def test_silent_preset_returns_html() -> None:
    """Silent preset serves valid HTML with 200 status."""
    config = load_config(preset="silent")
    app = create_app(config)
    client = TestClient(app)

    resp = client.get("/")

    assert resp.status_code == 200
    body = resp.text.lower()
    assert "<html" in body
    assert "<body" in body


@pytest.mark.integration
def test_gentle_preset_injects_errors() -> None:
    """Gentle preset injects errors at ~2% rate (rate_limit 1% + not_found 1%)."""
    config = load_config(preset="gentle", cli_overrides={"latency": {"base_ms": 0, "jitter_ms": 0}})
    app = create_app(config)
    client = TestClient(app)

    total = 500
    errors = sum(1 for _ in range(total) if client.get("/").status_code != 200)

    assert_rate_near(errors, total, expected_pct=2.0, tolerance_pct=4.0)


@pytest.mark.integration
def test_stress_scraping_anti_bot() -> None:
    """Stress scraping preset produces >30% non-200 responses."""
    config = load_config(
        preset="stress_scraping",
        cli_overrides={
            "latency": {"base_ms": 0, "jitter_ms": 0},
            "error_injection": {
                "timeout_pct": 0.0,
                "slow_response_pct": 0.0,
                "connection_reset_pct": 0.0,
                "connection_stall_pct": 0.0,
                "incomplete_response_pct": 0.0,
            },
        },
    )
    app = create_app(config)
    # Disable redirect following — SSRF redirects target private IPs that TestClient can't resolve
    client = TestClient(app, follow_redirects=False)

    total = 100
    errors = sum(1 for _ in range(total) if client.get("/").status_code != 200)

    assert errors > total * 0.30, f"Expected >30% errors, got {errors}/{total}"


@pytest.mark.integration
def test_preset_plus_config_file_merge(tmp_path: Path) -> None:
    """Config file overlay on silent preset can override error injection."""
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("error_injection:\n  rate_limit_pct: 100.0\n")

    config = load_config(preset="silent", config_file=overlay)
    app = create_app(config)
    client = TestClient(app)

    for _ in range(10):
        resp = client.get("/")
        assert resp.status_code == 429


@pytest.mark.integration
def test_content_structure() -> None:
    """Silent preset returns HTML with standard structural elements."""
    config = load_config(preset="silent")
    app = create_app(config)
    client = TestClient(app)

    resp = client.get("/")

    assert resp.status_code == 200
    body = resp.text.lower()
    assert "<html" in body
    assert "<head" in body
    assert "<body" in body


@pytest.mark.integration
def test_metrics_recorded() -> None:
    """Requests are recorded and accessible via /admin/stats."""
    config = load_config(preset="silent", cli_overrides={"server": {"admin_token": _TEST_TOKEN}})
    app = create_app(config)
    client = TestClient(app)

    for _ in range(10):
        client.get("/")

    resp = client.get("/admin/stats", headers=_ADMIN_HEADERS)

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.integration
def test_redirect_deterministic() -> None:
    """SSRF redirect at 100% always returns 301."""
    config = load_config(
        preset="silent",
        cli_overrides={"error_injection": {"ssrf_redirect_pct": 100.0}},
    )
    app = create_app(config)
    client = TestClient(app, follow_redirects=False)

    resp = client.get("/")

    assert resp.status_code == 301


@pytest.mark.integration
def test_malformed_html_injection() -> None:
    """Truncated HTML at 100% returns a partial/malformed document."""
    config = load_config(
        preset="silent",
        cli_overrides={"error_injection": {"truncated_html_pct": 100.0}},
    )
    app = create_app(config)
    client = TestClient(app)

    resp = client.get("/")

    # Truncated HTML handler returns 200 with partial content
    body = resp.text.strip()
    assert resp.status_code != 200 or not body.endswith("</html>")
