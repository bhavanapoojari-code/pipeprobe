"""
EvalForge — Spark Analyzer

Parses PySpark job files and extracts structured metadata as eval context.
Enables evaluation of AI systems that explain, diagnose, or optimize Spark jobs.
No Spark cluster required — pure static analysis using AST parsing.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


class SparkAnalyzer:
    """
    Static analyzer for PySpark job files.

    Parameters
    ----------
    job_path:
        Path to the PySpark .py file to analyze.

    Examples
    --------
    >>> analyzer = SparkAnalyzer("jobs/orders_aggregation.py")
    >>> context = analyzer.get_job_context()
    >>> # Use in EvalCase for Spark explanation/diagnosis evals
    """

    def __init__(self, job_path: str | Path) -> None:
        self.job_path = Path(job_path)
        if not self.job_path.exists():
            raise FileNotFoundError(f"Spark job not found: {job_path}")
        self._source = self.job_path.read_text()
        self._tree = ast.parse(self._source)

    # ── Public API ─────────────────────────────────────────────────────────

    def get_job_context(self) -> dict[str, Any]:
        """
        Return full structured context for a Spark job.
        Used in EvalCase.context for Spark explanation/optimization evals.
        """
        return {
            "job_file": str(self.job_path),
            "source_code": self._source,
            "transformations": self._extract_transformations(),
            "actions": self._extract_actions(),
            "read_sources": self._extract_reads(),
            "write_targets": self._extract_writes(),
            "joins": self._extract_joins(),
            "partitioning": self._extract_partitioning(),
            "schema_definitions": self._extract_schemas(),
            "potential_issues": self._detect_issues(),
            "imports": self._extract_imports(),
        }

    def detect_performance_issues(self) -> list[dict[str, Any]]:
        """
        Detect common PySpark performance anti-patterns.
        Used as ground truth for eval cases testing Spark optimization advice.
        """
        return self._detect_issues()

    def get_lineage_summary(self) -> dict[str, Any]:
        """
        High-level data lineage: what is read, how it flows, what is written.
        """
        return {
            "sources": self._extract_reads(),
            "transformations": self._extract_transformations(),
            "sinks": self._extract_writes(),
        }

    # ── Static analysis ────────────────────────────────────────────────────

    def _extract_transformations(self) -> list[str]:
        """Find all DataFrame transformation method calls."""
        transformation_methods = {
            "select", "filter", "where", "groupBy", "agg", "join", "union",
            "unionAll", "distinct", "dropDuplicates", "withColumn", "drop",
            "orderBy", "sort", "limit", "sample", "explode", "pivot",
            "rollup", "cube", "crossJoin", "broadcast",
        }
        found = []
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Attribute) and node.attr in transformation_methods:
                found.append(node.attr)
        return list(dict.fromkeys(found))  # deduplicated, order preserved

    def _extract_actions(self) -> list[str]:
        """Find Spark actions (things that trigger execution)."""
        action_methods = {
            "collect", "count", "first", "take", "show", "write",
            "save", "saveAsTextFile", "foreach", "foreachPartition",
            "toLocalIterator", "toPandas",
        }
        found = []
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Attribute) and node.attr in action_methods:
                found.append(node.attr)
        return list(dict.fromkeys(found))

    def _extract_reads(self) -> list[dict[str, str]]:
        """Find spark.read calls and their formats/paths."""
        reads = []
        source = self._source
        # spark.read.format(...).load(...)
        for match in re.finditer(
            r'spark\.read\.format\(["\'](\w+)["\']\).*?\.(?:load|table)\(["\']([^"\']+)["\']\)',
            source, re.DOTALL
        ):
            reads.append({"format": match.group(1), "path": match.group(2)})
        # spark.read.parquet/csv/json(...)
        for match in re.finditer(
            r'spark\.read\.(parquet|csv|json|orc|avro)\(["\']([^"\']+)["\']\)',
            source
        ):
            reads.append({"format": match.group(1), "path": match.group(2)})
        # spark.table(...)
        for match in re.finditer(r'spark\.table\(["\']([^"\']+)["\']\)', source):
            reads.append({"format": "table", "path": match.group(1)})
        return reads

    def _extract_writes(self) -> list[dict[str, str]]:
        """Find .write calls and their output formats/paths."""
        writes = []
        for match in re.finditer(
            r'\.write(?:Stream)?\..*?(?:format\(["\'](\w+)["\']\))?.*?'
            r'(?:save|saveAsTable|start)\(["\']?([^"\')\n]*)["\']?\)',
            self._source, re.DOTALL
        ):
            fmt = match.group(1) or "unknown"
            path = match.group(2).strip()
            if path:
                writes.append({"format": fmt, "target": path})
        return writes

    def _extract_joins(self) -> list[dict[str, Any]]:
        """Extract join operations with their types."""
        joins = []
        for match in re.finditer(
            r'\.join\((\w+)(?:,\s*["\']?([^"\']+)["\']?)?(?:,\s*["\'](\w+)["\'])?\)',
            self._source
        ):
            joins.append({
                "right_df": match.group(1),
                "condition": match.group(2) or "unknown",
                "join_type": match.group(3) or "inner",
            })
        return joins

    def _extract_partitioning(self) -> list[dict[str, Any]]:
        """Find repartition/coalesce/partitionBy calls."""
        partitioning = []
        for match in re.finditer(
            r'\.(repartition|coalesce|partitionBy)\(([^)]+)\)', self._source
        ):
            partitioning.append({
                "operation": match.group(1),
                "args": match.group(2).strip(),
            })
        return partitioning

    def _extract_schemas(self) -> list[str]:
        """Find StructType schema definitions."""
        return re.findall(r'StructType\(\[([^\]]+)\]\)', self._source)

    def _extract_imports(self) -> list[str]:
        return [
            ast.unparse(node)
            for node in ast.walk(self._tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]

    def _detect_issues(self) -> list[dict[str, str]]:
        """
        Detect common PySpark anti-patterns.
        Returns list of {issue, severity, suggestion}.
        """
        issues = []
        source = self._source

        if source.count("collect()") > 0:
            issues.append({
                "issue": "collect() called — pulls all data to driver",
                "severity": "high",
                "suggestion": "Use write() or aggregations instead of collect() on large datasets.",
            })

        if "toPandas()" in source:
            issues.append({
                "issue": "toPandas() called — materializes entire DataFrame in memory",
                "severity": "high",
                "suggestion": "Only call toPandas() on small aggregated results, not raw tables.",
            })

        joins = self._extract_joins()
        large_joins = [j for j in joins if "broadcast" not in source.lower()
                       and j["join_type"] in ("inner", "left", "right", "")]
        if len(large_joins) > 2:
            issues.append({
                "issue": f"{len(large_joins)} joins without explicit broadcast hints",
                "severity": "medium",
                "suggestion": "Consider broadcast() for small lookup tables to avoid shuffle joins.",
            })

        if "select('*')" in source or 'select("*")' in source:
            issues.append({
                "issue": "SELECT * used — reads all columns including unused ones",
                "severity": "low",
                "suggestion": "Specify only needed columns to reduce I/O and memory pressure.",
            })

        repartitions = len(re.findall(r'\.repartition\(', source))
        coalesces = len(re.findall(r'\.coalesce\(', source))
        if repartitions > 2:
            issues.append({
                "issue": f"repartition() called {repartitions} times — each causes a full shuffle",
                "severity": "medium",
                "suggestion": "Consolidate repartitions. Consider partitioning at read time instead.",
            })

        if "count()" in source and "cache()" not in source and "persist()" not in source:
            issues.append({
                "issue": "count() called without cache/persist — may recompute the full DAG",
                "severity": "low",
                "suggestion": "Cache the DataFrame before count() if it is used again afterward.",
            })

        return issues
