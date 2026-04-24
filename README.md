# 🔬 PipeProbe

[![CI](https://github.com/bhavanapoojari-code/pipeprobe/actions/workflows/pipeprobe-ci.yml/badge.svg)](https://github.com/bhavanapoojari-code/pipeprobe/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Think pytest, but for LLM outputs.**

CI/CD-first LLM evaluation framework that detects quality regressions in AI systems and blocks faulty deployments before production.

> Built by a Senior Data Engineer who got tired of deploying AI updates with no idea if quality got better or worse.

---

## The Problem

You update a prompt. You upgrade a model. You add new documents to your RAG pipeline.  
The AI silently gets worse — and nobody notices until users complain.

Generic eval tools like DeepEval and Ragas score text quality.  
**They don't know if your dbt lineage answer is correct. They don't know if your generated Airflow DAG is deployable. They don't know if your SQL optimization actually helped.**

PipeProbe does.

---

## What It Does

- ✅ Runs test cases against your AI / LLM / RAG system on every deployment
- ✅ Uses LLM-as-a-judge (Claude or OpenAI) with domain-specific rubrics
- ✅ Compares scores against the previous run — detects regressions automatically
- ✅ Fails CI/CD pipelines when quality drops — blocks the deployment
- ✅ Understands dbt, Airflow, Spark, Snowflake — not just generic text
- ✅ Generates terminal output + shareable HTML reports
- ✅ Posts regression alerts to Slack
- ✅ Comments score diff directly on GitHub PRs

---

## What It Looks Like

```
🔍 PipeProbe — 'dbt-rag-quality'  (4 cases)
   judge: claude / claude-sonnet-4-6
   run:   a3f2b1c9

   [01/04] lineage-001 (dbt)…              ✓ 0.912  (1243ms)
   [02/04] test-failure-001 (dbt)…         ✓ 0.847  ( 987ms)
   [03/04] airflow-schedule-001 (airflow)… ✓ 0.791  (1102ms)
   [04/04] sql-optimize-001 (sql)…         ✗ 0.523  (1345ms)

┌─ vs run 8f1a9c2d ──────────────────────────────────────────┐
│ avg score: 0.841 → 0.768  (-0.073)                         │
│ ▼ Regression:  sql-optimize-001  dropped -18.3%            │
│ ▲ Improved:    lineage-001       gained  +4.2%             │
└────────────────────────────────────────────────────────────┘

❌  Deployment BLOCKED — 1 regression detected
    sql-optimize-001  score 0.523  (Δ -18.3%)
```

---

## Why Not DeepEval or Ragas?

| Feature | DeepEval | Ragas | LangSmith | **PipeProbe** |
|---|:---:|:---:|:---:|:---:|
| Regression tracking across runs | ❌ | ❌ | Partial | ✅ |
| CI/CD blocking on score drop | ❌ | ❌ | ❌ | ✅ |
| dbt / Airflow / Spark aware | ❌ | ❌ | ❌ | ✅ |
| YAML-driven test suites | ❌ | ❌ | ❌ | ✅ |
| Claude + OpenAI judge support | ❌ | ❌ | ❌ | ✅ |
| PR comment with score diff | ❌ | ❌ | ❌ | ✅ |
| Slack regression alerts | ❌ | ❌ | ❌ | ✅ |
| Open-source + self-hostable | ✅ | ✅ | ❌ | ✅ |

---

## Quick Start

```bash
pip install pipeprobe
export ANTHROPIC_API_KEY=your_key_here

# Scaffold a suite in seconds
pipeprobe init my-dbt-evals

# Run it
pipeprobe run probes/my_dbt_evals.yaml
```

Your first suite is ready to run in under 5 minutes.

---

## YAML Suite Format

Define your test cases in plain YAML — no code required:

```yaml
# probes/dbt_rag.yaml
name: dbt-rag-quality

judge:
  provider: claude              # or: openai
  model: claude-sonnet-4-6
  thresholds:
    faithfulness:     0.85      # zero hallucination tolerance
    correctness:      0.75
    domain_relevance: 0.70
    actionability:    0.65

regression_threshold: 0.05      # flag if score drops >= 5%
fail_on_regression: true        # exit 1 in CI — blocks deployment

ai_module:   probes/my_ai.py    # point to your AI system
ai_function: run

cases:
  - id: lineage-001
    domain: dbt
    question: "Which models write to the orders table?"
    expected: "stg_orders → int_orders → fct_orders"
    tags: [lineage, critical]
    context:
      dbt_manifest_excerpt:
        fct_orders: { depends_on: [int_orders] }
        int_orders: { depends_on: [stg_orders] }

  - id: airflow-schedule-001
    domain: airflow
    question: "What time does the orders_daily DAG run?"
    expected: "6:00 AM UTC daily (cron: '0 6 * * *')"
    context:
      dag_config:
        dag_id: orders_daily
        schedule_interval: "0 6 * * *"
        timezone: UTC

  - id: sql-optimize-001
    domain: sql
    question: "How should I optimize this slow query?"
    expected: "Replace the subquery with a JOIN. Add index on (customer_id, region)."
    context:
      slow_query: "SELECT * FROM orders WHERE customer_id IN (SELECT id FROM customers)"
```

---

## CLI Commands

```bash
# Run a suite
pipeprobe run probes/dbt_rag.yaml

# Run with per-metric judge reasoning visible
pipeprobe run probes/dbt_rag.yaml --reasoning

# Run and generate an HTML report
pipeprobe run probes/dbt_rag.yaml --html --html-out report.html

# Use OpenAI as the judge instead of Claude
pipeprobe run probes/dbt_rag.yaml --provider openai --model gpt-4o

# Show regression diff between last 2 runs
pipeprobe diff dbt-rag-quality

# Show full run history
pipeprobe history dbt-rag-quality

# Scaffold a new suite
pipeprobe init my-suite
```

---

## Python API

```python
from pipeprobe import Suite, TestCase, Domain
from pipeprobe.judges import ClaudeJudge, get_judge

# Use Claude as judge
judge = ClaudeJudge(
    model="claude-sonnet-4-6",
    thresholds={"faithfulness": 0.85, "correctness": 0.75}
)

# Or swap to OpenAI — same prompts, comparable scores
# judge = get_judge("openai", model="gpt-4o")

suite = Suite("dbt-rag", judge=judge)

suite.case(
    id="lineage-001",
    domain=Domain.DBT,
    question="Which models write to the orders table?",
    expected="stg_orders → int_orders → fct_orders",
    context={"dbt_manifest_excerpt": {...}},
)

def my_ai(question: str, context: dict) -> str:
    # Your RAG pipeline / agent goes here
    ...

result = suite.run(my_ai)

# These call sys.exit(1) in CI — block the deployment
suite.assert_no_regressions(result)
suite.assert_pass_rate(result, minimum=0.80)
```

---

## Real Data Connectors

Pull real context from your actual data stack — no fake examples:

```python
from pipeprobe.connectors.dbt_connector import DbtConnector
from pipeprobe.connectors.airflow_connector import AirflowConnector
from pipeprobe.connectors.spark_analyzer import SparkAnalyzer

# Real dbt lineage from manifest.json
dbt     = DbtConnector("./dbt_project")
context = dbt.get_lineage("fct_orders")

# Real Airflow DAG structure
airflow = AirflowConnector("/opt/airflow/dags")
context = airflow.get_dag_context("orders_daily")

# Real PySpark job analysis — detects anti-patterns
spark   = SparkAnalyzer("jobs/orders_aggregation.py")
context = spark.get_job_context()
```

---

## How It Works

```
Your AI system answers a question
        ↓
PipeProbe sends (question + expected + actual + context) to Claude / GPT-4
        ↓
Judge scores 4 domain-specific metrics (0.0 – 1.0):
  • faithfulness     — did it hallucinate model / column / DAG names?
  • correctness      — is the lineage / diagnosis / SQL technically right?
  • domain_relevance — does it show real dbt / Airflow / SQL expertise?
  • actionability    — can a data engineer act on this answer right now?
        ↓
Scores compared against previous run in .pipeprobe/ history
  score dropped ≥ 5%?  →  flagged as REGRESSION
        ↓
exit 1  →  CI fails  →  deployment blocked
        ↓
PR comment + Slack alert with case IDs and exact score deltas
```

---

## GitHub Actions — CI/CD Integration

```yaml
# .github/workflows/pipeprobe-ci.yml
- name: Run PipeProbe
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  run: pipeprobe run probes/dbt_rag.yaml --html
  # Exit code 1 on regression → merge blocked automatically
```

**What the PR comment looks like:**

```
✅ PipeProbe Results

| Metric      | Value   |
|-------------|---------|
| Pass rate   | 100.0%  |
| Avg score   | 0.871   |
| Passed      | 4 / 4   |
| Regressions | 🟢 0    |

✅ No regressions detected. Safe to merge.
```

---

## Slack Alerts

```python
from pipeprobe.reporters.slack_notifier import SlackNotifier

notifier = SlackNotifier(
    channel="#data-ai-alerts",
    notify_on="regression_only"
)
notifier.post_result(suite_result)
```

Set `SLACK_WEBHOOK_URL` as an environment variable or GitHub Actions secret.

---

## Project Structure

```
pipeprobe/
├── pipeprobe/
│   ├── models.py                   ← TestCase, TestResult, SuiteResult
│   ├── suite.py                    ← Suite runner + YAML loader
│   ├── cli.py                      ← pipeprobe run / diff / history / init
│   ├── judges/
│   │   ├── base.py                 ← abstract BaseJudge interface
│   │   ├── prompts.py              ← shared prompts (identical across providers)
│   │   ├── claude_judge.py         ← Anthropic Claude judge
│   │   └── openai_judge.py         ← OpenAI judge (same prompts = comparable scores)
│   ├── connectors/
│   │   ├── dbt_connector.py        ← reads manifest.json, lineage, failing tests
│   │   ├── airflow_connector.py    ← parses DAGs, validates generated code
│   │   ├── snowflake_connector.py  ← schema, slow queries, null stats
│   │   └── spark_analyzer.py       ← AST analysis, anti-pattern detection
│   ├── metrics/
│   │   └── sql_metrics.py          ← AST-level SQL validity + optimization scoring
│   └── reporters/
│       ├── regression_tracker.py   ← stores runs, detects score drops, diffs
│       ├── terminal_reporter.py    ← Rich terminal output with Δ column
│       ├── html_reporter.py        ← self-contained HTML report
│       └── slack_notifier.py       ← Slack webhook + bot token support
├── probes/
│   ├── dbt_rag.yaml                ← ready-to-run example suite
│   └── my_ai.py                    ← demo AI stub (replace with your system)
├── tests/
│   └── test_pipeprobe.py           ← full test suite, no API key needed
└── .github/workflows/
    └── pipeprobe-ci.yml            ← CI with PR comments + Slack alerts
```

---

## Roadmap

- [ ] `pipeprobe compare run-a run-b` — diff any two specific runs
- [ ] Score trend dashboard (Streamlit)
- [ ] Gemini judge support
- [ ] pytest plugin — write evals as regular pytest tests
- [ ] `pipeprobe watch` — auto-run on every file change

---

## Contributing

```bash
git clone https://github.com/bhavanapoojari-code/pipeprobe
cd pipeprobe
pip install -e ".[dev]"
pytest tests/ -v
```

PRs welcome. Open an issue first for large changes.

---

## License

MIT

---

<div align="center">
<sub>
If this saved you from a silent AI regression, give it a ⭐
</sub>
</div>
