"""
PipeProbe — full test suite (no API key required).
All external deps (anthropic, rich, openai) are mocked.
Run: pytest tests/ -v
"""
from __future__ import annotations
import json, os, sys, types, tempfile
from datetime import datetime
from pathlib import Path

# ── Mock all external packages before any pipeprobe import ───────────────────
def _mock(name: str, **attrs: object) -> types.ModuleType:
    m = types.ModuleType(name)
    for k, v in attrs.items(): setattr(m, k, v)
    sys.modules[name] = m
    return m

_mock("anthropic",   Anthropic=lambda **kw: None)
_mock("openai",      OpenAI=lambda **kw: None)
_rich = _mock("rich")
_mock("rich.console", Console=type("Console", (), {"print": lambda *a,**kw: None}))
_mock("rich.panel",   Panel=type("Panel",   (), {"__init__": lambda *a,**kw: None}))
_mock("rich.table",   Table=type("Table",   (), {
    "__init__": lambda *a,**kw: None,
    "add_column": lambda *a,**kw: None,
    "add_row":    lambda *a,**kw: None,
}))
_mock("rich.text",    Text=type("Text", (), {"__init__": lambda s,t="",st="": None}))
_mock("rich.box",     SIMPLE_HEAD=None)
_mock("sqlglot")
_mock("sqlglot.errors", ParseError=Exception)
_mock("sqlglot.expressions")
_mock("yaml")  # mocked globally; individual tests that need real yaml use the real one

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from pipeprobe.models import Domain, MetricScore, TestCase, TestResult, SuiteResult, Verdict
from pipeprobe.metrics.sql_metrics import sql_optimization_score, sql_structural_similarity
from pipeprobe.reporters.regression_tracker import RegressionTracker
from pipeprobe.reporters.html_reporter import generate_html_report
from pipeprobe.connectors.airflow_connector import AirflowConnector
from pipeprobe.connectors.spark_analyzer import SparkAnalyzer


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_result(score: float, case_id: str = "c-001",
                domain: Domain = Domain.DBT) -> TestResult:
    passed = score >= 0.7
    return TestResult(
        case_id=case_id, domain=domain, question="Q?",
        expected="A", actual="B",
        metrics=[MetricScore("correctness", score, "ok", passed, 0.7)],
        verdict=Verdict.PASS if passed else Verdict.FAIL,
        latency_ms=100.0, model_used="claude", judge_provider="claude",
    )

def make_suite(results: list[TestResult], run_id: str = "run1") -> SuiteResult:
    return SuiteResult(
        suite_name="test-suite", run_id=run_id, results=results,
        started_at=datetime(2024, 1, 1, 12, 0),
        finished_at=datetime(2024, 1, 1, 12, 1),
    )


# ─────────────────────────────────────────────────────────────────────────────
# MetricScore
# ─────────────────────────────────────────────────────────────────────────────

class TestMetricScore:
    def test_valid(self):
        m = MetricScore("faithfulness", 0.85, "Good.", True, 0.7)
        assert m.score == 0.85
        assert m.passed is True

    def test_invalid_above_1(self):
        with pytest.raises(ValueError):
            MetricScore("x", 1.1, "bad", False, 0.7)

    def test_invalid_below_0(self):
        with pytest.raises(ValueError):
            MetricScore("x", -0.1, "bad", False, 0.7)

    def test_boundary_exactly_threshold(self):
        m = MetricScore("x", 0.7, "ok", True, 0.7)
        assert m.passed is True

    def test_just_below_threshold(self):
        m = MetricScore("x", 0.699, "ok", False, 0.7)
        assert m.passed is False


# ─────────────────────────────────────────────────────────────────────────────
# TestResult
# ─────────────────────────────────────────────────────────────────────────────

