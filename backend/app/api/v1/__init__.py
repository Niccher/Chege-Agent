from fastapi import APIRouter
from backend.app.api.auth_router import router as auth_router
from backend.app.api.events_router import router as events_router
from backend.app.api.files_router import router as files_router
from backend.app.api.projects_router import router as projects_router
from backend.app.api.runs_router import router as runs_router
from backend.app.api.sessions_router import router as sessions_router
from backend.app.api.settings_router import router as settings_router
from backend.app.api.v1.providers import router as providers_router

# Canonical Versioned REST API Router (ENG-01)
api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth_router)
api_v1_router.include_router(projects_router)
api_v1_router.include_router(sessions_router)
api_v1_router.include_router(runs_router)
api_v1_router.include_router(events_router)
api_v1_router.include_router(files_router)
api_v1_router.include_router(settings_router)
api_v1_router.include_router(providers_router)

# Backward-Compatibility Alias Router for legacy clients calling /api/* directly
legacy_api_router = APIRouter(prefix="/api")
legacy_api_router.include_router(auth_router)
legacy_api_router.include_router(projects_router)
legacy_api_router.include_router(sessions_router)
legacy_api_router.include_router(runs_router)
legacy_api_router.include_router(events_router)
legacy_api_router.include_router(files_router)
legacy_api_router.include_router(settings_router)
legacy_api_router.include_router(providers_router)
