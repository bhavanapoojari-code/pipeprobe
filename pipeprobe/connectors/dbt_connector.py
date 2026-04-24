"""
EvalForge — dbt Connector

Reads a real dbt project (manifest.json, schema.yml) and exposes it
as structured context for eval cases. This is what makes EvalForge
domain-aware — it knows your actual models, tests, and lineage.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DbtConnector:
    """
    Reads dbt project metadata and builds eval context.

    Parameters
    ----------
    project_dir:
        Path to the dbt project root (contains dbt_project.yml).
    manifest_path:
        Path to manifest.json. Defaults to target/manifest.json.

    Examples
    --------
    >>> connector = DbtConnector("/path/to/dbt/project")
    >>> context = connector.get_model_context("fct_orders")
    >>> # Use context in EvalCase for grounded evaluation
    """

    def __init__(
        self,
        project_dir: str | Path,
        manifest_path: str | Path | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.manifest_path = (
            Path(manifest_path)
            if manifest_path
            else self.project_dir / "target" / "manifest.json"
        )
        self._manifest: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self.manifest_path.exists():
            with open(self.manifest_path) as f:
                self._manifest = json.load(f)

    # ── Public API ─────────────────────────────────────────────────────────

    def get_model_context(self, model_name: str) -> dict[str, Any]:
        """
        Return structured context for a dbt model — used in EvalCase.context.
        Includes SQL, upstream models, tests, and column descriptions.
        """
        node = self._find_node(model_name)
        if not node:
            return {"error": f"Model '{model_name}' not found in manifest."}

        return {
            "model_name": model_name,
            "schema": node.get("schema"),
            "database": node.get("database"),
            "raw_sql": node.get("raw_code", node.get("raw_sql", "")),
            "compiled_sql": node.get("compiled_code", node.get("compiled_sql", "")),
            "description": node.get("description", ""),
            "columns": node.get("columns", {}),
            "upstream_models": self._get_upstream(node),
            "downstream_models": self._get_downstream(model_name),
            "tests": self._get_tests(model_name),
            "tags": node.get("tags", []),
            "materialized": node.get("config", {}).get("materialized", "view"),
        }

    def get_lineage(self, model_name: str, depth: int = 3) -> dict[str, Any]:
        """
        Return lineage graph up to `depth` levels for a model.
        Used in lineage-tracing eval cases.
        """
        visited: set[str] = set()
        graph: dict[str, list[str]] = {}
        self._build_lineage(model_name, depth, visited, graph)
        return {
            "root": model_name,
            "depth": depth,
            "graph": graph,
        }

    def list_models(self) -> list[str]:
        """All model names in the project."""
        return [
            node["name"]
            for node in self._manifest.get("nodes", {}).values()
            if node.get("resource_type") == "model"
        ]

    def get_all_tests(self) -> list[dict[str, Any]]:
        """All dbt tests with their attached models."""
        tests = []
        for node in self._manifest.get("nodes", {}).values():
            if node.get("resource_type") == "test":
                tests.append({
                    "test_name": node.get("name"),
                    "attached_model": node.get("attached_node", "").split(".")[-1],
                    "column": node.get("column_name"),
                    "test_type": node.get("test_metadata", {}).get("name"),
                })
        return tests

    def get_failing_tests(self) -> list[dict[str, Any]]:
        """
        Returns tests that failed in the last dbt test run.
        Reads from target/run_results.json.
        """
        results_path = self.project_dir / "target" / "run_results.json"
        if not results_path.exists():
            return []

        with open(results_path) as f:
            run_results = json.load(f)

        failing = []
        for result in run_results.get("results", []):
            if result.get("status") in ("fail", "error"):
                unique_id = result.get("unique_id", "")
                node = self._manifest.get("nodes", {}).get(unique_id, {})
                failing.append({
                    "test_id": unique_id,
                    "test_name": node.get("name", unique_id.split(".")[-1]),
                    "status": result.get("status"),
                    "message": result.get("message", ""),
                    "attached_model": node.get("attached_node", "").split(".")[-1],
                    "failures": result.get("failures", 0),
                })
        return failing

    # ── Internal helpers ───────────────────────────────────────────────────

    def _find_node(self, model_name: str) -> dict[str, Any] | None:
        for node in self._manifest.get("nodes", {}).values():
            if node.get("resource_type") == "model" and node.get("name") == model_name:
                return node
        return None

    def _get_upstream(self, node: dict[str, Any]) -> list[str]:
        return [
            dep.split(".")[-1]
            for dep in node.get("depends_on", {}).get("nodes", [])
            if "model" in dep
        ]

    def _get_downstream(self, model_name: str) -> list[str]:
        downstream = []
        for node in self._manifest.get("nodes", {}).values():
            if node.get("resource_type") == "model":
                deps = [
                    d.split(".")[-1]
                    for d in node.get("depends_on", {}).get("nodes", [])
                ]
                if model_name in deps:
                    downstream.append(node["name"])
        return downstream

    def _get_tests(self, model_name: str) -> list[dict[str, Any]]:
        tests = []
        for node in self._manifest.get("nodes", {}).values():
            if (
                node.get("resource_type") == "test"
                and model_name in node.get("attached_node", "")
            ):
                tests.append({
                    "name": node.get("name"),
                    "column": node.get("column_name"),
                    "type": node.get("test_metadata", {}).get("name"),
                })
        return tests

    def _build_lineage(
        self,
        model_name: str,
        depth: int,
        visited: set[str],
        graph: dict[str, list[str]],
    ) -> None:
        if depth == 0 or model_name in visited:
            return
        visited.add(model_name)
        node = self._find_node(model_name)
        if not node:
            return
        upstream = self._get_upstream(node)
        graph[model_name] = upstream
        for parent in upstream:
            self._build_lineage(parent, depth - 1, visited, graph)
