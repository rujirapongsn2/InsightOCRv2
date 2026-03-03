from fastapi import APIRouter
from app.api.v1.endpoints import schemas, jobs, documents, auth, users, settings, templates, ai_settings, dashboard, activity_logs, integrations, chat

api_router = APIRouter()
api_router.include_router(auth.router, tags=["login"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(schemas.router, prefix="/schemas", tags=["schemas"])
api_router.include_router(templates.router, prefix="/templates", tags=["templates"])
api_router.include_router(ai_settings.router, prefix="/ai-settings", tags=["ai-settings"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(activity_logs.router, prefix="/activity-logs", tags=["activity-logs"])
api_router.include_router(integrations.router, prefix="/integrations", tags=["integrations"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
