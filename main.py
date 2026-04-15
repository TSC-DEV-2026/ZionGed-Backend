from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database.connection import engine, Base
from app.models.auth import Pessoa, Usuario
from app.models.document import Documento, Tag
from app.routes import api_router
from app.routes.regras import router as regras_router
from app.routes.documents_desktop import router as documents_desktop_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="ZionGED API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://zionged-frontend.onrender.com", "https://ged.ziondocs.com.br", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(regras_router)
app.include_router(documents_desktop_router)

@app.get("/health")
def health():
    return {"status": "ok"}
