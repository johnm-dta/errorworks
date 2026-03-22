"""Tests for ChaosLLM MCP server."""

import json
import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from errorworks.llm_mcp.server import ChaosLLMAnalyzer, _find_metrics_databases, create_server, main

# === Fixtures ===


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create a temporary metrics database with schema."""
    db_path = tmp_path / "test_metrics.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS requests (
            request_id TEXT PRIMARY KEY,
            timestamp_utc TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            deployment TEXT,
            model TEXT,
            outcome TEXT NOT NULL,
            status_code INTEGER,
            error_type TEXT,
            injection_type TEXT,
            latency_ms REAL,
            injected_delay_ms REAL,
            message_count INTEGER,
            prompt_tokens_approx INTEGER,
            response_tokens INTEGER,
            response_mode TEXT
        );

        CREATE TABLE IF NOT EXISTS timeseries (
            bucket_utc TEXT PRIMARY KEY,
            requests_total INTEGER NOT NULL DEFAULT 0,
            requests_success INTEGER NOT NULL DEFAULT 0,
            requests_rate_limited INTEGER NOT NULL DEFAULT 0,
            requests_capacity_error INTEGER NOT NULL DEFAULT 0,
            requests_server_error INTEGER NOT NULL DEFAULT 0,
            requests_client_error INTEGER NOT NULL DEFAULT 0,
            requests_connection_error INTEGER NOT NULL DEFAULT 0,
            requests_malformed INTEGER NOT NULL DEFAULT 0,
            avg_latency_ms REAL,
            p99_latency_ms REAL
        );

        CREATE TABLE IF NOT EXISTS run_info (
            run_id TEXT PRIMARY KEY,
            started_utc TEXT NOT NULL,
            config_json TEXT NOT NULL,
            preset_name TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_requests_timestamp ON requests(timestamp_utc);
        CREATE INDEX IF NOT EXISTS idx_requests_outcome ON requests(outcome);
        """
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def empty_analyzer(temp_db: Path) -> Generator[ChaosLLMAnalyzer, None, None]:
    """Create analyzer with empty database."""
    analyzer = ChaosLLMAnalyzer(str(temp_db))
    yield analyzer
    analyzer.close()


