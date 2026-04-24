"""
PipeProbe
=========
Regression-aware LLM evaluation for AI systems built on data infrastructure.

The only eval framework that understands dbt, Airflow, Snowflake, and Spark —
and blocks CI deployments when your AI silently gets worse.

Quick start
-----------
    from pipeprobe import Suite, TestCase, Domain

    suite = Suite("dbt-rag")
    suite.case("lineage-001", Domain.DBT,
               question="Which models write to orders?",
               expected="stg_orders → int_orders → fct_orders")

    result = suite.run(your_ai_fn)
    suite.assert_no_regressions(result)

Or from a YAML file:
    suite = Suite.from_yaml("probes/dbt_rag.yaml")
    result = suite.run(your_ai_fn)
"""
from pipeprobe.models import Domain, TestCase, TestResult, SuiteResult, MetricScore, Verdict
from pipeprobe.suite import Suite
from pipeprobe.judges import ClaudeJudge, get_judge
from pipeprobe.reporters.regression_tracker import RegressionTracker

__version__ = "0.1.0"
__all__ = [
    "Suite", "TestCase", "TestResult", "SuiteResult",
    "MetricScore", "ClaudeJudge", "get_judge",
    "RegressionTracker", "Domain", "Verdict",
]
