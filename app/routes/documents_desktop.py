import hashlib
import os
import posixpath
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import and_
from sqlalchemy.orm import Session, aliased, joinedload
from starlette.background import BackgroundTask

from app.database.connection import get_db
from app.models.document import Documento, DocumentoConteudo, Tag
from app.models.regra_documento import RegraDocumento
from app.schemas.documents_desktop import (
    DocumentoDesktopDownloadMassaIn,
    DocumentoDesktopSearchIn,
    DocumentoDesktopSearchOutItem,
    UploadDesktopBatchIn,
    UploadDesktopBatchItemResult,
    UploadDesktopBatchOut,
    UploadDesktopMeta,
)
from app.services.document_processor import extrair_texto_pdf_bytes
from app.services.storage import StorageService

router = APIRouter(prefix="/documents-desktop", tags=["Documents Desktop"])
storage = StorageService()

REGRA_TAG_KEY = "__regra_id__"


def normalizar_filepath(valor: str | None) -> str | None:
    if not valor:
        return None

    valor = valor.replace("\\", "/").strip().strip("/")

    partes_limpas = []
    for parte in valor.split("/"):
        parte = parte.strip()
        if not parte or parte in (".", ".."):
            continue
        partes_limpas.append(parte)

    if not partes_limpas:
        return None

    return "/".join(partes_limpas)


def normalizar_parte_pasta(valor: str | None) -> str:
    if not valor:
        return ""
    valor = str(valor).replace("\\", "/").strip().strip("/")
    partes = []
    for parte in valor.split("/"):
        parte = parte.strip()
        if not parte or parte in (".", ".."):
            continue
        partes.append(parte)
    return "_".join(partes).strip()


def get_regra_id_from_tags(documento: Documento) -> int | None:
    for tag in documento.tags:
        if tag.chave == REGRA_TAG_KEY:
            try:
                return int(tag.valor)
            except Exception:
                return None
    return None


def get_tags_map(documento: Documento) -> dict:
    retorno = {}
    for tag in documento.tags:
        if tag.chave == REGRA_TAG_KEY:
            continue
        retorno[tag.chave] = tag.valor
    return retorno


def montar_arcname_filepath(documento: Documento, usados: set[str]) -> str:
    nome_arquivo = Path(documento.filename).name
    filepath = normalizar_filepath(documento.filepath)

    if filepath:
        arcname = posixpath.join(filepath, nome_arquivo)
    else:
        arcname = nome_arquivo

    if arcname not in usados:
        usados.add(arcname)
        return arcname

    stem = Path(nome_arquivo).stem
    suffix = Path(nome_arquivo).suffix
    contador = 1

    while True:
        novo_nome = f"{stem}_{contador}{suffix}"
        candidato = posixpath.join(filepath, novo_nome) if filepath else novo_nome
        if candidato not in usados:
            usados.add(candidato)
            return candidato
        contador += 1


def montar_arcname_tags(documento: Documento, ordem_tags: list[str], usados: set[str]) -> str:
    nome_arquivo = Path(documento.filename).name
    tags_map = get_tags_map(documento)

    partes_pasta = []
    for chave in ordem_tags:
        valor = tags_map.get(chave)
        valor_norm = normalizar_parte_pasta(valor)
        if valor_norm:
            partes_pasta.append(valor_norm)

    if partes_pasta:
        arcname = posixpath.join(*partes_pasta, nome_arquivo)
    else:
        arcname = nome_arquivo

    if arcname not in usados:
        usados.add(arcname)
        return arcname

    stem = Path(nome_arquivo).stem
    suffix = Path(nome_arquivo).suffix
    contador = 1

    while True:
        novo_nome = f"{stem}_{contador}{suffix}"
        candidato = posixpath.join(*partes_pasta, novo_nome) if partes_pasta else novo_nome
        if candidato not in usados:
            usados.add(candidato)
            return candidato
        contador += 1


