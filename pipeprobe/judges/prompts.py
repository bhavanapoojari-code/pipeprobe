"""
PipeProbe — Shared judge prompts.
Both Claude and OpenAI judges use identical prompts so scores are comparable
when you switch providers. Consistency is the whole point.
"""
from __future__ import annotations
from pipeprobe.models import Domain

SYSTEM_BASE = """You are PipeProbe, a strict evaluation judge for AI systems
built on data infrastructure. You have deep expertise in:
- dbt (models, lineage, manifest.json, tests, schema.yml)
- Apache Airflow (DAGs, operators, task dependencies, schedules)
- SQL (query correctness, EXPLAIN plans, optimisation patterns)
- Apache Spark (PySpark jobs, transformations, performance anti-patterns)
- Snowflake / BigQuery data warehouses

You score responses objectively. You always return valid JSON only —
no markdown fences, no commentary outside the JSON object."""

DOMAIN_HINTS: dict[Domain, str] = {
    Domain.DBT:
        "Penalise wrong model names, incorrect lineage order, hallucinated column names.",
    Domain.AIRFLOW:
        "Penalise wrong task order, missing retries, hallucinated operator names.",
    Domain.SQL:
        "Penalise syntax errors, incorrect joins, missed optimisation opportunities.",
    Domain.SNOWFLAKE:
        "Penalise incorrect Snowflake-specific syntax, wrong warehouse sizing advice.",
    Domain.SPARK:
        "Penalise wrong action vs transformation distinction, missed shuffle issues.",
    Domain.GENERIC:
        "Focus on factual accuracy and completeness.",
}

METRICS = {
    "faithfulness": (
        "Does the answer use ONLY information from the provided context? "
        "1.0 = zero hallucination. 0.0 = major fabricated technical facts."
    ),
    "correctness": (
        "Is the answer technically accurate vs the expected answer? "
        "1.0 = fully correct. 0.0 = factually wrong."
    ),
    "domain_relevance": (
        "Does the answer show genuine domain expertise (dbt/Airflow/SQL/Spark)? "
        "1.0 = deep expertise. 0.0 = generic non-answer."
    ),
    "actionability": (
        "Can a data engineer act on this immediately? "
        "1.0 = exact file/model/column + clear fix. 0.0 = vague with no path forward."
    ),
}


def build_system(domain: Domain) -> str:
    hint = DOMAIN_HINTS.get(domain, DOMAIN_HINTS[Domain.GENERIC])
    return f"{SYSTEM_BASE}\n\nDomain focus: {hint}"


def build_user(case: object, actual: str, metrics: list[str]) -> str:  # type: ignore[type-arg]
    import json
    rubrics = "\n".join(
        f"[{name}] {desc}"
        for name, desc in METRICS.items()
        if name in metrics
    )
    ctx = json.dumps(case.context, indent=2) if case.context else "none"  # type: ignore[union-attr]
    metric_keys = {m: {"score": 0.0, "reasoning": "..."} for m in metrics}
    return f"""
QUESTION asked to AI system:
{case.question}

EXPECTED answer:
{case.expected}

ACTUAL answer from AI system:
{actual}

CONTEXT available to AI system:
{ctx}

SCORING RUBRICS:
{rubrics}

Return ONLY this JSON (no markdown, no extra text):
{{
  "scores": {json.dumps(metric_keys, indent=2)},
  "summary": "one sentence overall assessment"
}}
Scores are floats 0.0–1.0.
"""
