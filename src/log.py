"""Structured batch logging with per-account tagging and timing."""

import time

from rich.console import Console

_CONSOLE = Console()


class Log:
    """Per-registration logger. Each coroutine gets its own instance —
    timing state is naturally isolated under concurrency.
    """

    def __init__(self, index: int, total: int) -> None:
        self._idx = index
        self._total = total
        self._t0: float | None = None

    # ── header ───────────────────────────────────────────────

    def section(self, title: str) -> None:
        """Section banner shown once per registration."""
        _CONSOLE.print(f"\n── {title} ({self._idx}/{self._total}) ──")

    # ── timed step — start / end ─────────────────────────────

    def step(self, message: str) -> None:
        """Mark the start of a timed operation."""
        self._t0 = time.monotonic()
        _CONSOLE.print(f"[{self._idx}]   {message}")

    def done(self, suffix: str = "") -> float:
        """Complete a timed step with ✓ and elapsed seconds."""
        elapsed = self._tic()
        tail = f" {elapsed:.1f}s  ✓"
        if suffix:
            tail = f" {elapsed:.1f}s  ✓ {suffix}"
        _CONSOLE.print(f"[{self._idx}]   ...{tail}")
        return elapsed

    def fail(self, reason: str = "") -> float:
        """Complete a timed step with ✗."""
        elapsed = self._tic()
        tail = f" {elapsed:.1f}s  ✗"
        if reason:
            tail += f" {reason}"
        _CONSOLE.print(f"[{self._idx}]   ...{tail}")
        return elapsed

    # ── unstructured lines ───────────────────────────────────

    def info(self, message: str) -> None:
        """Normal information line."""
        self._t0 = None
        _CONSOLE.print(f"[{self._idx}]   {message}")

    def ok(self, message: str) -> None:
        """Success milestone."""
        self._t0 = None
        _CONSOLE.print(f"[{self._idx}]   ✓ {message}")

    def error(self, message: str) -> None:
        """Error message."""
        self._t0 = None
        _CONSOLE.print(f"[{self._idx}]   ✗ {message}")

    def detail(self, message: str) -> None:
        """Indented sub-line (e.g. credentials)."""
        _CONSOLE.print(f"[{self._idx}]      {message}")

    # ── helpers ──────────────────────────────────────────────

    def _tic(self) -> float:
        elapsed = time.monotonic() - self._t0 if self._t0 else 0.0
        self._t0 = None
        return elapsed
