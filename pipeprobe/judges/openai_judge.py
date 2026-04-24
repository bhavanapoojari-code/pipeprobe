"""
PipeProbe — OpenAI judge.

Uses identical prompts as ClaudeJudge so scores are comparable
when you switch providers or run A/B comparisons.
Install: pip install pipeprobe[openai]
"""
from __future__ import annotations
import json, time
from typing import Any
from pipeprobe.judges.base import BaseJudge
from pipeprobe.judges.prompts import build_system, build_user, METRICS
from pipeprobe.models import MetricScore, TestCase, TestResult, Verdict

DEFAULT_METRICS    = list(METRICS.keys())
DEFAULT_THRESHOLD  = 0.7


class OpenAIJudge(BaseJudge):
    """
    Judge backed by OpenAI (gpt-4o, gpt-4-turbo, etc.)

    Parameters
    ----------
    model      : OpenAI model. Default = gpt-4o.
    metrics    : Rubrics to score. Default = all four.
    thresholds : Per-metric pass thresholds. Default = 0.7 each.
    api_key    : Overrides OPENAI_API_KEY env var.

    Examples
    --------
    >>> judge = OpenAIJudge(model="gpt-4o")
    >>> result = judge.evaluate(case, actual_answer)
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        metrics: list[str] | None = None,
        thresholds: dict[str, float] | None = None,
        api_key: str | None = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("Install OpenAI support: pip install pipeprobe[openai]")

        self.model      = model
        self.metrics    = metrics or DEFAULT_METRICS
        self.thresholds = thresholds or {m: DEFAULT_THRESHOLD for m in self.metrics}
        self._client    = OpenAI(api_key=api_key)

    @property
    def provider(self) -> str:
        return "openai"

    def evaluate(self, case: TestCase, actual: str) -> TestResult:
        t0 = time.perf_counter()
        system_prompt = build_system(case.domain)
        user_prompt   = build_user(case, actual, self.metrics)

        response = self._client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},   # OpenAI JSON mode
            messages=[
                {"role": "system",  "content": system_prompt},
                {"role": "user",    "content": user_prompt},
            ],
            max_tokens=1024,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        raw        = response.choices[0].message.content or ""
        scores     = self._parse(raw)
        verdict    = Verdict.PASS if all(m.passed for m in scores) else Verdict.FAIL

        return TestResult(
            case_id=case.id, domain=case.domain, question=case.question,
            expected=case.expected, actual=actual, metrics=scores,
            verdict=verdict, latency_ms=latency_ms,
            model_used=self.model, judge_provider=self.provider,
        )

    def _parse(self, raw: str) -> list[MetricScore]:
        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as e:
            return [MetricScore("parse_error", 0.0, f"JSON parse failed: {e}", False)]
        results = []
        for name in self.metrics:
            entry     = data.get("scores", {}).get(name, {})
            score     = float(entry.get("score", 0.0))
            threshold = self.thresholds.get(name, DEFAULT_THRESHOLD)
            results.append(MetricScore(
                name=name, score=score,
                reasoning=entry.get("reasoning", ""),
                passed=score >= threshold, threshold=threshold,
            ))
        return results
