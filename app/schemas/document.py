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