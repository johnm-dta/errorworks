"""HTML content generation for ChaosWeb server.

The ContentGenerator creates fake web page responses in multiple modes:
- random: Syntactically valid HTML5 with random structural content
- template: Jinja2 HTML template rendering (SandboxedEnvironment)
- preset: Real HTML snapshots loaded from JSONL file
- echo: Reflect request information as HTML (XSS-safe via escaping)

Also provides content corruption helpers for malformation error injection.
"""

import html
import json
import random as random_module
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import jinja2
import jinja2.sandbox
import structlog

from errorworks.engine.vocabulary import ENGLISH_VOCABULARY, LOREM_VOCABULARY
from errorworks.web.config import WebContentConfig

logger = structlog.get_logger(__name__)

# HTML structural elements used in random generation.
# Each entry is (tag, kind) where kind determines generation behavior.
_BLOCK_ELEMENTS: tuple[tuple[str, str], ...] = (
    ("h1", "heading"),
    ("h2", "heading"),
    ("h3", "heading"),
    ("p", "paragraph"),
    ("p", "paragraph"),
    ("p", "paragraph"),  # Weighted: paragraphs are most common
    ("p", "paragraph"),
    ("blockquote", "quote"),
    ("ul", "list"),
)


@dataclass(frozen=True, slots=True)
class WebResponse:
    """Generated web page response.

    Attributes:
        content: HTML content (str for text, bytes for binary/corrupted)
        content_type: Content-Type header value
        status_code: HTTP status code (200 for normal responses)
        headers: Additional response headers
        encoding: Character encoding used
    """

    content: str | bytes
    content_type: str
    status_code: int = 200
    headers: Mapping[str, str] | None = None
    encoding: str = "utf-8"

    def __post_init__(self) -> None:
        if not (100 <= self.status_code <= 599):
            raise ValueError(f"WebResponse.status_code must be a valid HTTP status (100-599), got {self.status_code}")
        if not self.content_type:
            raise ValueError("WebResponse.content_type must not be empty")
        if self.headers is not None and not isinstance(self.headers, MappingProxyType):
            object.__setattr__(self, "headers", MappingProxyType(self.headers))


