"""Tests for ChaosWeb content generator."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from errorworks.web.config import WebContentConfig
from errorworks.web.content_generator import (
    ContentGenerator,
    PresetBank,
    WebResponse,
    generate_wrong_content_type,
    inject_charset_confusion,
    inject_encoding_mismatch,
    inject_invalid_encoding,
    inject_malformed_meta,
    truncate_html,
)


class TestContentGeneratorRandomMode:
    """Tests for random content generation mode."""

    def test_generates_valid_html(self) -> None:
        """Random mode generates structurally valid HTML."""
        config = WebContentConfig(mode="random")
        generator = ContentGenerator(config, rng=random.Random(42))

        response = generator.generate(path="/test")

        assert isinstance(response, WebResponse)
        assert isinstance(response.content, str)
        content = response.content.lower()
        assert "<html" in content
        assert "<head" in content
        assert "<body" in content
        assert "</html>" in content
        assert "</body>" in content

    def test_content_type_set(self) -> None:
        """Random mode response has correct content type."""
        config = WebContentConfig(mode="random")
        generator = ContentGenerator(config, rng=random.Random(42))

        response = generator.generate()
        assert response.content_type == "text/html; charset=utf-8"

    def test_deterministic_with_seed(self) -> None:
        """Same seed produces same content."""
        config = WebContentConfig(mode="random")
        gen1 = ContentGenerator(config, rng=random.Random(42))
        gen2 = ContentGenerator(config, rng=random.Random(42))

        r1 = gen1.generate(path="/test")
        r2 = gen2.generate(path="/test")

        assert r1.content == r2.content


class TestContentGeneratorEchoMode:
    """Tests for echo content generation mode."""

    def test_echo_reflects_path(self) -> None:
        """Echo mode includes the request path in the response."""
        config = WebContentConfig(mode="echo")
        generator = ContentGenerator(config)

        response = generator.generate(path="/articles/test-page")
        assert isinstance(response.content, str)
        assert "/articles/test-page" in response.content

    def test_echo_reflects_headers(self) -> None:
        """Echo mode includes request headers in the response."""
        config = WebContentConfig(mode="echo")
        generator = ContentGenerator(config)

        response = generator.generate(
            path="/test",
            headers={"X-Custom-Header": "custom-value"},
        )
        assert "X-Custom-Header" in response.content
        assert "custom-value" in response.content

    def test_echo_xss_safe(self) -> None:
        """Echo mode escapes HTML-special characters."""
        config = WebContentConfig(mode="echo")
        generator = ContentGenerator(config)

        response = generator.generate(
            path='/<script>alert("xss")</script>',
            headers={"X-Evil": '<img onerror="alert(1)">'},
        )
        content = response.content
        # Raw script/img tags must not appear unescaped
        assert "<script>" not in content
        assert "<img onerror" not in content
        assert "&lt;script&gt;" in content


class TestContentGeneratorTemplateMode:
    """Tests for template content generation mode."""

    def test_template_renders_path(self) -> None:
        """Template mode renders with path context."""
        config = WebContentConfig(
            mode="template",
            template={"body": "<html><body>Path: {{ path }}</body></html>"},
        )
        generator = ContentGenerator(config)

        response = generator.generate(path="/my-page")
        assert isinstance(response.content, str)
        assert "/my-page" in response.content

    def test_template_renders_random_words(self) -> None:
        """Template mode random_words helper works."""
        config = WebContentConfig(
            mode="template",
            template={"body": "<html><body>{{ random_words(5) }}</body></html>"},
        )
        generator = ContentGenerator(config, rng=random.Random(42))

        response = generator.generate()
        # Should have some words between body tags
        assert len(response.content) > len("<html><body></body></html>")

    def test_template_too_long_raises_at_init(self) -> None:
        """Template exceeding max_template_length raises ValueError at construction."""
        long_template = "x" * 20_000
        config = WebContentConfig(
            mode="template",
            template={"body": long_template},
            max_template_length=100,
        )
        with pytest.raises(ValueError, match="exceeds max_template_length"):
            ContentGenerator(config)

    def test_template_syntax_error_raises_at_init(self) -> None:
        """Template with Jinja2 syntax error crashes at construction, not at serve time."""
        import jinja2

        config = WebContentConfig(
            mode="template",
            template={"body": "<html>{% if unclosed %}"},
        )
        with pytest.raises(jinja2.TemplateSyntaxError):
            ContentGenerator(config)

    def test_config_template_render_error_propagates(self) -> None:
        """Config-sourced template render errors propagate instead of returning error page."""
        import jinja2

        config = WebContentConfig(
            mode="template",
            template={"body": "<html>{{ undefined_var }}</html>"},
        )
        generator = ContentGenerator(config)
        # StrictUndefined should raise on undefined_var, and since this
        # is a config-sourced template (not a header override), the error
        # must propagate rather than being swallowed into an error page.
        with pytest.raises(jinja2.UndefinedError):
            generator.generate(path="/test")


class TestPresetBank:
    """Tests for PresetBank JSONL loading and selection."""

    def test_from_jsonl_loads(self, tmp_path: Path) -> None:
        """PresetBank.from_jsonl loads pages from JSONL."""
        jsonl = tmp_path / "pages.jsonl"
        pages = [
            {"url": "http://example.com/1", "content": "<html><body>Page 1</body></html>"},
            {"url": "http://example.com/2", "content": "<html><body>Page 2</body></html>"},
        ]
        jsonl.write_text("\n".join(json.dumps(p) for p in pages))

        bank = PresetBank.from_jsonl(jsonl, "sequential")
        page = bank.next()
        assert "Page 1" in page["content"]

    def test_sequential_selection(self, tmp_path: Path) -> None:
        """Sequential mode cycles through pages in order."""
        jsonl = tmp_path / "pages.jsonl"
        pages = [{"content": f"<html>Page {i}</html>"} for i in range(3)]
        jsonl.write_text("\n".join(json.dumps(p) for p in pages))

        bank = PresetBank.from_jsonl(jsonl, "sequential")

        assert "Page 0" in bank.next()["content"]
        assert "Page 1" in bank.next()["content"]
        assert "Page 2" in bank.next()["content"]
        # Wraps around
        assert "Page 0" in bank.next()["content"]

    def test_random_selection(self, tmp_path: Path) -> None:
        """Random mode picks pages non-sequentially over many draws."""
        jsonl = tmp_path / "pages.jsonl"
        pages = [{"content": f"<html>Page {i}</html>"} for i in range(10)]
        jsonl.write_text("\n".join(json.dumps(p) for p in pages))

        bank = PresetBank.from_jsonl(jsonl, "random", rng=random.Random(42))

        seen = set()
        for _ in range(50):
            page = bank.next()
            seen.add(page["content"])

        # Should see more than one page
        assert len(seen) > 1

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        """Empty JSONL file raises ValueError."""
        jsonl = tmp_path / "pages.jsonl"
        jsonl.write_text("")

        with pytest.raises(ValueError, match="no valid pages"):
            PresetBank.from_jsonl(jsonl, "sequential")

    def test_missing_content_field_raises(self, tmp_path: Path) -> None:
        """JSONL line missing 'content' field raises ValueError."""
        jsonl = tmp_path / "pages.jsonl"
        jsonl.write_text(json.dumps({"url": "http://example.com"}) + "\n")

        with pytest.raises(ValueError, match="missing required 'content'"):
            PresetBank.from_jsonl(jsonl, "sequential")

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        """Invalid JSON line raises ValueError."""
        jsonl = tmp_path / "pages.jsonl"
        jsonl.write_text("not json\n")

        with pytest.raises(ValueError, match="Invalid JSON"):
            PresetBank.from_jsonl(jsonl, "sequential")

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        """Non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            PresetBank.from_jsonl(tmp_path / "nonexistent.jsonl", "sequential")


