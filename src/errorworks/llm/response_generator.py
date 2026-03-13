"""Response generation logic for ChaosLLM.

The ResponseGenerator creates fake LLM responses in OpenAI-compatible format.
Supports multiple modes: random text, Jinja2 templates, echo, and preset banks.
"""

import json
import random as random_module
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jinja2
import jinja2.sandbox
import structlog

from errorworks.engine.vocabulary import (
    ENGLISH_VOCABULARY as ENGLISH_VOCABULARY,
)
from errorworks.engine.vocabulary import (
    LOREM_VOCABULARY as LOREM_VOCABULARY,
)
from errorworks.llm.config import ResponseConfig

__all__ = [
    "ENGLISH_VOCABULARY",
    "LOREM_VOCABULARY",
    "OpenAIResponse",
    "PresetBank",
    "ResponseGenerator",
]

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class OpenAIResponse:
    """OpenAI-compatible chat completion response structure.

    Attributes:
        id: Unique response ID (prefixed with "fake-")
        object: Response type ("chat.completion")
        created: Unix timestamp of response creation
        model: Model name from request
        content: Generated response content
        prompt_tokens: Estimated prompt token count
        completion_tokens: Estimated completion token count
        finish_reason: Completion finish reason ("stop")
    """

    id: str
    object: str
    created: int
    model: str
    content: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str

    def __post_init__(self) -> None:
        if self.prompt_tokens < 0:
            raise ValueError(f"OpenAIResponse.prompt_tokens must be non-negative, got {self.prompt_tokens}")
        if self.completion_tokens < 0:
            raise ValueError(f"OpenAIResponse.completion_tokens must be non-negative, got {self.completion_tokens}")
        if self.created < 0:
            raise ValueError(f"OpenAIResponse.created must be non-negative, got {self.created}")

    @property
    def total_tokens(self) -> int:
        """Total tokens (prompt + completion)."""
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict[str, Any]:
        """Convert to OpenAI API response format."""
        return {
            "id": self.id,
            "object": self.object,
            "created": self.created,
            "model": self.model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": self.content,
                    },
                    "finish_reason": self.finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
            },
        }


class PresetBank:
    """Manages preset responses loaded from JSONL files.

    Supports random and sequential selection modes.
    """

    def __init__(
        self,
        responses: Sequence[str],
        selection: str,
        *,
        rng: random_module.Random | None = None,
    ) -> None:
        """Initialize preset bank.

        Args:
            responses: List of preset response strings
            selection: Selection mode ("random" or "sequential")
            rng: Random instance for deterministic testing
        """
        if not responses:
            raise ValueError("PresetBank requires at least one response")
        self._responses = list(responses)
        self._selection = selection
        self._rng = rng if rng is not None else random_module.Random()
        self._index = 0
        self._lock = threading.Lock()

    def next(self) -> str:
        """Get the next preset response (thread-safe)."""
        if self._selection == "random":
            return self._rng.choice(self._responses)
        else:  # sequential
            with self._lock:
                response = self._responses[self._index]
                self._index = (self._index + 1) % len(self._responses)
            return response

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

        Each line in the JSONL file should contain a JSON object with a
        "content" field containing the response text.

        Args:
            file_path: Path to JSONL file
            selection: Selection mode ("random" or "sequential")
            rng: Random instance for deterministic testing

        Returns:
            PresetBank instance with loaded responses

        Raises:
            FileNotFoundError: If file does not exist
            ValueError: If file is empty or has invalid format
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Preset file not found: {path}")

        responses: list[str] = []
        with path.open() as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue  # Skip empty lines
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON on line {line_num} of {path}: {e}") from e

                if not isinstance(obj, dict):
                    raise ValueError(f"Line {line_num} of {path} must be a JSON object, got {type(obj).__name__}")
                if "content" not in obj:
                    raise ValueError(f"Line {line_num} of {path} missing required 'content' field")
                responses.append(str(obj["content"]))

        if not responses:
            raise ValueError(f"Preset file {path} contains no valid responses")

        return cls(responses, selection, rng=rng)


