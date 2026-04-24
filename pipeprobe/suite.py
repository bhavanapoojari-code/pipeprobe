"""
PipeProbe — Suite runner.

Supports two modes:
  1. Python API  : suite = Suite("name"); suite.case(...); suite.run(my_ai)
  2. YAML driver : Suite.from_yaml("tests.yaml").run(my_ai)
"""
from __future__ import annotations
import os, sys, uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Any
import yaml

from pipeprobe.judges.base import BaseJudge
from pipeprobe.judges import get_judge
from pipeprobe.models import Domain, TestCase, SuiteResult, Verdict
from pipeprobe.reporters.regression_tracker import RegressionTracker
from pipeprobe.reporters.terminal_reporter import print_suite_result


class Suite:
    """
    A named collection of test cases for one AI system.

    Parameters
    ----------
    name               : Suite name — used for regression history key.
    judge              : Any BaseJudge instance (ClaudeJudge, OpenAIJudge, …).
    tracker            : RegressionTracker. Created automatically if omitted.
    fail_on_regression : Exit(1) when quality drops — blocks CI deployments.
    """

    def __init__(
        self,
        name: str,
        judge: BaseJudge | None = None,
        tracker: RegressionTracker | None = None,
        fail_on_regression: bool = True,
    ) -> None:
        self.name               = name
        self.judge              = judge or get_judge("claude")
        self.tracker            = tracker or RegressionTracker()
        self.fail_on_regression = fail_on_regression
        self._cases: list[TestCase] = []

    # ── Case builders ──────────────────────────────────────────────────────

    def add(self, case: TestCase) -> "Suite":
        self._cases.append(case); return self

    def case(
        self,
        id: str,
        domain: Domain,
        question: str,
        expected: str,
        context: dict | None = None,
        tags: list[str] | None = None,
    ) -> "Suite":
        return self.add(TestCase(id=id, domain=domain, question=question,
                                 expected=expected, context=context or {},
                                 tags=tags or []))

    # ── YAML loader ────────────────────────────────────────────────────────

    @classmethod
    def from_yaml(
        cls,
        yaml_path: str | Path,
        judge: BaseJudge | None = None,
        tracker: RegressionTracker | None = None,
    ) -> "Suite":
        """
        Load a suite from a YAML file.

        YAML format
        -----------
        name: dbt-rag-quality
        judge:
          provider: claude          # or: openai
          model: claude-sonnet-4-6  # optional
          thresholds:               # optional per-metric overrides
            faithfulness: 0.85
        regression_threshold: 0.05  # optional, default 0.05

        cases:
          - id: lineage-001
            domain: dbt
            question: "Which models write to the orders table?"
            expected: "stg_orders → int_orders → fct_orders"
            tags: [lineage, critical]
            context:
              dbt_manifest_excerpt:
                fct_orders:
                  depends_on: [int_orders]
                int_orders:
                  depends_on: [stg_orders]
        """
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"Suite YAML not found: {yaml_path}")

        with open(path) as f:
            data: dict[str, Any] = yaml.safe_load(f)

        if judge is None:
            jcfg = data.get("judge", {})
            judge = get_judge(
                provider   = jcfg.get("provider", "claude"),
                model      = jcfg.get("model", "claude-sonnet-4-6"),
                thresholds = jcfg.get("thresholds"),
            )

        reg_threshold = float(data.get("regression_threshold", 0.05))
        if tracker is None:
            tracker = RegressionTracker(regression_threshold=reg_threshold)

        suite = cls(name=data.get("name", path.stem), judge=judge, tracker=tracker,
                    fail_on_regression=data.get("fail_on_regression", True))

        for raw in data.get("cases", []):
            suite.add(TestCase(
                id       = raw["id"],
                domain   = Domain(raw.get("domain", "generic")),
                question = raw["question"],
                expected = raw["expected"],
                context  = raw.get("context", {}),
                tags     = raw.get("tags", []),
            ))

        return suite

    # ── Run ────────────────────────────────────────────────────────────────

    def run(
        self,
        ai_fn: Callable[[str, dict], str],
        show_reasoning: bool = False,
        save: bool = True,
    ) -> SuiteResult:
        """
        Evaluate all cases through `ai_fn`, score with the judge, detect regressions.

        Parameters
        ----------
        ai_fn          : Your AI system. Signature: (question, context) -> str
        show_reasoning : Print Claude/OpenAI reasoning per metric in terminal.
        save           : Persist results for regression tracking.
        """
        if not self._cases:
            raise ValueError("No test cases. Use suite.case() or Suite.from_yaml().")

        run_id     = str(uuid.uuid4())[:8]
        started_at = datetime.utcnow()
        results    = []

        print(f"\n🔍 PipeProbe — '{self.name}'  ({len(self._cases)} cases)")
        print(f"   judge: {self.judge.provider} / {getattr(self.judge, 'model', '?')}")
        print(f"   run:   {run_id}\n")

        for i, case in enumerate(self._cases, 1):
            print(f"   [{i:02d}/{len(self._cases):02d}] {case.id} ({case.domain.value})… ",
                  end="", flush=True)
            try:
                actual = ai_fn(case.question, case.context)
                result = self.judge.evaluate(case, actual)
                results.append(result)
                icon = "✓" if result.verdict == Verdict.PASS else "✗"
                print(f"{icon} {result.overall_score:.3f}  ({result.latency_ms:.0f}ms)")
            except Exception as e:
                print(f"ERROR  {e}")

        suite_result = SuiteResult(
            suite_name=self.name, run_id=run_id, results=results,
            started_at=started_at, finished_at=datetime.utcnow(),
            git_sha=os.environ.get("GITHUB_SHA", ""),
            git_branch=os.environ.get("GITHUB_REF_NAME", ""),
            triggered_by="ci" if os.environ.get("CI") else "manual",
        )

        # Regression detection + comparison summary
        self.tracker.detect(suite_result)
        compare = self.tracker.compare_summary(suite_result)

        if save:
            self.tracker.save(suite_result)

        print_suite_result(suite_result, compare=compare, show_reasoning=show_reasoning)
        return suite_result

    # ── CI assertions ──────────────────────────────────────────────────────

    def assert_no_regressions(self, result: SuiteResult) -> None:
        """Call after run() in CI — exits 1 when regressions detected."""
        if result.regressions:
            print(f"\n❌  {len(result.regressions)} regression(s) — blocking deployment.\n")
            for r in result.regressions:
                print(f"   {r.case_id}  score {r.overall_score:.3f}  (Δ {r.delta:.1%})")
            sys.exit(1)

    def assert_pass_rate(self, result: SuiteResult, minimum: float = 0.8) -> None:
        if result.pass_rate < minimum:
            print(f"\n❌  Pass rate {result.pass_rate:.1%} < minimum {minimum:.1%} — blocking.\n")
            sys.exit(1)
