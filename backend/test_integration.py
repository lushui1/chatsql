"""ChatSQL integration test — verify all modules work together."""
import asyncio
import sys

async def test():
    print("=" * 50)
    print("ChatSQL Integration Test")
    print("=" * 50)
    
    # 1. Multi-source manager
    from app.application.datasources.manager import get_manager, reset_manager
    reset_manager()
    mgr = get_manager()
    sources = mgr.list_sources()
    print(f"\n[1] Data Sources: {len(sources)} loaded")
    for s in sources:
        print(f"    - {s['name']} ({s['type']})")
    
    # 2. Auto metadata
    meta = await mgr.get_full_metadata("demo")
    print(f"\n[2] Auto Metadata ({len(meta['tables'])} tables):")
    for t in meta["tables"]:
        cols = ", ".join(c["name"] for c in t["columns"])
        comment = f" — {t['comment']}" if t.get('comment') else ""
        print(f"    {t['name']}: {cols}{comment}")
    
    # 3. SQL execution
    ds = mgr.get_source("demo")
    result = await ds.execute("SELECT city, gmv FROM orders LIMIT 3")
    print(f"\n[3] SQL Execute: {len(result['rows'])} rows returned")
    for r in result["rows"]:
        print(f"    {r}")
    
    # 4. LLM providers
    from app.application.llm import PROVIDER_DEFAULTS
    print(f"\n[4] LLM Providers: {len(PROVIDER_DEFAULTS)} configured")
    for k, v in PROVIDER_DEFAULTS.items():
        models = ', '.join(v.get('models', [])[:2])
        print(f"    {k}: {v['base_url']}  models=[{models}]")
    
    # 5. Builtin tools
    from app.application.tools.builtin_tools import get_default_tools
    tools = get_default_tools()
    print(f"\n[5] Builtin Tools: {len(tools)} available")
    for t in tools:
        print(f"    - {t.get('name', t.get('function', {}).get('name', '?'))}")
    
    # 6. Learn service
    from app.application.learn.service import LearnService
    print(f"\n[6] Learn Service: importable")
    
    # 7. Routes
    from app.main import app
    import json
    schema = app.openapi()
    paths = schema.get("paths", {})
    print(f"\n[7] API Routes: {len(paths)} endpoints")
    for p in sorted(paths):
        methods = [m.upper() for m in paths[p] if m in ("get","post","put","delete","patch")]
        for m in methods:
            print(f"    {m:6s} {p}")
    
    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
    print("=" * 50)

asyncio.run(test())
