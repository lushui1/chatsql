"""PostgreSQL data source implementation using asyncpg."""

from __future__ import annotations

from typing import Any

from app.application.datasources import ColumnInfo, DataSource, TableInfo


class PostgreSQLDataSource(DataSource):
    """PostgreSQL data source via asyncpg."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "",
        username: str = "postgres",
        password: str = "",
    ):
        self._host = host
        self._port = port
        self._database = database
        self._username = username
        self._password = password
        self._pool = None

    async def _get_pool(self):
        if self._pool is None:
            try:
                import asyncpg
            except ImportError as e:
                raise RuntimeError(
                    "PostgreSQL data source requires `pip install asyncpg`. "
                    f"Original error: {e}"
                ) from e
            self._pool = await asyncpg.create_pool(
                host=self._host,
                port=self._port,
                database=self._database,
                user=self._username,
                password=self._password,
                min_size=1,
                max_size=10,
            )
        return self._pool

    async def execute(self, sql: str) -> dict[str, Any]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            result = await conn.fetch(sql)
            if not result:
                return {"columns": [], "rows": []}
            columns = list(result[0].keys())
            rows = [dict(zip(columns, row)) for row in result]
            return {"columns": [{"name": c} for c in columns], "rows": rows}

    async def list_tables(self) -> list[TableInfo]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
            return [TableInfo(name=r["tablename"]) for r in rows]

    async def describe_table(self, table_name: str) -> list[ColumnInfo]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = $1 "
                "ORDER BY ordinal_position",
                table_name,
            )
            return [
                ColumnInfo(
                    name=r["column_name"],
                    type=r["data_type"],
                    nullable=(r["is_nullable"] == "YES"),
                    default=str(r["column_default"]) if r["column_default"] else None,
                )
                for r in rows
            ]

    async def get_table_stats(self, table_name: str) -> dict:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT reltuples::bigint FROM pg_class WHERE relname = $1",
                table_name,
            )
            row_count = int(row["reltuples"]) if row and row["reltuples"] >= 0 else None
            return {"table": table_name, "row_count": row_count}

    def dialect(self) -> str:
        return "postgresql"

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None