class TestTestResult:
    def test_overall_score_average(self):
        r = make_result(0.0)  # single metric score 0.7 would be avg
        r.metrics = [
            MetricScore("faithfulness",  0.8, "ok", True,  0.7),
            MetricScore("correctness",   0.6, "ok", False, 0.7),
        ]
        assert abs(r.overall_score - 0.7) < 0.001

    def test_overall_score_empty(self):
        r = make_result(0.9)
        r.metrics = []
        assert r.overall_score == 0.0

    def test_failed_metrics(self):
        r = make_result(0.9)
        r.metrics = [
            MetricScore("faithfulness",  0.9, "ok", True,  0.7),
            MetricScore("actionability", 0.4, "vague", False, 0.7),
        ]
        assert len(r.failed_metrics) == 1
        assert r.failed_metrics[0].name == "actionability"

    def test_regression_defaults(self):
        r = make_result(0.8)
        assert r.regression is False
        assert r.delta == 0.0
        assert r.prev_score == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# SuiteResult
# ─────────────────────────────────────────────────────────────────────────────

class TestSuiteResult:
    def test_stats(self):
        suite = make_suite([
            make_result(0.9, "a"), make_result(0.8, "b"), make_result(0.3, "c")
        ])
        assert suite.total == 3
        assert suite.passed == 2
        assert suite.failed == 1
        assert abs(suite.pass_rate - 2/3) < 0.001

    def test_duration(self):
        suite = make_suite([make_result(0.9)])
        assert suite.duration_seconds == 60.0

    def test_avg_score(self):
        r1 = make_result(0.9, "a"); r2 = make_result(0.7, "b")
        suite = make_suite([r1, r2])
        assert abs(suite.avg_score - 0.8) < 0.001

    def test_regressions_list(self):
        r1 = make_result(0.9, "a")
        r2 = make_result(0.4, "b"); r2.regression = True
        suite = make_suite([r1, r2])
        assert len(suite.regressions) == 1
        assert suite.regressions[0].case_id == "b"


# ─────────────────────────────────────────────────────────────────────────────
# SQL Metrics
# ─────────────────────────────────────────────────────────────────────────────

class TestSqlMetrics:
    def test_cte_introduction(self):
        orig = "SELECT * FROM orders WHERE id IN (SELECT id FROM customers)"
        opt  = "WITH c AS (SELECT id FROM customers) SELECT o.id FROM orders o JOIN c ON o.id=c.id"
        s    = sql_optimization_score(orig, opt)
        assert s.score > 0.5

    def test_no_change_neutral(self):
        sql = "SELECT id FROM orders"
        s   = sql_optimization_score(sql, sql)
        assert s.score == 0.5

    def test_select_star_elimination(self):
        s = sql_optimization_score(
            "SELECT * FROM orders",
            "SELECT id, customer_id, total FROM orders",
        )
        assert s.score > 0.5

    def test_structural_similarity_range(self):
        s = sql_structural_similarity(
            "SELECT id FROM orders",
            "SELECT id FROM orders WHERE active = 1",
        )
        assert 0.0 <= s.score <= 1.0

    def test_structural_similarity_identical(self):
        sql = "SELECT id, name FROM customers"
        s   = sql_structural_similarity(sql, sql)
        assert s.score == pytest.approx(1.0, abs=0.05)


# ─────────────────────────────────────────────────────────────────────────────
# Regression Tracker
# ─────────────────────────────────────────────────────────────────────────────

