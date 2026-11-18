from __future__ import annotations

from fastapi import APIRouter

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.documents import router as documents_router, knowledge_router
from app.api.health import router as health_router
from app.api.history import router as history_router
from app.api.metrics import router as metrics_router
from app.api.pqa import router as pqa_router
from app.api.projects import router as projects_router, journals_router
from app.api.session_documents import router as session_documents_router
from app.api.sessions import router as sessions_router
from app.api.tasks import router as tasks_router
from app.api.users import router as users_router

router = APIRouter()

router.include_router(admin_router)
router.include_router(auth_router)
router.include_router(chat_router)
router.include_router(documents_router)
router.include_router(knowledge_router)
router.include_router(health_router)
router.include_router(history_router)
router.include_router(metrics_router)
router.include_router(pqa_router)
router.include_router(projects_router)
router.include_router(journals_router)
router.include_router(session_documents_router)
router.include_router(sessions_router)
router.include_router(tasks_router)
router.include_router(users_router)

__all__ = ["router"]
