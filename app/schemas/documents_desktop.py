from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class UploadTagDesktopIn(BaseModel):
    chave: str = Field(..., min_length=1, max_length=100)
    valor: str = Field(..., min_length=1)


class UploadMetaDesktopIn(BaseModel):
    cliente_id: int
    regra_id: Optional[int] = None
    tags: List[UploadTagDesktopIn] = []


class DocumentoDesktopTagOut(BaseModel):
    id: int
    chave: str
    valor: str

    model_config = {"from_attributes": True}


class DocumentoDesktopOut(BaseModel):
    id: int
    cliente_id: int
    regra_id: Optional[int] = None
    uuid: str
    nome_original: str
    nome_fisico: str
    extensao: Optional[str] = None
    content_type: Optional[str] = None
    tamanho_bytes: Optional[int] = None
    hash_sha256: Optional[str] = None
    caminho_arquivo: str
    status_documento: str
    criado_em: datetime
    tags: List[DocumentoDesktopTagOut] = []

    model_config = {"from_attributes": True}


class UploadDesktopResponse(BaseModel):
    message: str
    documento_id: int
    cliente_id: int
    regra_id: Optional[int] = None
    arquivo: str
    status_documento: str
    tags: List[dict]