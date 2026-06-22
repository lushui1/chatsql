"""DataSource Manager — manage multiple data source instances."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.application.datasources import (
    ColumnInfo,
    DataSource,
    DataSourceConfig,
    TableInfo,
    create_datasource,
)


class DataSourceManager:
    """Manage multiple data source instances."""

    def __init__(self):
        self._sources: dict[str, DataSource] = {}
        self._configs: dict[str, DataSourceConfig] = {}

    def add_source(self, config: DataSourceConfig) -> DataSource:
        """Add (or replace) a data source."""
        ds = create_datasource(config)
        self._sources[config.name] = ds
        self._configs[config.name] = config
        return ds

    def get_source(self, name: str) -> DataSource:
        """Get a data source by name."""
        if name not in self._sources:
            raise KeyError(f"Data source '{name}' not found")
        return self._sources[name]

    def get_config(self, name: str) -> DataSourceConfig:
        """Get config for a data source."""
        if name not in self._configs:
            raise KeyError(f"Data source '{name}' not found")
        return self._configs[name]

    def list_sources(self) -> list[dict]:
        """List all data sources (without passwords)."""
        return [cfg.to_public_dict() for cfg in self._configs.values()]

    def remove_source(self, name: str) -> bool:
        """Remove a data source. Returns True if removed."""
        if name in self._sources:
            del self._sources[name]
            del self._configs[name]
            return True
        return False

    def has_source(self, name: str) -> bool:
        return name in self._sources

    async def get_metadata(self, source_name: str, table_name: str | None = None) -> dict:
        """Get metadata for a data source: table list or specific table schema."""
        ds = self.get_source(source_name)
        if table_name is None:
            tables = await ds.list_tables()
            return {
                "source": source_name,
                "tables": [
                    {"name": t.name, "schema": t.schema, "type": t.type, "comment": t.comment}
                    for t in tables
                ],
            }
        else:
            columns = await ds.describe_table(table_name)
            stats = await ds.get_table_stats(table_name)
            return {
                "source": source_name,
                "table": table_name,
                "columns": [
                    {
                        "name": c.name,
                        "type": c.type,
                        "nullable": c.nullable,
                        "default": c.default,
                        "comment": c.comment,
                    }
                    for c in columns
                ],
                "stats": stats,
            }

    async def get_full_metadata(self, source_name: str) -> dict:
        """Get full metadata: all tables + all columns."""
        ds = self.get_source(source_name)
        tables = await ds.list_tables()
        result = {"source": source_name, "dialect": ds.dialect(), "tables": []}
        for t in tables:
            try:
                columns = await ds.describe_table(t.name)
                result["tables"].append({
                    "name": t.name,
                    "comment": t.comment,
                    "columns": [
                        {
                            "name": c.name,
                            "type": c.type,
                            "nullable": c.nullable,
                            "comment": c.comment,
                        }
                        for c in columns
                    ],
                })
            except Exception:
                # Skip tables that fail to describe
                result["tables"].append({"name": t.name, "columns": [], "error": "describe failed"})
        return result

    def save_config_file(self, path: str | Path):
        """Save current configs to JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"sources": []}
        for cfg in self._configs.values():
            d = {
                "name": cfg.name,
                "type": cfg.type,
                "description": cfg.description,
            }
            if cfg.host:
                d["host"] = cfg.host
            if cfg.port:
                d["port"] = cfg.port
            if cfg.database:
                d["database"] = cfg.database
            if cfg.username:
                d["username"] = cfg.username
            if cfg.password:
                d["password"] = cfg.password
            if cfg.url:
                d["url"] = cfg.url
            if cfg.schema and cfg.schema != "main":
                d["schema"] = cfg.schema
            if cfg.extra:
                d["extra"] = cfg.extra
            data["sources"].append(d)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def load_config_file(self, path: str | Path):
        """Load configs from JSON file."""
        path = Path(path)
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        for src in data.get("sources", []):
            cfg = DataSourceConfig(
                name=src["name"],
                type=src["type"],
                description=src.get("description", ""),
                host=src.get("host", ""),
                port=src.get("port", 0),
                database=src.get("database", ""),
                username=src.get("username", ""),
                password=src.get("password", ""),
                url=src.get("url", ""),
                schema=src.get("schema", "main"),
                extra=src.get("extra", {}),
            )
            try:
                self.add_source(cfg)
            except Exception as e:
                import logging
                logging.getLogger("chatsql").warning(
                    f"Failed to load datasource '{cfg.name}': {e}"
                )

    def load_from_env(self):
        """Load configs from CHATSQL_DATASOURCES_JSON env var."""
        raw = os.environ.get("CHATSQL_DATASOURCES_JSON", "")
        if not raw:
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            import logging
            logging.getLogger("chatsql").error("CHATSQL_DATASOURCES_JSON is not valid JSON")
            return
        for src in data.get("sources", []):
            cfg = DataSourceConfig(
                name=src["name"],
                type=src["type"],
                description=src.get("description", ""),
                host=src.get("host", ""),
                port=src.get("port", 0),
                database=src.get("database", ""),
                username=src.get("username", ""),
                password=src.get("password", ""),
                url=src.get("url", ""),
                schema=src.get("schema", "main"),
                extra=src.get("extra", {}),
            )
            try:
                self.add_source(cfg)
            except Exception as e:
                import logging
                logging.getLogger("chatsql").warning(
                    f"Failed to load datasource '{cfg.name}' from env: {e}"
                )

    def load_defaults(self):
        """Load default DuckDB demo source + config file + env."""
        # 1. Always add DuckDB demo
        demo_cfg = DataSourceConfig(
            name="demo",
            type="duckdb",
            url=":memory:",
            description="内置示例数据",
        )
        self.add_source(demo_cfg)

        # 2. Load from config file
        config_path = Path("data/sources.json")
        if config_path.exists():
            self.load_config_file(config_path)

        # 3. Load from env (overrides file)
        self.load_from_env()

    async def execute(self, source_name: str, sql: str) -> dict[str, Any]:
        """Execute SQL on a data source and return results.

        Returns: {columns: [{name, type}], rows: [dict], row_count: int}
        """
        ds = self.get_source(source_name)
        return await ds.execute(sql)


# ── Singleton ──

_manager: DataSourceManager | None = None


def get_manager() -> DataSourceManager:
    global _manager
    if _manager is None:
        _manager = DataSourceManager()
        _manager.load_defaults()
    return _manager


def reset_manager():
    """Reset manager (for testing)."""
    global _manager
    _manager = None
