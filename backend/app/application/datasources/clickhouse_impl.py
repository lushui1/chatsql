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

    async def execute(self, sql: str) -> dict[str, Any]:
        import asyncio
        client = self._get_client()
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: client.query(sql)
        )
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