class TestContentGeneratorReset:
    """Tests for ContentGenerator.reset()."""

    def test_reset_resets_preset_bank(self, tmp_path: Path) -> None:
        """reset() resets the preset bank sequential index."""
        jsonl = tmp_path / "pages.jsonl"
        pages = [
            {"content": "<html>Page 0</html>"},
            {"content": "<html>Page 1</html>"},
        ]
        jsonl.write_text("\n".join(json.dumps(p) for p in pages))

        config = WebContentConfig(
            mode="preset",
            preset={"file": str(jsonl), "selection": "sequential"},
        )
        generator = ContentGenerator(config)

        r1 = generator.generate()
        assert "Page 0" in r1.content

        r2 = generator.generate()
        assert "Page 1" in r2.content

        generator.reset()

        r3 = generator.generate()
        assert "Page 0" in r3.content


class TestTruncateHtml:
    """Tests for truncate_html corruption helper."""

    def test_returns_bytes(self) -> None:
        """truncate_html returns bytes."""
        result = truncate_html("<html><body>Some content</body></html>")
        assert isinstance(result, bytes)

    def test_truncates_at_max_bytes(self) -> None:
        """Output is truncated at max_bytes."""
        content = "<html><body>" + "A" * 1000 + "</body></html>"
        result = truncate_html(content, max_bytes=50)
        assert len(result) == 50

    def test_short_content_returned_whole(self) -> None:
        """Content shorter than max_bytes is returned as-is."""
        content = "<html><body>Short</body></html>"
        result = truncate_html(content, max_bytes=5000)
        assert result == content.encode("utf-8")


