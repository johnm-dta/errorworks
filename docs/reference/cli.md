# CLI Reference

Errorworks provides several CLI entry points, all built with [Typer](https://typer.tiangolo.com/).

## `chaosengine` -- Unified CLI

The `chaosengine` command aggregates ChaosLLM, ChaosWeb, and ChaosBlob under a single entry point. It mounts the same Typer apps as subcommands, so all flags are identical to the standalone commands.

```bash
chaosengine llm serve --preset=gentle
chaosengine llm presets
chaosengine web serve --preset=stress_scraping
chaosengine web presets
chaosengine blob serve --preset=stress_storage
chaosengine blob presets
```

The standalone entry points (`chaosllm`, `chaosweb`, `chaosblob`) continue to work unchanged.

---

## `chaosllm` -- ChaosLLM Server

### `chaosllm serve`

Start the ChaosLLM fake LLM server with OpenAI and Azure OpenAI compatible endpoints.

**Configuration precedence** (highest to lowest):

1. Command-line flags
2. Config file (`--config`)
3. Preset (`--preset`)
4. Built-in defaults

#### Configuration Source Flags

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--preset` | `-p` | `None` | Preset configuration to use. Use `chaosllm presets` to list available presets. |
| `--config` | `-c` | `None` | Path to YAML configuration file. |

#### Server Binding Flags

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--host` | `-h` | `127.0.0.1` | Host address to bind to. |
| `--port` | `-P` | `8000` | Port to listen on (1-65535). |
| `--workers` | `-w` | `1` (or from preset) | Number of uvicorn workers. Workers > 1 require `--database` to point at a file-backed SQLite database. |
| `--allow-external-bind` | | `false` | Permit binding to all interfaces such as `0.0.0.0`. |

#### Metrics Flags

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--database` | `-d` | In-memory SQLite | SQLite database path for metrics storage. |

#### Error Injection Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--rate-limit-pct` | `0.0` | 429 Rate Limit error percentage (0-100). |
| `--capacity-529-pct` | `0.0` | 529 Capacity error percentage (0-100). |
| `--service-unavailable-pct` | `0.0` | 503 Service Unavailable error percentage (0-100). |
| `--internal-error-pct` | `0.0` | 500 Internal Error percentage (0-100). |
| `--timeout-pct` | `0.0` | Connection timeout percentage (0-100). |
| `--selection-mode` | `priority` | Error selection strategy: `priority` or `weighted`. |

#### Latency Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--base-ms` | `50` | Base latency in milliseconds. |
| `--jitter-ms` | `30` | Latency jitter in milliseconds (+/-). |

#### Response Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--response-mode` | `random` | Response generation mode: `random`, `template`, `echo`, `preset`. |

#### Burst Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--burst-enabled` / `--no-burst` | `False` | Enable burst pattern injection. |
| `--burst-interval-sec` | `30` | Time between burst starts in seconds. |
| `--burst-duration-sec` | `5` | How long each burst lasts in seconds. |

#### Misc Flags

| Flag | Short | Description |
|------|-------|-------------|
| `--version` | `-v` | Show version and exit. |

**Examples:**

```bash
# Start with defaults
chaosllm serve

# Use a preset
chaosllm serve --preset=stress_aimd

# Custom error rates
chaosllm serve --rate-limit-pct=10 --capacity-529-pct=5

# Custom port and database
chaosllm serve --port=9000 --database=./my-metrics.db
```

### `chaosllm presets`

List available preset configurations.

```bash
chaosllm presets
```

### `chaosllm show-config`

Display the effective (merged) configuration.

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--preset` | `-p` | `None` | Preset to show configuration for. |
| `--config` | `-c` | `None` | Config file to show. |
| `--format` | `-f` | `yaml` | Output format: `json` or `yaml`. |

```bash
chaosllm show-config --preset=stress_aimd --format=json
```

---

## `chaosweb` -- ChaosWeb Server

### `chaosweb serve`

Start the ChaosWeb fake web server for scraping pipeline resilience testing. Serves HTML pages with configurable error injection, content malformations, redirect loops, and SSRF injection.

**Configuration precedence** is identical to ChaosLLM.

#### Configuration Source Flags

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--preset` | `-p` | `None` | Preset configuration to use. Use `chaosweb presets` to list available. |
| `--config` | `-c` | `None` | Path to YAML configuration file. |

#### Server Binding Flags

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--host` | `-h` | `127.0.0.1` | Host address to bind to. |
| `--port` | `-P` | `8200` | Port to listen on (1-65535). |
| `--workers` | `-w` | `1` (or from preset) | Number of uvicorn workers. Workers > 1 require `--database` to point at a file-backed SQLite database. |
| `--allow-external-bind` | | `false` | Permit binding to all interfaces such as `0.0.0.0`. |

#### Metrics Flags

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--database` | `-d` | In-memory SQLite | SQLite database path for metrics. |

#### Error Injection Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--rate-limit-pct` | `0.0` | 429 Rate Limit error percentage (0-100). |
| `--forbidden-pct` | `0.0` | 403 Forbidden error percentage (0-100). |
| `--not-found-pct` | `0.0` | 404 Not Found error percentage (0-100). |
| `--service-unavailable-pct` | `0.0` | 503 Service Unavailable percentage (0-100). |
| `--internal-error-pct` | `0.0` | 500 Internal Error percentage (0-100). |
| `--timeout-pct` | `0.0` | Connection timeout percentage (0-100). |
| `--ssrf-redirect-pct` | `0.0` | SSRF redirect injection percentage (0-100). |
| `--selection-mode` | `priority` | Error selection: `priority` or `weighted`. |

The ChaosWeb CLI exposes the most common fault percentages. Configure the full fault surface, including content malformations and advanced redirect/stall ranges, through a YAML config file passed with `--config`.

#### Latency Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--base-ms` | `50` | Base latency in milliseconds. |
| `--jitter-ms` | `30` | Latency jitter in milliseconds (+/-). |

#### Content Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--content-mode` | `random` | Content generation: `random`, `template`, `echo`, `preset`. |

#### Burst Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--burst-enabled` / `--no-burst` | `False` | Enable burst pattern injection. |
| `--burst-interval-sec` | `30` | Time between burst starts. |
| `--burst-duration-sec` | `5` | Burst duration in seconds. |

#### Misc Flags

| Flag | Short | Description |
|------|-------|-------------|
| `--version` | `-v` | Show version. |

**Examples:**

```bash
chaosweb serve
chaosweb serve --preset=stress_scraping
chaosweb serve --rate-limit-pct=10 --forbidden-pct=5
chaosweb serve --port=9000 --database=./web-metrics.db
```

### `chaosweb presets`

List available preset configurations.

### `chaosweb show-config`

Display the effective (merged) configuration.

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--preset` | `-p` | `None` | Preset to show configuration for. |
| `--config` | `-c` | `None` | Config file to show. |
| `--format` | `-f` | `yaml` | Output format: `json` or `yaml`. |

---

## `chaosblob` -- ChaosBlob Server

### `chaosblob serve`

Start the ChaosBlob fake object-storage server for S3-style blob pipeline resilience testing.

**Configuration precedence** is identical to ChaosLLM and ChaosWeb.

#### Configuration Source Flags

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--preset` | `-p` | `None` | Preset configuration to use. Use `chaosblob presets` to list available. |
| `--config` | `-c` | `None` | Path to YAML configuration file. |

#### Server Binding Flags

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--host` | `-h` | `127.0.0.1` | Host address to bind to. |
| `--port` | `-P` | `8300` | Port to listen on (1-65535). |
| `--workers` | `-w` | `1` (or from preset) | Number of uvicorn workers. Multi-worker mode requires a file-backed metrics database. |
| `--allow-external-bind` | | `false` | Permit binding to all interfaces such as `0.0.0.0`. |

#### Metrics Flags

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--database` | `-d` | In-memory SQLite | SQLite database path for metrics. |

#### Error Injection Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--slow-down-pct` | `0.0` | S3 SlowDown percentage (0-100). |
| `--access-denied-pct` | `0.0` | 403 AccessDenied percentage (0-100). |
| `--not-found-pct` | `0.0` | 404 NoSuchKey percentage (0-100). |
| `--service-unavailable-pct` | `0.0` | 503 ServiceUnavailable percentage (0-100). |
| `--internal-error-pct` | `0.0` | 500 InternalError percentage (0-100). |
| `--bad-gateway-pct` | `0.0` | 502 BadGateway percentage (0-100). |
| `--gateway-timeout-pct` | `0.0` | 504 GatewayTimeout percentage (0-100). |
| `--timeout-pct` | `0.0` | Connection timeout percentage (0-100). |
| `--connection-reset-pct` | `0.0` | Connection reset percentage (0-100). |
| `--connection-stall-pct` | `0.0` | Connection stall percentage (0-100). |
| `--slow-response-pct` | `0.0` | Slow response percentage (0-100). |
| `--truncated-body-pct` | `0.0` | Truncated object body percentage (0-100). |
| `--wrong-content-length-pct` | `0.0` | Wrong Content-Length percentage (0-100). |
| `--checksum-mismatch-pct` | `0.0` | ETag/checksum mismatch percentage (0-100). |
| `--metadata-corruption-pct` | `0.0` | Object metadata corruption percentage (0-100). |
| `--stale-list-pct` | `0.0` | Stale list response percentage (0-100). |
| `--malformed-xml-pct` | `0.0` | Malformed XML response percentage (0-100). |
| `--selection-mode` | `priority` | Error selection: `priority` or `weighted`. |

#### Latency Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--base-ms` | `50` | Base latency in milliseconds. |
| `--jitter-ms` | `30` | Latency jitter in milliseconds (+/-). |

#### Burst Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--burst-enabled` / `--no-burst` | `False` | Enable burst pattern injection. |
| `--burst-interval-sec` | `60` | Time between burst starts. |
| `--burst-duration-sec` | `10` | Burst duration in seconds. |

#### Storage Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--max-object-bytes` | `10485760` | Maximum accepted object size in bytes. |

#### Misc Flags

| Flag | Short | Description |
|------|-------|-------------|
| `--version` | `-v` | Show version. |

**Examples:**

```bash
chaosblob serve
chaosblob serve --preset=realistic
chaosblob serve --slow-down-pct=10 --stale-list-pct=5
chaosblob serve --port=8300 --database=./blob-metrics.db
```

### `chaosblob presets`

List available preset configurations.

### `chaosblob show-config`

Display the effective (merged) configuration.

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--preset` | `-p` | `None` | Preset to show configuration for. |
| `--config` | `-c` | `None` | Config file to show. |
| `--format` | `-f` | `yaml` | Output format: `json` or `yaml`. |

---

## `chaosllm-mcp` -- MCP Metrics Server

Start the ChaosLLM MCP (Model Context Protocol) server for metrics analysis. Provides Claude-optimized tools for analyzing ChaosLLM metrics and investigating error patterns.

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--database` | `-d` | Auto-discovered | SQLite database path. If not specified, searches for `chaosllm-metrics.db` in the current directory and `./runs/`. |
| `--version` | `-v` | | Show version and exit. |

```bash
# Auto-discover database
chaosllm-mcp

# Explicit database path
chaosllm-mcp --database=./my-metrics.db
```

If no database is found and none is specified, the command exits with an error suggesting you run `chaosllm serve` first to create one.
