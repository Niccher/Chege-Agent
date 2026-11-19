from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.auth_router import router as auth_router
from backend.app.api.events_router import router as events_router
from backend.app.api.files_router import router as files_router
from backend.app.api.projects_router import router as projects_router
from backend.app.api.runs_router import router as runs_router
from backend.app.api.sessions_router import router as sessions_router
from backend.app.api.settings_router import router as settings_router
from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging, get_logger
from backend.app.db.database import init_db

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: configure logging and initialize database
    configure_logging()
    logger.info("Starting Chege Agent harness...")
    init_db()
    yield
    # Shutdown
    logger.info("Shutting down Chege Agent harness.")


def create_app() -> FastAPI:
    """Application factory for Chege Agent (ENG-01)."""
    settings = get_settings()

    app = FastAPI(
        title="Chege Agent API",
        version="0.2.0",
        lifespan=lifespan,
    )

    # Restrictive CORS (SEC-03)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Security Headers Middleware (SEC-06)
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        # Content Security Policy (SEC-06)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "connect-src 'self' ws: wss:;"
        )
        return response

    # Health & Readiness probes (ENG-07)
    @app.get("/healthz", tags=["health"])
    def healthz():
        return {"status": "ok", "version": "0.2.0"}

    @app.get("/readyz", tags=["health"])
    def readyz():
        return {"status": "ready"}

    # Include API Routers
    app.include_router(auth_router)
    app.include_router(projects_router)
    app.include_router(sessions_router)
    app.include_router(runs_router)
    app.include_router(events_router)
    app.include_router(files_router)
    app.include_router(settings_router)

    # Static assets and UI fallback
    frontend_dist = settings.base_dir / "frontend" / "dist"
    legacy_webui = settings.base_dir / "webui" / "index.html"

    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
    elif legacy_webui.exists():
        @app.get("/", tags=["ui"])
        def serve_legacy_index():
            return FileResponse(str(legacy_webui))

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run("backend.app.main:app", host=settings.host, port=settings.port, reload=True)
