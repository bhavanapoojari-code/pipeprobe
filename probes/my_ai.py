"""
PipeProbe — demo AI system
Replace the `run` function with your real RAG pipeline / agent.

This stub gives realistic-looking answers so you can see
PipeProbe working end-to-end before wiring up your real system.
"""
from __future__ import annotations
import os


def run(question: str, context: dict) -> str:
    """
    Your AI system goes here.
    PipeProbe calls this for every test case in the YAML suite.

    To wire up a real Claude RAG system, replace the body below with:

        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system="You are a data engineering assistant. Answer using only the provided context.",
            messages=[{"role": "user", "content": f"Context: {context}\n\nQuestion: {question}"}],
        )
        return response.content[0].text
    """

    q = question.lower()

    # --- dbt lineage ---
    if "orders table" in q or "fct_orders" in q:
        return (
            "The models that write to the orders table in dependency order are: "
            "stg_orders (staging layer, reads raw_orders), then int_orders "
            "(intermediate transformation), and finally fct_orders (the final fact model). "
            "So the lineage is stg_orders → int_orders → fct_orders."
        )

    # --- dbt test failure ---
    if "failing" in q or "test" in q and "fail" in q:
        return (
            "The not_null test on fct_orders.order_id is currently failing with 143 failures. "
            "The root cause is in the int_orders model — the LEFT JOIN with stg_customers "
            "produces NULL order_id values for unmatched rows, which then propagate into fct_orders."
        )

    # --- Airflow schedule ---
    if "schedule" in q or "time" in q or "dag" in q:
        return (
            "The orders_daily DAG runs at 6:00 AM UTC every day. "
            "The cron schedule is '0 6 * * *' and catchup is set to False."
        )

    # --- SQL optimization ---
    if "optim" in q or "slow" in q or "query" in q:
        return (
            "To optimize this query: replace the correlated subquery with a JOIN, "
            "add a composite index on (customer_id, region), and avoid SELECT * "
            "by specifying only the columns you need. "
            "This should reduce query time by 60-80%."
        )

    return "I don't have enough context to answer that question accurately."
