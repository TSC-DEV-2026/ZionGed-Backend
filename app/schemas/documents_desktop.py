from typing import List, Optional

from pydantic import BaseModel, Field


class TagUploadDesktop(BaseModel):
    chave: str = Field(..., min_length=1)
    valor: str = Field(..., min_length=1)


class MapaNomeArquivoItem(BaseModel):
    chave: str = Field(..., min_length=1)
    posicao: int


class UploadDesktopMeta(BaseModel):
    cliente_id: int
    regra_id: int
    modo_tags: str = Field(..., min_length=1)
    pasta_relativa: Optional[str] = None
    tags: List[TagUploadDesktop] = Field(default_factory=list)
    mapa_nome_arquivo: List[MapaNomeArquivoItem] = Field(default_factory=list)


class DocumentoDesktopSearchIn(BaseModel):
    cliente_id: int
    regra_id: Optional[int] = None
    filename: Optional[str] = None
    somente_com_filepath: bool = False
    limit: int = 200


class DocumentoDesktopSearchOutItem(BaseModel):
    id: int
    uuid: str
    cliente_id: int
    filename: str
    filepath: Optional[str] = None
    bucket_key: str
    content_type: Optional[str] = None
    tamanho_bytes: Optional[int] = None
    criado_em: Optional[str] = None
    regra_id: Optional[int] = None


class DocumentoDesktopDownloadMassaIn(BaseModel):
    cliente_id: int
    regra_id: Optional[int] = None

    uuids: List[str] = Field(default_factory=list)
    filename: Optional[str] = None
    somente_com_filepath: bool = False
    baixar_todos: bool = False

    modo_estrutura: str = "filepath"  # filepath | tags
    ordem_tags: List[str] = Field(default_factory=list)