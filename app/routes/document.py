from datetime import datetime
from pathlib import Path
import hashlib
import secrets
import string
import os
from typing import Any
import re
from pathlib import Path
from typing import Tuple
from pypdf import PdfReader
from io import BytesIO

from math import ceil

import boto3
from typing import Any, List, Optional
from sqlalchemy import func, text, or_
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from pydantic import ValidationError

from app.database.connection import get_db
from app.models.document import Documento, Tag, DocumentoConteudo
from app.schemas.document import (
    DocumentoOut,
    DocumentoSearchResponse,
    DocumentoUploadMeta,
    DocumentoUpdate,
    PaginationMeta,
    DocumentoConteudoCreateResponse,
    DocumentoConteudoResponse,
    DocumentoSearchInteligentResponse,
    DocumentoSearchInteligentItem,
    TagOut,
)

router = APIRouter()

S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "")
if not S3_BUCKET_NAME:
    raise RuntimeError("S3_BUCKET_NAME não configurado no .env")

s3_client = boto3.client("s3")

def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\x00", " ")
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> Tuple[str, int]:
    reader = PdfReader(BytesIO(pdf_bytes))
    total_paginas = len(reader.pages)

    textos = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        textos.append(page_text)

    texto_extraido = "\n\n".join(textos).strip()
    return texto_extraido, total_paginas

def looks_like_empty_extraction(text: str, total_paginas: int) -> bool:
    if not text or not text.strip():
        return True

    texto_limpo = text.strip()
    if len(texto_limpo) < 20 and total_paginas >= 1:
        return True

    letras = sum(ch.isalpha() for ch in texto_limpo)
    if total_paginas > 0 and letras < (5 * total_paginas):
        return True

    return False

def generate_uuid12() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(12))

def build_snippet(text: Optional[str], query: str, max_len: int = 220) -> Optional[str]:
    if not text:
        return None

    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None

    q = query.strip()
    if not q:
        return text[:max_len]

    pos = text.lower().find(q.lower())
    if pos == -1:
        return text[:max_len]

    start = max(0, pos - 80)
    end = min(len(text), pos + len(q) + 120)

    trecho = text[start:end].strip()

    if start > 0:
        trecho = "..." + trecho
    if end < len(text):
        trecho = trecho + "..."

    return trecho

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
    base_query = (
        db.query(Documento)
        .options(joinedload(Documento.tags))
    )

    if cliente_id is not None:
        base_query = base_query.filter(Documento.cliente_id == cliente_id)

    # Só entra em joins se realmente precisar filtrar por tags/conteúdo
    if tag_chave is not None or tag_valor is not None or q is not None:
        base_query = (
            base_query
            .outerjoin(Tag, Tag.documento_id == Documento.id)
            .outerjoin(DocumentoConteudo, DocumentoConteudo.documento_id == Documento.id)
        )

        if tag_chave is not None:
            base_query = base_query.filter(Tag.chave == tag_chave)

        if tag_valor is not None:
            base_query = base_query.filter(Tag.valor == tag_valor)

        if q is not None:
            like_pattern = f"%{q}%"
            base_query = base_query.filter(
                or_(
                    Tag.chave.ilike(like_pattern),
                    Tag.valor.ilike(like_pattern),
                    Documento.filename.ilike(like_pattern),
                    DocumentoConteudo.texto_extraido.ilike(like_pattern),
                    DocumentoConteudo.texto_normalizado.ilike(like_pattern),
                )
            )

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

    return {
        "items": documentos,
        "meta": meta,
    }

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

