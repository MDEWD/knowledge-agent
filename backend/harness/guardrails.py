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

# Each entry is (pattern, fix_instruction) so that violations carry
# actionable remediation hints — not just "you were blocked".
_DEFAULT_BLOCKED_PATTERNS: list[tuple[str, str]] = [
    (
        r"ignore\s+(all\s+)?previous\s+instructions",
        "Do not attempt to override system instructions. Rephrase your request within allowed scope.",
    ),
    (
        r"forget\s+(all\s+)?previous\s+instructions",
        "Do not attempt to override system instructions. Rephrase your request within allowed scope.",
    ),
    (
        r"you\s+are\s+now\s+(?:a\s+)?(?:DAN|evil|unconstrained)",
        "Role-override prompts are not permitted. State your actual goal directly.",
    ),
    (
        r"jailbreak",
        "Jailbreak attempts are blocked. Describe what you need within normal boundaries.",
    ),
    (
        r"(?:;|\|{1,2}|&&)\s*(?:rm|wget|curl|bash|sh|exec)\b",
        "Shell injection sequences are not allowed. Use the provided tool APIs instead.",
    ),
    (
        r"<script[\s>]",
        "Inline scripts are not allowed in input. Strip HTML/JS tags before submitting.",
    ),
    (
        r"javascript\s*:",
        "JavaScript URI schemes are not allowed. Use plain text or approved tool calls.",
    ),
]

_DEFAULT_SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    (
        r"(?i)(?:password|passwd|secret|api[_-]?key)\s*[:=]\s*\S{6,}",
        "Output contains a credential-shaped string. Redact secrets before returning output.",
    ),
    (
        r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----",
        "Output contains a private key. Never include key material in responses.",
    ),
    (
        r"\b(?:\d[ -]?){13,19}\b",
        "Output may contain a card number. Mask or remove PAN data before returning.",
    ),
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
        blocked = _DEFAULT_BLOCKED_PATTERNS + [(p, "") for p in self.extra_blocked]
        sensitive = _DEFAULT_SENSITIVE_PATTERNS + [(p, "") for p in self.extra_sensitive]
        self._blocked: list[tuple[re.Pattern, str]] = [
            (re.compile(p, re.IGNORECASE), hint) for p, hint in blocked
        ]
        self._sensitive: list[tuple[re.Pattern, str]] = [
            (re.compile(p), hint) for p, hint in sensitive
        ]

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def pre_check(self, text: str) -> None:
        """
        Validate user / tool input before the model sees it.

        Raises GuardrailViolation on:
          - Input exceeding max_input_chars
          - Any blocked pattern match (with embedded fix instruction)
        """
        if len(text) > self.max_input_chars:
            raise GuardrailViolation(
                f"Input too long: {len(text)} chars (limit {self.max_input_chars}). "
                f"Fix: split the request into smaller chunks or summarise before submitting."
            )
        for pattern, fix in self._blocked:
            if pattern.search(text):
                hint = f" Fix: {fix}" if fix else ""
                raise GuardrailViolation(
                    f"Input blocked — matches restricted pattern /{pattern.pattern}/."
                    f"{hint}"
                )

    def post_check(self, text: str) -> None:
        """
        Validate model output before it is returned to the user.

        Raises GuardrailViolation on:
          - Output exceeding max_output_chars
          - Any sensitive-data pattern match (with embedded fix instruction)
        """
        if len(text) > self.max_output_chars:
            raise GuardrailViolation(
                f"Output too long: {len(text)} chars (limit {self.max_output_chars}). "
                f"Fix: truncate or paginate the response before returning."
            )
        for pattern, fix in self._sensitive:
            if pattern.search(text):
                logger.error(
                    "[guardrails] sensitive pattern /%s/ in output", pattern.pattern
                )
                hint = f" Fix: {fix}" if fix else ""
                raise GuardrailViolation(
                    f"Output blocked — contains potentially sensitive information "
                    f"matching /{pattern.pattern}/."
                    f"{hint}"
                )
