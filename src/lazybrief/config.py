"""Configuration and input limits for LazyBrief."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_ENDPOINT = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "gemma3:1b"
DEFAULT_TIMEOUT = 180
MAX_INPUT_BYTES = 1_048_576
MAX_INPUT_CHARS = 50_000


@dataclass(frozen=True)
class AppSettings:
    endpoint: str = DEFAULT_ENDPOINT
    model: str = DEFAULT_MODEL
    timeout: int = DEFAULT_TIMEOUT

    @classmethod
    def from_environment(cls) -> AppSettings:
        """Read optional deployment defaults without exposing secrets."""
        endpoint = os.getenv("LAZYBRIEF_OLLAMA_URL", DEFAULT_ENDPOINT).strip()
        model = os.getenv("LAZYBRIEF_MODEL", DEFAULT_MODEL).strip()
        timeout_value = os.getenv("LAZYBRIEF_TIMEOUT", str(DEFAULT_TIMEOUT)).strip()
        try:
            timeout = int(timeout_value)
        except ValueError as exc:
            raise ValueError("LAZYBRIEF_TIMEOUT must be a whole number of seconds.") from exc
        if not endpoint:
            raise ValueError("LAZYBRIEF_OLLAMA_URL cannot be empty.")
        if not model:
            raise ValueError("LAZYBRIEF_MODEL cannot be empty.")
        if not 1 <= timeout <= 900:
            raise ValueError("LAZYBRIEF_TIMEOUT must be between 1 and 900 seconds.")
        return cls(endpoint=endpoint, model=model, timeout=timeout)