def aplicar_filtros_documentos(query, payload):
    if getattr(payload, "uuids", None):
        if payload.uuids:
            query = query.filter(Documento.uuid.in_(payload.uuids))

    if getattr(payload, "filename", None):
        if payload.filename and payload.filename.strip():
            query = query.filter(Documento.filename.ilike(f"%{payload.filename.strip()}%"))

    if getattr(payload, "somente_com_filepath", False):
        query = query.filter(Documento.filepath.isnot(None)).filter(Documento.filepath != "")

    if getattr(payload, "regra_id", None) is not None:
        regra_tag = aliased(Tag)
        query = (
            query.join(
                regra_tag,
                and_(
                    regra_tag.documento_id == Documento.id,
                    regra_tag.chave == REGRA_TAG_KEY,
                ),
            )
            .filter(regra_tag.valor == str(payload.regra_id))
            .distinct()
        )

    return query


def split_text(valor: str, separador: str) -> list[str]:
    if separador == "":
        return [valor]
    return [parte.strip() for parte in valor.split(separador)]


def extrair_do_arquivo(nome_original: str, posicao: int, separador: str) -> str:
    nome_sem_extensao = Path(nome_original).stem
    partes = [p for p in split_text(nome_sem_extensao, separador) if p.strip()]
    indice = posicao - 1

    if indice < 0 or indice >= len(partes):
        return ""

    return partes[indice].strip()


def extrair_da_pasta(pasta_relativa: str | None, pasta_nivel: int, posicao: int, separador: str) -> str:
    if not pasta_relativa:
        return ""

    pasta_relativa = normalizar_filepath(pasta_relativa)
    if not pasta_relativa:
        return ""

    pastas = [p.strip() for p in pasta_relativa.split("/") if p.strip()]
    if not pastas:
        return ""

    idx_pasta = len(pastas) - 1 - pasta_nivel
    if idx_pasta < 0 or idx_pasta >= len(pastas):
        return ""

    pasta_nome = pastas[idx_pasta]
    partes = [p for p in split_text(pasta_nome, separador) if p.strip()]
    idx_parte = posicao - 1

    if idx_parte < 0 or idx_parte >= len(partes):
        return ""

    return partes[idx_parte].strip()


def montar_tags_automaticas(meta_data: UploadDesktopMeta, nome_original: str) -> dict[str, str]:
    tags_automaticas = {}

    for item in meta_data.mapa_nome_arquivo:
        origem = item.origem.strip().lower()
        valor = ""

        if origem == "arquivo":
            valor = extrair_do_arquivo(
                nome_original=nome_original,
                posicao=item.posicao,
                separador=item.separador or "_",
            )
        elif origem == "pasta":
            valor = extrair_da_pasta(
                pasta_relativa=meta_data.pasta_relativa,
                pasta_nivel=item.pasta_nivel,
                posicao=item.posicao,
                separador=item.separador or "_",
            )
        elif origem == "manual":
            valor = (item.valor_manual or "").strip()

        if valor:
            tags_automaticas[item.chave.strip()] = valor

    return tags_automaticas


def montar_tags_manuais(meta_data: UploadDesktopMeta) -> dict[str, str]:
    tags_manuais = {}

    for item in meta_data.tags:
        chave = item.chave.strip()
        valor = item.valor.strip()

        if chave and valor:
            tags_manuais[chave] = valor

    return tags_manuais


def validar_campos_obrigatorios(regra: RegraDocumento, tags_finais: dict[str, str]):
    faltantes = []

    for campo in regra.campos:
        if not getattr(campo, "obrigatorio", False):
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

def split_text(valor: str, separador: str) -> list[str]:
    if separador == "":
        return [valor]
    return [parte.strip() for parte in valor.split(separador)]


def extrair_do_arquivo(nome_original: str, posicao: int, separador: str) -> str:
    nome_sem_extensao = Path(nome_original).stem
    partes = [p for p in split_text(nome_sem_extensao, separador) if p.strip()]
    indice = posicao - 1

    if indice < 0 or indice >= len(partes):
        return ""

    return partes[indice].strip()


