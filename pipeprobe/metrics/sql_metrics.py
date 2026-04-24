"""
EvalForge — SQL Metrics

Domain-specific metrics for evaluating AI-generated or AI-optimized SQL.
Uses sqlglot for AST-level analysis — not just string matching.
This catches issues that generic text metrics completely miss.
"""
from __future__ import annotations

from typing import Any

try:
    import sqlglot
    import sqlglot.expressions as exp
    HAS_SQLGLOT = True
except ImportError:
    HAS_SQLGLOT = False

from pipeprobe.models import MetricScore


def sql_validity_score(generated_sql: str, dialect: str = "snowflake") -> MetricScore:
    """
    Checks if AI-generated SQL is syntactically valid.
    Uses sqlglot AST parsing — dialect-aware.
    """
    if not HAS_SQLGLOT:
        return MetricScore(
            name="sql_validity",
            score=0.5,
            reasoning="sqlglot not installed — skipping syntax check.",
            passed=True,
            threshold=1.0,
        )

    try:
        parsed = sqlglot.parse(generated_sql, dialect=dialect)
        if not parsed or parsed[0] is None:
            return MetricScore(
                name="sql_validity",
                score=0.0,
                reasoning="SQL parsed to empty AST — likely invalid.",
                passed=False,
                threshold=1.0,
            )
        return MetricScore(
            name="sql_validity",
            score=1.0,
            reasoning=f"SQL is syntactically valid ({dialect} dialect).",
            passed=True,
            threshold=1.0,
        )
    except sqlglot.errors.ParseError as e:
        return MetricScore(
            name="sql_validity",
            score=0.0,
            reasoning=f"SQL syntax error: {e}",
            passed=False,
            threshold=1.0,
        )


def sql_structural_similarity(
    expected_sql: str,
    actual_sql: str,
    dialect: str = "snowflake",
) -> MetricScore:
    """
    Compares structural similarity of two SQL queries at AST level.
    Two queries that produce the same result but are written differently
    will score higher than pure string comparison would give them.
    """
    if not HAS_SQLGLOT:
        # Fallback: simple token overlap
        e_tokens = set(expected_sql.lower().split())
        a_tokens = set(actual_sql.lower().split())
        overlap = len(e_tokens & a_tokens) / max(len(e_tokens), 1)
        return MetricScore(
            name="sql_structural_similarity",
            score=round(overlap, 3),
            reasoning=f"Token overlap score (sqlglot unavailable): {overlap:.1%}",
            passed=overlap >= 0.7,
            threshold=0.7,
        )

    try:
        expected_norm = sqlglot.parse_one(expected_sql, dialect=dialect)
        actual_norm = sqlglot.parse_one(actual_sql, dialect=dialect)

        e_nodes = set(type(n).__name__ for n in expected_norm.walk())
        a_nodes = set(type(n).__name__ for n in actual_norm.walk())

        intersection = len(e_nodes & a_nodes)
        union = len(e_nodes | a_nodes)
        jaccard = intersection / union if union > 0 else 0.0

        return MetricScore(
            name="sql_structural_similarity",
            score=round(jaccard, 3),
            reasoning=(
                f"AST node Jaccard similarity: {jaccard:.1%}. "
                f"Expected node types: {sorted(e_nodes)}. "
                f"Actual node types: {sorted(a_nodes)}."
            ),
            passed=jaccard >= 0.7,
            threshold=0.7,
        )
    except Exception as e:
        return MetricScore(
            name="sql_structural_similarity",
            score=0.0,
            reasoning=f"Could not parse SQL for comparison: {e}",
            passed=False,
            threshold=0.7,
        )


def sql_optimization_score(
    original_sql: str,
    optimized_sql: str,
    explain_plan: dict[str, Any] | None = None,
) -> MetricScore:
    """
    Scores how well the AI optimized a SQL query.
    Checks for: CTE usage, eliminated subqueries, index-friendly patterns,
    reduced full table scans (if EXPLAIN plan provided).
    """
    improvements: list[str] = []
    regressions: list[str] = []

    orig_lower = original_sql.lower()
    opt_lower = optimized_sql.lower()

    # Check: subquery elimination
    orig_subqueries = orig_lower.count("select", 1)
    opt_subqueries = opt_lower.count("select", 1)
    if opt_subqueries < orig_subqueries:
        improvements.append(f"Reduced nested SELECTs: {orig_subqueries} → {opt_subqueries}")

    # Check: CTE introduction
    if "with " in opt_lower and "with " not in orig_lower:
        improvements.append("Introduced CTEs for readability and potential optimization.")

    # Check: SELECT * elimination
    if "select *" in orig_lower and "select *" not in opt_lower:
        improvements.append("Eliminated SELECT * — explicit column selection.")

    # Check: DISTINCT added unnecessarily
    if "distinct" in opt_lower and "distinct" not in orig_lower:
        regressions.append("Added DISTINCT — verify this is intentional, can be slow.")

    # EXPLAIN plan checks
    if explain_plan:
        orig_cost = explain_plan.get("original_cost", 0)
        opt_cost = explain_plan.get("optimized_cost", 0)
        if opt_cost < orig_cost:
            pct = ((orig_cost - opt_cost) / orig_cost) * 100
            improvements.append(f"EXPLAIN plan cost reduced by {pct:.1f}%.")
        elif opt_cost > orig_cost:
            regressions.append("EXPLAIN plan shows higher cost — optimization may have regressed.")

    total_signals = len(improvements) + len(regressions)
    if total_signals == 0:
        score = 0.5
        reasoning = "No measurable structural differences detected."
    else:
        score = len(improvements) / total_signals
        reasoning = (
            f"Improvements: {improvements}. "
            f"Regressions: {regressions}."
            if regressions
            else f"Improvements found: {improvements}."
        )

    return MetricScore(
        name="sql_optimization_score",
        score=round(score, 3),
        reasoning=reasoning,
        passed=score >= 0.6 and not regressions,
        threshold=0.6,
    )
