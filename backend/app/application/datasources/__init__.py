"""DataSource plugin system — DuckDB, MySQL, PostgreSQL, ClickHouse.

All data sources implement the same interface: execute SQL → return columns + rows.
"""

from __future__ import annotations

import abc
import json
from typing import Any

import duckdb


class DataSource(abc.ABC):
    """Abstract data source — execute SQL and return structured results."""

    @abc.abstractmethod
    async def execute(self, sql: str) -> dict[str, Any]:
        """Execute SQL, return {"columns": [...], "rows": [...]}."""
        ...

    @abc.abstractmethod
    async def list_tables(self) -> list[str]:
        """List available tables."""
        ...

    @abc.abstractmethod
    async def describe_table(self, table_name: str) -> list[dict[str, str]]:
        """Describe a table's schema."""
        ...


class DuckDBDataSource(DataSource):
    """Embedded DuckDB — zero-config, file-based OLAP."""

    def __init__(self, db_path: str = ":memory:", schema: str = "main"):
        self._db_path = db_path
        self._schema = schema
        self._conn: duckdb.DuckDBPyConnection | None = None

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(self._db_path)
            if self._db_path == ":memory:":
                self._load_demo_data()
        return self._conn

    def _load_demo_data(self):
        """Load demo e-commerce dataset for first-run experience."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS orders AS
            SELECT * FROM (VALUES
                ('杭州', '2025-06-01', 12500, 320, 2.1),
                ('上海', '2025-06-01', 18200, 450, 1.8),
                ('北京', '2025-06-01', 15800, 380, 2.3),
                ('广州', '2025-06-01', 9600, 220, 2.5),
                ('深圳', '2025-06-01', 14200, 340, 2.0),
                ('杭州', '2025-06-02', 13100, 330, 2.0),
                ('上海', '2025-06-02', 17500, 430, 1.9),
                ('北京', '2025-06-02', 14900, 360, 2.2),
                ('广州', '2025-06-02', 10100, 240, 2.4),
                ('深圳', '2025-06-02', 13800, 325, 2.1),
                ('杭州', '2025-06-03', 14200, 350, 1.9),
                ('上海', '2025-06-03', 19000, 460, 1.7),
                ('北京', '2025-06-03', 16100, 390, 2.1),
                ('广州', '2025-06-03', 10500, 250, 2.3),
                ('深圳', '2025-06-03', 14500, 345, 2.0)
            ) AS t(city, dt, gmv, order_count, avg_delay_days)
        """)

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS routes AS
            SELECT * FROM (VALUES
                ('杭州-宁波', 500, 225, 0.45, '2025-06-15'),
                ('上海-苏州', 600, 312, 0.52, '2025-06-15'),
                ('北京-天津', 400, 280, 0.70, '2025-06-15'),
                ('广州-深圳', 550, 440, 0.80, '2025-06-15'),
                ('杭州-上海', 700, 560, 0.80, '2025-06-15'),
                ('成都-重庆', 450, 180, 0.40, '2025-06-15'),
                ('武汉-长沙', 500, 260, 0.52, '2025-06-15'),
                ('南京-合肥', 350, 140, 0.40, '2025-06-15')
            ) AS t(route, capacity, actual, load_rate, dt)
        """)

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sort_center AS
            SELECT * FROM (VALUES
                ('杭州分拣中心', 25600),
                ('上海分拣中心', 31200),
                ('南京分拣中心', 18400),
                ('广州分拣中心', 19800),
                ('北京分拣中心', 22500)
            ) AS t(center_name, volume)
        """)

    async def execute(self, sql: str) -> dict[str, Any]:
        result = self.conn.execute(sql)
        columns = [d[0] for d in result.description]
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
        return {"columns": [{"name": c} for c in columns], "rows": rows}

    async def list_tables(self) -> list[str]:
        result = self.conn.execute("SHOW TABLES").fetchall()
        return [r[0] for r in result]

    async def describe_table(self, table_name: str) -> list[dict[str, str]]:
        result = self.conn.execute(f"DESCRIBE {table_name}").fetchall()
        return [{"name": r[0], "type": r[1]} for r in result]


class MySQLDataSource(DataSource):
    """MySQL data source (async via aiomysql)."""

    def __init__(self, url: str):
        self._url = url

    async def execute(self, sql: str) -> dict[str, Any]:
        raise NotImplementedError("MySQL plugin requires `pip install chatsql[mysql]`")

    async def list_tables(self) -> list[str]:
        raise NotImplementedError

    async def describe_table(self, table_name: str) -> list[dict[str, str]]:
        raise NotImplementedError


class PostgreSQLDataSource(DataSource):
    """PostgreSQL data source."""

    def __init__(self, url: str):
        self._url = url

    async def execute(self, sql: str) -> dict[str, Any]:
        raise NotImplementedError("PostgreSQL plugin requires `pip install chatsql[postgresql]`")

    async def list_tables(self) -> list[str]:
        raise NotImplementedError

    async def describe_table(self, table_name: str) -> list[dict[str, str]]:
        raise NotImplementedError


class ClickHouseDataSource(DataSource):
    """ClickHouse data source."""

    def __init__(self, url: str):
        self._url = url

    async def execute(self, sql: str) -> dict[str, Any]:
        raise NotImplementedError("ClickHouse plugin requires `pip install chatsql[clickhouse]`")

    async def list_tables(self) -> list[str]:
        raise NotImplementedError

    async def describe_table(self, table_name: str) -> list[dict[str, str]]:
        raise NotImplementedError


# ── Factory ──

_datasource: DataSource | None = None


def get_datasource() -> DataSource:
    global _datasource
    if _datasource is None:
        from app.config import get_settings
        s = get_settings()
        if s.datasource_type == "duckdb":
            db_path = s.datasource_url or ":memory:"
            _datasource = DuckDBDataSource(db_path, s.datasource_schema)
        elif s.datasource_type == "mysql":
            _datasource = MySQLDataSource(s.datasource_url)
        elif s.datasource_type == "postgresql":
            _datasource = PostgreSQLDataSource(s.datasource_url)
        elif s.datasource_type == "clickhouse":
            _datasource = ClickHouseDataSource(s.datasource_url)
        else:
            raise ValueError(f"Unknown datasource type: {s.datasource_type}")
    return _datasource
