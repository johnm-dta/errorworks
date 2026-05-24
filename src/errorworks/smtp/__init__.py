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
from errorworks.smtp.metrics import SMTPMetricsRecorder
from errorworks.smtp.server import ChaosSMTPServer, create_admin_app

__all__ = [
    "DEFAULT_MEMORY_DB",
    "CapturedMessage",
    "ChaosSMTPConfig",
    "ChaosSMTPServer",
    "MessageCapture",
    "SMTPAdminConfig",
    "SMTPBurstConfig",
    "SMTPCaptureConfig",
    "SMTPErrorCategory",
    "SMTPErrorDecision",
    "SMTPErrorInjectionConfig",
    "SMTPErrorInjector",
    "SMTPMetricsRecorder",
    "SMTPServerConfig",
    "SMTPStage",
    "create_admin_app",
    "list_presets",
    "load_config",
    "load_preset",
]
