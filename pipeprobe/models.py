"""PipeProbe — Core data models."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


class Domain(str, Enum):
    DBT       = "dbt"
    AIRFLOW   = "airflow"
    SNOWFLAKE = "snowflake"
    SPARK     = "spark"
    SQL       = "sql"
    GENERIC   = "generic"


@dataclass
class TestCase:
    """A single evaluation test case."""
    id: str
    domain: Domain
    question: str
    expected: str
    context: dict[str, Any] = field(default_factory=dict)
    tags: list[str]         = field(default_factory=list)
    metadata: dict[str, Any]= field(default_factory=dict)


@dataclass
class MetricScore:
    name: str
    score: float       # 0.0 – 1.0
    reasoning: str
    passed: bool
    threshold: float = 0.7

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"Score must be in [0,1], got {self.score}")


@dataclass
class TestResult:
    """Full result for one TestCase across all metrics."""
    case_id: str
    domain: Domain
    question: str
    expected: str
    actual: str
    metrics: list[MetricScore]
    verdict: Verdict
    latency_ms: float
    model_used: str
    judge_provider: str = "claude"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    # Regression fields — populated by RegressionTracker
    regression: bool  = False
    delta: float      = 0.0          # score change vs previous run (+/-)
    prev_score: float = 0.0

    @property
    def overall_score(self) -> float:
        return sum(m.score for m in self.metrics) / len(self.metrics) if self.metrics else 0.0

    @property
    def failed_metrics(self) -> list[MetricScore]:
        return [m for m in self.metrics if not m.passed]


@dataclass
class SuiteResult:
    """Aggregated result across all cases in one probe run."""
    suite_name: str
    run_id: str
    results: list[TestResult]
    started_at: datetime
    finished_at: datetime
    git_sha: str    = ""
    git_branch: str = ""
    triggered_by: str = "manual"   # "manual" | "ci" | "schedule"

    @property
    def total(self)      -> int:   return len(self.results)
    @property
    def passed(self)     -> int:   return sum(1 for r in self.results if r.verdict == Verdict.PASS)
    @property
    def failed(self)     -> int:   return sum(1 for r in self.results if r.verdict == Verdict.FAIL)
    @property
    def regressions(self)-> list[TestResult]: return [r for r in self.results if r.regression]
    @property
    def pass_rate(self)  -> float: return self.passed / self.total if self.total else 0.0
    @property
    def avg_score(self)  -> float:
        return sum(r.overall_score for r in self.results) / self.total if self.total else 0.0
    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()
