"""Business context domain models — table metadata, relations, examples, terminology."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Table Metadata ──


class TableMeta(BaseModel):
    """Table metadata with business description."""
    name: str
    display_name: str = ""
    description: str = ""
    hidden: bool = False
    category: str = ""


class ColumnMeta(BaseModel):
    """Column metadata with business description."""
    name: str
    display_name: str = ""
    description: str = ""
    enum_values: dict | None = None  # {"FOLLOWING": "跟进中", "NEW": "新建"}


# ── Relations ──


class TableRelation(BaseModel):
    """Table join relationship."""
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    join_type: str = "INNER"
    description: str = ""


# ── Examples ──


class ExampleSQL(BaseModel):
    """Example question-SQL pair."""
    question: str
    sql: str
    description: str = ""
    datasource: str = ""


# ── Terminology ──


class Terminology(BaseModel):
    """Custom business term definition."""
    term: str
    definition: str
    description: str = ""


# ── RAG Result ──


class RAGResult(BaseModel):
    """Result from RAG retrieval."""
    relevant_tables: list[dict] = []
    relevant_relations: list[dict] = []
    relevant_examples: list[dict] = []
    relevant_terms: list[dict] = []
