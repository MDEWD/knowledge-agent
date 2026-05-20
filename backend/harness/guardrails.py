"""
Guardrails: pre- and post-execution safety checks.

Design:
  - GuardrailViolation is raised (not returned) so the caller cannot silently
    ignore a failed check.
  - Guardrails ships with sensible defaults; callers can extend both sets.
  - Checks are cheap synchronous operations — no LLM calls here.
  - Pre-checks gate the action before it runs.
  - Post-checks gate the result before it is returned to the user.

Usage:
    g = Guardrails()
    g.pre_check(user_input)          # raises GuardrailViolation if unsafe
    g.post_check(llm_output)         # raises GuardrailViolation if unsafe
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class GuardrailViolation(RuntimeError):
    """Raised when a guardrail check fails."""


# ---------------------------------------------------------------------------
# Default patterns
# ---------------------------------------------------------------------------

_DEFAULT_BLOCKED_PATTERNS: list[str] = [
    # Prompt injection attempts
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"forget\s+(all\s+)?previous\s+instructions",
    r"you\s+are\s+now\s+(?:a\s+)?(?:DAN|evil|unconstrained)",
    r"jailbreak",
    # Shell / code injection probes
    r"(?:;|\|{1,2}|&&)\s*(?:rm|wget|curl|bash|sh|exec)\b",
    r"<script[\s>]",
    r"javascript\s*:",
]

_DEFAULT_SENSITIVE_PATTERNS: list[str] = [
    # Credential-shaped strings in outputs
    r"(?i)(?:password|passwd|secret|api[_-]?key)\s*[:=]\s*\S{6,}",
    r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----",
    # Credit card numbers (Luhn format, 13-19 digits)
    r"\b(?:\d[ -]?){13,19}\b",
]


@dataclass
class Guardrails:
    """
    Configurable pre/post execution safety layer.

    Parameters
    ----------
    extra_blocked   : Additional regex patterns to add to the blocklist.
    extra_sensitive : Additional regex patterns for output scanning.
    max_input_chars : Hard limit on raw input length (DoS guard).
    max_output_chars: Hard limit on raw output length.
    """
    extra_blocked: list[str] = field(default_factory=list)
    extra_sensitive: list[str] = field(default_factory=list)
    max_input_chars: int = 32_000
    max_output_chars: int = 64_000

    def __post_init__(self) -> None:
        blocked = _DEFAULT_BLOCKED_PATTERNS + self.extra_blocked
        sensitive = _DEFAULT_SENSITIVE_PATTERNS + self.extra_sensitive
        self._blocked_re = [re.compile(p, re.IGNORECASE) for p in blocked]
        self._sensitive_re = [re.compile(p) for p in sensitive]

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def pre_check(self, text: str) -> None:
        """
        Validate user / tool input before the model sees it.

        Raises GuardrailViolation on:
          - Input exceeding max_input_chars
          - Any blocked pattern match
        """
        if len(text) > self.max_input_chars:
            raise GuardrailViolation(
                f"Input too long: {len(text)} chars (limit {self.max_input_chars})"
            )
        for pattern in self._blocked_re:
            if pattern.search(text):
                raise GuardrailViolation(
                    f"Input blocked: matches pattern /{pattern.pattern}/"
                )

    def post_check(self, text: str) -> None:
        """
        Validate model output before it is returned to the user.

        Raises GuardrailViolation on:
          - Output exceeding max_output_chars
          - Any sensitive-data pattern match
        """
        if len(text) > self.max_output_chars:
            raise GuardrailViolation(
                f"Output too long: {len(text)} chars (limit {self.max_output_chars})"
            )
        for pattern in self._sensitive_re:
            if pattern.search(text):
                logger.error(
                    "[guardrails] sensitive pattern /%s/ detected in output",
                    pattern.pattern,
                )
                raise GuardrailViolation(
                    "Output blocked: contains potentially sensitive information"
                )
