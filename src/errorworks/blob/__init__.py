"""ChaosBlob: Fake object storage server for blob pipeline resilience testing.

ChaosBlob provides an S3-shaped object-storage surface with configurable
latency, storage limits, object/read failures, response corruption, and SQLite
metrics.
"""

from errorworks.blob.config import (
    DEFAULT_MEMORY_DB,
    BlobBurstConfig,
    BlobErrorInjectionConfig,
    BlobServerConfig,
    BlobStorageConfig,
    ChaosBlobConfig,
    list_presets,
    load_config,
    load_preset,
)
from errorworks.blob.error_injector import BlobErrorCategory, BlobErrorDecision, BlobErrorInjector, BlobOperation
from errorworks.blob.metrics import BlobMetricsRecorder, BlobOutcomeCounter, BlobRequestRecord
from errorworks.blob.server import ChaosBlobServer, create_app
from errorworks.blob.store import BlobListPage, BlobObject, BlobStore

__all__ = [
    "DEFAULT_MEMORY_DB",
    "BlobBurstConfig",
    "BlobErrorCategory",
    "BlobErrorDecision",
    "BlobErrorInjectionConfig",
    "BlobErrorInjector",
    "BlobListPage",
    "BlobMetricsRecorder",
    "BlobObject",
    "BlobOperation",
    "BlobOutcomeCounter",
    "BlobRequestRecord",
    "BlobServerConfig",
    "BlobStorageConfig",
    "BlobStore",
    "ChaosBlobConfig",
    "ChaosBlobServer",
    "create_app",
    "list_presets",
    "load_config",
    "load_preset",
]