class TestInjectEncodingMismatch:
    """Tests for inject_encoding_mismatch corruption helper."""

    def test_returns_bytes(self) -> None:
        """inject_encoding_mismatch returns bytes."""
        result = inject_encoding_mismatch("<html><body>Hello</body></html>")
        assert isinstance(result, bytes)

    def test_encodes_as_iso_8859_1(self) -> None:
        """Output is ISO-8859-1 encoded."""
        content = "<html><body>Hello World</body></html>"
        result = inject_encoding_mismatch(content)
        # Should be decodable as ISO-8859-1
        decoded = result.decode("iso-8859-1")
        assert "Hello World" in decoded


class TestInjectCharsetConfusion:
    """Tests for inject_charset_confusion corruption helper."""

    def test_returns_str(self) -> None:
        """inject_charset_confusion returns str."""
        result = inject_charset_confusion("<html><head></head><body>Hello</body></html>")
        assert isinstance(result, str)

    def test_adds_conflicting_meta(self) -> None:
        """Injects conflicting charset meta tags."""
        content = "<html><head></head><body>Hello</body></html>"
        result = inject_charset_confusion(content)
        assert 'charset="iso-8859-1"' in result
        assert "windows-1252" in result

    def test_no_head_tag_prepends(self) -> None:
        """Without <head>, conflicting meta is prepended."""
        content = "<body>Hello</body>"
        result = inject_charset_confusion(content)
        assert 'charset="iso-8859-1"' in result


class TestInjectInvalidEncoding:
    """Tests for inject_invalid_encoding corruption helper."""

    def test_returns_bytes(self) -> None:
        """inject_invalid_encoding returns bytes."""
        result = inject_invalid_encoding("<html><body>Hello</body></html>")
        assert isinstance(result, bytes)

    def test_contains_invalid_utf8(self) -> None:
        """Output contains bytes that are not valid UTF-8."""
        content = "<html><body>" + "A" * 100 + "</body></html>"
        result = inject_invalid_encoding(content)
        with pytest.raises(UnicodeDecodeError):
            result.decode("utf-8", errors="strict")


