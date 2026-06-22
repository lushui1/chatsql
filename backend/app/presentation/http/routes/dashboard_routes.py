"""Dashboard routes — CRUD for dashboards and charts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure import get_db
from app.infrastructure.persistence import dashboard_store as store
from app.presentation.http.security.auth_utils import verify_api_key

router = APIRouter(prefix="/v1")


# ── Request Models ──


class DashboardCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = ""
    layout: str = "grid"


class DashboardUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    layout: str | None = None


class ChartAddRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    chart_type: str = Field(..., pattern="^(column|bar|line|pie|table)$")
    config: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)
    sql: str = ""
    datasource: str = ""


class ChartUpdateRequest(BaseModel):
    title: str | None = None
    chart_type: str | None = None
    config: dict[str, Any] | None = None
    data: dict[str, Any] | None = None
    sql: str | None = None
    datasource: str | None = None


class SaveChartRequest(BaseModel):
    dashboard_id: str = Field(..., min_length=1)
    chart_data: ChartAddRequest


# ── Routes ──


@router.get("/dashboards")
async def list_dashboards(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """List all dashboards (without charts)."""
    dashboards = await store.list_dashboards(db)
    return JSONResponse(content=[
        {
            "id": d.id,
            "name": d.name,
            "description": d.description,
            "layout": d.layout,
            "created_at": d.created_at,
            "updated_at": d.updated_at,
        }
        for d in dashboards
    ])


@router.post("/dashboards")
async def create_dashboard(
    body: DashboardCreateRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """Create a new dashboard."""
    dashboard = await store.create_dashboard(
        db,
        name=body.name,
        description=body.description,
        layout=body.layout,
    )
    return JSONResponse(status_code=201, content={
        "id": dashboard.id,
        "name": dashboard.name,
        "description": dashboard.description,
        "layout": dashboard.layout,
        "created_at": dashboard.created_at,
        "updated_at": dashboard.updated_at,
        "charts": [],
    })


@router.get("/dashboards/{dashboard_id}")
async def get_dashboard(
    dashboard_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """Get a dashboard with all its charts."""
    result = await store.get_dashboard_with_charts(db, dashboard_id)
    if result is None:
        raise HTTPException(status_code=404, detail="dashboard not found")
    return JSONResponse(content=result)


@router.put("/dashboards/{dashboard_id}")
async def update_dashboard(
    dashboard_id: str,
    body: DashboardUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """Update a dashboard's name, description, or layout."""
    dashboard = await store.update_dashboard(
        db,
        dashboard_id,
        name=body.name,
        description=body.description,
        layout=body.layout,
    )
    if dashboard is None:
        raise HTTPException(status_code=404, detail="dashboard not found")
    return JSONResponse(content={
        "id": dashboard.id,
        "name": dashboard.name,
        "description": dashboard.description,
        "layout": dashboard.layout,
        "created_at": dashboard.created_at,
        "updated_at": dashboard.updated_at,
    })


@router.delete("/dashboards/{dashboard_id}")
async def delete_dashboard(
    dashboard_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """Delete a dashboard and all its charts."""
    deleted = await store.delete_dashboard(db, dashboard_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="dashboard not found")
    return JSONResponse(status_code=204, content=None)


@router.post("/dashboards/{dashboard_id}/charts")
async def add_chart(
    dashboard_id: str,
    body: ChartAddRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """Add a chart to a dashboard."""
    chart = await store.add_chart(
        db,
        dashboard_id,
        title=body.title,
        chart_type=body.chart_type,
        config=body.config,
        data=body.data,
        sql=body.sql,
        datasource=body.datasource,
    )
    if chart is None:
        raise HTTPException(status_code=404, detail="dashboard not found")
    return JSONResponse(status_code=201, content={
        "id": chart.id,
        "title": chart.title,
        "chart_type": chart.chart_type,
        "config": body.config,
        "data": body.data,
        "sql": chart.sql_text or "",
        "datasource": chart.datasource or "",
        "created_at": chart.created_at,
    })


@router.put("/dashboards/{dashboard_id}/charts/{chart_id}")
async def update_chart(
    dashboard_id: str,
    chart_id: str,
    body: ChartUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """Update a chart's properties."""
    # Verify chart belongs to dashboard
    chart = await store.get_chart(db, chart_id)
    if chart is None or chart.dashboard_id != dashboard_id:
        raise HTTPException(status_code=404, detail="chart not found")

    updated = await store.update_chart(
        db,
        chart_id,
        title=body.title,
        chart_type=body.chart_type,
        config=body.config,
        data=body.data,
        sql=body.sql,
        datasource=body.datasource,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="chart not found")
    return JSONResponse(content={
        "id": updated.id,
        "title": updated.title,
        "chart_type": updated.chart_type,
        "config": body.config if body.config is not None else {},
        "data": body.data if body.data is not None else {},
        "sql": updated.sql_text or "",
        "datasource": updated.datasource or "",
        "created_at": updated.created_at,
    })


@router.delete("/dashboards/{dashboard_id}/charts/{chart_id}")
async def delete_chart(
    dashboard_id: str,
    chart_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """Delete a chart from a dashboard."""
    # Verify chart belongs to dashboard
    chart = await store.get_chart(db, chart_id)
    if chart is None or chart.dashboard_id != dashboard_id:
        raise HTTPException(status_code=404, detail="chart not found")

    deleted = await store.delete_chart(db, chart_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="chart not found")
    return JSONResponse(status_code=204, content=None)


@router.post("/dashboards/save-chart")
async def save_chart(
    body: SaveChartRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_api_key),
):
    """Save a chart from conversation to a dashboard."""
    chart = await store.add_chart(
        db,
        body.dashboard_id,
        title=body.chart_data.title,
        chart_type=body.chart_data.chart_type,
        config=body.chart_data.config,
        data=body.chart_data.data,
        sql=body.chart_data.sql,
        datasource=body.chart_data.datasource,
    )
    if chart is None:
        raise HTTPException(status_code=404, detail="dashboard not found")
    return JSONResponse(status_code=201, content={
        "id": chart.id,
        "dashboard_id": body.dashboard_id,
        "title": chart.title,
        "chart_type": chart.chart_type,
        "created_at": chart.created_at,
    })
