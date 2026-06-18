"""DataSource plugin system — DuckDB, MySQL, PostgreSQL, ClickHouse, Hive, Presto, Spark, Doris.

All data sources implement the same interface: execute SQL → return columns + rows.
Supports multi-source management via DataSourceManager.
"""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass, field
from typing import Any

import duckdb


# ── Data Models ──

@dataclass
class TableInfo:
    """Table metadata."""
    name: str
    schema: str = ""
    type: str = "table"  # table / view / etc.
    comment: str = ""
    row_count: int | None = None


@dataclass
class ColumnInfo:
    """Column metadata."""
    name: str
    type: str
    nullable: bool = True
    default: str | None = None
    comment: str = ""


@dataclass
class DataSourceConfig:
    """Configuration for a data source."""
    name: str
    type: str  # duckdb / mysql / postgresql / clickhouse / hive / presto / spark / doris
    description: str = ""
    # Connection params (used by relational sources)
    host: str = ""
    port: int = 0
    database: str = ""
    username: str = ""
    password: str = ""
    # For DuckDB
    url: str = ""
    schema: str = "main"
    # Extra options
    extra: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict:
        """Return config dict without password."""
        d = {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "username": self.username,
            "url": self.url,
            "schema": self.schema,
        }
        return d


# ── Abstract DataSource ──

class DataSource(abc.ABC):
    """Abstract data source — execute SQL and return structured results."""

    @abc.abstractmethod
    async def execute(self, sql: str) -> dict[str, Any]:
        """Execute SQL, return {"columns": [...], "rows": [...]}."""
        ...

    @abc.abstractmethod
    async def list_tables(self) -> list[TableInfo]:
        """List available tables."""
        ...

    @abc.abstractmethod
    async def describe_table(self, table_name: str) -> list[ColumnInfo]:
        """Describe a table's schema."""
        ...

    @abc.abstractmethod
    async def get_table_stats(self, table_name: str) -> dict:
        """Get table statistics (row count, size, etc.)."""
        ...

    @abc.abstractmethod
    def dialect(self) -> str:
        """Return SQL dialect identifier."""
        ...


# ── DuckDB Implementation ──

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

    async def list_tables(self) -> list[TableInfo]:
        result = self.conn.execute("SHOW TABLES").fetchall()
        return [TableInfo(name=r[0]) for r in result]

    async def describe_table(self, table_name: str) -> list[ColumnInfo]:
        result = self.conn.execute(f"DESCRIBE {table_name}").fetchall()
        return [ColumnInfo(name=r[0], type=r[1]) for r in result]

    async def get_table_stats(self, table_name: str) -> dict:
        try:
            count_result = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
            row_count = count_result[0] if count_result else 0
        except Exception:
            row_count = None
        return {"table": table_name, "row_count": row_count}

    def dialect(self) -> str:
        return "duckdb"


# ── Factory: create DataSource from config ──

def create_datasource(config: DataSourceConfig) -> DataSource:
    """Create a DataSource instance from config."""
    source_type = config.type.lower()

    if source_type == "duckdb":
        db_path = config.url or ":memory:"
        return DuckDBDataSource(db_path, config.schema)

    elif source_type == "mysql":
        from app.application.datasources.mysql_impl import MySQLDataSource
        return MySQLDataSource(
            host=config.host, port=config.port or 3306,
            database=config.database, username=config.username,
            password=config.password,
        )

    elif source_type == "doris":
        from app.application.datasources.doris import DorisDataSource
        return DorisDataSource(
            host=config.host, port=config.port or 9030,
            database=config.database, username=config.username,
            password=config.password,
        )

    elif source_type == "postgresql":
        from app.application.datasources.postgresql_impl import PostgreSQLDataSource
        return PostgreSQLDataSource(
            host=config.host, port=config.port or 5432,
            database=config.database, username=config.username,
            password=config.password,
        )

    elif source_type == "clickhouse":
        from app.application.datasources.clickhouse_impl import ClickHouseDataSource
        return ClickHouseDataSource(
            host=config.host, port=config.port or 8123,
            database=config.database, username=config.username,
            password=config.password,
        )

    elif source_type == "hive":
        from app.application.datasources.hive import HiveDataSource
        return HiveDataSource(
            host=config.host, port=config.port or 10000,
            database=config.database or "default",
            username=config.username,
        )

    elif source_type == "presto":
        from app.application.datasources.presto import PrestoDataSource
        return PrestoDataSource(
            host=config.host, port=config.port or 8080,
            catalog=config.extra.get("catalog", "hive"),
            schema=config.database or "default",
            username=config.username,
        )

    elif source_type == "spark":
        from app.application.datasources.spark import SparkDataSource
        return SparkDataSource(
            host=config.host, port=config.port or 10000,
            database=config.database or "default",
            username=config.username,
        )

    else:
        raise ValueError(f"Unknown datasource type: {source_type}")


# ── Backward-compatible singleton accessor ──

_datasource: DataSource | None = None


def get_datasource() -> DataSource:
    """Get the default (first) datasource — backward compat."""
    global _datasource
    if _datasource is None:
        from app.application.datasources.manager import get_manager
        mgr = get_manager()
        sources = mgr.list_sources()
        if sources:
            _datasource = mgr.get_source(sources[0]["name"])
        else:
            # Fallback to DuckDB demo
            _datasource = DuckDBDataSource(":memory:", "main")
    return _datasource