class PresetBank:
    """Manages preset HTML page snapshots loaded from JSONL files.

    Each line in the JSONL file should be:
    {"url": "...", "content": "<html>...", "content_type": "text/html"}

    Supports random and sequential selection modes.
    """

    def __init__(
        self,
        pages: Sequence[dict[str, str]],
        selection: str,
        *,
        rng: random_module.Random | None = None,
    ) -> None:
        if not pages:
            raise ValueError("PresetBank requires at least one page")
        self._pages = list(pages)
        self._selection = selection
        self._rng = rng if rng is not None else random_module.Random()
        self._index = 0
        self._lock = threading.Lock()

    def next(self) -> dict[str, str]:
        """Get the next preset page (thread-safe)."""
        if self._selection == "random":
            return self._rng.choice(self._pages)
        else:  # sequential
            with self._lock:
                page = self._pages[self._index]
                self._index = (self._index + 1) % len(self._pages)
            return page

    def reset(self) -> None:
        """Reset sequential index to beginning."""
        with self._lock:
            self._index = 0

    @classmethod
    def from_jsonl(
        cls,
        file_path: Path | str,
        selection: str,
        *,
        rng: random_module.Random | None = None,
    ) -> "PresetBank":
        """Load preset bank from JSONL file.

        Each line should be a JSON object with at least a "content" field.
        Optional: "url", "content_type".

        Raises:
            FileNotFoundError: If file does not exist
            ValueError: If file is empty or has invalid format
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Preset file not found: {path}")

        pages: list[dict[str, str]] = []
        with path.open() as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON on line {line_num} of {path}: {e}") from e

                if not isinstance(obj, dict):
                    raise ValueError(f"Line {line_num} of {path} must be a JSON object")
                if "content" not in obj:
                    raise ValueError(f"Line {line_num} of {path} missing required 'content' field")
                pages.append(
                    {
                        "content": str(obj["content"]),
                        "url": str(obj.get("url", "")),
                        "content_type": str(obj.get("content_type", "text/html; charset=utf-8")),
                    }
                )

        if not pages:
            raise ValueError(f"Preset file {path} contains no valid pages")

        return cls(pages, selection, rng=rng)


class ContentGenerator:
    """Generates fake HTML web page content.

    Supports multiple generation modes matching ChaosLLM's pattern:
    - random: Syntactically valid HTML5 with random structure
    - template: Jinja2 template rendering with request context
    - preset: Real HTML snapshots from JSONL
    - echo: Reflect request info as HTML (XSS-safe)

    """

    def __init__(
        self,
        config: WebContentConfig,
        *,
        rng: random_module.Random | None = None,
    ) -> None:
        self._config = config
        self._rng = rng if rng is not None else random_module.Random()
        self._preset_bank: PresetBank | None = None
        self._jinja_env = self._create_jinja_env()

        # Pre-compile template at construction — fail fast on syntax errors.
        # Matches ResponseGenerator's pattern (llm/response_generator.py).
        self._compiled_template: jinja2.Template | None = None
        if config.mode == "template":
            template_str = config.template.body
            if len(template_str) > config.max_template_length:
                raise ValueError(
                    f"Template body ({len(template_str)} chars) exceeds max_template_length ({config.max_template_length})"
                )
            self._compiled_template = self._jinja_env.from_string(template_str)

    @property
    def config(self) -> WebContentConfig:
        """Current content generation configuration (frozen/immutable)."""
        return self._config

    def _create_jinja_env(self) -> jinja2.sandbox.SandboxedEnvironment:
        """Create Jinja2 SandboxedEnvironment with template helpers.

        Uses SandboxedEnvironment to prevent arbitrary code execution
        in user-provided templates.
        """
        env = jinja2.sandbox.SandboxedEnvironment(
            autoescape=True,  # HTML context — auto-escape for safety
            undefined=jinja2.StrictUndefined,
        )
        env.globals["random_choice"] = self._template_random_choice
        env.globals["random_int"] = self._template_random_int
        env.globals["random_words"] = self._template_random_words
        env.globals["timestamp"] = self._template_timestamp
        return env

    def _template_random_choice(self, *options: str) -> str:
        """Jinja2 helper: Pick random item from options."""
        if not options:
            return ""
        return self._rng.choice(options)

    def _template_random_int(self, min_val: int = 0, max_val: int = 100) -> int:
        """Jinja2 helper: Generate random integer in range."""
        return self._rng.randint(min_val, max_val)

    def _template_random_words(self, min_count: int = 5, max_count: int | None = None) -> str:
        """Jinja2 helper: Generate random words.

        Can be called as random_words(50) for exactly 50 words,
        or random_words(50, 100) for 50-100 words.
        """
        if max_count is None:
            count = min_count
        else:
            count = self._rng.randint(min_count, max_count)
        vocab = self._get_vocabulary()
        words = [self._rng.choice(vocab) for _ in range(count)]
        return " ".join(words)

    def _template_timestamp(self) -> str:
        """Jinja2 helper: Generate a plausible date string."""
        year = self._rng.randint(2020, 2026)
        month = self._rng.randint(1, 12)
        day = self._rng.randint(1, 28)
        return f"{year}-{month:02d}-{day:02d}"

    def _get_vocabulary(self) -> tuple[str, ...]:
        """Get vocabulary based on config."""
        if self._config.random.vocabulary == "lorem":
            return LOREM_VOCABULARY
        return ENGLISH_VOCABULARY

    def _random_words(self, count: int) -> str:
        """Generate N random words from configured vocabulary."""
        vocab = self._get_vocabulary()
        return " ".join(self._rng.choice(vocab) for _ in range(count))

    def _random_sentence(self, min_words: int = 5, max_words: int = 20) -> str:
        """Generate a random sentence with capitalization and period."""
        count = self._rng.randint(min_words, max_words)
        words = self._random_words(count).split()
        if words:
            words[0] = words[0].capitalize()
        return " ".join(words) + "."

    def _generate_random_html(self) -> str:
        """Generate syntactically valid HTML5 with random structural content."""
        min_words = self._config.random.min_words
        max_words = self._config.random.max_words
        total_words = self._rng.randint(min_words, max_words)

        title = self._random_sentence(3, 8).rstrip(".")
        parts: list[str] = [
            "<!DOCTYPE html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            f"<title>{html.escape(title)}</title>",
            "</head>",
            "<body>",
        ]

        words_used = 0
        while words_used < total_words:
            remaining = total_words - words_used
            tag, kind = self._rng.choice(_BLOCK_ELEMENTS)

            if kind == "heading":
                sentence = self._random_sentence(3, 8)
                words_used += len(sentence.split())
                parts.append(f"<{tag}>{html.escape(sentence)}</{tag}>")

            elif kind == "paragraph":
                # 1-4 sentences per paragraph
                sentences_count = self._rng.randint(1, min(4, max(1, remaining // 5)))
                sentences = []
                for _ in range(sentences_count):
                    max_sent = max(5, min(20, remaining - words_used + 5))
                    s = self._random_sentence(5, max_sent)
                    words_used += len(s.split())
                    sentences.append(html.escape(s))
                parts.append(f"<p>{' '.join(sentences)}</p>")

            elif kind == "quote":
                max_quote = max(8, min(25, remaining))
                sentence = self._random_sentence(8, max_quote)
                words_used += len(sentence.split())
                parts.append(f"<blockquote><p>{html.escape(sentence)}</p></blockquote>")

            elif kind == "list":
                item_count = self._rng.randint(2, min(5, max(2, remaining // 3)))
                items = []
                for _ in range(item_count):
                    item = self._random_sentence(3, 10)
                    words_used += len(item.split())
                    items.append(f"<li>{html.escape(item)}</li>")
                parts.append(f"<ul>{''.join(items)}</ul>")

        parts.extend(["</body>", "</html>"])
        return "\n".join(parts)

    def _generate_template_html(self, path: str, headers: dict[str, str]) -> str:
        """Generate HTML from Jinja2 template.

        Config-sourced templates are pre-compiled at init time — a broken
        template is a config bug that crashes at startup.  Runtime compilation
        only happens for header-override templates (Tier 3 external data),
        where errors return a generic error page instead of crashing.
        """
        if self._compiled_template is not None:
            template = self._compiled_template
        else:
            # Header-override path or mode changed via update_config
            template_str = self._config.template.body
            max_len = self._config.max_template_length
            if len(template_str) > max_len:
                logger.warning(
                    "template_exceeds_max_length",
                    template_length=len(template_str),
                    max_length=max_len,
                )
                return self._error_page("Template Error", "Template exceeds maximum length")

            try:
                template = self._jinja_env.from_string(template_str)
            except jinja2.TemplateError as exc:
                logger.error(
                    "template_compilation_failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                    template_length=len(template_str),
                )
                return self._error_page("Template Error", "Failed to compile template")

        try:
            rendered = template.render(
                path=path,
                headers=headers,
                query_params={},
            )
        except jinja2.TemplateError as exc:
            logger.error(
                "template_rendering_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return self._error_page("Template Error", "Failed to render template")

        # Cap output length
        max_len = self._config.max_template_length
        if len(rendered) > max_len * 2:
            rendered = rendered[: max_len * 2]

        return rendered

    def _generate_echo_html(self, path: str, headers: dict[str, str]) -> str:
        """Generate HTML that reflects request information.

        All reflected content is HTML-escaped to prevent XSS.
        """
        escaped_path = html.escape(path)
        header_rows = "\n".join(f"<tr><td>{html.escape(k)}</td><td>{html.escape(v)}</td></tr>" for k, v in sorted(headers.items()))

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ChaosWeb Echo: {escaped_path}</title>
</head>
<body>
<h1>ChaosWeb Echo</h1>
<h2>Request Path</h2>
<pre>{escaped_path}</pre>
<h2>Request Headers</h2>
<table border="1">
<tr><th>Header</th><th>Value</th></tr>
{header_rows}
</table>
</body>
</html>"""

    def _generate_preset_html(self) -> WebResponse:
        """Get next HTML page from preset bank."""
        bank = self._get_preset_bank()
        page = bank.next()
        return WebResponse(
            content=page["content"],
            content_type=page["content_type"],
        )

    def _get_preset_bank(self) -> PresetBank:
        """Get or create preset bank (lazy loading)."""
        if self._preset_bank is None:
            self._preset_bank = PresetBank.from_jsonl(
                self._config.preset.file,
                self._config.preset.selection,
                rng=self._rng,
            )
        return self._preset_bank

    def _error_page(self, title: str, message: str) -> str:
        """Generate a simple error page (no information disclosure)."""
        return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{html.escape(title)}</title></head>
