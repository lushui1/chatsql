"""Dashboard domain — data models for dashboards and charts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DashboardChart:
    """保存的图表"""

    id: str = ""
    title: str = ""
    chart_type: str = ""  # column/bar/line/pie/table
    config: dict = field(default_factory=dict)  # 图表配置（x, y, title等）
    data: dict = field(default_factory=dict)  # 数据（columns, rows）
    sql: str = ""  # 来源SQL
    datasource: str = ""  # 来源数据源
    created_at: str = ""


@dataclass
class Dashboard:
    """仪表盘"""

    id: str = ""
    name: str = ""
    description: str = ""
    charts: list[DashboardChart] = field(default_factory=list)
    layout: str = "grid"  # grid/free
    created_at: str = ""
    updated_at: str = ""
