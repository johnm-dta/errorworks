"""ChaosLLM: Fake LLM server for load testing and fault injection.

ChaosLLM provides:
- OpenAI and Azure OpenAI compatible endpoints
- Configurable error injection (rate limits, capacity errors, timeouts, malformed responses)
- Response generation (random, template, preset bank)
- Burst pattern simulation for AIMD throttle testing
- SQLite metrics storage for analysis

Usage:
    # CLI - Start server
    chaosllm serve --preset=stress_aimd --port=8000

    # CLI - List presets
    chaosllm presets

    # Pytest fixture
    def test_pipeline(chaosllm_server):
        response = chaosllm_server.post_completion()
        assert response.status_code == 200

    # With marker for configuration
    @pytest.mark.chaosllm(preset="stress_aimd")
    def test_under_stress(chaosllm_server):
        ...
"""

from errorworks.llm.config import (
    DEFAULT_MEMORY_DB,
    ChaosLLMConfig,
    ErrorInjectionConfig,
    LatencyConfig,
    MetricsConfig,
    ResponseConfig,
    ServerConfig,
    list_presets,
    load_config,
    load_preset,
)
from errorworks.llm.error_injector import ErrorDecision, ErrorInjector
from errorworks.llm.metrics import MetricsRecorder
from errorworks.llm.response_generator import (
    ENGLISH_VOCABULARY,
    LOREM_VOCABULARY,
    OpenAIResponse,
    ResponseGenerator,
)
from errorworks.llm.server import ChaosLLMServer, create_app

__all__ = [
    "DEFAULT_MEMORY_DB",
    "ENGLISH_VOCABULARY",
    "LOREM_VOCABULARY",
    "ChaosLLMConfig",
    "ChaosLLMServer",
    "ErrorDecision",
    "ErrorInjectionConfig",
    "ErrorInjector",
    "LatencyConfig",
    "MetricsConfig",
    "MetricsRecorder",
    "OpenAIResponse",
    "ResponseConfig",
    "ResponseGenerator",
    "ServerConfig",
    "create_app",
    "list_presets",
    "load_config",
    "load_preset",
]
