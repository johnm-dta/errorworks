"""ChaosWeb: Fake web server for testing web scraping pipeline resilience.

ChaosWeb provides:
- Multi-path HTTP server impersonating real websites
- Configurable error injection (rate limits, bot detection, SSRF redirects)
- HTML content generation (random, template, preset snapshots, echo)
- Connection-level failures (timeout, reset, stall, incomplete response)
- Content malformations (encoding mismatches, truncated HTML, charset confusion)
- SQLite metrics storage for analysis

Usage:
    # CLI - Start server
    chaosweb serve --preset=realistic --port=8200

    # CLI - List presets
    chaosweb presets

    # Pytest fixture
    def test_pipeline(chaosweb_server):
        response = chaosweb_server.fetch_page("/articles/test")
        assert response.status_code == 200

    # With marker for configuration
    @pytest.mark.chaosweb(preset="stress_scraping")
    def test_under_stress(chaosweb_server):
        ...
"""

from errorworks.web.config import (
    ChaosWebConfig,
    WebBurstConfig,
    WebContentConfig,
    WebErrorInjectionConfig,
    list_presets,
    load_config,
    load_preset,
)
from errorworks.web.content_generator import ContentGenerator, WebResponse
from errorworks.web.error_injector import (
    SSRF_TARGETS,
    WebErrorCategory,
    WebErrorDecision,
    WebErrorInjector,
)
from errorworks.web.metrics import WebMetricsRecorder
from errorworks.web.server import ChaosWebServer, create_app

__all__ = [
    "SSRF_TARGETS",
    "ChaosWebConfig",
    "ChaosWebServer",
    "ContentGenerator",
    "WebBurstConfig",
    "WebContentConfig",
    "WebErrorCategory",
    "WebErrorDecision",
    "WebErrorInjectionConfig",
    "WebErrorInjector",
    "WebMetricsRecorder",
    "WebResponse",
    "create_app",
    "list_presets",
    "load_config",
    "load_preset",
]
