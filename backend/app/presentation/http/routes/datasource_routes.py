"""DataSource routes — CRUD + metadata + SQL execution."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.application.datasources import DataSourceConfig
from app.application.datasources.manager import get_manager
from app.application.sql_validator import SQLValidator

router = APIRouter()


# ── Request/Response Models ──


class AddSourceRequest(BaseModel):
    name: str
    type: str  # duckdb / mysql / postgresql / clickhouse / hive / presto / spark / doris
    description: str = ""
    host: str = ""
    port: int = 0
    database: str = ""
    username: str = ""
    password: str = ""
    url: str = ""
    db_schema: str = "main"
    extra: dict = {}


class ExecuteRequest(BaseModel):
    source: str  # datasource name
    sql: str


# ── Routes ──


@router.get("/v1/datasources")
async def list_datasources():
    """List all configured data sources."""
    mgr = get_manager()
    return JSONResponse(content={"sources": mgr.list_sources()})


@router.post("/v1/datasources")
async def add_datasource(req: AddSourceRequest):
    """Add a new data source."""
    mgr = get_manager()
    config = DataSourceConfig(
        name=req.name,
        type=req.type,
        description=req.description,
        host=req.host,
        port=req.port,
        database=req.database,
        username=req.username,
        password=req.password,
        url=req.url,
        schema=req.db_schema,
        extra=req.extra,
    )
    try:
        mgr.add_source(config)
        # Persist to file
        mgr.save_config_file("data/sources.json")
        return JSONResponse(content={"ok": True, "source": config.to_public_dict()})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/v1/datasources/{name}")
async def remove_datasource(name: str):
    """Remove a data source."""
    mgr = get_manager()
    if mgr.remove_source(name):
        mgr.save_config_file("data/sources.json")
        return JSONResponse(content={"ok": True})
    raise HTTPException(status_code=404, detail=f"Data source '{name}' not found")


@router.get("/v1/datasources/{name}/metadata")
async def get_metadata(name: str, table: str | None = None):
    """Get metadata for a data source (table list or specific table schema)."""
    mgr = get_manager()
    try:
        metadata = await mgr.get_metadata(name, table)
        return JSONResponse(content=metadata)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Data source '{name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/v1/datasources/{name}/full-metadata")
async def get_full_metadata(name: str):
    """Get full metadata for all tables in a data source."""
    mgr = get_manager()
    try:
        metadata = await mgr.get_full_metadata(name)
        return JSONResponse(content=metadata)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Data source '{name}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 允许 DESCRIBE / SHOW / EXPLAIN 等只读管理语句（前端"查看表结构"会用到），
# 但 DDL / DML 依然被 FORBIDDEN_KEYWORDS 拦住。
_EXEC_VALIDATOR = SQLValidator(allow_readonly_admin=True)
_EXEC_ROW_LIMIT = 1000


@router.post("/v1/datasources/execute")
async def execute_sql(req: ExecuteRequest):
    """Execute SQL against a named data source.

    安全约束（缺一不可）：
    1. 语句必须以 SELECT / WITH / DESCRIBE / SHOW / EXPLAIN 开头
    2. 禁止多语句堆叠
    3. 禁止 DDL / DML / 文件读写函数
    4. 自动追加 LIMIT，避免全表拉取打到 OOM
    """
    is_safe, reason = _EXEC_VALIDATOR.validate(req.sql)
    if not is_safe:
        raise HTTPException(status_code=400, detail=f"SQL 安全校验不通过: {reason}")

    mgr = get_manager()
    try:
        ds = mgr.get_source(req.source)
        sql = _EXEC_VALIDATOR.enforce_limit(req.sql, limit=_EXEC_ROW_LIMIT)
        result = await ds.execute(sql)
        # 截断：即使底层没吃 LIMIT（部分方言不支持），这里再兜一层
        rows = result.get("rows", [])
        if len(rows) > _EXEC_ROW_LIMIT:
            result["rows"] = rows[:_EXEC_ROW_LIMIT]
            result["truncated"] = True
        return JSONResponse(content=result)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Data source '{req.source}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class TestSourceRequest(BaseModel):
    type: str
    host: str = ""
    port: int = 0
    database: str = ""
    username: str = ""
    password: str = ""
    url: str = ""


@router.post("/v1/datasources/test")
async def test_datasource_connection(req: TestSourceRequest):
    """Test a data source connection without saving."""
    from app.application.datasources import create_datasource, DataSourceConfig
    config = DataSourceConfig(
        name="_test_",
        type=req.type,
        host=req.host,
        port=req.port,
        database=req.database,
        username=req.username,
        password=req.password,
        url=req.url,
    )
    try:
        ds = create_datasource(config)
        tables = await ds.list_tables()
        return JSONResponse(content={
            "ok": True,
            "message": f"连接成功，发现 {len(tables)} 张表",
            "tables": [t.name for t in tables],
        })
    except Exception as e:
        return JSONResponse(content={"ok": False, "message": f"连接失败: {str(e)}"})
