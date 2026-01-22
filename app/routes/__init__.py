from fastapi import APIRouter
from .auth import router as auth_router
from .document import router as document_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["Auth"])
api_router.include_router(document_router, prefix="/documents", tags=["Documents"])
