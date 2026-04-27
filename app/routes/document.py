from datetime import datetime
from pathlib import Path
import hashlib
import secrets
import string
import re
from typing import Any, Optional, Tuple
from io import BytesIO
from math import ceil

from pypdf import PdfReader
from sqlalchemy import and_, func, or_
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload, aliased
from pydantic import ValidationError

from app.dependencies.auth import get_current_user
from app.models.auth import Usuario
from app.models.regra_documento import RegraDocumento, RegraDocumentoCampo
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
)
from app.services.storage import StorageService

router = APIRouter()
storage = StorageService()

REGRA_TAG_KEY = "regra id"
USER_TAG_KEY = "user_id"
USER_TAG_KEY_LEGACY = "id_user"

def montar_tags_manuais(tags):
    retorno = {}
    for item in tags:
        chave = item.chave.strip()
        valor = item.valor.strip()
        if chave and valor:
            retorno[chave] = valor
    return retorno

def validar_campos_obrigatorios(regra, tags_finais: dict[str, str]):
    faltantes = []
    for campo in regra.campos:
        if not campo.obrigatorio:
            continue
        chave = (campo.chave_tag or "").strip()
        if not chave:
            continue
        valor = tags_finais.get(chave)
        if valor is None or str(valor).strip() == "":
            faltantes.append(chave)

    if faltantes:
        raise HTTPException(
            status_code=400,
            detail=f"Campos obrigatórios não preenchidos: {', '.join(faltantes)}",
        )

def anexar_tags_sistema(tags_finais: dict[str, str], pessoa_id: int, regra_id: int | None = None):
    tags_finais[USER_TAG_KEY] = str(pessoa_id)
    if regra_id is not None:
        tags_finais[REGRA_TAG_KEY] = str(regra_id)
    return tags_finais

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


def generate_document_uuid12() -> str:
    return secrets.token_hex(32)

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


def only_digits(value: str | None) -> str:
    return re.sub(r"\D+", "", value or "")


def is_valid_cpf(value: str | None) -> bool:
    cpf = only_digits(value)
    if len(cpf) != 11:
        return False
    if cpf == cpf[0] * 11:
        return False

    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    resto = (soma * 10) % 11
    d1 = 0 if resto == 10 else resto
    if d1 != int(cpf[9]):
        return False

    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    resto = (soma * 10) % 11
    d2 = 0 if resto == 10 else resto
    return d2 == int(cpf[10])


def is_valid_cnpj(value: str | None) -> bool:
    cnpj = only_digits(value)
    if len(cnpj) != 14:
        return False
    if cnpj == cnpj[0] * 14:
        return False

    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    soma = sum(int(cnpj[i]) * pesos1[i] for i in range(12))
    resto = soma % 11
    d1 = 0 if resto < 2 else 11 - resto
    if d1 != int(cnpj[12]):
        return False

    pesos2 = [6] + pesos1
    soma = sum(int(cnpj[i]) * pesos2[i] for i in range(13))
    resto = soma % 11
    d2 = 0 if resto < 2 else 11 - resto
    return d2 == int(cnpj[13])


def format_cpf(value: str | None) -> str | None:
    cpf = only_digits(value)
    if len(cpf) != 11:
        return None
    return f"{cpf[0:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:11]}"


def format_cnpj(value: str | None) -> str | None:
    cnpj = only_digits(value)
    if len(cnpj) != 14:
        return None
    return f"{cnpj[0:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:14]}"


def build_query_variants(q: str) -> list[str]:
    variants: list[str] = []
    base = (q or "").strip()
    if not base:
        return variants

    variants.append(base)

    digits = only_digits(base)
    if digits and digits != base:
        variants.append(digits)

    if is_valid_cpf(digits):
        masked = format_cpf(digits)
        if masked:
            variants.append(masked)
    elif is_valid_cnpj(digits):
        masked = format_cnpj(digits)
        if masked:
            variants.append(masked)

    # unique, keep order
    seen = set()
    out: list[str] = []
    for item in variants:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out

