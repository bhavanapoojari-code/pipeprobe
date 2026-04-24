"""
EvalForge — pytest Plugin

Lets you write EvalForge cases as regular pytest tests.
This means eval results show up in your normal pytest output,
CI already knows how to run them, and you get familiar pytest
fixtures, markers, and parametrize support.

Usage
-----
In your conftest.py:
    pytest_plugins = ["pipeprobe.pytest_plugin"]

In your test file:
    import pytest
    from pipeprobe import EvalCase, Domain

    @pytest.mark.pipeprobe(domain=Domain.DBT, threshold=0.8)
    def test_lineage_answer(pipeprobe_judge, dbt_context):
        result = pipeprobe_judge.evaluate(
            EvalCase(
                id="lineage-001",
                domain=Domain.DBT,
                question="Which models feed into fct_orders?",
                expected="stg_orders → int_orders → fct_orders",
                context=dbt_context,
            ),
            actual=my_ai_system("Which models feed into fct_orders?", dbt_context),
        )
        assert result.overall_score >= 0.8, (
            f"Score {result.overall_score:.2f} below threshold. "
            f"Failed metrics: {[m.name for m in result.failed_metrics]}"
        )
"""
from __future__ import annotations

import os
from typing import Any, Generator

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False

from pipeprobe.models import Domain, EvalCase


if HAS_PYTEST:

    def pytest_configure(config: Any) -> None:
        """Register the pipeprobe marker."""
        config.addinivalue_line(
            "markers",
            "pipeprobe(domain, threshold): mark test as an EvalForge evaluation case",
        )

    def pytest_collection_modifyitems(
        config: Any, items: list[Any]
    ) -> None:
        """Add 'pipeprobe' marker to test IDs for filtering."""
        for item in items:
            if item.get_closest_marker("pipeprobe"):
                item.add_marker(pytest.mark.slow)

    @pytest.fixture(scope="session")
    def pipeprobe_judge() -> Any:
        """
        Session-scoped ClaudeJudge fixture.
        Reuses one judge across all eval tests in a session (efficient).
        Requires ANTHROPIC_API_KEY to be set.
        """
        from pipeprobe.judges.claude_judge import ClaudeJudge
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            pytest.skip("ANTHROPIC_API_KEY not set — skipping eval tests")
        return ClaudeJudge(api_key=api_key)

    @pytest.fixture(scope="session")
    def pipeprobe_tracker() -> Any:
        """Session-scoped RegressionTracker fixture."""
        from pipeprobe.reporters.regression_tracker import RegressionTracker
        return RegressionTracker()

    @pytest.fixture
    def make_eval_case() -> Any:
        """Factory fixture to create EvalCase objects cleanly in tests."""
        def _make(
            id: str,
            domain: Domain,
            question: str,
            expected: str,
            context: dict | None = None,
            tags: list[str] | None = None,
        ) -> EvalCase:
            return EvalCase(
                id=id,
                domain=domain,
                question=question,
                expected=expected,
                context=context or {},
                tags=tags or [],
            )
        return _make

    @pytest.fixture
    def assert_eval_score() -> Any:
        """
        Fixture that provides a helper for asserting eval scores.

        Usage:
            def test_my_eval(pipeprobe_judge, assert_eval_score):
                result = pipeprobe_judge.evaluate(case, actual)
                assert_eval_score(result, minimum=0.8)
        """
        def _assert(result: Any, minimum: float = 0.7) -> None:
            if result.overall_score < minimum:
                failed = "\n".join(
                    f"  - {m.name}: {m.score:.2f} < {m.threshold:.2f}\n    {m.reasoning}"
                    for m in result.failed_metrics
                )
                pytest.fail(
                    f"EvalForge score {result.overall_score:.2f} below minimum {minimum:.2f}\n"
                    f"Failed metrics:\n{failed}"
                )
        return _assert


# ── Example test file (generated on pipeprobe init) ───────────────────────────

EXAMPLE_TEST_FILE = '''"""
Example EvalForge pytest tests.
Run with: pytest tests/test_evals.py -m pipeprobe -v
"""
import pytest
from pipeprobe import Domain, EvalCase


@pytest.mark.pipeprobe(domain=Domain.DBT, threshold=0.8)
def test_dbt_lineage_explanation(pipeprobe_judge, make_eval_case, assert_eval_score):
    """Test that the AI correctly explains dbt model lineage."""
    from your_ai_module import your_ai_function  # replace with your system

    case = make_eval_case(
        id="lineage-001",
        domain=Domain.DBT,
        question="Which models feed into fct_orders?",
        expected="stg_orders → int_orders → fct_orders",
        context={
            "dbt_manifest_excerpt": {
                "fct_orders": {"depends_on": ["int_orders"]},
                "int_orders": {"depends_on": ["stg_orders"]},
            }
        },
        tags=["lineage", "critical"],
    )

    actual = your_ai_function(case.question, case.context)
    result = pipeprobe_judge.evaluate(case, actual)
    assert_eval_score(result, minimum=0.8)


@pytest.mark.pipeprobe(domain=Domain.SQL, threshold=0.7)
@pytest.mark.parametrize("query,expected_optimization", [
    (
        "SELECT * FROM orders WHERE customer_id IN (SELECT id FROM customers)",
        "Use a JOIN instead of a correlated subquery. Add index on customer_id.",
    ),
    (
        "SELECT DISTINCT order_id FROM orders ORDER BY created_at",
        "Remove unnecessary DISTINCT if order_id is already unique. Add index on created_at.",
    ),
])
def test_sql_optimization_advice(
    pipeprobe_judge, make_eval_case, assert_eval_score,
    query, expected_optimization
):
    """Parametrized test — runs each slow query through the AI and scores the advice."""
    from your_ai_module import your_sql_optimizer  # replace with your system

    case = make_eval_case(
        id=f"sql-opt-{hash(query) % 9999}",
        domain=Domain.SQL,
        question=f"How should I optimize this query?\\n\\n{query}",
        expected=expected_optimization,
        context={"slow_query": query},
    )

    actual = your_sql_optimizer(case.question, case.context)
    result = pipeprobe_judge.evaluate(case, actual)
    assert_eval_score(result, minimum=0.7)
'''
