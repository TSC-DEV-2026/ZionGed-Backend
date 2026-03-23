from typing import List
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
    tags: List[TagUploadDesktop] = []
    mapa_nome_arquivo: List[MapaNomeArquivoItem] = []