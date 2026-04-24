<div align="center">

# 🔬 PipeProbe

**Regression-aware LLM evaluation for AI systems built on data infrastructure.**

[![CI](https://github.com/yourusername/pipeprobe/actions/workflows/pipeprobe-ci.yml/badge.svg)](https://github.com/yourusername/pipeprobe/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

*The only eval framework that understands dbt, Airflow, Snowflake, and Spark —<br>and **blocks CI deployments** when your AI silently gets worse.*

</div>

---

## The problem

You deploy a RAG system that answers questions about your data pipelines.
A prompt changes. A model gets upgraded. A new document is added.
Suddenly the AI gives wrong lineage answers — and nobody notices until users complain.

**Generic eval tools (DeepEval, Ragas, LangSmith) miss this** because they score generic NLP quality.
They don't know what a correct dbt lineage path looks like.
They don't know whether a generated Airflow DAG is actually deployable.
They don't know if an AI's SQL optimization made things better or worse.

PipeProbe does.

---

## Why PipeProbe is different

| | DeepEval | Ragas | LangSmith | **PipeProbe** |
|---|:---:|:---:|:---:|:---:|
| dbt / Airflow / Spark aware | ❌ | ❌ | ❌ | ✅ |
| Regression tracking across runs | ❌ | ❌ | Partial | ✅ |
| CI/CD blocking on regression | ❌ | ❌ | ❌ | ✅ |
| YAML-driven test suites | ❌ | ❌ | ❌ | ✅ |
| Multi-LLM judge (Claude + OpenAI) | ❌ | ❌ | ❌ | ✅ |
| PR comment with score diff | ❌ | ❌ | ❌ | ✅ |
| Slack regression alerts | ❌ | ❌ | ❌ | ✅ |
| Open-source + self-hostable | ✅ | ✅ | ❌ | ✅ |

---

## Quick start

```bash
pip install pipeprobe
export ANTHROPIC_API_KEY=sk-ant-...

# Scaffold a suite in 10 seconds
pipeprobe init my-dbt-evals

# Run it
pipeprobe run probes/my_dbt_evals.yaml --reasoning --html
```

---

## How it works — 60 second overview

```
Your AI system answers a question
          ↓
PipeProbe sends the answer to Claude (or GPT-4) as a judge
          ↓
Judge scores 4 domain-specific metrics (0.0 – 1.0):
  • faithfulness     — did it hallucinate model/column/DAG names?
  • correctness      — is the lineage / diagnosis / SQL right?
  • domain_relevance — does it show real dbt/Airflow/SQL depth?
  • actionability    — can a data engineer act on this answer now?
          ↓
Scores compared against previous run
  → score dropped ≥ 5%?  → flagged as REGRESSION
          ↓
CI exits 1  →  deployment blocked  →  PR comment + Slack alert
```

---

## CLI — `pipeprobe run tests.yaml`

```bash
# Run a suite
pipeprobe run probes/dbt_rag.yaml

# Run with per-metric reasoning visible
pipeprobe run probes/dbt_rag.yaml --reasoning

# Run + generate HTML report
pipeprobe run probes/dbt_rag.yaml --html --html-out report.html

# Run with OpenAI as the judge instead of Claude
pipeprobe run probes/dbt_rag.yaml --provider openai --model gpt-4o

# Show regression diff between last 2 runs
pipeprobe diff dbt-rag-quality

# Show run history
pipeprobe history dbt-rag-quality
```

---

## YAML suite format

```yaml
# probes/dbt_rag.yaml
name: dbt-rag-quality

judge:
  provider: claude                # or: openai
  model: claude-sonnet-4-6
  thresholds:
    faithfulness:     0.85        # high bar — no hallucinations in data systems
    correctness:      0.75
    domain_relevance: 0.70
    actionability:    0.65

regression_threshold: 0.05        # flag if score drops >= 5%
fail_on_regression: true          # exit 1 in CI → blocks deployment

ai_module:   probes/my_ai.py      # your AI system
ai_function: run                  # function name

cases:
  - id: lineage-001
    domain: dbt
    question: "Which models write to the orders table?"
    expected: "stg_orders → int_orders → fct_orders"
    tags: [lineage, critical]
    context:
      dbt_manifest_excerpt:
        fct_orders: {depends_on: [int_orders]}
        int_orders: {depends_on: [stg_orders]}

  - id: airflow-schedule-001
    domain: airflow
    question: "What time does the orders_daily DAG run?"
    expected: "6:00 AM UTC daily (cron: '0 6 * * *')"
    context:
      dag_config:
        dag_id: orders_daily
        schedule_interval: "0 6 * * *"
        timezone: UTC
```

---

## What the terminal output looks like

```
🔍 PipeProbe — 'dbt-rag-quality'  (4 cases)
   judge: claude / claude-sonnet-4-6
   run:   a3f2b1c9

   [01/04] lineage-001 (dbt)…          ✓ 0.912  (1243ms)
   [02/04] test-failure-001 (dbt)…     ✓ 0.847  (987ms)
   [03/04] airflow-schedule-001 (airflow)… ✓ 0.791  (1102ms)
   [04/04] sql-optimize-001 (sql)…     ✗ 0.523  (1345ms)

┌─ Regression comparison vs run 8f1a9c2d ──────────────────────┐
│ avg score: 0.841 → 0.768  (-0.073)                           │
│ ▼ Regressions (1):  sql-optimize-001 -18.3%                  │
│ ▲ Improved   (1):  lineage-001 +4.2%                         │
└──────────────────────────────────────────────────────────────┘

  Case ID              Domain   Score    Δ        Verdict  Judge   Failed metrics
  ───────────────────────────────────────────────────────────────────────────────
  lineage-001          dbt      0.912   +4.2%    ✓ pass   claude  —
  test-failure-001     dbt      0.847    —       ✓ pass   claude  —
  airflow-schedule-001 airflow  0.791    —       ✓ pass   claude  —
  sql-optimize-001     sql      0.523  -18.3%    ✗ fail   claude  actionability

┌─ Regressions detected ───────────────────────────────────────┐
│ ▼ REGRESSION  sql-optimize-001  0.706 → 0.523  (-18.3%)     │
└──────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────┐
│  ✗ FAILED   3/4 passed (75.0%)  ·  avg score 0.768  ·  regressions 1  │
└───────────────────────────────────────────────────────────────┘

❌  1 regression(s) — blocking deployment.
   sql-optimize-001  score 0.523  (Δ -18.3%)
```

---

## Python API

```python
from pipeprobe import Suite, TestCase, Domain
from pipeprobe.judges import ClaudeJudge, get_judge

# Use Claude
judge = ClaudeJudge(
    model="claude-sonnet-4-6",
    thresholds={"faithfulness": 0.85, "correctness": 0.75}
)

# Or switch to OpenAI — same prompts, comparable scores
# judge = get_judge("openai", model="gpt-4o")

suite = Suite("dbt-rag", judge=judge)

suite.case(
    id="lineage-001",
    domain=Domain.DBT,
    question="Which models write to the orders table?",
    expected="stg_orders → int_orders → fct_orders",
    context={"dbt_manifest_excerpt": {...}},
)

result = suite.run(your_ai_function)

# CI assertions — both call sys.exit(1) on failure
suite.assert_no_regressions(result)
suite.assert_pass_rate(result, minimum=0.80)
```

---

## Real data connectors

PipeProbe can read your actual data infrastructure as test context:

```python
from pipeprobe.connectors.dbt_connector import DbtConnector
from pipeprobe.connectors.airflow_connector import AirflowConnector
from pipeprobe.connectors.spark_analyzer import SparkAnalyzer

# Read real dbt manifest — no fake context
dbt     = DbtConnector("./dbt_project")
context = dbt.get_lineage("fct_orders")    # real lineage from manifest.json

# Parse real Airflow DAGs
airflow = AirflowConnector("/opt/airflow/dags")
context = airflow.get_dag_context("orders_daily")

# Analyze real PySpark jobs
spark   = SparkAnalyzer("jobs/orders_aggregation.py")
context = spark.get_job_context()           # detects collect() anti-patterns
```

---

## GitHub Actions — CI/CD blocking

```yaml
# .github/workflows/pipeprobe.yml
- name: Run PipeProbe
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  run: pipeprobe run probes/dbt_rag.yaml --html
  # Exit code 1 on regression → blocks merge automatically

- name: Comment on PR
  # Posts score table + regression diff as PR comment
  # See .github/workflows/pipeprobe-ci.yml for full config
```

**What the PR comment looks like:**

```
✅ PipeProbe Results

| Metric      | Value    |
|-------------|----------|
| Pass rate   | 100.0%   |
| Avg score   | 0.871    |
| Passed      | 4 / 4    |
| Regressions | 🟢 0     |

✅ No regressions detected.
```

---

## Slack alerts

```python
# In your CI or suite file:
from pipeprobe.reporters.slack_notifier import SlackNotifier

notifier = SlackNotifier(
    channel="#data-ai-alerts",
    notify_on="regression_only"  # "always" | "failure_only" | "regression_only"
)
notifier.post_result(suite_result)
```

Set `SLACK_WEBHOOK_URL` in your environment or GitHub Actions secrets.

---

## Architecture

```
pipeprobe/
├── pipeprobe/
│   ├── models.py              ← TestCase, TestResult, SuiteResult, MetricScore
│   ├── suite.py               ← Suite runner + YAML loader
│   ├── cli.py                 ← pipeprobe run / diff / history / init
│   ├── judges/
│   │   ├── base.py            ← BaseJudge interface
│   │   ├── prompts.py         ← shared prompts (identical across providers)
│   │   ├── claude_judge.py    ← Anthropic Claude judge
│   │   └── openai_judge.py    ← OpenAI judge (same prompts = comparable scores)
│   ├── connectors/
│   │   ├── dbt_connector.py       ← reads manifest.json, lineage, failing tests
│   │   ├── airflow_connector.py   ← parses DAGs, validates generated code
│   │   ├── snowflake_connector.py ← schema, slow queries, null stats
│   │   └── spark_analyzer.py      ← AST analysis, anti-pattern detection
│   ├── metrics/
│   │   └── sql_metrics.py     ← AST-level SQL validity + optimization scoring
│   └── reporters/
│       ├── regression_tracker.py  ← run history + regression detection + diff
│       ├── terminal_reporter.py   ← Rich terminal output with regression table
│       ├── html_reporter.py       ← self-contained HTML report with diff section
│       └── slack_notifier.py      ← Slack webhook + bot token support
├── probes/
│   └── dbt_rag.yaml           ← example YAML suite (ready to run)
├── tests/
│   └── test_pipeprobe.py      ← 24 unit tests, no API key needed
└── .github/workflows/
    └── pipeprobe-ci.yml       ← full CI with PR comments + Slack
```

---

## Roadmap

- [ ] `pipeprobe compare run-a run-b` — compare any two specific runs
- [ ] Score trend dashboard (Streamlit)
- [ ] Gemini judge support
- [ ] pytest plugin (`@pipeprobe.mark.probe`)
- [ ] `pipeprobe watch` — run suite on every file change

---

## Contributing

```bash
git clone https://github.com/yourusername/pipeprobe
cd pipeprobe
pip install -e ".[dev]"
pre-commit install
pytest tests/ -v
```

---

## License

MIT

---

<div align="center">
<sub>Built by a senior data engineer who got tired of deploying AI updates and having no idea if quality got worse.</sub>
</div>
