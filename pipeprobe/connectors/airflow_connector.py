"""
EvalForge — Airflow Connector

Reads Airflow DAG structure and run logs as eval context.
Enables evaluation of AI systems that diagnose pipeline failures,
explain DAG structure, or generate new DAGs.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


class AirflowConnector:
    """
    Parses Airflow DAG files and run metadata for eval context.

    Parameters
    ----------
    dags_dir:
        Path to Airflow DAGs directory.
    logs_dir:
        Optional path to Airflow logs directory.

    Examples
    --------
    >>> connector = AirflowConnector("/opt/airflow/dags")
    >>> context = connector.get_dag_context("orders_daily")
    """

    def __init__(
        self,
        dags_dir: str | Path,
        logs_dir: str | Path | None = None,
    ) -> None:
        self.dags_dir = Path(dags_dir)
        self.logs_dir = Path(logs_dir) if logs_dir else None

    # ── Public API ─────────────────────────────────────────────────────────

    def get_dag_context(self, dag_id: str) -> dict[str, Any]:
        """
        Parse a DAG file and return structured context for eval cases.
        Extracts: tasks, dependencies, schedule, operators used.
        """
        dag_file = self._find_dag_file(dag_id)
        if not dag_file:
            return {"error": f"DAG '{dag_id}' not found in {self.dags_dir}"}

        source = dag_file.read_text()
        return {
            "dag_id": dag_id,
            "file": str(dag_file),
            "source_code": source,
            "tasks": self._extract_tasks(source),
            "dependencies": self._extract_dependencies(source),
            "schedule": self._extract_schedule(source),
            "operators_used": self._extract_operators(source),
            "imports": self._extract_imports(source),
        }

    def get_failure_context(self, dag_id: str, run_id: str | None = None) -> dict[str, Any]:
        """
        Extract failure context from Airflow logs for a DAG run.
        Used for eval cases testing root-cause diagnosis.
        """
        if not self.logs_dir:
            return {"error": "logs_dir not configured."}

        log_dir = self.logs_dir / dag_id
        if not log_dir.exists():
            return {"error": f"No logs found for DAG '{dag_id}'"}

        logs: list[dict[str, Any]] = []
        for task_dir in sorted(log_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            for attempt_file in sorted(task_dir.glob("*.log")):
                content = attempt_file.read_text(errors="replace")
                if "ERROR" in content or "FAILED" in content or "Exception" in content:
                    logs.append({
                        "task_id": task_dir.name,
                        "log_file": str(attempt_file),
                        "error_lines": self._extract_error_lines(content),
                        "traceback": self._extract_traceback(content),
                    })

        return {
            "dag_id": dag_id,
            "run_id": run_id,
            "failed_tasks": logs,
            "total_failures": len(logs),
        }

    def list_dags(self) -> list[str]:
        """List all DAG IDs found in the DAGs directory."""
        dag_ids = []
        for dag_file in self.dags_dir.glob("**/*.py"):
            content = dag_file.read_text(errors="replace")
            matches = re.findall(r'dag_id\s*=\s*["\']([^"\']+)["\']', content)
            dag_ids.extend(matches)
        return dag_ids

    def validate_generated_dag(self, dag_code: str) -> dict[str, Any]:
        """
        Validates AI-generated DAG code for correctness.
        Used as ground-truth in eval cases testing DAG generation.

        Returns structural validity, syntax errors, and missing best practices.
        """
        issues: list[str] = []
        warnings: list[str] = []

        # Syntax check
        try:
            ast.parse(dag_code)
        except SyntaxError as e:
            return {
                "valid": False,
                "syntax_error": str(e),
                "issues": [f"Syntax error: {e}"],
                "warnings": [],
            }

        # Best practices checks
        if "retries" not in dag_code:
            warnings.append("No retries configured — recommended for production DAGs.")
        if "retry_delay" not in dag_code:
            warnings.append("No retry_delay configured.")
        if "catchup=False" not in dag_code and "catchup = False" not in dag_code:
            warnings.append("catchup not explicitly set to False — may cause backfill.")
        if "owner" not in dag_code:
            warnings.append("No owner set in default_args.")
        if "on_failure_callback" not in dag_code:
            warnings.append("No failure callback — consider adding alerting.")

        # Required patterns
        if "DAG(" not in dag_code and "dag = DAG" not in dag_code:
            issues.append("No DAG definition found.")
        if "schedule" not in dag_code and "schedule_interval" not in dag_code:
            issues.append("No schedule defined.")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "operators_used": self._extract_operators(dag_code),
            "tasks": self._extract_tasks(dag_code),
        }

    # ── Internal helpers ───────────────────────────────────────────────────

    def _find_dag_file(self, dag_id: str) -> Path | None:
        for dag_file in self.dags_dir.glob("**/*.py"):
            content = dag_file.read_text(errors="replace")
            if f'"{dag_id}"' in content or f"'{dag_id}'" in content:
                return dag_file
        return None

    def _extract_tasks(self, source: str) -> list[str]:
        """Extract task IDs from DAG source code."""
        return re.findall(r'task_id\s*=\s*["\']([^"\']+)["\']', source)

    def _extract_dependencies(self, source: str) -> list[str]:
        """Extract >> dependency chains."""
        return re.findall(r'(\w+)\s*>>\s*(\w+)', source)

    def _extract_schedule(self, source: str) -> str:
        match = re.search(
            r'schedule(?:_interval)?\s*=\s*["\']([^"\']+)["\']', source
        )
        return match.group(1) if match else "not found"

    def _extract_operators(self, source: str) -> list[str]:
        return re.findall(r'from airflow\.operators\.\w+ import (\w+)', source)

    def _extract_imports(self, source: str) -> list[str]:
        return re.findall(r'^(?:import|from)\s+.+', source, re.MULTILINE)

    def _extract_error_lines(self, log_content: str) -> list[str]:
        return [
            line.strip()
            for line in log_content.splitlines()
            if any(kw in line for kw in ["ERROR", "FAILED", "Exception", "Traceback"])
        ][:20]  # cap at 20 lines

    def _extract_traceback(self, log_content: str) -> str:
        match = re.search(
            r'(Traceback \(most recent call last\):.*?)(?:\n\n|\Z)',
            log_content,
            re.DOTALL,
        )
        return match.group(1).strip() if match else ""