@router.post("/upload", response_model=DocumentoOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    meta: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
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

    regra = None
    if meta_obj.regra_id is not None:
        regra = (
            db.query(RegraDocumento)
            .options(joinedload(RegraDocumento.campos))
            .filter(RegraDocumento.id == meta_obj.regra_id)
            .first()
        )
        if not regra:
            raise HTTPException(status_code=404, detail="Regra não encontrada.")

    tags_finais = montar_tags_manuais(meta_obj.tags)

    # garante que ninguém injete id_user manualmente
    tags_finais.pop(USER_TAG_KEY, None)
    tags_finais.pop(USER_TAG_KEY_LEGACY, None)

    if regra:
        validar_campos_obrigatorios(regra, tags_finais)

    tags_finais = anexar_tags_sistema(
        tags_finais=tags_finais,
        pessoa_id=current_user.pessoa_id,
        regra_id=meta_obj.regra_id,
    )

    hoje_str = datetime.utcnow().strftime("%Y-%m-%d")
    document_uuid = generate_document_uuid12()

    ext = Path(file.filename).suffix.lower()
    bucket_key = f"{meta_obj.user_id}/{hoje_str}/{document_uuid}{ext}"

    content = await file.read()
    tamanho_bytes = len(content)
    hash_sha256 = hashlib.sha256(content).hexdigest() if tamanho_bytes > 0 else None

    try:
        storage.upload_bytes(
            content=content,
            key=bucket_key,
            content_type=file.content_type or "application/octet-stream",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao enviar arquivo para o storage: {e}",
        )

    documento = Documento(
        uuid=document_uuid,
        user_id=meta_obj.user_id,
        bucket_key=bucket_key,
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        tamanho_bytes=tamanho_bytes,
        hash_sha256=hash_sha256,
    )

    for chave, valor in tags_finais.items():
        documento.tags.append(
            Tag(
                chave=chave,
                valor=valor,
            )
        )

    db.add(documento)
    db.flush()

    texto_extraido = None
    texto_normalizado = None
    total_paginas = None
    status_processamento = False
    erro_processamento = None
    processado_em = None

    try:
        if documento.content_type.lower() == "application/pdf" or Path(documento.filename).suffix.lower() == ".pdf":
            texto_extraido, total_paginas = extract_text_from_pdf_bytes(content)
            if looks_like_empty_extraction(texto_extraido, total_paginas):
                status_processamento = False
                erro_processamento = "Não foi possível extrair texto útil do PDF. Provável PDF escaneado ou sem camada de texto."
                texto_extraido = None
                texto_normalizado = None
            else:
                texto_normalizado = normalize_text(texto_extraido)
                status_processamento = True
            processado_em = datetime.utcnow()
    except Exception as e:
        status_processamento = False
        erro_processamento = str(e)
        texto_extraido = None
        texto_normalizado = None
        total_paginas = None
        processado_em = datetime.utcnow()

    db.add(
        DocumentoConteudo(
            documento_id=documento.id,
            texto_extraido=texto_extraido,
            texto_normalizado=texto_normalizado,
            total_paginas=total_paginas,
            ocr_aplicado=False,
            status_processamento=status_processamento,
            erro_processamento=erro_processamento,
            processado_em=processado_em,
        )
    )

    db.commit()
    db.refresh(documento)

    return documento

@router.get(
    "/search",
    response_model=DocumentoSearchResponse,
)
def search_documents(
    user_id: int = Query(..., ge=1),
    tag_chave: Optional[str] = None,
    tag_valor: Optional[str] = None,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> Any:
    if (tag_chave is None) != (tag_valor is None):
        raise HTTPException(
            status_code=400,
            detail="Informe tag_chave e tag_valor juntos.",
        )

    base_query = (
        db.query(Documento)
        .options(joinedload(Documento.tags))
    )

    TagUser = aliased(Tag)
    base_query = base_query.filter(
        db.query(TagUser.id)
        .filter(
            TagUser.documento_id == Documento.id,
            TagUser.chave.in_([USER_TAG_KEY, USER_TAG_KEY_LEGACY]),
            TagUser.valor == str(user_id),
        )
        .exists()
    )

    if tag_chave is not None and tag_valor is not None:
        TagFiltro = aliased(Tag)
        base_query = base_query.filter(
            db.query(TagFiltro.id)
            .filter(
                TagFiltro.documento_id == Documento.id,
                TagFiltro.chave == tag_chave,
                TagFiltro.valor == tag_valor,
            )
            .exists()
        )

    if q is not None:
        variants = build_query_variants(q)
        if not variants:
            variants = [q]

        like_patterns = [f"%{v}%" for v in variants if v is not None]

        TagQ = aliased(Tag)
        ConteudoQ = aliased(DocumentoConteudo)

        base_query = (
            base_query
            .outerjoin(TagQ, TagQ.documento_id == Documento.id)
            .outerjoin(ConteudoQ, ConteudoQ.documento_id == Documento.id)
            .filter(
                or_(
                    or_(*[TagQ.chave.ilike(p) for p in like_patterns]),
                    or_(*[TagQ.valor.ilike(p) for p in like_patterns]),
                    or_(*[Documento.filename.ilike(p) for p in like_patterns]),
                    or_(*[Documento.filepath.ilike(p) for p in like_patterns]),
                    or_(*[ConteudoQ.texto_extraido.ilike(p) for p in like_patterns]),
                    or_(*[ConteudoQ.texto_normalizado.ilike(p) for p in like_patterns]),
                )
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
        body = storage.download_stream(documento.bucket_key)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao buscar arquivo no storage: {e}",
        )

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
def list_user_tags(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    rows = (
        db.query(RegraDocumentoCampo.nome_campo)
        .join(RegraDocumento, RegraDocumento.id == RegraDocumentoCampo.regra_id)
        .filter(RegraDocumento.user_id == current_user.pessoa_id)
        .distinct()
        .order_by(RegraDocumentoCampo.nome_campo.asc())
        .all()
    )

    return [row[0] for row in rows if row and row[0]]

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
        storage.delete_object(documento.bucket_key)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao apagar arquivo no storage: {e}",
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
            pdf_bytes = storage.download_bytes(documento.bucket_key)
        except Exception as e:
            conteudo.status_processamento = "erro"
            conteudo.erro_processamento = f"Falha ao buscar arquivo no storage: {str(e)}"
            conteudo.processado_em = datetime.utcnow()
            db.commit()
            db.refresh(conteudo)
            raise HTTPException(status_code=404, detail=f"Arquivo não encontrado no storage: {documento.bucket_key}")

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