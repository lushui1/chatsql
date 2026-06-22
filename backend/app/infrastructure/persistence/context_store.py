"""Business context store — SQLite CRUD for tables, relations, examples, terminology.

Reuses existing chatsql.db via aiosqlite.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger("chatsql")

# ── Schema DDL ──

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS bc_tables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    display_name TEXT DEFAULT '',
    description TEXT DEFAULT '',
    hidden INTEGER DEFAULT 0,
    category TEXT DEFAULT '',
    datasource TEXT DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bc_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table TEXT NOT NULL,
    source_column TEXT NOT NULL,
    target_table TEXT NOT NULL,
    target_column TEXT NOT NULL,
    join_type TEXT DEFAULT 'INNER',
    description TEXT DEFAULT '',
    datasource TEXT DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bc_examples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    sql TEXT NOT NULL,
    description TEXT DEFAULT '',
    datasource TEXT DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bc_terminology (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL,
    definition TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
"""


def _now() -> int:
    return int(time.time())


def _db_path() -> str:
    """Resolve chatsql.db path relative to project root."""
    # Match config: sqlite+aiosqlite:///./data/chatsql.db
    p = Path("data/chatsql.db")
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


async def _get_conn() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(_db_path())
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    return conn


async def init_context_db() -> None:
    """Create business context tables if they don't exist."""
    conn = await _get_conn()
    try:
        await conn.executescript(_CREATE_TABLES_SQL)
        await conn.commit()
        logger.info("Business context tables initialized")
    finally:
        await conn.close()


# ═══════════════════════════════════════════════════════
# TABLE METADATA
# ═══════════════════════════════════════════════════════


async def list_tables_meta(datasource: str | None = None) -> list[dict]:
    """List all table metadata, optionally filtered by datasource."""
    conn = await _get_conn()
    try:
        if datasource:
            cursor = await conn.execute(
                "SELECT * FROM bc_tables WHERE datasource = ? ORDER BY name",
                (datasource,),
            )
        else:
            cursor = await conn.execute("SELECT * FROM bc_tables ORDER BY name")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def get_table_meta(name: str, datasource: str | None = None) -> dict | None:
    """Get a single table's metadata."""
    conn = await _get_conn()
    try:
        if datasource:
            cursor = await conn.execute(
                "SELECT * FROM bc_tables WHERE name = ? AND datasource = ?",
                (name, datasource),
            )
        else:
            cursor = await conn.execute(
                "SELECT * FROM bc_tables WHERE name = ?", (name,)
            )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await conn.close()


async def upsert_table_meta(
    name: str,
    *,
    display_name: str = "",
    description: str = "",
    hidden: bool = False,
    category: str = "",
    datasource: str = "",
) -> dict:
    """Insert or update table metadata."""
    now = _now()
    conn = await _get_conn()
    try:
        await conn.execute(
            """INSERT INTO bc_tables (name, display_name, description, hidden, category, datasource, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                 display_name = excluded.display_name,
                 description = excluded.description,
                 hidden = excluded.hidden,
                 category = excluded.category,
                 updated_at = excluded.updated_at
            """,
            (name, display_name, description, int(hidden), category, datasource, now, now),
        )
        await conn.commit()
        return await get_table_meta(name, datasource) or {}
    finally:
        await conn.close()


async def delete_table_meta(name: str) -> bool:
    conn = await _get_conn()
    try:
        cursor = await conn.execute("DELETE FROM bc_tables WHERE name = ?", (name,))
        await conn.commit()
        return cursor.rowcount > 0
    finally:
        await conn.close()


# ═══════════════════════════════════════════════════════
# RELATIONS
# ═══════════════════════════════════════════════════════