class TestInjectMalformedMeta:
    """Tests for inject_malformed_meta corruption helper."""

    def test_returns_str(self) -> None:
        """inject_malformed_meta returns str."""
        result = inject_malformed_meta("<html><head></head><body>Hello</body></html>")
        assert isinstance(result, str)

    def test_injects_meta_refresh(self) -> None:
        """Injects a malformed meta refresh tag."""
        content = "<html><head></head><body>Hello</body></html>"
        result = inject_malformed_meta(content)
        assert 'http-equiv="refresh"' in result
        assert "javascript:void(0)" in result

    def test_no_head_tag_prepends(self) -> None:
        """Without <head>, malformed meta is prepended."""
        content = "<body>Hello</body>"
        result = inject_malformed_meta(content)
        assert 'http-equiv="refresh"' in result


class TestContentGeneratorTemplateModeAdvanced:
    """Tests for template mode with web-specific helpers and error handling."""

    def test_template_random_choice_helper(self) -> None:
        """Template random_choice helper picks from provided options."""
        config = WebContentConfig(
            mode="template",
            template={"body": '<html><body>{{ random_choice("apple", "banana", "cherry") }}</body></html>'},
        )
        generator = ContentGenerator(config, rng=random.Random(42))

        response = generator.generate()
        assert isinstance(response.content, str)
        assert any(fruit in response.content for fruit in ["apple", "banana", "cherry"])

    def test_template_random_int_helper(self) -> None:
        """Template random_int helper generates integer in range."""
        config = WebContentConfig(
            mode="template",
            template={"body": "<html><body>{{ random_int(1, 100) }}</body></html>"},
        )
        generator = ContentGenerator(config, rng=random.Random(42))

        response = generator.generate()
        assert isinstance(response.content, str)
        # Extract the number between body tags
        import re

        match = re.search(r"<body>(\d+)</body>", response.content)
        assert match is not None
        val = int(match.group(1))
        assert 1 <= val <= 100

    def test_template_timestamp_helper(self) -> None:
        """Template timestamp helper generates a date string."""
        config = WebContentConfig(
            mode="template",
            template={"body": "<html><body>{{ timestamp() }}</body></html>"},
        )
        generator = ContentGenerator(config, rng=random.Random(42))

        response = generator.generate()
        assert isinstance(response.content, str)
        # Date format: YYYY-MM-DD
        import re

        match = re.search(r"\d{4}-\d{2}-\d{2}", response.content)
        assert match is not None

    def test_template_random_words_range(self) -> None:
        """Template random_words(min, max) generates words in range."""
        config = WebContentConfig(
            mode="template",
            template={"body": "<html><body>{{ random_words(10, 20) }}</body></html>"},
        )
        generator = ContentGenerator(config, rng=random.Random(42))

        response = generator.generate()
        # Extract text between body tags
        import re

        match = re.search(r"<body>(.*?)</body>", response.content)
        assert match is not None
        word_count = len(match.group(1).split())
        assert 10 <= word_count <= 20

    def test_template_random_choice_empty_returns_empty(self) -> None:
        """Template random_choice with no args returns empty string."""
        config = WebContentConfig(
            mode="template",
            template={"body": "<html><body>{{ random_choice() }}</body></html>"},
        )
        generator = ContentGenerator(config, rng=random.Random(42))

        response = generator.generate()
        assert "<body></body>" in response.content

    def test_template_renders_headers_context(self) -> None:
        """Template mode can access request headers in context."""
        config = WebContentConfig(
            mode="template",
            template={"body": "<html><body>{{ headers.get('User-Agent', 'none') }}</body></html>"},
        )
        generator = ContentGenerator(config)

        response = generator.generate(
            path="/test",
            headers={"User-Agent": "TestBot/1.0"},
        )
        assert "TestBot/1.0" in response.content

    def test_template_malformed_syntax_returns_error_page(self) -> None:
        """Malformed template at runtime (via mode override) returns error page, not crash."""
        # Use random mode config, but pass template via mode_override
        # The template won't be pre-compiled since mode != "template"
        config = WebContentConfig(
            mode="random",
            template={"body": "<html><body>{{ undefined_var }}</body></html>"},
        )
        generator = ContentGenerator(config)

        # When mode_override="template", it uses the config's template body
        # which references undefined_var -- StrictUndefined will fail
        response = generator.generate(path="/test", mode_override="template")
        assert isinstance(response, WebResponse)
        assert "Template Error" in response.content

    def test_template_too_long_at_runtime_returns_error_page(self) -> None:
        """Template exceeding max_template_length at runtime returns error page."""
        long_body = "x" * 20_000
        config = WebContentConfig(
            mode="random",
            template={"body": long_body},
            max_template_length=100,
        )
        generator = ContentGenerator(config)

        response = generator.generate(path="/test", mode_override="template")
        assert isinstance(response, WebResponse)
        assert "Template Error" in response.content

    def test_template_output_capped_at_double_max_length(self) -> None:
        """Template output exceeding 2x max_template_length is truncated."""
        # Create a template that produces very long output
        repeat_template = "<html><body>{{ random_words(5000) }}</body></html>"
        config = WebContentConfig(
            mode="template",
            template={"body": repeat_template},
            max_template_length=10_000,
        )
        generator = ContentGenerator(config, rng=random.Random(42))

        response = generator.generate(path="/test")
        # Output should be capped at 2 * max_template_length = 20000
        assert len(response.content) <= 20_000