def extrair_da_pasta(pasta_relativa: str | None, pasta_nivel: int, posicao: int, separador: str) -> str:
    if not pasta_relativa:
        return ""

    pasta_relativa = normalizar_filepath(pasta_relativa)
    if not pasta_relativa:
        return ""

    pastas = [p.strip() for p in pasta_relativa.split("/") if p.strip()]
    if not pastas:
        return ""

    idx_pasta = len(pastas) - 1 - pasta_nivel
    if idx_pasta < 0 or idx_pasta >= len(pastas):
        return ""

    pasta_nome = pastas[idx_pasta]
    partes = [p for p in split_text(pasta_nome, separador) if p.strip()]
    idx_parte = posicao - 1

    if idx_parte < 0 or idx_parte >= len(partes):
        return ""

    return partes[idx_parte].strip()


def montar_tags_automaticas_generico(mapa_nome_arquivo, pasta_relativa: str | None, nome_original: str) -> dict[str, str]:
    tags_automaticas = {}

    for item in mapa_nome_arquivo:
        origem = item.origem.strip().lower()
        valor = ""

        if origem == "arquivo":
            valor = extrair_do_arquivo(
                nome_original=nome_original,
                posicao=item.posicao,
                separador=item.separador or "_",
            )
        elif origem == "pasta":
            valor = extrair_da_pasta(
                pasta_relativa=pasta_relativa,
                pasta_nivel=item.pasta_nivel,
                posicao=item.posicao,
                separador=item.separador or "_",
            )
        elif origem == "manual":
            valor = (item.valor_manual or "").strip()

        if valor:
            tags_automaticas[item.chave.strip()] = valor

    return tags_automaticas


def montar_tags_manuais_generico(tags) -> dict[str, str]:
    tags_manuais = {}

    for item in tags:
        chave = item.chave.strip()
        valor = item.valor.strip()

        if chave and valor:
            tags_manuais[chave] = valor

    return tags_manuais


def validar_campos_obrigatorios(regra: RegraDocumento, tags_finais: dict[str, str]):
    faltantes = []

    for campo in regra.campos:
        if not getattr(campo, "obrigatorio", False):
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