class TestRegressionTracker:
    def test_no_regression_on_first_run(self, tmp_path):
        tk   = RegressionTracker(store_path=tmp_path, regression_threshold=0.05)
        regs = tk.detect(make_suite([make_result(0.9)], "run1"))
        assert len(regs) == 0

    def test_regression_detected(self, tmp_path):
        tk = RegressionTracker(store_path=tmp_path, regression_threshold=0.05)
        tk.save(make_suite([make_result(0.9, "c")], "run1"))
        second = make_suite([make_result(0.7, "c")], "run2")
        regs   = tk.detect(second)
        assert len(regs) == 1
        assert regs[0].regression is True
        assert regs[0].delta < -0.05

    def test_improvement_not_flagged(self, tmp_path):
        tk = RegressionTracker(store_path=tmp_path, regression_threshold=0.05)
        tk.save(make_suite([make_result(0.7, "c")], "run1"))
        third = make_suite([make_result(0.95, "c")], "run2")
        regs  = tk.detect(third)
        assert len(regs) == 0

    def test_delta_value_correct(self, tmp_path):
        tk = RegressionTracker(store_path=tmp_path, regression_threshold=0.05)
        tk.save(make_suite([make_result(0.9, "c")], "run1"))
        second = make_suite([make_result(0.7, "c")], "run2")
        tk.detect(second)
        assert abs(second.results[0].delta - (-0.2)) < 0.01

    def test_prev_score_populated(self, tmp_path):
        tk = RegressionTracker(store_path=tmp_path)
        tk.save(make_suite([make_result(0.85, "c")], "run1"))
        second = make_suite([make_result(0.75, "c")], "run2")
        tk.detect(second)
        assert abs(second.results[0].prev_score - 0.85) < 0.01

    def test_history_returns_all_runs(self, tmp_path):
        tk = RegressionTracker(store_path=tmp_path)
        for i, score in enumerate([0.9, 0.85, 0.78], 1):
            tk.save(make_suite([make_result(score, "c")], f"run{i}"))
        h = tk.get_history("test-suite")
        assert len(h) == 3

    def test_history_limit(self, tmp_path):
        tk = RegressionTracker(store_path=tmp_path)
        for i in range(5):
            tk.save(make_suite([make_result(0.8, "c")], f"run{i}"))
        h = tk.get_history("test-suite", limit=3)
        assert len(h) == 3

    def test_case_trend(self, tmp_path):
        tk = RegressionTracker(store_path=tmp_path)
        for i, score in enumerate([0.9, 0.8, 0.7], 1):
            tk.save(make_suite([make_result(score, "c")], f"run{i}"))
        trend = tk.get_case_trend("test-suite", "c-001")
        assert len(trend) == 3

    def test_compare_summary_first_run(self, tmp_path):
        tk      = RegressionTracker(store_path=tmp_path)
        summary = tk.compare_summary(make_suite([make_result(0.9)], "run1"))
        assert summary["has_baseline"] is False

    def test_compare_summary_with_baseline(self, tmp_path):
        tk = RegressionTracker(store_path=tmp_path, regression_threshold=0.05)
        tk.save(make_suite([make_result(0.9, "c")], "run1"))
        second  = make_suite([make_result(0.6, "c")], "run2")
        summary = tk.compare_summary(second)
        assert summary["has_baseline"] is True
        assert len(summary["regressed"]) == 1
        assert summary["regressed"][0]["case_id"] == "c-001"


# ─────────────────────────────────────────────────────────────────────────────
# HTML Reporter
# ─────────────────────────────────────────────────────────────────────────────

class TestHtmlReporter:
    def _suite_with_regression(self) -> SuiteResult:
        r1 = make_result(0.92, "case-001")
        r2 = make_result(0.40, "case-002"); r2.regression = True; r2.delta = -0.18; r2.prev_score = 0.58
        return SuiteResult(
            suite_name="dbt-rag", run_id="abc123", results=[r1, r2],
            started_at=datetime(2024, 1, 15, 6, 0),
            finished_at=datetime(2024, 1, 15, 6, 1),
            git_sha="abc12345", git_branch="main", triggered_by="ci",
        )

    def test_generates_valid_html(self):
        html = generate_html_report(self._suite_with_regression())
        assert "<!DOCTYPE html>" in html
        assert "PipeProbe" in html
        assert "dbt-rag" in html

    def test_contains_case_ids(self):
        html = generate_html_report(self._suite_with_regression())
        assert "case-001" in html
        assert "case-002" in html

    def test_regression_section_present(self):
        html = generate_html_report(self._suite_with_regression())
        assert "regression" in html.lower()

    def test_compare_section_present(self):
        compare = {
            "has_baseline": True, "prev_run_id": "prev1",
            "prev_avg": 0.75, "curr_avg": 0.66, "avg_delta": -0.09,
            "regressed": [{"case_id": "case-002", "delta": -0.18}],
            "improved": [], "unchanged": [],
        }
        html = generate_html_report(self._suite_with_regression(), compare=compare)
        assert "prev1" in html

    def test_saves_to_file(self, tmp_path):
        out = tmp_path / "report.html"
        generate_html_report(make_suite([make_result(0.9)]), output_path=out)
        assert out.exists()
        assert out.stat().st_size > 2000

    def test_no_compare_section_when_first_run(self):
        compare = {"has_baseline": False, "message": "First run."}
        html = generate_html_report(make_suite([make_result(0.9)]), compare=compare)
        assert "PipeProbe" in html