class TestContentGeneratorPresetMode:
    """Tests for preset mode content generation via ContentGenerator.generate()."""

    def test_preset_mode_returns_preset_content(self, tmp_path: Path) -> None:
        """Preset mode returns content from the JSONL bank."""
        jsonl = tmp_path / "pages.jsonl"
        pages = [
            {"content": "<html><body>Preset Page Alpha</body></html>", "content_type": "text/html; charset=utf-8"},
            {"content": "<html><body>Preset Page Beta</body></html>", "content_type": "text/html; charset=utf-8"},
        ]
        jsonl.write_text("\n".join(json.dumps(p) for p in pages))

        config = WebContentConfig(
            mode="preset",
            preset={"file": str(jsonl), "selection": "sequential"},
        )
        generator = ContentGenerator(config)

        r1 = generator.generate()
        assert "Preset Page Alpha" in r1.content

        r2 = generator.generate()
        assert "Preset Page Beta" in r2.content

    def test_preset_mode_uses_content_type_from_jsonl(self, tmp_path: Path) -> None:
        """Preset mode uses the content_type from the JSONL entry."""
        jsonl = tmp_path / "pages.jsonl"
        pages = [
            {"content": "<html><body>Custom CT</body></html>", "content_type": "text/html; charset=iso-8859-1"},
        ]
        jsonl.write_text(json.dumps(pages[0]))

        config = WebContentConfig(
            mode="preset",
            preset={"file": str(jsonl), "selection": "sequential"},
        )
        generator = ContentGenerator(config)

        response = generator.generate()
        assert response.content_type == "text/html; charset=iso-8859-1"

    def test_preset_mode_defaults_content_type(self, tmp_path: Path) -> None:
        """Preset mode defaults content_type when not specified in JSONL."""
        jsonl = tmp_path / "pages.jsonl"
        pages = [{"content": "<html><body>No CT</body></html>"}]
        jsonl.write_text(json.dumps(pages[0]))

        config = WebContentConfig(
            mode="preset",
            preset={"file": str(jsonl), "selection": "sequential"},
        )
        generator = ContentGenerator(config)

        response = generator.generate()
        assert response.content_type == "text/html; charset=utf-8"

    def test_preset_mode_random_selection(self, tmp_path: Path) -> None:
        """Preset mode with random selection picks pages non-deterministically."""
        jsonl = tmp_path / "pages.jsonl"
        pages = [{"content": f"<html>Page {i}</html>"} for i in range(10)]
        jsonl.write_text("\n".join(json.dumps(p) for p in pages))

        config = WebContentConfig(
            mode="preset",
            preset={"file": str(jsonl), "selection": "random"},
        )
        generator = ContentGenerator(config, rng=random.Random(42))

        seen = set()
        for _ in range(30):
            r = generator.generate()
            seen.add(r.content)
        assert len(seen) > 1

    def test_preset_mode_lazy_loads_bank(self, tmp_path: Path) -> None:
        """Preset bank is lazy-loaded on first generate(), not at construction."""
        jsonl = tmp_path / "pages.jsonl"
        pages = [{"content": "<html>Lazy</html>"}]
        jsonl.write_text(json.dumps(pages[0]))

        config = WebContentConfig(
            mode="preset",
            preset={"file": str(jsonl), "selection": "sequential"},
        )
        generator = ContentGenerator(config)
        # Bank not loaded yet
        assert generator._preset_bank is None

        generator.generate()
        # Now it should be loaded
        assert generator._preset_bank is not None

    def test_preset_mode_missing_file_raises(self, tmp_path: Path) -> None:
        """Preset mode with missing JSONL file raises FileNotFoundError on generate()."""
        config = WebContentConfig(
            mode="preset",
            preset={"file": str(tmp_path / "nonexistent.jsonl"), "selection": "sequential"},
        )
        generator = ContentGenerator(config)

        with pytest.raises(FileNotFoundError):
            generator.generate()

    def test_preset_mode_via_mode_override(self, tmp_path: Path) -> None:
        """Preset mode works via mode_override header."""
        jsonl = tmp_path / "pages.jsonl"
        pages = [{"content": "<html><body>Override Preset</body></html>"}]
        jsonl.write_text(json.dumps(pages[0]))

        config = WebContentConfig(
            mode="random",
            preset={"file": str(jsonl), "selection": "sequential"},
        )
        generator = ContentGenerator(config)

        response = generator.generate(path="/test", mode_override="preset")
        assert "Override Preset" in response.content


