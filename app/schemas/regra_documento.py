from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class RegraDocumentoCampoBase(BaseModel):
    nome_campo: str = Field(..., min_length=1, max_length=255)
    chave_tag: str = Field(..., min_length=1, max_length=100)
    tipo: str = Field(default="text", min_length=1, max_length=50)
    obrigatorio: bool = True
    ordem: int = 0
    posicao_nome: Optional[int] = None
    placeholder: Optional[str] = Field(default=None, max_length=255)
    mascara: Optional[str] = Field(default=None, max_length=100)


class RegraDocumentoCampoCreate(RegraDocumentoCampoBase):
    pass


class RegraDocumentoCampoUpdate(BaseModel):
    nome_campo: Optional[str] = Field(default=None, min_length=1, max_length=255)
    chave_tag: Optional[str] = Field(default=None, min_length=1, max_length=100)
    tipo: Optional[str] = Field(default=None, min_length=1, max_length=50)
    obrigatorio: Optional[bool] = None
    ordem: Optional[int] = None
    posicao_nome: Optional[int] = None
    placeholder: Optional[str] = Field(default=None, max_length=255)
    mascara: Optional[str] = Field(default=None, max_length=100)


class RegraDocumentoCampoOut(RegraDocumentoCampoBase):
    id: int
    regra_id: int

    model_config = {"from_attributes": True}


class RegraDocumentoBase(BaseModel):
    cliente_id: int
    nome: str = Field(..., min_length=1, max_length=255)
    descricao: Optional[str] = None
    ativo: bool = True


class RegraDocumentoCreate(RegraDocumentoBase):
    campos: List[RegraDocumentoCampoCreate]


class RegraDocumentoUpdate(BaseModel):
    cliente_id: Optional[int] = None
    nome: Optional[str] = Field(default=None, min_length=1, max_length=255)
    descricao: Optional[str] = None
    ativo: Optional[bool] = None
    campos: Optional[List[RegraDocumentoCampoCreate]] = None


class RegraDocumentoOut(RegraDocumentoBase):
    id: int
    criado_em: datetime
    atualizado_em: datetime

    model_config = {"from_attributes": True}


class RegraDocumentoDetalheOut(RegraDocumentoOut):
    campos: List[RegraDocumentoCampoOut] = []

    model_config = {"from_attributes": True}