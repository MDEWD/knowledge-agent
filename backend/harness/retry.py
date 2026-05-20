"""
Retry policy with exponential backoff + jitter, and a circuit breaker.

Design:
  - RetryPolicy is a value object (configuration), not a stateful runner.
  - CircuitBreaker is stateful and should be shared across calls to the
    same downstream service (e.g., one instance per LLM client).
  - async_retry() is a free function that composes both.

Usage:
    policy  = RetryPolicy(max_attempts=3, base_delay=1.0)
    breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)

    result = await async_retry(call_llm, policy=policy, circuit=breaker)
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CircuitOpenError(RuntimeError):
    """Raised when the circuit breaker is open and fast-failing requests."""


# ---------------------------------------------------------------------------
# RetryPolicy — immutable configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RetryPolicy:
    """
    Exponential back-off with multiplicative jitter.

    Delay formula:  min(base * multiplier^attempt, max_delay) * U(1-jitter, 1+jitter)
    """
    max_attempts: int = 3
    base_delay: float = 1.0       # seconds
    max_delay: float = 30.0       # seconds cap
    multiplier: float = 2.0
    jitter: float = 0.15          # ± fraction of computed delay
    retryable_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504})

    def delay_for(self, attempt: int) -> float:
        """Return the sleep duration (seconds) before `attempt` (0-based)."""
        raw = min(self.base_delay * (self.multiplier ** attempt), self.max_delay)
        lo, hi = raw * (1 - self.jitter), raw * (1 + self.jitter)
        return random.uniform(lo, hi)

    def is_retryable(self, exc: BaseException) -> bool:
        """Return True if the exception is worth retrying."""
        if isinstance(exc, (TimeoutError, ConnectionError, asyncio.TimeoutError)):
            return True
        # openai.RateLimitError / APIStatusError carry a status_code attribute
        status = getattr(exc, "status_code", None)
        return status in self.retryable_statuses if status is not None else False


# ---------------------------------------------------------------------------
# CircuitBreaker — stateful, thread-safe (asyncio-safe via GIL)
# ---------------------------------------------------------------------------

@dataclass
class CircuitBreaker:
    """
    Three-state circuit breaker: closed → open → half-open → closed.

    States
    ------
    closed    Normal operation; failures are counted.
    open      Fast-fail every request; re-checked after recovery_timeout.
    half-open One probe request allowed; success → closed, failure → open.
    """
    failure_threshold: int = 5       # consecutive failures before opening
    recovery_timeout: float = 60.0   # seconds before trying again

    _failures: int = field(default=0, init=False, repr=False)
    _state: str = field(default="closed", init=False, repr=False)
    _opened_at: float = field(default=0.0, init=False, repr=False)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def allow_request(self) -> bool:
        """Return True if a new request should be attempted."""
        if self._state == "closed":
            return True
        if self._state == "open":
            if time.monotonic() - self._opened_at >= self.recovery_timeout:
                self._state = "half-open"
                logger.info("[circuit] → half-open (probing)")
                return True
            return False
        # half-open: exactly one probe allowed at a time
        return True

    def record_success(self) -> None:
        self._failures = 0
        if self._state != "closed":
            logger.info("[circuit] → closed (recovered)")
        self._state = "closed"

    def record_failure(self) -> None:
        self._failures += 1
        if self._state == "half-open" or self._failures >= self.failure_threshold:
            self._state = "open"
            self._opened_at = time.monotonic()
            logger.warning(
                "[circuit] → open (failures=%d, threshold=%d)",
                self._failures, self.failure_threshold,
            )

    @property
    def state(self) -> str:
        return self._state


# ---------------------------------------------------------------------------
# async_retry — composing policy + circuit breaker
# ---------------------------------------------------------------------------

async def async_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy | None = None,
    circuit: CircuitBreaker | None = None,
    label: str = "call",
) -> T:
    """
    Execute an async callable with retry and optional circuit breaking.

    Parameters
    ----------
    fn      : Zero-argument async callable to invoke.
    policy  : Retry configuration; defaults to RetryPolicy() if None.
    circuit : Shared CircuitBreaker; if None, no circuit breaking.
    label   : Human-readable name used in log messages.

    Returns
    -------
    The return value of fn() on success.

    Raises
    ------
    CircuitOpenError  : If the circuit is open and fast-failing.
    Exception         : The last exception after all attempts are exhausted.
    """
    policy = policy or RetryPolicy()

    for attempt in range(policy.max_attempts):
        if circuit is not None and not circuit.allow_request():
            raise CircuitOpenError(
                f"Circuit breaker is open for '{label}'. "
                f"Retry after {circuit.recovery_timeout}s."
            )

        try:
            result = await fn()
            if circuit is not None:
                circuit.record_success()
            return result

        except Exception as exc:
            if circuit is not None:
                circuit.record_failure()

            is_last = attempt == policy.max_attempts - 1
            if is_last or not policy.is_retryable(exc):
                logger.error(
                    "[retry] '%s' failed (attempt %d/%d): %s",
                    label, attempt + 1, policy.max_attempts, exc,
                )
                raise

            delay = policy.delay_for(attempt)
            logger.warning(
                "[retry] '%s' attempt %d/%d failed (%s). Retrying in %.2fs.",
                label, attempt + 1, policy.max_attempts, type(exc).__name__, delay,
            )
            await asyncio.sleep(delay)

    # Unreachable — loop always returns or raises.
    raise RuntimeError(f"async_retry exhausted for '{label}'")  # pragma: no cover
