"""
PipeProbe — Regression Tracker

The core differentiating feature.
Stores every run, compares the latest against the previous,
and flags cases where the score dropped by >= threshold.

This is what makes PipeProbe CI-blocking: your pipeline fails
the moment AI quality regresses, before users notice.
"""
from __future__ import annotations
import json, uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from pipeprobe.models import SuiteResult, TestResult, Verdict


class RegressionTracker:
    """
    Persists run history and detects metric regressions between runs.

    Parameters
    ----------
    store_path          : Directory for JSON run history. Default = .pipeprobe/
    regression_threshold: Minimum score drop to flag as regression. Default = 0.05.

    Examples
    --------
    >>> tracker = RegressionTracker()
    >>> tracker.save(suite_result)
    >>> regressions = tracker.detect(suite_result)
    >>> print(tracker.compare_summary(suite_result))
    """

    def __init__(
        self,
        store_path: str | Path = ".pipeprobe",
        regression_threshold: float = 0.05,
    ) -> None:
        self.store_path           = Path(store_path)
        self.regression_threshold = regression_threshold
        self.store_path.mkdir(parents=True, exist_ok=True)

    # ── Core API ───────────────────────────────────────────────────────────

    def save(self, suite: SuiteResult) -> str:
        """Persist a suite result. Returns the run_id."""
        run_id = suite.run_id or str(uuid.uuid4())[:8]
        path   = self.store_path / f"{suite.suite_name}__{run_id}.json"
        with open(path, "w") as f:
            json.dump(self._serialise(suite, run_id), f, indent=2, default=str)
        return run_id

    def detect(self, current: SuiteResult) -> list[TestResult]:
        """
        Compare current run vs the previous run of the same suite.
        Mutates current.results in place: sets .regression, .delta, .prev_score.
        Returns list of regressed TestResult objects.
        """
        previous = self._load_previous(current.suite_name, current.run_id)
        if not previous:
            return []

        prev_scores: dict[str, float] = {
            r["case_id"]: r["overall_score"]
            for r in previous.get("results", [])
        }
        regressions: list[TestResult] = []
        for result in current.results:
            prev = prev_scores.get(result.case_id)
            if prev is None:
                continue
            delta = result.overall_score - prev
            result.delta      = round(delta, 4)
            result.prev_score = round(prev, 4)
            if delta <= -self.regression_threshold:
                result.regression = True
                result.verdict    = Verdict.FAIL
                regressions.append(result)
        return regressions

    def compare_summary(self, current: SuiteResult) -> dict[str, Any]:
        """
        Return a structured diff between current and previous run.
        Used by the CLI --compare flag and the HTML report.
        """
        previous = self._load_previous(current.suite_name, current.run_id)
        if not previous:
            return {"has_baseline": False, "message": "First run — no baseline to compare."}

        prev_scores = {r["case_id"]: r["overall_score"] for r in previous.get("results", [])}
        curr_scores = {r.case_id: r.overall_score for r in current.results}

        improved   = []
        regressed  = []
        unchanged  = []
        new_cases  = []

        for cid, cscore in curr_scores.items():
            prev = prev_scores.get(cid)
            if prev is None:
                new_cases.append(cid)
                continue
            delta = cscore - prev
            entry = {"case_id": cid, "prev": round(prev, 3), "current": round(cscore, 3), "delta": round(delta, 4)}
            if delta <= -self.regression_threshold:
                regressed.append(entry)
            elif delta >= self.regression_threshold:
                improved.append(entry)
            else:
                unchanged.append(entry)

        return {
            "has_baseline": True,
            "prev_run_id":  previous.get("run_id"),
            "prev_avg":     round(previous.get("avg_score", 0), 3),
            "curr_avg":     round(current.avg_score, 3),
            "avg_delta":    round(current.avg_score - previous.get("avg_score", 0), 4),
            "regressed":    regressed,
            "improved":     improved,
            "unchanged":    unchanged,
            "new_cases":    new_cases,
        }

    def get_history(self, suite_name: str, limit: int = 10) -> list[dict[str, Any]]:
        runs = sorted(
            self.store_path.glob(f"{suite_name}__*.json"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        history = []
        for rf in runs[:limit]:
            with open(rf) as f:
                d = json.load(f)
            history.append({
                "run_id": d.get("run_id"), "timestamp": d.get("started_at"),
                "pass_rate": d.get("pass_rate"), "avg_score": d.get("avg_score"),
                "total": d.get("total"), "passed": d.get("passed"),
                "failed": d.get("failed"), "regressions": d.get("regression_count", 0),
                "git_sha": d.get("git_sha", ""), "git_branch": d.get("git_branch", ""),
            })
        return history

    def get_case_trend(self, suite_name: str, case_id: str) -> list[dict[str, Any]]:
        """Score history for a single case across all runs — spot gradual drift."""
        runs = sorted(
            self.store_path.glob(f"{suite_name}__*.json"),
            key=lambda p: p.stat().st_mtime,
        )
        trend = []
        for rf in runs:
            with open(rf) as f:
                d = json.load(f)
            for r in d.get("results", []):
                if r.get("case_id") == case_id:
                    trend.append({
                        "run_id": d.get("run_id"), "timestamp": d.get("started_at"),
                        "overall_score": r.get("overall_score"),
                        "verdict": r.get("verdict"),
                        "per_metric": {m["name"]: m["score"] for m in r.get("metrics", [])},
                    })
        return trend

    # ── Serialisation ──────────────────────────────────────────────────────

    def _serialise(self, suite: SuiteResult, run_id: str) -> dict[str, Any]:
        return {
            "suite_name": suite.suite_name, "run_id": run_id,
            "started_at": suite.started_at.isoformat(),
            "finished_at": suite.finished_at.isoformat(),
            "duration_seconds": suite.duration_seconds,
            "git_sha": suite.git_sha, "git_branch": suite.git_branch,
            "triggered_by": suite.triggered_by,
            "pass_rate": round(suite.pass_rate, 4),
            "avg_score": round(suite.avg_score, 4),
            "total": suite.total, "passed": suite.passed, "failed": suite.failed,
            "regression_count": len(suite.regressions),
            "results": [
                {
                    "case_id": r.case_id, "domain": r.domain.value,
                    "verdict": r.verdict.value,
                    "overall_score": round(r.overall_score, 4),
                    "regression": r.regression, "delta": r.delta,
                    "prev_score": r.prev_score, "latency_ms": round(r.latency_ms, 1),
                    "judge_provider": r.judge_provider, "model_used": r.model_used,
                    "metrics": [
                        {"name": m.name, "score": round(m.score, 4),
                         "passed": m.passed, "reasoning": m.reasoning}
                        for m in r.metrics
                    ],
                }
                for r in suite.results
            ],
        }

    def _load_previous(self, suite_name: str, current_run_id: str) -> dict[str, Any] | None:
        runs = sorted(
            self.store_path.glob(f"{suite_name}__*.json"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        for rf in runs:
            if current_run_id not in rf.name:
                with open(rf) as f:
                    return json.load(f)
        return None
