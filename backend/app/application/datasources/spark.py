"""Spark SQL data source using PyHive (Spark Thrift Server)."""

from __future__ import annotations

from typing import Any

from app.application.datasources import ColumnInfo, DataSource, TableInfo


class SparkDataSource(DataSource):
    """Apache Spark SQL data source via PyHive Thrift interface."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 10000,
        database: str = "default",
        username: str = "",
    ):
        self._host = host
        self._port = port
        self._database = database
        self._username = username
        self._conn = None

    def _get_conn(self):
        if self._conn is None:
            try:
                from pyhive import hive
            except ImportError as e:
                raise RuntimeError(
                    "Spark data source requires `pip install pyhive[sasl]`. "
                    f"Original error: {e}"
                ) from e
            self._conn = hive.connect(
                host=self._host,
                port=self._port,
                database=self._database,
                username=self._username,
            )
        return self._conn

    def _discard_conn(self) -> None:
        """超时后断开连接。

        pyhive 这类 DBAPI 驱动没有中断接口，已提交的查询无法撤回，
        只能断开连接让服务端回收。置 None 是为了下次查询重建连接，
        避免复用一个状态不明的连接。
        """
        conn = self._conn
        self._conn = None
        if conn is None:
            return
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    async def execute(self, sql: str) -> dict[str, Any]:
        from app.application.datasources.query_guard import run_blocking

        conn = self._get_conn()

        def _run():
            cur = conn.cursor()
            cur.execute(sql)
            if cur.description:
                columns = [d[0] for d in cur.description]
                rows = [dict(zip(columns, row)) for row in cur.fetchall()]
                return {"columns": [{"name": c} for c in columns], "rows": rows}
            return {"columns": [], "rows": []}

        return await run_blocking(_run, sql=sql, on_cancel=self._discard_conn)

    async def list_tables(self) -> list[TableInfo]:
        import asyncio
        conn = self._get_conn()
        def _run():
            cur = conn.cursor()
            cur.execute("SHOW TABLES")
            return [TableInfo(name=r[0]) for r in cur.fetchall()]
        return await asyncio.get_event_loop().run_in_executor(None, _run)

    async def describe_table(self, table_name: str) -> list[ColumnInfo]:
        import asyncio
        conn = self._get_conn()
        def _run():
            cur = conn.cursor()
            cur.execute(f"DESCRIBE {table_name}")
            return [
                ColumnInfo(name=r[0], type=r[1] if len(r) > 1 else "string")
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
        return "spark"

    async def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
