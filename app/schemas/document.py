from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class TagBase(BaseModel):
    chave: str = Field(..., min_length=1, max_length=100)
    valor: str


class TagCreate(TagBase):
    pass


class TagOut(TagBase):
    id: int

    model_config = {"from_attributes": True}


class DocumentoOut(BaseModel):
    id: int
    uuid: str
    cliente_id: int
    bucket_key: str
    filename: str
    content_type: str
    tamanho_bytes: int
    hash_sha256: Optional[str] = None
    criado_em: datetime
    tags: List[TagOut] = []

    model_config = {"from_attributes": True}

class DocumentoUploadMeta(BaseModel):
    cliente_id: int
    regra_id: Optional[int] = None
    tags: List[TagCreate] = []

class DocumentoUpdate(BaseModel):
    filename: Optional[str] = None
    tags: Optional[List[TagCreate]] = None

class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_prev: bool

class DocumentoSearchResponse(BaseModel):
    items: List["DocumentoOut"]
    meta: PaginationMeta

class DocumentoConteudoCreateResponse(BaseModel):
    id: int
    documento_id: int
    status_processamento: str
    criado_em: datetime

    class Config:
        from_attributes = True


class DocumentoConteudoResponse(BaseModel):
    id: int
    documento_id: int
    texto_extraido: Optional[str] = None
    texto_normalizado: Optional[str] = None
    total_paginas: Optional[int] = None
    ocr_aplicado: bool
    status_processamento: str
    erro_processamento: Optional[str] = None
    processado_em: Optional[datetime] = None
    criado_em: datetime
    atualizado_em: datetime

    class Config:
        from_attributes = True

class DocumentoSearchInteligentItem(BaseModel):
    id: int
    uuid: str
    cliente_id: int
    filename: str
    content_type: str
    tamanho_bytes: int
    criado_em: datetime
    score: float
    trecho: Optional[str] = None
    tags: List[TagOut] = []

    model_config = {"from_attributes": True}


class DocumentoSearchInteligentResponse(BaseModel):
    q: str
    total: int
    page: int
    page_size: int
    items: List[DocumentoSearchInteligentItem]