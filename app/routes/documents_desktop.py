import hashlib
import os
import secrets
import string
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.orm import Session, joinedload

from app.database.connection import get_db
from app.models.documents_desktop import DocumentoDesktop, DocumentoDesktopTag
from app.schemas.documents_desktop import (
    DocumentoDesktopOut,
    UploadDesktopResponse,
    UploadMetaDesktopIn,
)

router = APIRouter(prefix="/documents-desktop", tags=["Documents Desktop"])


def generate_uuid12() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(12))


@router.post(
    "/upload",
    response_model=UploadDesktopResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_document_desktop(
    meta: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> Any:
    try:
        payload = UploadMetaDesktopIn.model_validate_json(meta)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao validar meta: {e.errors()}",
        )

    if not file.filename:
        raise HTTPException(status_code=400, detail="Arquivo sem nome.")

    os.makedirs("storage/uploads_desktop", exist_ok=True)

    uuid12 = generate_uuid12()
    ext = Path(file.filename).suffix.lower()
    nome_fisico = f"{uuid12}{ext}"
    caminho_local = os.path.join("storage", "uploads_desktop", nome_fisico)

    conteudo_bytes = file.file.read()
    with open(caminho_local, "wb") as f:
        f.write(conteudo_bytes)

    tamanho_bytes = len(conteudo_bytes)
    hash_sha256 = hashlib.sha256(conteudo_bytes).hexdigest() if tamanho_bytes > 0 else None

    documento = DocumentoDesktop(
        cliente_id=payload.cliente_id,
        regra_id=payload.regra_id,
        uuid=uuid12,
        nome_original=file.filename,
        nome_fisico=nome_fisico,
        extensao=ext,
        content_type=file.content_type or "application/octet-stream",
        tamanho_bytes=tamanho_bytes,
        hash_sha256=hash_sha256,
        caminho_arquivo=caminho_local,
        status_documento="cadastrado",
    )
    db.add(documento)
    db.flush()

    for tag in payload.tags:
        db.add(
            DocumentoDesktopTag(
                documento_id=documento.id,
                chave=tag.chave,
                valor=tag.valor,
            )
        )

    db.commit()

    return {
        "message": "Upload realizado com sucesso.",
        "documento_id": documento.id,
        "cliente_id": payload.cliente_id,
        "regra_id": payload.regra_id,
        "arquivo": file.filename,
        "status_documento": "cadastrado",
        "tags": [tag.model_dump() for tag in payload.tags],
    }


@router.get("/{documento_id}", response_model=DocumentoDesktopOut)
def obter_documento_desktop(documento_id: int, db: Session = Depends(get_db)):
    item = (
        db.query(DocumentoDesktop)
        .options(joinedload(DocumentoDesktop.tags))
        .filter(DocumentoDesktop.id == documento_id)
        .first()
    )

    if not item:
        raise HTTPException(status_code=404, detail="Documento desktop não encontrado.")

    return item