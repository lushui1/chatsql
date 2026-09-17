"""ClickHouse data source implementation using clickhouse-connect."""

from __future__ import annotations

from typing import Any

from app.application.datasources import ColumnInfo, DataSource, TableInfo


class ClickHouseDataSource(DataSource):
    """ClickHouse data source via clickhouse-connect (sync, run in executor)."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8123,
        database: str = "default",
        username: str = "default",
        password: str = "",
    ):
        self._host = host
        self._port = port
        self._database = database
        self._username = username
        self._password = password
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import clickhouse_connect
            except ImportError as e:
                raise RuntimeError(
                    "ClickHouse data source requires `pip install clickhouse-connect`. "
                    f"Original error: {e}"
                ) from e
            self._client = clickhouse_connect.get_client(
                host=self._host,
                port=self._port,
                database=self._database,
                username=self._username,
                password=self._password,
            )
        return self._client

    def _discard_client(self) -> None:
        """超时后丢弃连接。

        HTTP 客户端无法中断已发出的请求，只能断开连接并丢弃，
        下次查询重建。不断开的话这条查询会一直占着服务端资源。
        """
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass

    async def execute(self, sql: str) -> dict[str, Any]:
        from app.application.datasources.query_guard import query_timeout, run_blocking

        client = self._get_client()
        timeout = query_timeout()

        def _run():
            # max_execution_time 让服务端自己也会在超时后中止查询，
            # 客户端断开只是兜底。
            return client.query(
                sql, settings={"max_execution_time": max(1, int(timeout))}
            )

        result = await run_blocking(_run, sql=sql, on_cancel=self._discard_client)
        columns = result.column_names
        rows = [dict(zip(columns, row)) for row in result.result_rows]
        return {"columns": [{"name": c} for c in columns], "rows": rows}

    async def list_tables(self) -> list[TableInfo]:
        import asyncio
        client = self._get_client()
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: client.query(f"SHOW TABLES FROM {self._database}")
        )
        return [TableInfo(name=r[0]) for r in result.result_rows]

    async def describe_table(self, table_name: str) -> list[ColumnInfo]:
        import asyncio
        client = self._get_client()
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: client.query(f"DESCRIBE TABLE {table_name}")
        )
        return [
            ColumnInfo(name=r[0], type=r[1], nullable=True)
            for r in result.result_rows
        ]

    async def get_table_stats(self, table_name: str) -> dict:
        import asyncio
        client = self._get_client()
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.query(
                f"SELECT count() FROM {table_name}"
            ),
        )
        row_count = result.result_rows[0][0] if result.result_rows else 0
        return {"table": table_name, "row_count": row_count}

    def dialect(self) -> str:
        return "clickhouse"

    async def close(self):
        if self._client:
            self._client.close()
            self._client = None
