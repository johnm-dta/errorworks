# ChaosBlob Guide

ChaosBlob is a fake object storage server that injects configurable faults into S3-style blob workflows. Point an object-storage client at ChaosBlob to test throttling, stale listings, corrupted object reads, metadata surprises, and retry behavior before those failures show up in production.

ChaosBlob is intentionally S3-compatible-ish, not a complete S3 implementation. It supports path-style object operations and S3-shaped XML responses for the core workflows that pipelines usually depend on.

## Quick Start

```bash
# Start with a realistic object-store failure profile
uv run chaosblob serve --preset=realistic

# Store an object
curl -X PUT http://127.0.0.1:8300/my-bucket/logs/1.json \
  -H "Content-Type: application/json" \
  -d '{"id": 1}'

# Read it back
curl http://127.0.0.1:8300/my-bucket/logs/1.json

# List objects with the S3 ListObjectsV2 shape
curl "http://127.0.0.1:8300/my-bucket?list-type=2&prefix=logs/"
```

## Scope

ChaosBlob focuses on object workflow resilience, not full AWS compatibility.

Supported:

- Path-style object URLs: `/{bucket}/{key}`
- `PUT`, `GET`, `HEAD`, and `DELETE` object operations
- `ListObjectsV2` style listing with `list-type=2`, `prefix`, `max-keys`, and `continuation-token`
- S3-shaped XML errors and list responses
- ETag, content type, object metadata, and object size handling
- Runtime config updates, metrics, presets, CLI, and pytest fixture support

Not implemented:

- Virtual-hosted bucket addressing
- SigV4 authentication or authorization policies
- Multipart upload, versioning, lifecycle rules, ACLs, or bucket policies
- Durable object persistence

## Endpoints

### Object Operations

| Endpoint | Method | Description |
|---|---|---|
| `/{bucket}/{key:path}` | PUT | Store an object body and headers |
| `/{bucket}/{key:path}` | GET | Return object bytes and metadata |
| `/{bucket}/{key:path}` | HEAD | Return object metadata without a body |
| `/{bucket}/{key:path}` | DELETE | Delete an object, returning 204 whether or not it existed |
| `/{bucket}?list-type=2` | GET | List objects in key order |

`PUT` stores `Content-Type` and any `x-amz-meta-*` headers. The server returns quoted MD5 ETags for stored objects. Objects live in memory and are cleared by `/admin/reset` or process restart.

List pagination uses opaque continuation tokens that resume after the last key returned on the previous page. `max-keys` must be at least `1`; values above S3's `1000` key page limit are capped to `1000`.

### Health and Admin

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/health` | GET | None | Server health check with `run_id`, `started_utc`, and `in_burst` |
| `/admin/config` | GET | Bearer token | View current configuration |
| `/admin/config` | POST | Bearer token | Update configuration at runtime |
| `/admin/stats` | GET | Bearer token | Request statistics summary |
| `/admin/export` | GET | Bearer token | Export raw metrics and config |
| `/admin/reset` | POST | Bearer token | Reset metrics, stored objects, and burst state |

Admin endpoints require an `Authorization: Bearer <token>` header. The token is auto-generated if omitted, but generated tokens are not printed. Set `server.admin_token` explicitly in config when you need to call the admin API.

## Error Injection

ChaosBlob injects object-storage failures with percentage fields from `0.0` to `100.0`.

### S3 HTTP Errors

These return XML error bodies with S3-style `Code`, `Message`, `Resource`, and `RequestId` fields.

| Error Type | Status | Config Field | S3 Code | Description |
|---|---:|---|---|---|
| Slow Down | 503 | `slow_down_pct` | `SlowDown` | Throttling response with `Retry-After` |
| Access Denied | 403 | `access_denied_pct` | `AccessDenied` | Permission-style failure |
| Not Found | 404 | `not_found_pct` | `NoSuchKey` | Missing object response |
| Service Unavailable | 503 | `service_unavailable_pct` | `ServiceUnavailable` | Temporary service outage |
| Internal Error | 500 | `internal_error_pct` | `InternalError` | Server-side failure |
| Bad Gateway | 502 | `bad_gateway_pct` | `BadGateway` | Upstream failure |
| Gateway Timeout | 504 | `gateway_timeout_pct` | `GatewayTimeout` | Upstream timeout |

`slow_down_pct` uses `retry_after_sec` to choose the `Retry-After` header value.

### Connection Failures

| Error Type | Config Field | Behavior |
|---|---|---|
| Timeout | `timeout_pct` | Waits for `timeout_sec`, records a timeout, then returns 504 XML |
| Connection Reset | `connection_reset_pct` | Starts a response and then disconnects |
| Connection Stall | `connection_stall_pct` | Delays, stalls for `connection_stall_sec`, then disconnects |
| Slow Response | `slow_response_pct` | Delays `slow_response_sec`, then returns a 503 SlowDown-style response |

### Object Corruption

These failures return HTTP 200, so clients need to validate bodies, metadata, and checksums instead of relying only on status codes.

| Error Type | Config Field | Applies To | Behavior |
|---|---|---|---|
| Truncated Body | `truncated_body_pct` | GET | Returns half the object body and matching shorter `Content-Length` |
| Wrong Content-Length | `wrong_content_length_pct` | GET | Declares the full length, sends a partial body, then disconnects |
| Checksum Mismatch | `checksum_mismatch_pct` | GET | Returns the object body with a corrupted ETag |
| Metadata Corruption | `metadata_corruption_pct` | GET, HEAD | Drops one stored `x-amz-meta-*` header |

### List Corruption

| Error Type | Config Field | Behavior |
|---|---|---|
| Stale List | `stale_list_pct` | Omits the newest object from a list page |
| Malformed XML | `malformed_xml_pct` | Returns a broken `ListBucketResult` document |

### Burst Patterns

Bursts simulate short windows where an object store starts throttling or returning service errors.

```yaml
error_injection:
  burst:
    enabled: true
    interval_sec: 90
    duration_sec: 10
    slow_down_pct: 35.0
    service_unavailable_pct: 10.0