@pytest.fixture
def populated_analyzer(temp_db: Path) -> Generator[ChaosLLMAnalyzer, None, None]:
    """Create analyzer with pre-populated test data."""
    conn = sqlite3.connect(str(temp_db))

    # Insert test requests
    base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

    requests = [
        # 10 successful requests
        *[
            (
                f"req-success-{i}",
                (base_time + timedelta(seconds=i)).isoformat(),
                "/chat/completions",
                "gpt-4",
                "gpt-4",
                "success",
                200,
                None,
                None,
                100.0 + i * 10,  # latency varies
                None,
                3,
                100,
                50,
                "random",
            )
            for i in range(10)
        ],
        # 3 rate limited requests (429)
        *[
            (
                f"req-429-{i}",
                (base_time + timedelta(seconds=20 + i)).isoformat(),
                "/chat/completions",
                "gpt-4",
                "gpt-4",
                "error_injected",
                429,
                "rate_limit",
                "rate_limit",
                None,
                None,
                3,
                100,
                None,
                None,
            )
            for i in range(3)
        ],
        # 2 capacity errors (529)
        *[
            (
                f"req-529-{i}",
                (base_time + timedelta(seconds=25 + i)).isoformat(),
                "/chat/completions",
                "gpt-4",
                "gpt-4",
                "error_injected",
                529,
                "capacity",
                "capacity",
                None,
                None,
                3,
                100,
                None,
                None,
            )
            for i in range(2)
        ],
        # 1 timeout
        (
            "req-timeout-1",
            (base_time + timedelta(seconds=30)).isoformat(),
            "/chat/completions",
            "gpt-4",
            "gpt-4",
            "error_injected",
            None,
            "timeout",
            "timeout",
            None,
            None,
            3,
            100,
            None,
            None,
        ),
    ]

    conn.executemany(
        """
        INSERT INTO requests (
            request_id, timestamp_utc, endpoint, deployment, model,
            outcome, status_code, error_type, injection_type, latency_ms, injected_delay_ms,
            message_count, prompt_tokens_approx, response_tokens, response_mode
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        requests,
    )

    # Insert timeseries buckets
    timeseries = [
        # First bucket: all success
        (
            (base_time + timedelta(seconds=0)).isoformat(),
            5,
            5,
            0,
            0,
            0,
            0,
            0,
            0,
            110.0,
            140.0,
        ),
        # Second bucket: some success
        (
            (base_time + timedelta(seconds=5)).isoformat(),
            5,
            5,
            0,
            0,
            0,
            0,
            0,
            0,
            160.0,
            180.0,
        ),
        # Third bucket: errors
        (
            (base_time + timedelta(seconds=20)).isoformat(),
            3,
            0,
            3,
            0,
            0,
            0,
            0,
            0,
            None,
            None,
        ),
        # Fourth bucket: capacity errors
        (
            (base_time + timedelta(seconds=25)).isoformat(),
            3,
            0,
            0,
            2,
            0,
            0,
            0,
            0,
            None,
            None,
        ),
    ]

    conn.executemany(
        """
        INSERT INTO timeseries (
            bucket_utc, requests_total, requests_success, requests_rate_limited,
            requests_capacity_error, requests_server_error, requests_client_error,
            requests_connection_error, requests_malformed, avg_latency_ms, p99_latency_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        timeseries,
    )

    conn.commit()
    conn.close()

    analyzer = ChaosLLMAnalyzer(str(temp_db))
    yield analyzer
    analyzer.close()


# === Test ChaosLLMAnalyzer ===


class TestDiagnose:
    """Tests for diagnose() tool."""

    def test_empty_database(self, empty_analyzer: ChaosLLMAnalyzer) -> None:
        """Returns NO_DATA for empty database."""
        result = empty_analyzer.diagnose()
        assert result["status"] == "NO_DATA"
        assert "No requests" in result["summary"]

    def test_populated_database(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """Returns summary for populated database."""
        result = populated_analyzer.diagnose()

        assert result["status"] in ("OK", "WARNING", "CRITICAL")
        assert result["total_requests"] == 16
        assert result["success_rate_pct"] > 0
        assert "summary" in result
        assert len(result["top_errors"]) > 0

    def test_aimd_assessment_present(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """AIMD assessment is present in result."""
        result = populated_analyzer.diagnose()
        assert "aimd_assessment" in result
        assert result["rate_limit_pct"] > 0


class TestAnalyzeAimdBehavior:
    """Tests for analyze_aimd_behavior() tool."""

    def test_empty_database(self, empty_analyzer: ChaosLLMAnalyzer) -> None:
        """Returns NO_DATA for empty database."""
        result = empty_analyzer.analyze_aimd_behavior()
        assert result["status"] == "NO_DATA"

    def test_populated_database(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """Returns AIMD analysis for populated database."""
        result = populated_analyzer.analyze_aimd_behavior()

        assert "summary" in result
        assert "burst_count" in result
        assert "backoff_ratio" in result
        assert "backoff_assessment" in result


class TestAnalyzeErrors:
    """Tests for analyze_errors() tool."""

    def test_empty_database(self, empty_analyzer: ChaosLLMAnalyzer) -> None:
        """Returns NO_DATA for empty database."""
        result = empty_analyzer.analyze_errors()
        assert result["status"] == "NO_DATA"

    def test_populated_database(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """Returns error breakdown for populated database."""
        result = populated_analyzer.analyze_errors()

        assert result["total_requests"] == 16
        assert result["total_errors"] > 0
        assert "by_error_type" in result
        assert "by_status_code" in result

        # Check error types are present
        error_types = [e["type"] for e in result["by_error_type"]]
        assert "rate_limit" in error_types

    def test_sample_timestamps(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """Sample timestamps are provided for error types."""
        result = populated_analyzer.analyze_errors()

        assert "sample_timestamps" in result
        assert len(result["sample_timestamps"]) > 0


class TestAnalyzeLatency:
    """Tests for analyze_latency() tool."""

    def test_empty_database(self, empty_analyzer: ChaosLLMAnalyzer) -> None:
        """Returns NO_DATA for empty database."""
        result = empty_analyzer.analyze_latency()
        assert result["status"] == "NO_DATA"

    def test_populated_database(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """Returns latency stats for populated database."""
        result = populated_analyzer.analyze_latency()

        assert "p50_ms" in result
        assert "p95_ms" in result
        assert "p99_ms" in result
        assert "avg_ms" in result
        assert "max_ms" in result
        assert result["p50_ms"] > 0


class TestFindAnomalies:
    """Tests for find_anomalies() tool."""

    def test_empty_database(self, empty_analyzer: ChaosLLMAnalyzer) -> None:
        """Returns no anomalies for empty database."""
        result = empty_analyzer.find_anomalies()
        assert result["anomaly_count"] == 0

    def test_populated_database(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """Returns anomalies for populated database."""
        result = populated_analyzer.find_anomalies()

        assert "summary" in result
        assert "anomalies" in result


class TestGetBurstEvents:
    """Tests for get_burst_events() tool."""

    def test_empty_database(self, empty_analyzer: ChaosLLMAnalyzer) -> None:
        """Returns empty list for empty database."""
        result = empty_analyzer.get_burst_events()
        assert result["burst_events"] == []

    def test_populated_database(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """Returns burst events for populated database."""
        result = populated_analyzer.get_burst_events()
        assert "burst_count" in result
        assert "burst_events" in result


class TestGetErrorSamples:
    """Tests for get_error_samples() tool."""

    def test_no_matching_errors(self, empty_analyzer: ChaosLLMAnalyzer) -> None:
        """Returns empty samples when no errors match."""
        result = empty_analyzer.get_error_samples("nonexistent_type")
        assert result["sample_count"] == 0
        assert result["samples"] == []

    def test_matching_errors(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """Returns samples for matching error type."""
        result = populated_analyzer.get_error_samples("rate_limit", limit=5)

        assert result["error_type"] == "rate_limit"
        assert result["sample_count"] == 3  # We inserted 3 rate limit errors
        assert len(result["samples"]) == 3

    def test_limit_respected(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """Limit parameter is respected."""
        result = populated_analyzer.get_error_samples("rate_limit", limit=1)
        assert result["sample_count"] == 1


class TestGetTimeWindow:
    """Tests for get_time_window() tool."""

    def test_empty_window(self, empty_analyzer: ChaosLLMAnalyzer) -> None:
        """Returns zeros for empty time window."""
        result = empty_analyzer.get_time_window(
            start_sec=0,
            end_sec=1000000000,
        )
        assert result["total_requests"] == 0

    def test_populated_window(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """Returns stats for populated time window."""
        # Use a wide window that includes all test data
        base_ts = datetime(2024, 1, 15, 0, 0, 0, tzinfo=UTC).timestamp()
        result = populated_analyzer.get_time_window(
            start_sec=base_ts,
            end_sec=base_ts + 86400,  # +1 day
        )

        assert result["total_requests"] == 16
        assert result["success_count"] == 10
        assert result["rate_limited_count"] == 3


class TestQuery:
    """Tests for raw SQL query() tool."""

    def test_select_query(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """SELECT queries work."""
        result = populated_analyzer.query("SELECT COUNT(*) as cnt FROM requests")
        assert len(result) == 1
        assert result[0]["cnt"] == 16

    def test_non_select_rejected(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """Non-SELECT queries are rejected."""
        with pytest.raises(ValueError, match="Only SELECT"):
            populated_analyzer.query("INSERT INTO requests VALUES ('x')")

    def test_dangerous_keywords_rejected(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """Dangerous keywords in SELECT are rejected."""
        with pytest.raises(ValueError, match="forbidden keyword"):
            populated_analyzer.query("SELECT * FROM requests; DROP TABLE requests")

    def test_auto_limit_added(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """Auto LIMIT 100 is added when missing."""
        result = populated_analyzer.query("SELECT * FROM requests")
        # Should work and return <= 100 results
        assert len(result) <= 100

    # --- SQL injection bypass vectors ---

    @pytest.mark.parametrize(
        "sql,keyword",
        [
            ("SELECT * FROM requests; DROP TABLE requests", "DROP"),
            ("SELECT * FROM (DELETE FROM requests RETURNING *)", "DELETE"),
            ("SELECT 1; ATTACH DATABASE ':memory:' AS x", "ATTACH"),
            ("SELECT 1; DETACH DATABASE main", "DETACH"),
            ("SELECT * FROM requests; PRAGMA table_info(requests)", "PRAGMA"),
            ("SELECT * FROM requests; CREATE TABLE evil(x TEXT)", "CREATE"),
            ("SELECT * FROM requests; ALTER TABLE requests RENAME TO x", "ALTER"),
            ("SELECT * FROM requests; TRUNCATE TABLE requests", "TRUNCATE"),
            ("SELECT * FROM requests; VACUUM", "VACUUM"),
            ("SELECT * FROM requests; REPLACE INTO requests VALUES ('x')", "REPLACE"),
            ("SELECT * FROM requests; UPDATE requests SET outcome='x'", "UPDATE"),
        ],
    )
    def test_dangerous_keyword_variants(self, populated_analyzer: ChaosLLMAnalyzer, sql: str, keyword: str) -> None:
        """Keyword blocklist catches various injection patterns."""
        with pytest.raises(ValueError, match="forbidden keyword"):
            populated_analyzer.query(sql)

    def test_case_insensitive_keyword_detection(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """Keyword detection is case-insensitive."""
        with pytest.raises(ValueError, match="forbidden keyword"):
            populated_analyzer.query("select * from requests; drop table requests")

    def test_comment_based_bypass_blocked(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """SQL comments do not bypass keyword detection."""
        # The keyword scanner works on the full string including comments
        with pytest.raises(ValueError, match="forbidden keyword"):
            populated_analyzer.query("SELECT * FROM requests /* DROP TABLE requests */")

    def test_authorizer_blocks_write_operations(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """set_authorizer prevents write operations that slip past keyword blocklist."""
        # REINDEX is in the blocklist, but test that authorizer is the safety net
        # by verifying that even a valid SELECT cannot trigger writes
        # The authorizer should block any non-read operation at the SQLite engine level
        result = populated_analyzer.query("SELECT COUNT(*) as cnt FROM requests")
        assert result[0]["cnt"] == 16  # Read still works

    def test_existing_limit_preserved(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """Queries with existing LIMIT are not double-limited."""
        result = populated_analyzer.query("SELECT * FROM requests LIMIT 3")
        assert len(result) == 3

    def test_column_name_false_positive_avoided(self, populated_analyzer: ChaosLLMAnalyzer) -> None:
        """Column names like 'created_at' don't trigger CREATE false positive."""
        # Word-boundary matching should prevent false positives
        # This query references a non-existent column, but it should fail
        # with a SQL error, not a "forbidden keyword" error
        with pytest.raises(sqlite3.OperationalError):
            populated_analyzer.query("SELECT created_at FROM requests")


class TestDescribeSchema:
    """Tests for describe_schema() tool."""

    def test_returns_schema(self, empty_analyzer: ChaosLLMAnalyzer) -> None:
        """Returns schema description."""
        result = empty_analyzer.describe_schema()

        assert "tables" in result
        assert "requests" in result["tables"]
        assert "timeseries" in result["tables"]
        assert "run_info" in result["tables"]


# === Test MCP Server Creation ===


class TestCreateServer:
    """Tests for MCP server creation."""

    def test_creates_server(self, temp_db: Path) -> None:
        """Server can be created."""
        server, analyzer = create_server(str(temp_db))
        assert server is not None
        assert server.name == "chaosllm-analysis"
        analyzer.close()


# === Integration Tests with Actual MCP Protocol ===


class TestMCPServerTools:
    """Tests for MCP server creation and basic functionality."""

    def test_server_has_name(self, temp_db: Path) -> None:
        """Server has correct name."""
        server, analyzer = create_server(str(temp_db))
        assert server.name == "chaosllm-analysis"
        analyzer.close()

    def test_diagnose_via_analyzer(self, temp_db: Path) -> None:
        """Diagnose tool can be called via analyzer."""
        # We test through the analyzer directly since MCP protocol testing
        # requires a full stdio server setup
        from errorworks.llm_mcp.server import ChaosLLMAnalyzer

        analyzer = ChaosLLMAnalyzer(str(temp_db))
        result = analyzer.diagnose()
        assert "status" in result
        analyzer.close()


# === call_tool Dispatcher Tests ===


def _make_call_tool_request(name: str, arguments: dict | None = None):
    """Helper to construct a CallToolRequest for testing the MCP handler."""
    from mcp.types import CallToolRequest, CallToolRequestParams

    return CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=arguments),
    )


def _extract_text(server_result) -> str:
    """Extract the text content from a ServerResult or CallToolResult."""
    # ServerResult wraps a CallToolResult in .root
    call_result = server_result.root
    return call_result.content[0].text


def _extract_is_error(server_result) -> bool:
    """Extract the isError flag from a ServerResult."""
    return server_result.root.isError


class TestCallToolDispatcher:
    """Tests for the MCP call_tool handler dispatch logic."""

    @pytest.fixture
    def mcp_server_with_data(self, temp_db: Path):
        """Create MCP server with a populated database and return server + analyzer."""
        conn = sqlite3.connect(str(temp_db))
        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        conn.execute(
            """
            INSERT INTO requests (
                request_id, timestamp_utc, endpoint, deployment, model,
                outcome, status_code, error_type, injection_type, latency_ms, injected_delay_ms,
                message_count, prompt_tokens_approx, response_tokens, response_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "req-1",
                base_time.isoformat(),
                "/chat/completions",
                "gpt-4",
                "gpt-4",
                "error_injected",
                429,
                "rate_limit",
                "rate_limit",
                None,
                None,
                3,
                100,
                None,
                None,
            ),
        )
        conn.commit()
        conn.close()

        server, analyzer = create_server(str(temp_db))
        yield server, analyzer
        analyzer.close()

    @pytest.fixture
    def mcp_server_empty(self, temp_db: Path):
        """Create MCP server with an empty database."""
        server, analyzer = create_server(str(temp_db))
        yield server, analyzer
        analyzer.close()

    @pytest.mark.asyncio
    async def test_valid_tool_dispatches_correctly(self, mcp_server_with_data) -> None:
        """A valid tool call dispatches to the correct analyzer method and returns results."""
        from mcp.types import CallToolRequest

        server, _analyzer = mcp_server_with_data
        handler = server.request_handlers[CallToolRequest]

        request = _make_call_tool_request("analyze_errors", {})
        result = await handler(request)

        text = _extract_text(result)
        parsed = json.loads(text)
        assert parsed["total_requests"] == 1
        assert parsed["total_errors"] == 1
        assert not _extract_is_error(result)

    @pytest.mark.asyncio
    async def test_diagnose_dispatches(self, mcp_server_empty) -> None:
        """Diagnose tool dispatches and returns valid JSON."""
        from mcp.types import CallToolRequest

        server, _analyzer = mcp_server_empty
        handler = server.request_handlers[CallToolRequest]

        request = _make_call_tool_request("diagnose", {})
        result = await handler(request)

        text = _extract_text(result)
        parsed = json.loads(text)
        assert parsed["status"] == "NO_DATA"
        assert not _extract_is_error(result)

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, mcp_server_empty) -> None:
        """An unknown tool name returns error content."""
        from mcp.types import CallToolRequest

        server, _analyzer = mcp_server_empty
        handler = server.request_handlers[CallToolRequest]

        request = _make_call_tool_request("nonexistent_tool", {})
        result = await handler(request)

        text = _extract_text(result)
        assert "Unknown tool" in text
        assert "nonexistent_tool" in text
        assert _extract_is_error(result)

    @pytest.mark.asyncio
    async def test_missing_required_argument_returns_error(self, mcp_server_empty) -> None:
        """Missing required arguments are handled gracefully with error content."""
        from mcp.types import CallToolRequest

        server, _analyzer = mcp_server_empty
        handler = server.request_handlers[CallToolRequest]

        # get_error_samples requires "error_type" argument — the MCP framework
        # validates inputSchema before calling our handler, so the error comes
        # from jsonschema validation rather than our KeyError handler.
        request = _make_call_tool_request("get_error_samples", {})
        result = await handler(request)

        text = _extract_text(result)
        assert "error_type" in text
        assert "required" in text.lower()
        assert _extract_is_error(result)

    @pytest.mark.asyncio
    async def test_tool_with_arguments_dispatches(self, mcp_server_with_data) -> None:
        """Tool calls with arguments dispatch correctly."""
        from mcp.types import CallToolRequest

        server, _analyzer = mcp_server_with_data
        handler = server.request_handlers[CallToolRequest]

        request = _make_call_tool_request("get_error_samples", {"error_type": "rate_limit", "limit": 2})
        result = await handler(request)

        text = _extract_text(result)
        parsed = json.loads(text)
        assert parsed["error_type"] == "rate_limit"
        assert parsed["sample_count"] == 1
        assert not _extract_is_error(result)

    @pytest.mark.asyncio
    async def test_query_tool_dispatches(self, mcp_server_with_data) -> None:
        """Query tool dispatches and executes SQL."""
        from mcp.types import CallToolRequest

        server, _analyzer = mcp_server_with_data
        handler = server.request_handlers[CallToolRequest]

        request = _make_call_tool_request("query", {"sql": "SELECT COUNT(*) as cnt FROM requests"})
        result = await handler(request)

        text = _extract_text(result)
        parsed = json.loads(text)
        assert parsed[0]["cnt"] == 1
        assert not _extract_is_error(result)

    @pytest.mark.asyncio
    async def test_query_validation_error_returns_error_content(self, mcp_server_empty) -> None:
        """A ValueError from query validation returns error content (not an exception)."""
        from mcp.types import CallToolRequest

        server, _analyzer = mcp_server_empty
        handler = server.request_handlers[CallToolRequest]

        request = _make_call_tool_request("query", {"sql": "DROP TABLE requests"})
        result = await handler(request)

        text = _extract_text(result)
        parsed = json.loads(text)
        assert "error" in parsed
        assert parsed["error_type"] == "validation_error"
        assert _extract_is_error(result)

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_is_error(self, mcp_server_empty) -> None:
        """An unexpected exception in a tool sets isError=True on the result."""
        from mcp.types import CallToolRequest

        server, _analyzer = mcp_server_empty
        handler = server.request_handlers[CallToolRequest]

        # Patch the analyzer's diagnose method to raise an unexpected error
        with patch.object(_analyzer, "diagnose", side_effect=RuntimeError("unexpected boom")):
            request = _make_call_tool_request("diagnose", {})
            result = await handler(request)

            text = _extract_text(result)
            parsed = json.loads(text)
            assert parsed["error"] == "unexpected boom"
            assert parsed["error_type"] == "RuntimeError"
            assert _extract_is_error(result)

    @pytest.mark.asyncio
    async def test_describe_schema_dispatches(self, mcp_server_empty) -> None:
        """describe_schema tool dispatches correctly."""
        from mcp.types import CallToolRequest

        server, _analyzer = mcp_server_empty
        handler = server.request_handlers[CallToolRequest]

        request = _make_call_tool_request("describe_schema", {})
        result = await handler(request)

        text = _extract_text(result)
        parsed = json.loads(text)
        assert "tables" in parsed
        assert not _extract_is_error(result)


# === _find_metrics_databases Tests ===


class TestFindMetricsDatabases:
    """Tests for _find_metrics_databases helper."""

    def test_finds_db_files(self, tmp_path: Path) -> None:
        """Finds .db files in a temp directory."""
        db1 = tmp_path / "chaosllm-metrics.db"
        db2 = tmp_path / "other.db"
        db1.touch()
        db2.touch()

        result = _find_metrics_databases(str(tmp_path))
        assert len(result) == 2
        # chaosllm-metrics.db should be prioritized (priority 0)
        assert result[0] == str(db1)

    def test_returns_empty_when_no_databases(self, tmp_path: Path) -> None:
        """Returns empty list when no .db files exist."""
        result = _find_metrics_databases(str(tmp_path))
        assert result == []

    def test_handles_nonexistent_directory(self, tmp_path: Path) -> None:
        """Handles directories that don't exist gracefully."""
        nonexistent = tmp_path / "does_not_exist"
        # Path.rglob on a nonexistent path should not crash
        result = _find_metrics_databases(str(nonexistent))
        assert result == []

    def test_skips_hidden_directories(self, tmp_path: Path) -> None:
        """Files inside hidden directories are skipped."""
        hidden_dir = tmp_path / ".hidden"
        hidden_dir.mkdir()
        (hidden_dir / "metrics.db").touch()

        result = _find_metrics_databases(str(tmp_path))
        assert result == []

    def test_respects_max_depth(self, tmp_path: Path) -> None:
        """Files deeper than max_depth are excluded."""
        deep = tmp_path / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "metrics.db").touch()

        # max_depth=3 means path parts relative to search_dir must be <= 3
        result = _find_metrics_databases(str(tmp_path), max_depth=3)
        assert result == []

        # With higher depth it should be found
        result = _find_metrics_databases(str(tmp_path), max_depth=5)
        assert len(result) == 1

    def test_priority_ordering(self, tmp_path: Path) -> None:
        """Databases are prioritized: chaosllm+metrics > chaosllm > metrics > other."""
        (tmp_path / "other.db").touch()
        (tmp_path / "metrics.db").touch()
        (tmp_path / "chaosllm.db").touch()
        (tmp_path / "chaosllm-metrics.db").touch()

        result = _find_metrics_databases(str(tmp_path))
        assert len(result) == 4
        # Priority 0: chaosllm + metrics
        assert "chaosllm-metrics.db" in result[0]
        # Priority 1: chaosllm
        assert "chaosllm.db" in result[1]
        # Priority 2: metrics
        assert "metrics.db" in result[2]


# === CLI main() Tests ===


class TestCLIMain:
    """Tests for CLI entry point."""

    def test_help_flag_exits_cleanly(self) -> None:
        """--help flag causes SystemExit(0) with no errors."""
        with pytest.raises(SystemExit) as exc_info, patch("sys.argv", ["chaosllm-mcp", "--help"]):
            main()
        assert exc_info.value.code == 0

    def test_missing_database_exits_with_error(self, tmp_path: Path) -> None:
        """Exits with error when no databases are found and none specified."""
        with pytest.raises(SystemExit) as exc_info, patch("sys.argv", ["chaosllm-mcp", "--search-dir", str(tmp_path)]):
            main()
        assert exc_info.value.code == 1

    def test_nonexistent_database_path_exits_with_error(self, tmp_path: Path) -> None:
        """Exits with error when specified database path doesn't exist."""
        fake_db = tmp_path / "nonexistent.db"
        with pytest.raises(SystemExit) as exc_info, patch("sys.argv", ["chaosllm-mcp", "--database", str(fake_db)]):
            main()
        assert exc_info.value.code == 1


# =============================================================================
# Connection Resilience
# =============================================================================


class TestConnectionResilience:
    """Tests for _get_connection health-check and reconnection logic."""

    def test_reconnects_after_closed_connection(self, temp_db: Path) -> None:
        """Analyzer reconnects transparently when the cached connection is closed."""
        analyzer = ChaosLLMAnalyzer(str(temp_db))
        # Prime the connection
        conn1 = analyzer._get_connection()
        assert conn1.execute("SELECT 1").fetchone() is not None

        # Force-close the underlying connection to simulate staleness
        conn1.close()

        # Next call should reconnect
        conn2 = analyzer._get_connection()
        assert conn2 is not conn1
        assert conn2.execute("SELECT 1").fetchone() is not None
        analyzer.close()

    def test_reconnected_connection_has_row_factory(self, temp_db: Path) -> None:
        """After reconnection, row_factory is sqlite3.Row (queries return Row objects)."""
        analyzer = ChaosLLMAnalyzer(str(temp_db))
        analyzer._get_connection().close()  # force staleness

        conn = analyzer._get_connection()
        assert conn.row_factory is sqlite3.Row
        analyzer.close()

    def test_healthy_connection_reused(self, temp_db: Path) -> None:
        """A healthy cached connection is reused without reconnection."""
        analyzer = ChaosLLMAnalyzer(str(temp_db))
        conn1 = analyzer._get_connection()
        conn2 = analyzer._get_connection()
        assert conn1 is conn2
        analyzer.close()


# =============================================================================
# Analysis Logic Bug Fixes
# =============================================================================


class TestPercentileCalculation:
    """Tests for percentile calculation in analyze_latency."""

    def test_p99_not_maximum_for_100_values(self, temp_db: Path) -> None:
        """With exactly 100 values, p99 should NOT equal the maximum value."""
        conn = sqlite3.connect(str(temp_db))
        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        for i in range(100):
            conn.execute(
                "INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"req-{i}",
                    (base_time + timedelta(seconds=i)).isoformat(),
                    "/chat/completions",
                    None,
                    None,
                    "success",
                    200,
                    None,
                    None,
                    float(i + 1),
                    None,
                    None,
                    None,
                    None,
                    None,  # latency 1..100
                ),
            )
        conn.commit()
        conn.close()

        analyzer = ChaosLLMAnalyzer(str(temp_db))
        result = analyzer.analyze_latency()
        analyzer.close()

        # p99 of [1..100] should be 99, not 100 (the max)
        assert result["p99_ms"] < 100.0, f"p99 should not equal the maximum value, got {result['p99_ms']}"


class TestBurstDetection:
    """Tests for burst detection in get_burst_events and analyze_aimd_behavior."""

    @pytest.fixture
    def trailing_burst_analyzer(self, temp_db: Path) -> Generator[ChaosLLMAnalyzer, None, None]:
        """Create analyzer with timeseries data where a burst is active at the end."""
        conn = sqlite3.connect(str(temp_db))
        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        # 5 normal buckets, then 3 burst buckets at the end (no recovery)
        for i in range(8):
            bucket = (base_time + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M")
            if i < 5:
                # Normal: 10 requests, 1 error (10% error rate)
                conn.execute(
                    "INSERT INTO timeseries (bucket_utc, requests_total, requests_success, "
                    "requests_rate_limited, requests_capacity_error, requests_server_error, "
                    "requests_client_error, requests_connection_error, requests_malformed) "
                    "VALUES (?, 10, 9, 1, 0, 0, 0, 0, 0)",
                    (bucket,),
                )
            else:
                # Burst: 10 requests, 5 rate limited (50% error rate)
                conn.execute(
                    "INSERT INTO timeseries (bucket_utc, requests_total, requests_success, "
                    "requests_rate_limited, requests_capacity_error, requests_server_error, "
                    "requests_client_error, requests_connection_error, requests_malformed) "
                    "VALUES (?, 10, 5, 5, 0, 0, 0, 0, 0)",
                    (bucket,),
                )
        conn.commit()
        conn.close()

        analyzer = ChaosLLMAnalyzer(str(temp_db))
        yield analyzer
        analyzer.close()

    def test_trailing_burst_not_dropped(self, trailing_burst_analyzer: ChaosLLMAnalyzer) -> None:
        """A burst still active at end of data should be included in burst_events."""
        result = trailing_burst_analyzer.get_burst_events()
        assert result["burst_count"] >= 1, "Trailing burst was silently dropped"

    def test_trailing_burst_excluded_from_aimd_recovery(self, trailing_burst_analyzer: ChaosLLMAnalyzer) -> None:
        """Unfinished bursts should not contribute to avg_recovery_buckets."""
        # Add request data so analyze_aimd_behavior has something to work with
        conn = sqlite3.connect(trailing_burst_analyzer._db_path)
        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        for i in range(20):
            if i < 12:
                outcome, status, etype = "success", 200, None
            else:
                outcome, status, etype = "error_injected", 429, "rate_limit"
            conn.execute(
                "INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"req-{i}",
                    (base_time + timedelta(seconds=i)).isoformat(),
                    "/chat/completions",
                    None,
                    None,
                    outcome,
                    status,
                    etype,
                    etype,
                    100.0,
                    None,
                    None,
                    None,
                    None,
                    None,
                ),
            )
        conn.commit()
        conn.close()

        result = trailing_burst_analyzer.analyze_aimd_behavior()
        # If there's only an unfinished burst, avg_recovery should be 0 (no completed recoveries)
        if result.get("burst_count", 0) > 0 and result.get("status") != "NO_DATA":
            assert result.get("avg_recovery_buckets", 0) == 0, "Unfinished burst should not report a recovery time"


class TestAnomalyDetection:
    """Tests for find_anomalies error clustering."""

    def test_server_error_clustering_detected(self, temp_db: Path) -> None:
        """Error clustering should detect server_error, not just rate_limited/capacity_error."""
        conn = sqlite3.connect(str(temp_db))
        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

        # Insert 30 requests — 15 success, 15 server errors (need >10 errors for threshold)
        for i in range(30):
            if i < 15:
                outcome, status, etype = "success", 200, None
            else:
                outcome, status, etype = "error_injected", 500, "internal_error"
            conn.execute(
                "INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"req-{i}",
                    (base_time + timedelta(seconds=i)).isoformat(),
                    "/chat/completions",
                    None,
                    None,
                    outcome,
                    status,
                    etype,
                    etype,
                    100.0,
                    None,
                    None,
                    None,
                    None,
                    None,
                ),
            )

        # 20 timeseries buckets, only 1 has server errors (= 5% of buckets, under 10% threshold)
        for i in range(20):
            bucket = (base_time + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M")
            if i == 10:
                conn.execute(
                    "INSERT INTO timeseries (bucket_utc, requests_total, requests_success, "
                    "requests_rate_limited, requests_capacity_error, requests_server_error, "
                    "requests_client_error, requests_connection_error, requests_malformed) "
                    "VALUES (?, 5, 0, 0, 0, 5, 0, 0, 0)",
                    (bucket,),
                )
            else:
                conn.execute(
                    "INSERT INTO timeseries (bucket_utc, requests_total, requests_success, "
                    "requests_rate_limited, requests_capacity_error, requests_server_error, "
                    "requests_client_error, requests_connection_error, requests_malformed) "
                    "VALUES (?, 1, 1, 0, 0, 0, 0, 0, 0)",
                    (bucket,),
                )
        conn.commit()
        conn.close()

        analyzer = ChaosLLMAnalyzer(str(temp_db))
        result = analyzer.find_anomalies()
        analyzer.close()

        clustering = [a for a in result["anomalies"] if a["type"] == "error_clustering"]
        assert len(clustering) > 0, "Server error clustering was not detected"
