# Test Remediation Plan — Overview

**Date:** 2026-03-12
**Status:** Draft
**Scope:** Errorworks v0.1.x test suite improvements

## Current State

| Metric | Value |
|--------|-------|
| Total tests | 583 |
| Test speed | 2.7s |
| Overall coverage | 72% |
| Test levels | Unit only (no integration, no E2E) |
| Pyramid shape | Pillar (100% unit) |

### Coverage by Module

| Module | Coverage | Assessment |
|--------|----------|------------|
| Engine core (types, injection, metrics, config, latency) | 95–100% | Strong |
| LLM config / injector / generator | 84–96% | Strong |
| Web config / injector / generator | 86–97% | Strong |
| LLM server | 77% | Moderate |
| Web server | 50% | Moderate |
| MCP server | 62% | Moderate |
| LLM CLI | 16% (1 test) | Critical gap |
| Web CLI | 0% (0 tests) | Critical gap |

### What's Working Well

- Core business logic is thoroughly tested with real objects (not mocks)
- Thread safety is validated across metrics stores and injectors
- Test fixtures (`ChaosLLMFixture`, `ChaosWebFixture`) are well-designed
- Tests run fast — 583 tests in under 3 seconds

## Goals

1. **Close the CLI coverage gap** — bring both CLI modules to ≥80% coverage
2. **Add an integration test layer** — validate config→server→HTTP pipelines
3. **Introduce property-based testing** — leverage Hypothesis (already a dependency) for distribution and invariant validation
4. **Maintain test speed** — all new tests should complete in <5s total

## Subordinate Plans

| Plan | Priority | Target Coverage Impact | Estimated Tests |
|------|----------|----------------------|-----------------|
| [01 — CLI Test Coverage](01-cli-test-coverage.md) | High | +8–10% overall | ~41 tests (24 LLM + 18 Web) |
| [02 — Integration Test Layer](02-integration-test-layer.md) | Medium | +5% overall | ~20 tests |
| [03 — Property-Based Testing](03-property-based-testing.md) | Medium | Strengthens existing | ~12 tests |

## Execution Order

```
01-cli-test-coverage      (no dependencies, biggest gap)
02-integration-test-layer  (benefits from CLI patterns established in 01)
03-property-based-testing  (independent, can run in parallel with 02)
```

## Success Criteria

- [ ] Overall coverage ≥ 85%
- [ ] No module below 50% coverage
- [ ] CLI modules ≥ 80% coverage
- [ ] At least one integration test per server (LLM, Web, MCP)
- [ ] Hypothesis tests for error rate accuracy and deep_merge properties
- [ ] Full test suite still completes in < 10 seconds
- [ ] Test pyramid: ≥ 70% unit, ≥ 15% integration, remainder property-based
