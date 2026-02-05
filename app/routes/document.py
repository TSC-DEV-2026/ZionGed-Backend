from datetime import datetime
from pathlib import Path
import hashlib
import secrets
import string
import os
from typing import Any

from numpy import ceil

import boto3
from typing import Any, List, Optional
from sqlalchemy import func
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from pydantic import ValidationError

from app.database.connection import get_db
from app.models.document import Documento, Tag
from app.schemas.document import DocumentoOut, DocumentoSearchResponse, DocumentoUploadMeta, DocumentoUpdate, PaginationMeta

router = APIRouter()

S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "")
if not S3_BUCKET_NAME:
    raise RuntimeError("S3_BUCKET_NAME não configurado no .env")

s3_client = boto3.client("s3")


def generate_uuid12() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(12))


@router.post(
    "/upload",
    response_model=DocumentoOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    meta: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> Any:
    try:
        meta_obj = DocumentoUploadMeta.model_validate_json(meta)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao validar meta: {e.errors()}",
        )

    if not file.filename:
        raise HTTPException(status_code=400, detail="Arquivo sem nome.")

    hoje_str = datetime.utcnow().strftime("%Y-%m-%d")
    uuid12 = generate_uuid12()

    ext = Path(file.filename).suffix.lower()
    bucket_key = f"{meta_obj.cliente_id}/{hoje_str}/{uuid12}{ext}"

    content = await file.read()
    tamanho_bytes = len(content)

    import base64

    file_base64 = base64.b64encode(content).decode("utf-8")
    hash_sha256 = hashlib.sha256(content).hexdigest() if tamanho_bytes > 0 else None
    try:
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=bucket_key,
            Body=content,
            ContentType=file.content_type or "application/octet-stream",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao enviar arquivo para o bucket: {e}",
        )

    documento = Documento(
        uuid=uuid12,
        cliente_id=meta_obj.cliente_id,
        bucket_key=bucket_key,
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        tamanho_bytes=tamanho_bytes,
        hash_sha256=hash_sha256,
    )

    for tag in meta_obj.tags:
        documento.tags.append(
            Tag(
                chave=tag.chave,
                valor=tag.valor,
            )
        )

    db.add(documento)
    db.commit()
    db.refresh(documento)

    return documento

@router.get(
    "/search",
    response_model=DocumentoSearchResponse,
)
def search_documents(
    cliente_id: Optional[int] = None,
    tag_chave: Optional[str] = None,
    tag_valor: Optional[str] = None,
    q: Optional[str] = None,

    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),

    db: Session = Depends(get_db),
) -> Any:
    base_query = db.query(Documento).options(joinedload(Documento.tags))

    if cliente_id is not None:
        base_query = base_query.filter(Documento.cliente_id == cliente_id)

    if tag_chave is not None or tag_valor is not None or q is not None:
        base_query = base_query.join(Tag)

        if tag_chave is not None:
            base_query = base_query.filter(Tag.chave == tag_chave)

        if tag_valor is not None:
            base_query = base_query.filter(Tag.valor == tag_valor)

        if q is not None:
            like_pattern = f"%{q}%"
            base_query = base_query.filter(Tag.valor.ilike(like_pattern))

        base_query = base_query.distinct()

    total_items = (
        base_query
        .with_entities(func.count(func.distinct(Documento.id)))
        .scalar()
    ) or 0

    total_pages = ceil(total_items / page_size) if total_items > 0 else 0

    offset = (page - 1) * page_size

    documentos = (
        base_query
        .order_by(Documento.criado_em.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    meta = PaginationMeta(
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=total_pages,
        has_next=(page < total_pages) if total_pages else False,
        has_prev=(page > 1) if total_pages else False,
    )

    return {"items": documentos, "meta": meta}

@router.get(
    "/{uuid}/download",
)
def download_document(
    uuid: str,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    documento = (
        db.query(Documento)
        .options(joinedload(Documento.tags))
        .filter(Documento.uuid == uuid)
        .first()
    )

    if not documento:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")

    try:
        obj = s3_client.get_object(
            Bucket=S3_BUCKET_NAME,
            Key=documento.bucket_key,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao buscar arquivo no bucket: {e}",
        )

    body = obj["Body"]

    def iterfile():
        for chunk in body.iter_chunks(chunk_size=8192):
            if chunk:
                yield chunk

    return StreamingResponse(
        iterfile(),
        media_type=documento.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{documento.filename}"'
        },
    )

@router.get("/tags")
def listar_tags_disponiveis(
    cliente_id: int | None = None,
    db: Session = Depends(get_db),
):
    """
    Retorna a lista de chaves de tags disponíveis no banco,
    opcionalmente filtradas por cliente_id.
    Exemplo de retorno:
    { "tags": ["tipo", "cpf", "competencia"] }
    """

    query = db.query(Tag.chave).distinct()

    if cliente_id is not None:
        query = (
            db.query(Tag.chave)
            .join(Documento, Documento.id == Tag.documento_id)
            .filter(Documento.cliente_id == cliente_id)
            .distinct()
        )

    rows = query.order_by(Tag.chave).all()
    tags = [row[0] for row in rows]

    return {"tags": tags}

@router.put(
    "/{uuid}/update",
    response_model=DocumentoOut,
)
def update_document(
    uuid: str,
    payload: DocumentoUpdate,
    db: Session = Depends(get_db),
) -> Any:
    documento = (
        db.query(Documento)
        .options(joinedload(Documento.tags))
        .filter(Documento.uuid == uuid)
        .first()
    )

    if not documento:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")

    if payload.filename is not None:
        documento.filename = payload.filename

    if payload.tags is not None:
        documento.tags.clear()
        for tag in payload.tags:
            documento.tags.append(Tag(chave=tag.chave, valor=tag.valor))

    db.add(documento)
    db.commit()
    db.refresh(documento)

    return documento

@router.delete(
    "/{uuid}/delete",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_document(
    uuid: str,
    db: Session = Depends(get_db),
) -> Response:
    documento = (
        db.query(Documento)
        .filter(Documento.uuid == uuid)
        .first()
    )

    if not documento:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")

    try:
        s3_client.delete_object(
            Bucket=S3_BUCKET_NAME,
            Key=documento.bucket_key,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao apagar arquivo no bucket: {e}",
        )

    db.delete(documento)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
