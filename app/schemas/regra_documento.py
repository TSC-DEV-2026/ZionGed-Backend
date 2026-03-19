from typing import List, Optional, Literal
from pydantic import BaseModel, Field


CampoTipo = Literal["text", "number", "date", "cpf", "cnpj"]


class RegraDocumentoCampoBase(BaseModel):
    nome_campo: str = Field(..., max_length=100)
    chave_tag: str = Field(..., max_length=100)
    tipo: CampoTipo = "text"
    obrigatorio: bool = True
    ordem: int = 0
    placeholder: Optional[str] = Field(default=None, max_length=255)
    mascara: Optional[str] = Field(default=None, max_length=50)


class RegraDocumentoCampoCreate(RegraDocumentoCampoBase):
    pass


class RegraDocumentoCampoUpdate(BaseModel):
    nome_campo: Optional[str] = Field(default=None, max_length=100)
    chave_tag: Optional[str] = Field(default=None, max_length=100)
    tipo: Optional[CampoTipo] = None
    obrigatorio: Optional[bool] = None
    ordem: Optional[int] = None
    placeholder: Optional[str] = Field(default=None, max_length=255)
    mascara: Optional[str] = Field(default=None, max_length=50)


class RegraDocumentoCampoOut(RegraDocumentoCampoBase):
    id: int

    class Config:
        from_attributes = True


class RegraDocumentoBase(BaseModel):
    cliente_id: int
    nome: str = Field(..., max_length=150)
    descricao: Optional[str] = None
    ativo: bool = True


class RegraDocumentoCreate(RegraDocumentoBase):
    campos: List[RegraDocumentoCampoCreate] = []


class RegraDocumentoUpdate(BaseModel):
    cliente_id: Optional[int] = None
    nome: Optional[str] = Field(default=None, max_length=150)
    descricao: Optional[str] = None
    ativo: Optional[bool] = None


class RegraDocumentoOut(RegraDocumentoBase):
    id: int

    class Config:
        from_attributes = True


class RegraDocumentoDetalheOut(RegraDocumentoOut):
    campos: List[RegraDocumentoCampoOut] = []

    class Config:
        from_attributes = True