@router.post("/upload-massa", response_model=UploadDesktopBatchOut)
async def upload_document_desktop_massa(
    payload: str = Form(...),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    try:
        payload_data = UploadDesktopBatchIn.model_validate_json(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Payload inválido: {e}")

    if not payload_data.itens:
        raise HTTPException(status_code=400, detail="Nenhum item informado no payload.")

    if not files:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")

    if len(files) != len(payload_data.itens):
        raise HTTPException(
            status_code=400,
            detail="A quantidade de arquivos enviados não corresponde à quantidade de itens do payload.",
        )

    if len(files) > 500:
        raise HTTPException(
            status_code=400,
            detail="O limite por lote é de 500 arquivos.",
        )

    regra = (
        db.query(RegraDocumento)
        .options(joinedload(RegraDocumento.campos))
        .filter(RegraDocumento.id == payload_data.regra_id)
        .first()
    )

    if not regra:
        raise HTTPException(status_code=404, detail="Regra não encontrada.")

    modo = payload_data.modo_tags.strip().lower()
    if modo not in ("manual", "arquivo", "hibrido"):
        raise HTTPException(status_code=400, detail="modo_tags inválido. Use manual, arquivo ou hibrido.")

    resultados: list[UploadDesktopBatchItemResult] = []

    for idx, upload_file in enumerate(files):
        item = payload_data.itens[idx]
        nome_cliente = (item.client_file_name or "").strip() or f"arquivo_{idx + 1}"

        try:
            nome_original = (upload_file.filename or nome_cliente or "arquivo_sem_nome").strip()
            if not nome_original:
                nome_original = nome_cliente or "arquivo_sem_nome"

            content_type = upload_file.content_type or "application/octet-stream"

            tags_automaticas = montar_tags_automaticas_generico(
                mapa_nome_arquivo=item.mapa_nome_arquivo,
                pasta_relativa=item.pasta_relativa,
                nome_original=nome_original,
            )

            tags_manuais = montar_tags_manuais_generico(item.tags)

            if modo == "manual":
                tags_finais = tags_manuais
            elif modo == "arquivo":
                tags_finais = tags_automaticas
            else:
                tags_finais = {**tags_automaticas, **tags_manuais}

            validar_campos_obrigatorios(regra=regra, tags_finais=tags_finais)

            filepath = normalizar_filepath(item.pasta_relativa)

            content = await upload_file.read()
            tamanho_bytes = len(content)
            hash_sha256 = hashlib.sha256(content).hexdigest() if tamanho_bytes > 0 else None

            hoje_str = datetime.utcnow().strftime("%Y-%m-%d")
            ext = Path(nome_original).suffix.lower()
            uuid12 = uuid4().hex[:12]
            bucket_key = f"{payload_data.cliente_id}/{hoje_str}/{uuid12}{ext}"

            storage.upload_bytes(
                content=content,
                key=bucket_key,
                content_type=content_type,
            )

            documento = Documento(
                uuid=uuid12,
                cliente_id=payload_data.cliente_id,
                bucket_key=bucket_key,
                filename=Path(nome_original).name,
                filepath=filepath,
                content_type=content_type,
                tamanho_bytes=tamanho_bytes,
                hash_sha256=hash_sha256,
            )

            db.add(documento)
            db.flush()

            db.add(
                Tag(
                    documento_id=documento.id,
                    chave=REGRA_TAG_KEY,
                    valor=str(payload_data.regra_id),
                )
            )

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
            total_paginas = None
            status_processamento = False
            erro_processamento = None

            try:
                if Path(nome_original).suffix.lower() == ".pdf":
                    texto_extraido, total_paginas = extrair_texto_pdf_bytes(content)
                else:
                    texto_extraido = ""
                    total_paginas = None

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
                    total_paginas=total_paginas,
                    ocr_aplicado=False,
                    status_processamento=status_processamento,
                    erro_processamento=erro_processamento,
                    processado_em=datetime.utcnow(),
                )
            )

            db.commit()
            db.refresh(documento)

            resultados.append(
                UploadDesktopBatchItemResult(
                    client_file_name=nome_cliente,
                    sucesso=True,
                    documento_id=documento.id,
                    uuid=documento.uuid,
                    filename=documento.filename,
                    filepath=documento.filepath,
                    bucket_key=documento.bucket_key,
                    erro=None,
                )
            )

        except Exception as e:
            db.rollback()
            resultados.append(
                UploadDesktopBatchItemResult(
                    client_file_name=nome_cliente,
                    sucesso=False,
                    erro=str(e),
                )
            )

    total_recebidos = len(payload_data.itens)
    total_processados = len(resultados)
    total_sucesso = len([r for r in resultados if r.sucesso])
    total_erro = len([r for r in resultados if not r.sucesso])

    return UploadDesktopBatchOut(
        message="Upload em massa processado.",
        cliente_id=payload_data.cliente_id,
        regra_id=payload_data.regra_id,
        total_recebidos=total_recebidos,
        total_processados=total_processados,
        total_sucesso=total_sucesso,
        total_erro=total_erro,
        resultados=resultados,
    )

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

    nome_original = (file.filename or "arquivo_sem_nome").strip()
    if not nome_original:
        nome_original = "arquivo_sem_nome"

    content_type = file.content_type or "application/octet-stream"

    tags_automaticas = montar_tags_automaticas(meta_data=meta_data, nome_original=nome_original)
    tags_manuais = montar_tags_manuais(meta_data=meta_data)

    modo = meta_data.modo_tags.strip().lower()

    if modo == "manual":
        tags_finais = tags_manuais
    elif modo == "arquivo":
        tags_finais = tags_automaticas
    elif modo == "hibrido":
        tags_finais = {**tags_automaticas, **tags_manuais}
    else:
        raise HTTPException(status_code=400, detail="modo_tags inválido. Use manual, arquivo ou hibrido.")

    validar_campos_obrigatorios(regra=regra, tags_finais=tags_finais)

    filepath = normalizar_filepath(meta_data.pasta_relativa)

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
            filename=Path(nome_original).name,
            filepath=filepath,
            content_type=content_type,
            tamanho_bytes=tamanho_bytes,
            hash_sha256=hash_sha256,
        )

        db.add(documento)
        db.flush()

        db.add(
            Tag(
                documento_id=documento.id,
                chave=REGRA_TAG_KEY,
                valor=str(meta_data.regra_id),
            )
        )

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
        total_paginas = None
        status_processamento = False
        erro_processamento = None

        try:
            if Path(nome_original).suffix.lower() == ".pdf":
                texto_extraido, total_paginas = extrair_texto_pdf_bytes(content)
            else:
                texto_extraido = ""
                total_paginas = None

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
                total_paginas=total_paginas,
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
            "filepath": documento.filepath,
            "bucket_key": documento.bucket_key,
            "tags_criadas": [{"chave": k, "valor": v} for k, v in tags_finais.items()],
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao processar upload: {e}")


