"""Business context routes — CRUD for table metadata, relations, examples, terminology."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.infrastructure.persistence import context_store

router = APIRouter()


# ── Request Models ──


class TableMetaUpdate(BaseModel):
    display_name: str = ""
    description: str = ""
    hidden: bool = False
    category: str = ""


class RelationCreate(BaseModel):
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    join_type: str = "INNER"
    description: str = ""
    datasource: str = ""


class ExampleCreate(BaseModel):
    question: str
    sql: str
    description: str = ""
    datasource: str = ""


class TerminologyCreate(BaseModel):
    term: str
    definition: str
    description: str = ""


class ImportRequest(BaseModel):
    tables: list[dict] = []
    relations: list[dict] = []
    examples: list[dict] = []
    terminology: list[dict] = []


# ── Table Metadata ──


@router.get("/v1/context/tables")
async def get_tables(datasource: str | None = None):
    """Get all table metadata."""
    tables = await context_store.list_tables_meta(datasource)
    return JSONResponse(content={"tables": tables})


@router.put("/v1/context/tables/{name}")
async def update_table(name: str, req: TableMetaUpdate):
    """Update table metadata (display_name, description, hidden, category)."""
    result = await context_store.upsert_table_meta(
        name,
        display_name=req.display_name,
        description=req.description,
        hidden=req.hidden,
        category=req.category,
    )
    return JSONResponse(content={"ok": True, "table": result})


# ── Relations ──


@router.get("/v1/context/relations")
async def get_relations(datasource: str | None = None):
    """Get all table relations."""
    relations = await context_store.list_relations(datasource)
    return JSONResponse(content={"relations": relations})


@router.post("/v1/context/relations")
async def create_relation(req: RelationCreate):
    """Add a table relation."""
    result = await context_store.add_relation(
        source_table=req.source_table,
        source_column=req.source_column,
        target_table=req.target_table,
        target_column=req.target_column,
        join_type=req.join_type,
        description=req.description,
        datasource=req.datasource,
    )
    return JSONResponse(content={"ok": True, "relation": result})


@router.delete("/v1/context/relations/{relation_id}")
async def delete_relation(relation_id: int):
    """Delete a table relation."""
    deleted = await context_store.delete_relation(relation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Relation {relation_id} not found")
    return JSONResponse(content={"ok": True})


# ── Examples ──


@router.get("/v1/context/examples")
async def get_examples(datasource: str | None = None):
    """Get all example SQL."""
    examples = await context_store.list_examples(datasource)
    return JSONResponse(content={"examples": examples})


@router.post("/v1/context/examples")
async def create_example(req: ExampleCreate):
    """Add an example SQL."""
    result = await context_store.add_example(
        question=req.question,
        sql=req.sql,
        description=req.description,
        datasource=req.datasource,
    )
    return JSONResponse(content={"ok": True, "example": result})


@router.delete("/v1/context/examples/{example_id}")
async def delete_example(example_id: int):
    """Delete an example SQL."""
    deleted = await context_store.delete_example(example_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Example {example_id} not found")
    return JSONResponse(content={"ok": True})


# ── Terminology ──


@router.get("/v1/context/terminology")
async def get_terminology():
    """Get all terminology."""
    terms = await context_store.list_terminology()
    return JSONResponse(content={"terminology": terms})


@router.post("/v1/context/terminology")
async def create_terminology(req: TerminologyCreate):
    """Add a terminology entry."""
    result = await context_store.add_terminology(
        term=req.term,
        definition=req.definition,
        description=req.description,
    )
    return JSONResponse(content={"ok": True, "terminology": result})


@router.delete("/v1/context/terminology/{term_id}")
async def delete_terminology(term_id: int):
    """Delete a terminology entry."""
    deleted = await context_store.delete_terminology(term_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Terminology {term_id} not found")
    return JSONResponse(content={"ok": True})


# ── Import / Export ──


@router.post("/v1/context/import")
async def import_context(req: ImportRequest):
    """Import all business context from JSON."""
    data = req.model_dump()
    counts = await context_store.import_all(data)
    return JSONResponse(content={"ok": True, "imported": counts})


@router.get("/v1/context/export")
async def export_context():
    """Export all business context as JSON."""
    data = await context_store.export_all()
    return JSONResponse(content=data)