```

During a burst, the burst `slow_down_pct` and `service_unavailable_pct` temporarily override the baseline values. `/health` exposes `in_burst` for test harnesses that need to observe the current window.

### Selection Mode

- **`priority`** (default): Errors are evaluated in a fixed order and the first triggered error wins.
- **`weighted`**: Configured percentages are treated as proportional weights and one error type is selected from the weighted set.

## Storage Settings

| Field | Default | Description |
|---|---:|---|
| `max_object_bytes` | `10485760` | Maximum accepted object body size |
| `default_content_type` | `application/octet-stream` | Content type used when a PUT has no `Content-Type` header |
| `expose_s3_xml` | `true` | Reserved setting for S3-shaped XML responses |

Objects are stored in memory. If you update `storage` at runtime, ChaosBlob rebuilds the store with the new limits and clears existing objects.

## Available Presets

| Preset | Error Rate | Latency | Burst | Best For |
|---|---:|---|---|---|
| `silent` | 0% | 50ms +/- 25ms | Off | Baseline object workflow measurement |
| `gentle` | ~1.5% | 100ms +/- 50ms | Off | Happy-path tests with light throttling |
| `realistic` | ~15% | 150ms +/- 75ms | 90s/10s | Production-like object-store behavior |
| `stress_storage` | ~64% | 250ms +/- 150ms | 60s/12s | Body, metadata, and stale-list resilience |
| `stress_extreme` | ~108% configured weights | 600ms +/- 300ms | 30s/8s | Breaking-point retry and corruption testing |

## Usage Examples

### CLI

```bash
# Start with a preset
uv run chaosblob serve --preset=realistic

# Stress storage corruption and stale listings
uv run chaosblob serve --preset=stress_storage

# Custom object limit and metrics database
uv run chaosblob serve --max-object-bytes=1048576 --database=./blob-metrics.db

# Via the unified CLI
uv run chaosengine blob serve --preset=realistic
```

### Python

```python
from errorworks.blob.config import load_config
from errorworks.blob.server import ChaosBlobServer, create_app

config = load_config(preset="realistic")
app = create_app(config)

server = ChaosBlobServer(config)
server.update_config({"error_injection": {"slow_down_pct": 25.0}})
stats = server.get_stats()
```

### Pytest Fixture

```python
import pytest

from tests.fixtures.chaosblob import chaosblob  # noqa: F401


@pytest.mark.chaosblob(preset="silent", slow_down_pct=100.0)
def test_pipeline_retries_slow_down(chaosblob):
    response = chaosblob.put_object("bucket", "incoming/item.json", b'{"id": 1}')
    assert response.status_code == 503
    assert "retry-after" in response.headers

    chaosblob.update_config(slow_down_pct=0.0)
    assert chaosblob.put_object("bucket", "incoming/item.json", b'{"id": 1}').status_code == 200
```

## Related Pages

- [Presets](presets.md) -- Full preset comparison and customization
- [Configuration](configuration.md) -- YAML config file structure and precedence rules
- [Metrics](metrics.md) -- Querying request statistics
- [Testing Fixtures](testing-fixtures.md) -- In-process testing with pytest
