"""PipeProbe — Anthropic Claude judge."""
from __future__ import annotations
import json, time
from typing import Any
import anthropic
from pipeprobe.judges.base import BaseJudge
from pipeprobe.judges.prompts import build_system, build_user, METRICS
from pipeprobe.models import Domain, MetricScore, TestCase, TestResult, Verdict

DEFAULT_METRICS = list(METRICS.keys())
DEFAULT_THRESHOLD = 0.7


class ClaudeJudge(BaseJudge):
    """
    Judge backed by Anthropic Claude.

    Parameters
    ----------
    model      : Claude model string. Default = claude-sonnet-4-6.
    metrics    : Which rubrics to score. Default = all four.
    thresholds : Per-metric pass thresholds (0–1). Default = 0.7 each.
    api_key    : Overrides ANTHROPIC_API_KEY env var.

    Examples
    --------
    >>> judge = ClaudeJudge(model="claude-sonnet-4-6", thresholds={"faithfulness": 0.85})
    >>> result = judge.evaluate(case, actual_answer)
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        metrics: list[str] | None = None,
        thresholds: dict[str, float] | None = None,
        api_key: str | None = None,
    ) -> None:
        self.model      = model
        self.metrics    = metrics or DEFAULT_METRICS
        self.thresholds = thresholds or {m: DEFAULT_THRESHOLD for m in self.metrics}
        self._client    = anthropic.Anthropic(api_key=api_key)

    @property
    def provider(self) -> str:
        return "claude"

    def evaluate(self, case: TestCase, actual: str) -> TestResult:
        t0 = time.perf_counter()
        response = self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=build_system(case.domain),
            messages=[{"role": "user", "content": build_user(case, actual, self.metrics)}],
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        scores = self._parse(response.content[0].text, case)
        verdict = Verdict.PASS if all(m.passed for m in scores) else Verdict.FAIL
        return TestResult(
            case_id=case.id, domain=case.domain, question=case.question,
            expected=case.expected, actual=actual, metrics=scores,
            verdict=verdict, latency_ms=latency_ms,
            model_used=self.model, judge_provider=self.provider,
        )

    def _parse(self, raw: str, case: TestCase) -> list[MetricScore]:
        try:
            clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            data: dict[str, Any] = json.loads(clean)
        except json.JSONDecodeError as e:
            return [MetricScore("parse_error", 0.0, f"JSON parse failed: {e}", False)]
        results = []
        for name in self.metrics:
            entry = data.get("scores", {}).get(name, {})
            score = float(entry.get("score", 0.0))
            threshold = self.thresholds.get(name, DEFAULT_THRESHOLD)
            results.append(MetricScore(
                name=name, score=score,
                reasoning=entry.get("reasoning", ""),
                passed=score >= threshold, threshold=threshold,
            ))
        return results