@router.post("/{document_id}/content/register", response_model=DocumentoConteudoCreateResponse)
def register_document_content(
    document_id: int,
    db: Session = Depends(get_db),
):
    documento = db.query(Documento).filter(Documento.id == document_id).first()
    if not documento:
        raise HTTPException(status_code=404, detail="Documento não encontrado")

    existente = (
        db.query(DocumentoConteudo)
        .filter(DocumentoConteudo.documento_id == document_id)
        .first()
    )
    if existente:
        raise HTTPException(status_code=409, detail="Conteúdo do documento já registrado")

    conteudo = DocumentoConteudo(
        documento_id=document_id,
        status_processamento="pendente",
        ocr_aplicado=False,
    )

    db.add(conteudo)
    db.commit()
    db.refresh(conteudo)

    return conteudo

@router.get("/{document_id}/content", response_model=DocumentoConteudoResponse)
def get_document_content(
    document_id: int,
    db: Session = Depends(get_db),
):
    conteudo = (
        db.query(DocumentoConteudo)
        .filter(DocumentoConteudo.documento_id == document_id)
        .first()
    )

    if not conteudo:
        raise HTTPException(status_code=404, detail="Conteúdo do documento não encontrado")

    return conteudo

@router.post("/{document_id}/content/process", response_model=DocumentoConteudoResponse)
def process_document_content(
    document_id: int,
    db: Session = Depends(get_db),
):
    documento = db.query(Documento).filter(Documento.id == document_id).first()
    if not documento:
        raise HTTPException(status_code=404, detail="Documento não encontrado")

    if not documento.bucket_key:
        raise HTTPException(status_code=400, detail="Documento sem bucket_key definido")

    if documento.content_type.lower() != "application/pdf":
        raise HTTPException(status_code=400, detail="Apenas arquivos PDF podem ser processados nesta rota")

    conteudo = (
        db.query(DocumentoConteudo)
        .filter(DocumentoConteudo.documento_id == document_id)
        .first()
    )

    if not conteudo:
        conteudo = DocumentoConteudo(
            documento_id=document_id,
            status_processamento="pendente",
            ocr_aplicado=False,
        )
        db.add(conteudo)
        db.commit()
        db.refresh(conteudo)

    try:
        conteudo.status_processamento = "processando"
        conteudo.erro_processamento = None
        db.commit()

        try:
            obj = s3_client.get_object(
                Bucket=S3_BUCKET_NAME,
                Key=documento.bucket_key,
            )
            pdf_bytes = obj["Body"].read()
        except Exception as e:
            conteudo.status_processamento = "erro"
            conteudo.erro_processamento = f"Falha ao buscar arquivo no bucket: {str(e)}"
            conteudo.processado_em = datetime.utcnow()
            db.commit()
            db.refresh(conteudo)
            raise HTTPException(status_code=404, detail=f"Arquivo não encontrado no bucket: {documento.bucket_key}")

        texto_extraido, total_paginas = extract_text_from_pdf_bytes(pdf_bytes)

        if looks_like_empty_extraction(texto_extraido, total_paginas):
            conteudo.status_processamento = "erro"
            conteudo.erro_processamento = "Não foi possível extrair texto útil do PDF. Provável PDF escaneado ou sem camada de texto."
            conteudo.texto_extraido = None
            conteudo.texto_normalizado = None
            conteudo.total_paginas = total_paginas
            conteudo.ocr_aplicado = False
            conteudo.processado_em = datetime.utcnow()
            db.commit()
            db.refresh(conteudo)
            return conteudo

        conteudo.texto_extraido = texto_extraido
        conteudo.texto_normalizado = normalize_text(texto_extraido)
        conteudo.total_paginas = total_paginas
        conteudo.ocr_aplicado = False
        conteudo.status_processamento = "pronto"
        conteudo.erro_processamento = None
        conteudo.processado_em = datetime.utcnow()

        db.commit()
        db.refresh(conteudo)
        return conteudo

    except HTTPException:
        raise

    except Exception as e:
        conteudo.status_processamento = "erro"
        conteudo.erro_processamento = str(e)
        conteudo.processado_em = datetime.utcnow()
        db.commit()
        db.refresh(conteudo)
        raise HTTPException(status_code=500, detail=f"Erro ao processar documento: {str(e)}")