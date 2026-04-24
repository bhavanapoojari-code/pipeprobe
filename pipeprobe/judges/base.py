"""PipeProbe — Abstract judge interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from pipeprobe.models import TestCase, TestResult


class BaseJudge(ABC):
    """All LLM judges implement this interface."""

    @abstractmethod
    def evaluate(self, case: TestCase, actual: str) -> TestResult:
        """Score `actual` against `case.expected` and return a TestResult."""
        ...

    @property
    @abstractmethod
    def provider(self) -> str:
        """Human-readable provider name: 'claude', 'openai', 'gemini'."""
        ...
