"""
EvalForge — Example: Evaluating a dbt RAG system

This shows exactly how to use EvalForge to evaluate an AI system
that answers questions about your dbt project.

Run with:
    ANTHROPIC_API_KEY=your_key python examples/dbt_rag_eval.py
"""
from __future__ import annotations

import os
import sys

# ── Simulated AI system (replace with your real one) ──────────────────────────

def my_dbt_rag_system(question: str, context: dict) -> str:
    """
    This is a placeholder for your real AI system.
    Replace this with your actual RAG pipeline / agent.

    In a real scenario this would:
    1. Embed the question
    2. Search your vector store with the context
    3. Call Claude/GPT-4 with retrieved chunks
    4. Return the generated answer
    """
    # Simulate different quality answers to show EvalForge working
    if "lineage" in question.lower() and "orders" in question.lower():
        return "The fct_orders model depends on int_orders, which in turn reads from stg_orders."

    if "failing" in question.lower() or "test" in question.lower():
        return "The not_null test on fct_orders.order_id is failing due to NULL values introduced in the int_orders transformation step."

    if "schedule" in question.lower() and "dag" in question.lower():
        return "The orders_daily DAG runs at 6:00 AM UTC every day using a cron schedule of '0 6 * * *'."

    if "optimize" in question.lower() or "slow" in question.lower():
        # Deliberately vague — should score low on actionability
        return "You should try to optimize the query by adding some indexes and maybe rewriting the joins."

    return "I don't have enough context to answer that question accurately."


# ── EvalForge setup ────────────────────────────────────────────────────────────

def run_evals() -> None:
    from evalforge import EvalSuite, Domain, EvalCase
    from evalforge.judges.claude_judge import ClaudeJudge

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ Set ANTHROPIC_API_KEY environment variable first.")
        sys.exit(1)

    # Configure Claude as the judge
    judge = ClaudeJudge(
        model="claude-sonnet-4-6",
        metrics=["faithfulness", "correctness", "domain_relevance", "actionability"],
        thresholds={
            "faithfulness": 0.8,      # High bar — no hallucination in data systems
            "correctness": 0.7,
            "domain_relevance": 0.7,
            "actionability": 0.6,
        },
    )

    suite = EvalSuite(
        name="dbt-rag-pipeline",
        judge=judge,
        fail_on_regression=True,
    )

    # ── Test cases — grounded in real dbt concepts ─────────────────────────

    suite.add_cases([
        EvalCase(
            id="lineage-001",
            domain=Domain.DBT,
            question="Which models write to the orders table, in dependency order?",
            expected="stg_orders → int_orders → fct_orders (upstream to downstream)",
            context={
                "dbt_manifest_excerpt": {
                    "fct_orders": {"depends_on": ["int_orders"]},
                    "int_orders": {"depends_on": ["stg_orders"]},
                    "stg_orders": {"depends_on": ["raw_orders"]},
                }
            },
            tags=["lineage", "critical"],
        ),
        EvalCase(
            id="test-failure-001",
            domain=Domain.DBT,
            question="Which dbt test is currently failing and what is the root cause?",
            expected="The not_null test on fct_orders.order_id is failing. Root cause: NULL values from int_orders transformation.",
            context={
                "failing_tests": [
                    {
                        "test_name": "not_null_fct_orders_order_id",
                        "model": "fct_orders",
                        "column": "order_id",
                        "failures": 143,
                        "status": "fail",
                    }
                ],
                "int_orders_sql": "SELECT order_id, ... FROM stg_orders WHERE order_id IS NOT NULL"
            },
            tags=["diagnosis", "critical"],
        ),
        EvalCase(
            id="airflow-schedule-001",
            domain=Domain.AIRFLOW,
            question="What time does the orders_daily DAG run and in which timezone?",
            expected="orders_daily runs at 6:00 AM UTC daily (cron: '0 6 * * *')",
            context={
                "dag_config": {
                    "dag_id": "orders_daily",
                    "schedule_interval": "0 6 * * *",
                    "timezone": "UTC",
                    "catchup": False,
                }
            },
            tags=["airflow", "schedule"],
        ),
        EvalCase(
            id="sql-optimize-001",
            domain=Domain.SQL,
            question="How should I optimize this slow query on the orders table?",
            expected=(
                "Add a composite index on (customer_id, created_at). "
                "Replace the correlated subquery with a CTE or JOIN. "
                "Estimated 60-80% reduction in query time."
            ),
            context={
                "slow_query": "SELECT * FROM orders WHERE customer_id IN (SELECT id FROM customers WHERE region = 'US')",
                "explain_plan": {"full_table_scan": True, "estimated_rows": 4500000},
                "table_stats": {"orders_row_count": 45000000},
            },
            tags=["sql", "optimization"],
        ),
    ])

    # ── Run the suite ──────────────────────────────────────────────────────

    result = suite.run(
        ai_function=my_dbt_rag_system,
        show_reasoning=True,   # Show Claude's reasoning for each metric
        save=True,             # Persist for regression tracking
    )

    # ── CI assertions ──────────────────────────────────────────────────────

    suite.assert_no_regressions(result)      # Fail if any score dropped
    suite.assert_pass_rate(result, 0.75)     # Fail if < 75% pass rate


if __name__ == "__main__":
    run_evals()
