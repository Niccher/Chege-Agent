from fastapi import APIRouter
from backend.app.api.activity_router import router as activity_router
from backend.app.api.events_router import router as events_router
from backend.app.api.files_router import router as files_router
from backend.app.api.models_router import router as models_router
from backend.app.api.projects_router import router as projects_router
from backend.app.api.runs_router import router as runs_router
from backend.app.api.sessions_router import router as sessions_router
from backend.app.api.settings_router import router as settings_router
from backend.app.api.tools_router import router as tools_router
from backend.app.api.v1.providers import router as providers_router

# Canonical versioned REST API. /api/v1 is the ONLY API prefix.
api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(activity_router)
api_v1_router.include_router(projects_router)
api_v1_router.include_router(sessions_router)
api_v1_router.include_router(runs_router)
api_v1_router.include_router(events_router)
api_v1_router.include_router(files_router)
api_v1_router.include_router(settings_router)
api_v1_router.include_router(models_router)
api_v1_router.include_router(providers_router)
api_v1_router.include_router(tools_router)
