
  ---
  Source Code (9,307 lines → 14 chunks)

  Chunk 1: Engine Core Types & Init (326 lines)

  - src/errorworks/engine/types.py (270)
  - src/errorworks/engine/__init__.py (53)
  - src/errorworks/__init__.py (3)

  Chunk 2: Injection Engine & Latency (254 lines)

  - src/errorworks/engine/injection_engine.py (176)
  - src/errorworks/engine/latency.py (78)

  Chunk 3: Config Loading & Validation (273 lines)

  - src/errorworks/engine/config_loader.py (153)
  - src/errorworks/engine/validators.py (120)

  Chunk 4: Metrics Store (614 lines)

  - src/errorworks/engine/metrics_store.py (614)

  Chunk 5: Engine Utilities (372 lines)

  - src/errorworks/engine/vocabulary.py (219)
  - src/errorworks/engine/admin.py (116)
  - src/errorworks/engine/cli.py (37)

  Chunk 6: LLM Config (498 lines)

  - src/errorworks/llm/config.py (498)

  Chunk 7: LLM Error Injector & Response Generator (814 lines)

  - src/errorworks/llm/error_injector.py (354)
  - src/errorworks/llm/response_generator.py (460)

  Chunk 8: LLM Server (811 lines)

  - src/errorworks/llm/server.py (811)

  Chunk 9: LLM CLI & Metrics (917 lines)

  - src/errorworks/llm/cli.py (558)
  - src/errorworks/llm/metrics.py (289)
  - src/errorworks/llm/__init__.py (70)

  Chunk 10: Web Config (551 lines)

  - src/errorworks/web/config.py (551)

  Chunk 11: Web Error Injector & Content Generator (1,012 lines — slightly over, tightly coupled)

  - src/errorworks/web/error_injector.py (436)
  - src/errorworks/web/content_generator.py (576)

  Chunk 12: Web Server (937 lines)

  - src/errorworks/web/server.py (937)

  Chunk 13: Web CLI & Metrics (694 lines)

  - src/errorworks/web/cli.py (363)
  - src/errorworks/web/metrics.py (266)
  - src/errorworks/web/__init__.py (65)
  - src/errorworks/testing/__init__.py (5)

  Chunk 14: MCP Server (1,229 lines — single file, can't split)

  - src/errorworks/llm_mcp/server.py (1,203)
  - src/errorworks/llm_mcp/__init__.py (26)

  ---
  Test Code (13,234 lines → 16 chunks)

  Chunk 15: Engine Tests — Types & Injection (671 lines)

  - tests/unit/engine/test_types.py (367)
  - tests/unit/engine/test_injection_engine.py (304)

  Chunk 16: Engine Tests — Config & Admin (520 lines)

  - tests/unit/engine/test_config_loader.py (229)
  - tests/unit/engine/test_admin.py (291)

  Chunk 17: Engine Tests — Metrics Store (708 lines)

  - tests/unit/engine/test_metrics_store.py (708)

  Chunk 18: LLM Tests — Config (412 lines)

  - tests/unit/llm/test_config.py (412)

  Chunk 19: LLM Tests — Error Injector (897 lines)

  - tests/unit/llm/test_error_injector.py (897)

  Chunk 20: LLM Tests — Response Generator (938 lines)

  - tests/unit/llm/test_response_generator.py (938)

  Chunk 21: LLM Tests — Server (1,029 lines — single file)

  - tests/unit/llm/test_server.py (1,029)

  Chunk 22: LLM Tests — Metrics (1,102 lines — single file)

  - tests/unit/llm/test_metrics.py (1,102)

  Chunk 23: LLM Tests — CLI, Latency, Fixture (882 lines)

  - tests/unit/llm/test_cli.py (285)
  - tests/unit/llm/test_latency_simulator.py (368)
  - tests/unit/llm/test_fixture.py (229)

  Chunk 24: Web Tests — Config (386 lines)

  - tests/unit/web/test_config.py (386)

  Chunk 25: Web Tests — Error Injector (910 lines)

  - tests/unit/web/test_error_injector.py (910)

  Chunk 26: Web Tests — Content Generator (665 lines)

  - tests/unit/web/test_content_generator.py (665)

  Chunk 27: Web Tests — Server (1,051 lines — single file)

  - tests/unit/web/test_server.py (1,051)

  Chunk 28: Web Tests — Metrics, CLI, Fixture (945 lines)

  - tests/unit/web/test_metrics.py (720)
  - tests/unit/web/test_cli.py (239) — this pair is slightly over but tightly related

  Chunk 29: Web Test Fixture & MCP Tests (1,115 lines)

  - tests/unit/web/test_fixture.py (186)
  - tests/unit/llm_mcp/test_server.py (929)

  Chunk 30: Test Fixtures & Integration (970 lines)

  - tests/fixtures/chaosllm.py (239)
  - tests/fixtures/chaosweb.py (312)
  - tests/integration/test_llm_pipeline.py (115)
  - tests/integration/test_web_pipeline.py (147)
  - tests/integration/test_mcp_pipeline.py (157)