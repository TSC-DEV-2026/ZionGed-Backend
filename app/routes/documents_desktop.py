import hashlib
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session, joinedload

from app.database.connection import get_db
from app.models.document import Documento, Tag, DocumentoConteudo
from app.models.regra_documento import RegraDocumento
from app.schemas.documents_desktop import UploadDesktopMeta
from app.services.document_processor import extrair_texto_arquivo
from app.services.storage import StorageService

router = APIRouter(prefix="/documents-desktop", tags=["Documents Desktop"])
storage = StorageService()


@router.post("/upload")
async def upload_document_desktop(
    meta: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    try:
        meta_data = UploadDesktopMeta.model_validate_json(meta)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Meta inválido: {e}")

    regra = (
        db.query(RegraDocumento)
        .options(joinedload(RegraDocumento.campos))
        .filter(RegraDocumento.id == meta_data.regra_id)
        .first()
    )

    if not regra:
        raise HTTPException(status_code=404, detail="Regra não encontrada.")

    nome_original = file.filename or "arquivo_sem_nome"
    content_type = file.content_type or "application/octet-stream"

    nome_sem_extensao = Path(nome_original).stem
    partes_nome = [p.strip() for p in nome_sem_extensao.split("_") if p.strip()]

    tags_arquivo = {}
    for item in meta_data.mapa_nome_arquivo:
        indice = item.posicao - 1
        if 0 <= indice < len(partes_nome):
            valor = partes_nome[indice].strip()
            if valor:
                tags_arquivo[item.chave] = valor

    tags_manuais = {}
    for item in meta_data.tags:
        chave = item.chave.strip()
        valor = item.valor.strip()
        if chave and valor:
            tags_manuais[chave] = valor

    modo = meta_data.modo_tags.strip().lower()

    if modo == "manual":
        tags_finais = tags_manuais
    elif modo == "arquivo":
        tags_finais = tags_arquivo
    elif modo == "hibrido":
        tags_finais = {**tags_arquivo, **tags_manuais}
    else:
        raise HTTPException(status_code=400, detail="modo_tags inválido.")

    try:
        content = await file.read()
        tamanho_bytes = len(content)
        hash_sha256 = hashlib.sha256(content).hexdigest() if tamanho_bytes > 0 else None

        hoje_str = datetime.utcnow().strftime("%Y-%m-%d")
        ext = Path(nome_original).suffix.lower()
        uuid12 = uuid4().hex[:12]
        bucket_key = f"{meta_data.cliente_id}/{hoje_str}/{uuid12}{ext}"

        storage.upload_bytes(
            content=content,
            key=bucket_key,
            content_type=content_type,
        )

        documento = Documento(
            uuid=uuid12,
            cliente_id=meta_data.cliente_id,
            bucket_key=bucket_key,
            filename=nome_original,
            content_type=content_type,
            tamanho_bytes=tamanho_bytes,
            hash_sha256=hash_sha256,
        )

        db.add(documento)
        db.flush()

        for chave, valor in tags_finais.items():
            db.add(
                Tag(
                    documento_id=documento.id,
                    chave=chave,
                    valor=valor,
                )
            )

        texto_extraido = ""
        texto_normalizado = ""
        status_processamento = False
        erro_processamento = None

        try:
            sufixo = Path(nome_original).suffix.lower()
            if sufixo == ".pdf":
                texto_extraido = extrair_texto_arquivo(content) or ""
            else:
                texto_extraido = ""

            texto_normalizado = " ".join(texto_extraido.split()) if texto_extraido else ""
            status_processamento = True
        except Exception as e:
            erro_processamento = str(e)
            status_processamento = False

        db.add(
            DocumentoConteudo(
                documento_id=documento.id,
                texto_extraido=texto_extraido,
                texto_normalizado=texto_normalizado,
                total_paginas=None,
                ocr_aplicado=False,
                status_processamento=status_processamento,
                erro_processamento=erro_processamento,
                processado_em=datetime.utcnow(),
            )
        )

        db.commit()
        db.refresh(documento)

        return {
            "message": "Upload realizado com sucesso.",
            "documento_id": documento.id,
            "uuid": documento.uuid,
            "filename": documento.filename,
            "tags_criadas": [
                {"chave": chave, "valor": valor}
                for chave, valor in tags_finais.items()
            ],
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao processar upload: {e}")