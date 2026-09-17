"""Doris data source implementation using MySQL protocol (Doris is MySQL-compatible)."""

from __future__ import annotations

from typing import Any

from app.application.datasources import ColumnInfo, DataSource, TableInfo


class DorisDataSource(DataSource):
    """Apache Doris data source — uses MySQL wire protocol (aiomysql)."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9030,
        database: str = "",
        username: str = "root",
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
                import aiomysql
            except ImportError as e:
                raise RuntimeError(
                    "Doris data source requires `pip install aiomysql`. "
                    f"Original error: {e}"
                ) from e
            self._pool = await aiomysql.create_pool(
                host=self._host,
                port=self._port,
                db=self._database,
                user=self._username,
                password=self._password,
                autocommit=True,
                minsize=1,
                maxsize=10,
            )
        return self._pool

    async def execute(self, sql: str) -> dict[str, Any]:
        from app.application.datasources.query_guard import run_async

        pool = await self._get_pool()
        holder: dict[str, Any] = {}
        released = False

        async def _query():
            nonlocal released
            conn = await pool.acquire()
            holder["conn"] = conn
            try:
                async with conn.cursor() as cur:
                    await cur.execute(sql)
                    if cur.description:
                        columns = [d[0] for d in cur.description]
                        rows = [dict(zip(columns, row)) for row in await cur.fetchall()]
                        return {"columns": [{"name": c} for c in columns], "rows": rows}
                    return {"columns": [], "rows": []}
            finally:
                if not released:
                    released = True
                    pool.release(conn)

        def _cancel():
            conn = holder.get("conn")
            if conn is None:
                return
            try:
                if not released:
                    released = True
                    pool.release(conn)
                conn.close()
            except Exception:  # noqa: BLE001
                pass

        return await run_async(lambda: _query(), sql=sql, on_cancel=_cancel)

    async def list_tables(self) -> list[TableInfo]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SHOW TABLES")
                rows = await cur.fetchall()
                return [TableInfo(name=r[0]) for r in rows]

    async def describe_table(self, table_name: str) -> list[ColumnInfo]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"DESCRIBE `{table_name}`")
                rows = await cur.fetchall()
                return [
                    ColumnInfo(
                        name=r[0],
                        type=r[1],
                        nullable=(r[2] == "YES") if len(r) > 2 else True,
                        comment=r[-1] if len(r) > 4 else "",
                    )
                    for r in rows
                ]

    async def get_table_stats(self, table_name: str) -> dict:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"SELECT COUNT(*) FROM `{table_name}`")
                row = await cur.fetchone()
                return {"table": table_name, "row_count": row[0] if row else None}

    def dialect(self) -> str:
        return "doris"

    async def close(self):
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