@router.post("/search", response_model=list[DocumentoDesktopSearchOutItem])
def search_documents_desktop(
    payload: DocumentoDesktopSearchIn,
    db: Session = Depends(get_db),
):
    query = (
        db.query(Documento)
        .options(joinedload(Documento.tags))
        .filter(Documento.cliente_id == payload.cliente_id)
    )

    query = aplicar_filtros_documentos(query, payload)

    limit = payload.limit if payload.limit > 0 else 200
    if limit > 1000:
        limit = 1000

    documentos = query.order_by(Documento.criado_em.desc()).limit(limit).all()

    retorno = []
    for doc in documentos:
        retorno.append(
            DocumentoDesktopSearchOutItem(
                id=doc.id,
                uuid=doc.uuid,
                cliente_id=doc.cliente_id,
                filename=doc.filename,
                filepath=doc.filepath,
                bucket_key=doc.bucket_key,
                content_type=doc.content_type,
                tamanho_bytes=doc.tamanho_bytes,
                criado_em=doc.criado_em.isoformat() if doc.criado_em else None,
                regra_id=get_regra_id_from_tags(doc),
            )
        )

    return retorno


@router.post("/download-massa")
def download_massa_desktop(
    payload: DocumentoDesktopDownloadMassaIn,
    db: Session = Depends(get_db),
):
    query = (
        db.query(Documento)
        .options(joinedload(Documento.tags))
        .filter(Documento.cliente_id == payload.cliente_id)
    )

    query = aplicar_filtros_documentos(query, payload)

    filtros_informados = any(
        [
            payload.uuids,
            payload.filename,
            payload.regra_id is not None,
            payload.somente_com_filepath,
        ]
    )

    if not payload.baixar_todos and not filtros_informados:
        raise HTTPException(
            status_code=400,
            detail="Informe algum filtro, selecione documentos, ou marque baixar_todos=true.",
        )

    modo_estrutura = (payload.modo_estrutura or "filepath").strip().lower()
    if modo_estrutura not in ("filepath", "tags"):
        raise HTTPException(status_code=400, detail="modo_estrutura inválido. Use filepath ou tags.")

    if modo_estrutura == "tags" and not payload.ordem_tags:
        raise HTTPException(status_code=400, detail="Informe ordem_tags quando modo_estrutura='tags'.")

    documentos = query.order_by(Documento.criado_em.asc()).all()

    if not documentos:
        raise HTTPException(status_code=404, detail="Nenhum documento encontrado para download.")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp.close()
    zip_path = tmp.name

    try:
        usados = set()

        with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for documento in documentos:
                try:
                    content = storage.download_bytes(documento.bucket_key)
                except Exception as e:
                    nome_erro = f"_erros/{documento.id}.txt"
                    zf.writestr(
                        nome_erro,
                        f"Falha ao baixar documento {documento.id} - {documento.filename}\n{e}",
                    )
                    continue

                if modo_estrutura == "tags":
                    arcname = montar_arcname_tags(documento, payload.ordem_tags, usados)
                else:
                    arcname = montar_arcname_filepath(documento, usados)

                zf.writestr(arcname, content)

        nome_zip = f"cliente_{payload.cliente_id}_download_massa.zip"

        return FileResponse(
            path=zip_path,
            media_type="application/zip",
            filename=nome_zip,
            background=BackgroundTask(lambda: os.path.exists(zip_path) and os.remove(zip_path)),
        )

    except Exception:
        if os.path.exists(zip_path):
            os.remove(zip_path)
        raise