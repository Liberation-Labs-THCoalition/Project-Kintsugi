"""Kintsugi FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from kintsugi import __version__
from kintsugi.config.settings import settings

logger = logging.getLogger("kintsugi")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Database is optional for the framework layer: agents, sessions, the
    # dashboard, and the Oracle Loop are all process-local. Persistent
    # memory (CMA, temporal log) activates only when Postgres is reachable.
    # Load the built-in skill chip catalog so agents have skills to route to.
    try:
        from kintsugi.skills.bootstrap import register_builtin_chips

        register_builtin_chips()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("skill bootstrap failed: %s", exc)

    app.state.db_available = False
    try:
        from kintsugi.db import engine

        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        app.state.db_available = True
    except Exception as exc:
        logger.warning(
            "database unavailable (%s) — running without persistent memory", exc
        )

    yield

    if app.state.db_available:
        from kintsugi.db import engine

        await engine.dispose()


app = FastAPI(
    title="Kintsugi Engine",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Route registration (graceful if modules missing) ---
_route_modules = [
    # Legacy org-scoped routes (DB-backed)
    "kintsugi.api.routes.health",
    "kintsugi.api.routes.agent",
    "kintsugi.api.routes.agent_v2",
    "kintsugi.api.routes.memory",
    "kintsugi.api.routes.config",
    # Framework layer (v1): agents, sessions, skills, oracle, events
    "kintsugi.api.routes.fleet",
    "kintsugi.api.routes.sessions",
    "kintsugi.api.routes.skills",
    "kintsugi.api.routes.oracle",
    "kintsugi.api.routes.events",
]

for _mod_path in _route_modules:
    try:
        import importlib

        _mod = importlib.import_module(_mod_path)
        app.include_router(_mod.router)
    except (ImportError, AttributeError) as _exc:
        logger.warning("route module %s not loaded: %s", _mod_path, _exc)

# --- Dashboard (htmx, served from the package) ---
if settings.DASHBOARD_ENABLED:
    try:
        from kintsugi.dashboard import router as dashboard_router, static_dir

        app.include_router(dashboard_router)
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/", include_in_schema=False)
        async def root() -> RedirectResponse:
            return RedirectResponse("/dashboard")

    except Exception as _exc:  # pragma: no cover - packaging error
        logger.warning("dashboard not loaded: %s", _exc)


# --- Exception handlers ---

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(PermissionError)
async def permission_error_handler(request: Request, exc: PermissionError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
