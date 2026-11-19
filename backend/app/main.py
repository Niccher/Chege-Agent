from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.v1 import api_v1_router
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
        openapi_url="/api/v1/openapi.json",
        # Docs are registered manually below so Swagger UI uses our local
        # favicon instead of the cross-origin FastAPI one (blocked by CSP).
        docs_url=None,
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Restrictive CORS (SEC-03)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Security Headers Middleware (SEC-06)
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        # This is a small, frequently redeployed local app. Force revalidation
        # so a new deploy is never masked by a heuristically cached HTML page
        # or asset (ETag/304 still keeps unchanged responses cheap).
        response.headers["Cache-Control"] = "no-cache"
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

    @app.get("/docs", include_in_schema=False, tags=["ui"])
    def swagger_docs():
        # Local favicon avoids the CSP img-src violation from FastAPI's
        # default https://fastapi.tiangolo.com/img/favicon.png.
        return get_swagger_ui_html(
            openapi_url=app.openapi_url,
            title=app.title + " - Swagger UI",
            swagger_favicon_url="/assets/chege.svg",
            swagger_ui_parameters={"deepLinking": True, "persistAuthorization": False},
        )

    # Only the canonical v1 API is exposed. No legacy /api aliases.
    app.include_router(api_v1_router)

    # Static UI: real pages for landing, playground and documentation.
    webui_dir = settings.base_dir / "webui"
    if (webui_dir / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=str(webui_dir / "assets")), name="ui-assets")

        ui_pages = {
            "/": "index.html",
            "/app": "app.html",
            "/guide": "guide.html",
            "/setup": "setup.html",
            "/settings": "settings.html",
            "/tools": "tools.html",
            "/models": "models.html",
            "/api": "api.html",
            "/security": "security.html",
            "/status": "status.html",
        }

        def make_page(filename: str):
            def page():
                return FileResponse(str(webui_dir / filename))
            return page

        for route_path, filename in ui_pages.items():
            app.add_api_route(
                route_path, make_page(filename), methods=["GET"],
                include_in_schema=False, tags=["ui"],
            )

    # Optional pre-built frontend remains a fallback for unmatched paths.
    frontend_dist = settings.base_dir / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run("backend.app.main:app", host=settings.host, port=settings.port, reload=True)