# ─────────────────────────────────────────────────────────────────────────────
# Airflow Connector
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_DAG = '''
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
from datetime import datetime
default_args = {"owner": "data-eng", "retries": 3, "retry_delay": 300}
with DAG(dag_id="orders_daily", schedule_interval="0 6 * * *",
         start_date=datetime(2024,1,1), catchup=False,
         default_args=default_args) as dag:
    t1 = PythonOperator(task_id="extract_orders",  python_callable=lambda: None)
    t2 = PythonOperator(task_id="transform_orders",python_callable=lambda: None)
    t3 = BashOperator(task_id="load_to_snowflake", bash_command="dbt run")
    t1 >> t2 >> t3
'''

class TestAirflowConnector:
    @pytest.fixture
    def dag_dir(self, tmp_path):
        (tmp_path / "orders_daily.py").write_text(SAMPLE_DAG)
        return tmp_path

    def test_get_dag_context(self, dag_dir):
        c   = AirflowConnector(dag_dir)
        ctx = c.get_dag_context("orders_daily")
        assert ctx["dag_id"] == "orders_daily"
        assert "0 6 * * *" in ctx["schedule"]
        assert len(ctx["tasks"]) == 3

    def test_list_dags(self, dag_dir):
        assert "orders_daily" in AirflowConnector(dag_dir).list_dags()

    def test_validate_good_dag(self, dag_dir):
        result = AirflowConnector(dag_dir).validate_generated_dag(SAMPLE_DAG)
        assert result["valid"] is True
        assert len(result["issues"]) == 0

    def test_validate_no_dag_definition(self, dag_dir):
        result = AirflowConnector(dag_dir).validate_generated_dag("def foo(): pass")
        assert result["valid"] is False
        assert any("No DAG" in i for i in result["issues"])

    def test_validate_syntax_error(self, dag_dir):
        result = AirflowConnector(dag_dir).validate_generated_dag("def foo(:::")
        assert result["valid"] is False
        assert "syntax_error" in result

    def test_validate_missing_catchup_warning(self, dag_dir):
        dag_no_catchup = SAMPLE_DAG.replace("catchup=False,", "")
        result = AirflowConnector(dag_dir).validate_generated_dag(dag_no_catchup)
        assert any("catchup" in w for w in result["warnings"])


# ─────────────────────────────────────────────────────────────────────────────
# Spark Analyzer
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_SPARK = '''
from pyspark.sql import SparkSession
spark = SparkSession.builder.appName("test").getOrCreate()
orders    = spark.read.parquet("s3://data/orders")
customers = spark.table("analytics.customers")
joined    = orders.join(customers, orders.customer_id == customers.id, "inner")
filtered  = joined.filter("status = 'done'")
agg       = filtered.groupBy("region").agg({"total": "sum"})
data      = agg.collect()
agg.write.format("delta").save("s3://output/revenue")
'''

class TestSparkAnalyzer:
    @pytest.fixture
    def spark_file(self, tmp_path):
        f = tmp_path / "job.py"
        f.write_text(SAMPLE_SPARK)
        return f

    def test_get_job_context_keys(self, spark_file):
        ctx = SparkAnalyzer(spark_file).get_job_context()
        for key in ["transformations", "actions", "joins", "read_sources", "potential_issues"]:
            assert key in ctx

    def test_detects_collect_antipattern(self, spark_file):
        issues = SparkAnalyzer(spark_file).detect_performance_issues()
        assert any("collect" in i["issue"].lower() for i in issues)

    def test_extracts_parquet_read(self, spark_file):
        reads = SparkAnalyzer(spark_file).get_job_context()["read_sources"]
        assert any("orders" in r.get("path", "") for r in reads)

    def test_extracts_joins(self, spark_file):
        joins = SparkAnalyzer(spark_file).get_job_context()["joins"]
        assert len(joins) >= 1

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            SparkAnalyzer(tmp_path / "nonexistent.py")

    def test_lineage_summary(self, spark_file):
        summary = SparkAnalyzer(spark_file).get_lineage_summary()
        assert "sources" in summary
        assert "sinks" in summary
