"""
EvalForge — Snowflake Connector

Reads real Snowflake schema metadata and query history as eval context.
Enables evaluation of AI systems that answer questions about your data warehouse —
table structures, column lineage, slow queries, and warehouse usage.
"""
from __future__ import annotations

from typing import Any


class SnowflakeConnector:
    """
    Connects to Snowflake and exposes schema + query history as eval context.

    Parameters
    ----------
    account, user, password, warehouse, database, schema:
        Standard Snowflake connection parameters.
    role:
        Snowflake role to use. Defaults to current session role.

    Examples
    --------
    >>> connector = SnowflakeConnector(
    ...     account="myorg-myaccount",
    ...     user="pipeprobe_user",
    ...     password="...",
    ...     warehouse="COMPUTE_WH",
    ...     database="ANALYTICS",
    ...     schema="PUBLIC",
    ... )
    >>> context = connector.get_table_context("FCT_ORDERS")
    """

    def __init__(
        self,
        account: str,
        user: str,
        password: str,
        warehouse: str,
        database: str,
        schema: str = "PUBLIC",
        role: str | None = None,
    ) -> None:
        self.account = account
        self.user = user
        self.warehouse = warehouse
        self.database = database
        self.schema = schema
        self.role = role
        self._conn: Any = None
        self._connect(password)

    def _connect(self, password: str) -> None:
        try:
            import snowflake.connector
            self._conn = snowflake.connector.connect(
                account=self.account,
                user=self.user,
                password=password,
                warehouse=self.warehouse,
                database=self.database,
                schema=self.schema,
                **({"role": self.role} if self.role else {}),
            )
        except ImportError:
            raise ImportError(
                "Install snowflake support: pip install pipeprobe[snowflake]"
            )

    def _query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        cursor = self._conn.cursor()
        cursor.execute(sql, params)
        cols = [desc[0].lower() for desc in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    # ── Public API ─────────────────────────────────────────────────────────

    def get_table_context(self, table_name: str) -> dict[str, Any]:
        """
        Return column metadata for a table — used in EvalCase.context.
        Includes column names, types, nullable flags, and row count.
        """
        columns = self._query(
            """
            SELECT column_name, data_type, is_nullable, character_maximum_length,
                   numeric_precision, numeric_scale, column_default, comment
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (self.schema.upper(), table_name.upper()),
        )

        row_count = self._query(
            f"SELECT COUNT(*) AS cnt FROM {self.database}.{self.schema}.{table_name}"
        )

        return {
            "table": f"{self.database}.{self.schema}.{table_name}",
            "columns": columns,
            "row_count": row_count[0]["cnt"] if row_count else 0,
            "database": self.database,
            "schema": self.schema,
        }

    def get_slow_queries(
        self,
        days: int = 7,
        min_duration_seconds: float = 10.0,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Return recent slow queries from QUERY_HISTORY.
        Used in eval cases testing SQL diagnosis and optimization.
        """
        return self._query(
            """
            SELECT query_id, query_text, total_elapsed_time / 1000 AS duration_seconds,
                   bytes_scanned, rows_produced, warehouse_name, start_time,
                   error_message
            FROM snowflake.account_usage.query_history
            WHERE start_time >= DATEADD(day, %s, CURRENT_TIMESTAMP())
              AND total_elapsed_time / 1000 >= %s
              AND execution_status = 'SUCCESS'
            ORDER BY total_elapsed_time DESC
            LIMIT %s
            """,
            (-days, min_duration_seconds, limit),
        )

    def get_warehouse_usage(self, days: int = 30) -> list[dict[str, Any]]:
        """Return warehouse credit usage over the past N days."""
        return self._query(
            """
            SELECT warehouse_name,
                   SUM(credits_used) AS total_credits,
                   COUNT(*) AS query_count,
                   AVG(total_elapsed_time) / 1000 AS avg_duration_seconds
            FROM snowflake.account_usage.query_history
            WHERE start_time >= DATEADD(day, %s, CURRENT_TIMESTAMP())
            GROUP BY warehouse_name
            ORDER BY total_credits DESC
            """,
            (-days,),
        )

    def get_null_stats(self, table_name: str) -> dict[str, Any]:
        """
        Compute null rates for every column in a table.
        Used in eval cases testing data quality diagnosis.
        """
        columns = self._query(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (self.schema.upper(), table_name.upper()),
        )

        null_checks = ", ".join(
            f"SUM(CASE WHEN {col['column_name']} IS NULL THEN 1 ELSE 0 END) AS {col['column_name']}_nulls"
            for col in columns
        )

        total = self._query(
            f"SELECT COUNT(*) AS cnt FROM {self.database}.{self.schema}.{table_name}"
        )[0]["cnt"]

        if total == 0 or not columns:
            return {"table": table_name, "total_rows": 0, "null_rates": {}}

        null_counts = self._query(
            f"SELECT {null_checks} FROM {self.database}.{self.schema}.{table_name}"
        )[0]

        null_rates = {
            col["column_name"]: round(
                null_counts.get(f"{col['column_name']}_nulls", 0) / total, 4
            )
            for col in columns
        }

        return {
            "table": f"{self.database}.{self.schema}.{table_name}",
            "total_rows": total,
            "null_rates": null_rates,
            "high_null_columns": {
                col: rate for col, rate in null_rates.items() if rate > 0.05
            },
        }

    def close(self) -> None:
        if self._conn:
            self._conn.close()

    def __enter__(self) -> "SnowflakeConnector":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