<body><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p></body>
</html>"""

    def generate(
        self,
        path: str = "/",
        headers: dict[str, str] | None = None,
        *,
        mode_override: str | None = None,
    ) -> WebResponse:
        """Generate a fake HTML web page response.

        Args:
            path: Requested URL path
            headers: Request headers
            mode_override: Override content mode (from X-Fake-Content-Mode header)

        Returns:
            WebResponse with generated HTML content
        """
        if headers is None:
            headers = {}

        mode = mode_override if mode_override is not None else self._config.mode

        if mode == "random":
            content = self._generate_random_html()
        elif mode == "template":
            content = self._generate_template_html(path, headers)
        elif mode == "echo":
            content = self._generate_echo_html(path, headers)
        elif mode == "preset":
            return self._generate_preset_html()
        else:
            # Config mode is Pydantic Literal-validated, so invalid config mode
            # is impossible. This branch is only reachable via mode_override from
            # the X-Fake-Content-Mode header (Tier 3 external data).
            logger.warning("unknown_content_mode_override", mode=mode)
            content = f"<html><body>[unknown_mode: {html.escape(repr(mode))}]</body></html>"

        return WebResponse(
            content=content,
            content_type=self._config.default_content_type,
        )

    def reset(self) -> None:
        """Reset generator state (clears preset bank index)."""
        if self._preset_bank is not None:
            self._preset_bank.reset()


# === Content Corruption Helpers ===
# Used by the server when the error injector decides to inject content malformations.


def truncate_html(content: str, max_bytes: int = 500) -> bytes:
    """Truncate HTML mid-tag to simulate incomplete response.

    Encodes to UTF-8 and cuts at max_bytes, potentially splitting
    a multi-byte character or HTML tag in half.
    """
    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return encoded
    return encoded[:max_bytes]


def inject_encoding_mismatch(content: str) -> bytes:
    """Encode content as ISO-8859-1 (to be served with UTF-8 Content-Type header).

    Characters outside ISO-8859-1 range are replaced, creating the mismatch
    that real websites sometimes exhibit.
    """
    return content.encode("iso-8859-1", errors="replace")


def inject_charset_confusion(content: str) -> str:
    """Add conflicting charset declarations.

    Injects both ``<meta charset="iso-8859-1">`` and a
    ``<meta http-equiv="Content-Type" content="text/html; charset=windows-1252">``
    into an HTML page that will be served with
    ``Content-Type: text/html; charset=windows-1252``, creating the kind
    of charset confusion found on poorly maintained websites.
    """
    # Insert conflicting meta tag after <head>
    insertion = '<meta charset="iso-8859-1">\n<meta http-equiv="Content-Type" content="text/html; charset=windows-1252">\n'
    head_pos = content.lower().find("<head>")
    if head_pos != -1:
        insert_at = head_pos + len("<head>")
        return content[:insert_at] + "\n" + insertion + content[insert_at:]
    # No <head> tag — prepend
    return insertion + content


def inject_invalid_encoding(content: str) -> bytes:
    """Inject non-decodable bytes into UTF-8 declared content.

    Inserts byte sequences that are invalid UTF-8 into the content body,
    simulating corrupted or mixed-encoding pages.
    """
    encoded = content.encode("utf-8")
    # Insert invalid UTF-8 sequences at roughly 1/3 and 2/3 through the content
    invalid_bytes = b"\xfe\xff\x80\x81"
    third = len(encoded) // 3
    return encoded[:third] + invalid_bytes + encoded[third : 2 * third] + invalid_bytes + encoded[2 * third :]


def inject_malformed_meta(content: str) -> str:
    """Inject malformed <meta http-equiv="refresh"> directive.

    Real websites sometimes have broken refresh tags that cause unpredictable
    browser behavior.
    """
    malformed_meta = '<meta http-equiv="refresh" content="0;url=javascript:void(0)">\n'
    head_pos = content.lower().find("<head>")
    if head_pos != -1:
        insert_at = head_pos + len("<head>")
        return content[:insert_at] + "\n" + malformed_meta + content[insert_at:]
    return malformed_meta + content


_WRONG_CONTENT_TYPES: tuple[str, ...] = (
    "application/pdf",
    "application/octet-stream",
    "image/jpeg",
    "application/xml",
    "text/plain",
    "application/json",
)


def generate_wrong_content_type(rng: random_module.Random | None = None) -> str:
    """Return a realistic non-HTML content type for wrong_content_type injection."""
    r = rng if rng is not None else random_module.Random()
    return r.choice(_WRONG_CONTENT_TYPES)
