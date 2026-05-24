"""ChaosSMTP: Fake SMTP server for outbound email resilience testing."""

from errorworks.smtp.config import (
    DEFAULT_MEMORY_DB,
    ChaosSMTPConfig,
    SMTPAdminConfig,
    SMTPBurstConfig,
    SMTPCaptureConfig,
    SMTPErrorInjectionConfig,
    SMTPServerConfig,
    list_presets,
    load_config,
    load_preset,
)

__all__ = [
    "DEFAULT_MEMORY_DB",
    "ChaosSMTPConfig",
    "SMTPAdminConfig",
    "SMTPBurstConfig",
    "SMTPCaptureConfig",
    "SMTPErrorInjectionConfig",
    "SMTPServerConfig",
    "list_presets",
    "load_config",
    "load_preset",
]