class ResponseGenerator:
    """Generates fake LLM responses in OpenAI-compatible format.

    Supports multiple generation modes:
    - random: Generate random words from vocabulary
    - template: Jinja2 template rendering with helpers
    - echo: Reflect parts of input prompt
    - preset: Return responses from a preset bank

    Usage:
        config = ResponseConfig(mode="random")
        generator = ResponseGenerator(config)
        response = generator.generate(request_data)
        # response.to_dict() -> OpenAI-compatible JSON
    """

    def __init__(
        self,
        config: ResponseConfig,
        *,
        time_func: Callable[[], float] | None = None,
        rng: random_module.Random | None = None,
        uuid_func: Callable[[], str] | None = None,
    ) -> None:
        """Initialize response generator.

        Args:
            config: Response generation configuration
            time_func: Time function for testing (default: time.time)
            rng: Random instance for deterministic testing
            uuid_func: UUID function for testing (default: uuid4().hex)
        """
        self._config = config
        self._time_func = time_func if time_func is not None else time.time
        self._rng = rng if rng is not None else random_module.Random()
        self._uuid_func = uuid_func if uuid_func is not None else lambda: uuid.uuid4().hex

        # Lazy-load preset bank
        self._preset_bank: PresetBank | None = None

        # Setup Jinja2 environment with custom helpers
        self._jinja_env = self._create_jinja_env()

        # Pre-compile template at construction — fail fast on syntax errors
        self._compiled_template: jinja2.Template | None = None
        if config.mode == "template":
            self._compiled_template = self._jinja_env.from_string(config.template.body)

    @property
    def config(self) -> ResponseConfig:
        """Current response generation configuration (frozen/immutable)."""
        return self._config

    def _create_jinja_env(self) -> jinja2.Environment:
        """Create Jinja2 environment with custom helpers."""
        env = jinja2.sandbox.SandboxedEnvironment(
            autoescape=False,  # We're generating text, not HTML
            undefined=jinja2.StrictUndefined,
        )

        # Add global helper functions
        env.globals["random_choice"] = self._template_random_choice
        env.globals["random_float"] = self._template_random_float
        env.globals["random_int"] = self._template_random_int
        env.globals["random_words"] = self._template_random_words
        env.globals["timestamp"] = self._template_timestamp

        return env

    def _template_random_choice(self, *options: Any) -> Any:
        """Jinja2 helper: Pick random item from options."""
        if not options:
            raise ValueError("random_choice requires at least one argument")
        return self._rng.choice(options)

    def _template_random_float(self, min_val: float = 0.0, max_val: float = 1.0) -> float:
        """Jinja2 helper: Generate random float in range."""
        return self._rng.uniform(min_val, max_val)

    def _template_random_int(self, min_val: int = 0, max_val: int = 100) -> int:
        """Jinja2 helper: Generate random integer in range."""
        return self._rng.randint(min_val, max_val)

    def _template_random_words(self, count: int = 5, vocabulary: str = "english") -> str:
        """Jinja2 helper: Generate random words."""
        vocab = ENGLISH_VOCABULARY if vocabulary == "english" else LOREM_VOCABULARY
        words = [self._rng.choice(vocab) for _ in range(count)]
        return " ".join(words)

    def _template_timestamp(self) -> int:
        """Jinja2 helper: Get current Unix timestamp."""
        return int(self._time_func())

    def _get_vocabulary(self) -> tuple[str, ...]:
        """Get vocabulary based on config."""
        if self._config.random.vocabulary == "lorem":
            return LOREM_VOCABULARY
        return ENGLISH_VOCABULARY

    def _generate_random_text(self) -> str:
        """Generate random text using configured vocabulary."""
        vocab = self._get_vocabulary()
        word_count = self._rng.randint(
            self._config.random.min_words,
            self._config.random.max_words,
        )

        words = [self._rng.choice(vocab) for _ in range(word_count)]

        # Capitalize first word and add period at end for realism
        if words:
            words[0] = words[0].capitalize()
        return " ".join(words) + "."

    def _generate_template_response(self, request: dict[str, Any]) -> str:
        """Generate response from Jinja2 template.

        Config-sourced templates are system data — a broken template is a
        config bug that should crash. Let TemplateError propagate.
        """
        assert self._compiled_template is not None, "mode must be 'template'"
        return self._compiled_template.render(
            request=request,
            messages=request.get("messages", []),
            model=request.get("model"),
        )

    def _generate_echo_response(self, request: dict[str, Any]) -> str:
        """Echo parts of the input prompt."""
        messages = request.get("messages", [])
        if not messages:
            return "Echo: (no messages provided)"

        # Get the last user message
        user_messages = [m for m in messages if m.get("role") == "user"]
        if user_messages:
            last_content = user_messages[-1].get("content", "")
        else:
            # Fall back to last message of any role
            last_content = messages[-1].get("content", "")

        # Truncate if too long
        max_echo_len = 200
        if len(last_content) > max_echo_len:
            last_content = last_content[:max_echo_len] + "..."

        return f"Echo: {last_content}"

    def _get_preset_bank(self) -> PresetBank:
        """Get or create preset bank (lazy loading)."""
        if self._preset_bank is None:
            self._preset_bank = PresetBank.from_jsonl(
                self._config.preset.file,
                self._config.preset.selection,
                rng=self._rng,
            )
        return self._preset_bank

    def _generate_preset_response(self) -> str:
        """Get next response from preset bank."""
        bank = self._get_preset_bank()
        return bank.next()

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Uses a simple approximation: ~4 characters per token on average.
        This is a rough estimate suitable for fake responses.
        """
        # OpenAI tokenization averages about 4 chars per token for English
        return max(1, len(text) // 4)

    def _extract_prompt_text(self, request: dict[str, Any]) -> str:
        """Extract full prompt text from request for token estimation."""
        messages = request.get("messages", [])
        parts = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            parts.append(f"{role}: {content}")
        return "\n".join(parts)

    def generate(
        self,
        request: dict[str, Any],
        *,
        mode_override: str | None = None,
        template_override: str | None = None,
    ) -> OpenAIResponse:
        """Generate a fake LLM response.

        Args:
            request: OpenAI-compatible chat completion request
            mode_override: Override response mode (from X-Fake-Response-Mode header)
            template_override: Override template body (from X-Fake-Template header)

        Returns:
            OpenAIResponse with generated content and metadata
        """
        # Determine mode (override takes precedence)
        mode = mode_override if mode_override is not None else self._config.mode

        # Generate content based on mode
        max_len = self._config.max_template_length
        if mode == "random":
            content = self._generate_random_text()
        elif mode == "template":
            # Use override template if provided
            if template_override is not None:
                if len(template_override) > max_len:
                    raise ValueError(f"Template override exceeds max length ({len(template_override)} > {max_len})")
                # Header-override template is Tier 3 (external data from request header).
                # Return error content instead of crashing — the server must produce
                # a deterministic response, not an unplanned 500.
                try:
                    template = self._jinja_env.from_string(template_override)
                    content = template.render(
                        request=request,
                        messages=request.get("messages", []),
                        model=request.get("model"),
                    )
                except jinja2.TemplateError as exc:
                    content = f"[template_override_error: {exc}]"
            else:
                if self._compiled_template is None:
                    content = "[template_mode_unavailable: server not configured for template mode]"
                else:
                    content = self._generate_template_response(request)
        elif mode == "echo":
            content = self._generate_echo_response(request)
        elif mode == "preset":
            if mode_override is not None and self._config.mode != "preset":
                content = "[preset_mode_unavailable: server not configured for preset mode]"
            else:
                content = self._generate_preset_response()
        else:
            # Config mode is Pydantic Literal-validated, so invalid config mode
            # is impossible. This branch is only reachable via mode_override from
            # the X-Fake-Response-Mode header (Tier 3 external data).
            logger.warning("unknown_response_mode_override", mode=mode)
            content = f"[unknown_mode: {mode!r}]"

        # Estimate token counts
        prompt_text = self._extract_prompt_text(request)
        prompt_tokens = self._estimate_tokens(prompt_text)
        completion_tokens = self._estimate_tokens(content)

        # Build response
        return OpenAIResponse(
            id=f"fake-{self._uuid_func()}",
            object="chat.completion",
            created=int(self._time_func()),
            model=request.get("model", "gpt-4"),
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason="stop",
        )

    def reset(self) -> None:
        """Reset generator state (clears preset bank index)."""
        if self._preset_bank is not None:
            self._preset_bank.reset()
