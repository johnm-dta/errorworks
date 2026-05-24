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
from errorworks.smtp.error_injector import SMTPErrorCategory, SMTPErrorDecision, SMTPErrorInjector, SMTPStage
from errorworks.smtp.message_capture import CapturedMessage, MessageCapture

__all__ = [
    "DEFAULT_MEMORY_DB",
    "CapturedMessage",
    "ChaosSMTPConfig",
    "MessageCapture",
    "SMTPAdminConfig",
    "SMTPBurstConfig",
    "SMTPCaptureConfig",
    "SMTPErrorCategory",
    "SMTPErrorDecision",
    "SMTPErrorInjectionConfig",
    "SMTPErrorInjector",
    "SMTPServerConfig",
    "SMTPStage",
    "list_presets",
    "load_config",
    "load_preset",
]
