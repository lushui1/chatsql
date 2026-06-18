"""Presto data source implementation using PyHive."""

from __future__ import annotations

from typing import Any

from app.application.datasources import ColumnInfo, DataSource, TableInfo


class PrestoDataSource(DataSource):
    """Presto/Trino data source via PyHive."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8080,
        catalog: str = "hive",
        schema: str = "default",
        username: str = "",
    ):
        self._host = host
        self._port = port
        self._catalog = catalog
        self._schema = schema
        self._username = username
        self._conn = None

    def _get_conn(self):
        if self._conn is None:
            try:
                from pyhive import presto
            except ImportError as e:
                raise RuntimeError(
                    "Presto data source requires `pip install pyhive`. "
                    f"Original error: {e}"
                ) from e
            self._conn = presto.connect(
                host=self._host,
                port=self._port,
                catalog=self._catalog,
                schema=self._schema,
                username=self._username,
            )
        return self._conn

    async def execute(self, sql: str) -> dict[str, Any]:
        import asyncio
        conn = self._get_conn()
        def _run():
            cur = conn.cursor()
            cur.execute(sql)
            if cur.description:
                columns = [d[0] for d in cur.description]
                rows = [dict(zip(columns, row)) for row in cur.fetchall()]
                return {"columns": [{"name": c} for c in columns], "rows": rows}
            return {"columns": [], "rows": []}
        return await asyncio.get_event_loop().run_in_executor(None, _run)

    async def list_tables(self) -> list[TableInfo]:
        import asyncio
        conn = self._get_conn()
        def _run():
            cur = conn.cursor()
            cur.execute(f"SHOW TABLES FROM {self._schema}")
            return [TableInfo(name=r[0]) for r in cur.fetchall()]
        return await asyncio.get_event_loop().run_in_executor(None, _run)

    async def describe_table(self, table_name: str) -> list[ColumnInfo]:
        import asyncio
        conn = self._get_conn()
        def _run():
            cur = conn.cursor()
            cur.execute(f"DESCRIBE {table_name}")
            return [
                ColumnInfo(name=r[0], type=r[1] if len(r) > 1 else "varchar")
                for r in cur.fetchall()
            ]
        return await asyncio.get_event_loop().run_in_executor(None, _run)

    async def get_table_stats(self, table_name: str) -> dict:
        import asyncio
        conn = self._get_conn()
        def _run():
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM {table_name}")
            row = cur.fetchone()
            return {"table": table_name, "row_count": row[0] if row else None}
        return await asyncio.get_event_loop().run_in_executor(None, _run)

    def dialect(self) -> str:
        return "presto"

    async def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