async def list_relations(datasource: str | None = None) -> list[dict]:
    conn = await _get_conn()
    try:
        if datasource:
            cursor = await conn.execute(
                "SELECT * FROM bc_relations WHERE datasource = ? ORDER BY id",
                (datasource,),
            )
        else:
            cursor = await conn.execute("SELECT * FROM bc_relations ORDER BY id")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def add_relation(
    source_table: str,
    source_column: str,
    target_table: str,
    target_column: str,
    *,
    join_type: str = "INNER",
    description: str = "",
    datasource: str = "",
) -> dict:
    now = _now()
    conn = await _get_conn()
    try:
        cursor = await conn.execute(
            """INSERT INTO bc_relations
               (source_table, source_column, target_table, target_column, join_type, description, datasource, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (source_table, source_column, target_table, target_column, join_type, description, datasource, now, now),
        )
        await conn.commit()
        row_id = cursor.lastrowid
        cursor = await conn.execute("SELECT * FROM bc_relations WHERE id = ?", (row_id,))
        row = await cursor.fetchone()
        return dict(row) if row else {"id": row_id}
    finally:
        await conn.close()


async def delete_relation(relation_id: int) -> bool:
    conn = await _get_conn()
    try:
        cursor = await conn.execute("DELETE FROM bc_relations WHERE id = ?", (relation_id,))
        await conn.commit()
        return cursor.rowcount > 0
    finally:
        await conn.close()


# ═══════════════════════════════════════════════════════
# EXAMPLES
# ═══════════════════════════════════════════════════════


async def list_examples(datasource: str | None = None) -> list[dict]:
    conn = await _get_conn()
    try:
        if datasource:
            cursor = await conn.execute(
                "SELECT * FROM bc_examples WHERE datasource = ? ORDER BY id",
                (datasource,),
            )
        else:
            cursor = await conn.execute("SELECT * FROM bc_examples ORDER BY id")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def add_example(
    question: str,
    sql: str,
    *,
    description: str = "",
    datasource: str = "",
) -> dict:
    now = _now()
    conn = await _get_conn()
    try:
        cursor = await conn.execute(
            """INSERT INTO bc_examples (question, sql, description, datasource, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (question, sql, description, datasource, now, now),
        )
        await conn.commit()
        row_id = cursor.lastrowid
        cursor = await conn.execute("SELECT * FROM bc_examples WHERE id = ?", (row_id,))
        row = await cursor.fetchone()
        return dict(row) if row else {"id": row_id}
    finally:
        await conn.close()


async def delete_example(example_id: int) -> bool:
    conn = await _get_conn()
    try:
        cursor = await conn.execute("DELETE FROM bc_examples WHERE id = ?", (example_id,))
        await conn.commit()
        return cursor.rowcount > 0
    finally:
        await conn.close()


# ═══════════════════════════════════════════════════════
# TERMINOLOGY
# ═══════════════════════════════════════════════════════


async def list_terminology() -> list[dict]:
    conn = await _get_conn()
    try:
        cursor = await conn.execute("SELECT * FROM bc_terminology ORDER BY id")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def add_terminology(
    term: str,
    definition: str,
    *,
    description: str = "",
) -> dict:
    now = _now()
    conn = await _get_conn()
    try:
        cursor = await conn.execute(
            """INSERT INTO bc_terminology (term, definition, description, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (term, definition, description, now, now),
        )
        await conn.commit()
        row_id = cursor.lastrowid
        cursor = await conn.execute("SELECT * FROM bc_terminology WHERE id = ?", (row_id,))
        row = await cursor.fetchone()
        return dict(row) if row else {"id": row_id}
    finally:
        await conn.close()


async def delete_terminology(term_id: int) -> bool:
    conn = await _get_conn()
    try:
        cursor = await conn.execute("DELETE FROM bc_terminology WHERE id = ?", (term_id,))
        await conn.commit()
        return cursor.rowcount > 0
    finally:
        await conn.close()


# ═══════════════════════════════════════════════════════
# IMPORT / EXPORT
# ═══════════════════════════════════════════════════════


async def export_all() -> dict[str, Any]:
    """Export all business context as JSON-compatible dict."""
    return {
        "tables": await list_tables_meta(),
        "relations": await list_relations(),
        "examples": await list_examples(),
        "terminology": await list_terminology(),
    }


async def import_all(data: dict[str, Any]) -> dict[str, int]:
    """Import business context from JSON dict. Returns counts of imported items."""
    counts = {"tables": 0, "relations": 0, "examples": 0, "terminology": 0}

    for t in data.get("tables", []):
        await upsert_table_meta(
            name=t["name"],
            display_name=t.get("display_name", ""),
            description=t.get("description", ""),
            hidden=bool(t.get("hidden", False)),
            category=t.get("category", ""),
            datasource=t.get("datasource", ""),
        )
        counts["tables"] += 1

    for r in data.get("relations", []):
        await add_relation(
            source_table=r["source_table"],
            source_column=r["source_column"],
            target_table=r["target_table"],
            target_column=r["target_column"],
            join_type=r.get("join_type", "INNER"),
            description=r.get("description", ""),
            datasource=r.get("datasource", ""),
        )
        counts["relations"] += 1

    for e in data.get("examples", []):
        await add_example(
            question=e["question"],
            sql=e["sql"],
            description=e.get("description", ""),
            datasource=e.get("datasource", ""),
        )
        counts["examples"] += 1

    for term in data.get("terminology", []):
        await add_terminology(
            term=term["term"],
            definition=term["definition"],
            description=term.get("description", ""),
        )
        counts["terminology"] += 1

    return counts
