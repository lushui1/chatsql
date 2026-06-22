"""Dashboard persistence — async CRUD for dashboards and charts."""

from __future__ import annotations

import json
import secrets
import time

from sqlalchemy import select, update, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.models import Dashboard as DashboardModel, DashboardChart as DashboardChartModel


def _new_dashboard_id() -> str:
    return f"dash_{secrets.token_hex(16)}"


def _new_chart_id() -> str:
    return f"chart_{secrets.token_hex(16)}"


# ── Dashboards ──


async def list_dashboards(db: AsyncSession) -> list[DashboardModel]:
    """List all dashboards, ordered by updated_at desc."""
    result = await db.execute(select(DashboardModel).order_by(desc(DashboardModel.updated_at)))
    return list(result.scalars().all())


async def create_dashboard(
    db: AsyncSession,
    *,
    name: str,
    description: str = "",
    layout: str = "grid",
) -> DashboardModel:
    """Create a new dashboard."""
    now = int(time.time())
    dashboard = DashboardModel(
        id=_new_dashboard_id(),
        name=name,
        description=description,
        layout=layout,
        created_at=now,
        updated_at=now,
    )
    db.add(dashboard)
    await db.commit()
    await db.refresh(dashboard)
    return dashboard


async def get_dashboard(db: AsyncSession, dashboard_id: str) -> DashboardModel | None:
    """Get a single dashboard by ID."""
    result = await db.execute(select(DashboardModel).where(DashboardModel.id == dashboard_id))
    return result.scalar_one_or_none()


async def get_dashboard_with_charts(db: AsyncSession, dashboard_id: str) -> dict | None:
    """Get dashboard with all its charts."""
    dashboard = await get_dashboard(db, dashboard_id)
    if dashboard is None:
        return None

    charts_result = await db.execute(
        select(DashboardChartModel)
        .where(DashboardChartModel.dashboard_id == dashboard_id)
        .order_by(DashboardChartModel.created_at)
    )
    charts = list(charts_result.scalars().all())

    return {
        "id": dashboard.id,
        "name": dashboard.name,
        "description": dashboard.description,
        "layout": dashboard.layout,
        "created_at": dashboard.created_at,
        "updated_at": dashboard.updated_at,
        "charts": [
            {
                "id": c.id,
                "title": c.title,
                "chart_type": c.chart_type,
                "config": json.loads(c.config_json) if c.config_json else {},
                "data": json.loads(c.data_json) if c.data_json else {},
                "sql": c.sql_text or "",
                "datasource": c.datasource or "",
                "created_at": c.created_at,
            }
            for c in charts
        ],
    }


async def update_dashboard(
    db: AsyncSession,
    dashboard_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    layout: str | None = None,
) -> DashboardModel | None:
    """Update dashboard fields."""
    values: dict = {"updated_at": int(time.time())}
    if name is not None:
        values["name"] = name
    if description is not None:
        values["description"] = description
    if layout is not None:
        values["layout"] = layout

    await db.execute(
        update(DashboardModel).where(DashboardModel.id == dashboard_id).values(**values)
    )
    await db.commit()
    return await get_dashboard(db, dashboard_id)


async def delete_dashboard(db: AsyncSession, dashboard_id: str) -> bool:
    """Delete a dashboard and all its charts."""
    # Delete charts first
    await db.execute(
        DashboardChartModel.__table__.delete().where(DashboardChartModel.dashboard_id == dashboard_id)
    )
    result = await db.execute(
        DashboardModel.__table__.delete().where(DashboardModel.id == dashboard_id)
    )
    await db.commit()
    return result.rowcount > 0


# ── Charts ──


async def add_chart(
    db: AsyncSession,
    dashboard_id: str,
    *,
    title: str,
    chart_type: str,
    config: dict | None = None,
    data: dict | None = None,
    sql: str = "",
    datasource: str = "",
) -> DashboardChartModel | None:
    """Add a chart to a dashboard."""
    dashboard = await get_dashboard(db, dashboard_id)
    if dashboard is None:
        return None

    now = int(time.time())
    chart = DashboardChartModel(
        id=_new_chart_id(),
        dashboard_id=dashboard_id,
        title=title,
        chart_type=chart_type,
        config_json=json.dumps(config or {}, ensure_ascii=False),
        data_json=json.dumps(data or {}, ensure_ascii=False),
        sql_text=sql,
        datasource=datasource,
        created_at=now,
    )
    db.add(chart)

    # Update dashboard updated_at
    dashboard.updated_at = now

    await db.commit()
    await db.refresh(chart)
    return chart


async def get_chart(db: AsyncSession, chart_id: str) -> DashboardChartModel | None:
    """Get a single chart by ID."""
    result = await db.execute(select(DashboardChartModel).where(DashboardChartModel.id == chart_id))
    return result.scalar_one_or_none()


async def update_chart(
    db: AsyncSession,
    chart_id: str,
    *,
    title: str | None = None,
    chart_type: str | None = None,
    config: dict | None = None,
    data: dict | None = None,
    sql: str | None = None,
    datasource: str | None = None,
) -> DashboardChartModel | None:
    """Update a chart's fields."""
    chart = await get_chart(db, chart_id)
    if chart is None:
        return None

    if title is not None:
        chart.title = title
    if chart_type is not None:
        chart.chart_type = chart_type
    if config is not None:
        chart.config_json = json.dumps(config, ensure_ascii=False)
    if data is not None:
        chart.data_json = json.dumps(data, ensure_ascii=False)
    if sql is not None:
        chart.sql_text = sql
    if datasource is not None:
        chart.datasource = datasource

    # Update parent dashboard updated_at
    dashboard = await get_dashboard(db, chart.dashboard_id)
    if dashboard:
        dashboard.updated_at = int(time.time())

    await db.commit()
    await db.refresh(chart)
    return chart


async def delete_chart(db: AsyncSession, chart_id: str) -> bool:
    """Delete a chart."""
    chart = await get_chart(db, chart_id)
    if chart is None:
        return False

    # Update parent dashboard updated_at
    dashboard = await get_dashboard(db, chart.dashboard_id)
    if dashboard:
        dashboard.updated_at = int(time.time())

    result = await db.execute(
        DashboardChartModel.__table__.delete().where(DashboardChartModel.id == chart_id)
    )
    await db.commit()
    return result.rowcount > 0