class TestModeOverrideErrors:
    """Tests for graceful handling of invalid header overrides."""

    def test_unknown_mode_override_returns_error_content(self) -> None:
        """Unknown X-Fake-Content-Mode returns error in content, not crash."""
        config = WebContentConfig(mode="random")
        generator = ContentGenerator(config)

        response = generator.generate(path="/test", mode_override="typo_mode")

        assert isinstance(response, WebResponse)
        assert "unknown_mode" in response.content


class TestGenerateWrongContentType:
    """Tests for generate_wrong_content_type helper."""

    def test_returns_non_html(self) -> None:
        """Returns a MIME type that is not text/html."""
        for _ in range(20):
            ct = generate_wrong_content_type()
            assert isinstance(ct, str)
            assert "text/html" not in ct

    def test_returns_known_types(self) -> None:
        """Returns one of the known wrong types."""
        known = {
            "application/pdf",
            "application/octet-stream",
            "image/jpeg",
            "application/xml",
            "text/plain",
            "application/json",
        }
        for _ in range(50):
            ct = generate_wrong_content_type()
            assert ct in known


class TestPresetBankRandomThreadSafety:
    """Verify PresetBank.next() in random mode is thread-safe."""

    def test_concurrent_random_next_no_crash(self) -> None:
        """Spawn many threads calling next() in random mode concurrently."""
        import threading

        pages = [{"body": f"<p>page-{i}</p>", "content_type": "text/html"} for i in range(10)]
        bank = PresetBank(pages=pages, selection="random")
        errors: list[Exception] = []
        results: list[dict[str, str]] = []
        barrier = threading.Barrier(20)

        def worker() -> None:
            barrier.wait()
            try:
                for _ in range(200):
                    result = bank.next()
                    results.append(result)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        assert len(results) == 20 * 200
        assert all(r in pages for r in results)
