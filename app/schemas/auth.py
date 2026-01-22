from __future__ import annotations
from datetime import date, datetime
from pydantic import BaseModel, EmailStr

# ---- PESSOA ----
class PessoaIn(BaseModel):
    nome: str
    cpf: str | None = None
    data_nascimento: date | None = None
    telefone: str | None = None

class PessoaOut(BaseModel):
    id: int
    nome: str
    cpf: str | None
    data_nascimento: date | None
    telefone: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

# ---- USUÁRIO ----
class UsuarioIn(BaseModel):
    email: EmailStr
    senha: str

class UsuarioOut(BaseModel):
    id: int
    pessoa_id: int
    email: EmailStr
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

# ---- REGISTER (entrada achatada ou por blocos, aqui vamos de blocos pessoa+usuario) ----
class RegisterIn(BaseModel):
    pessoa: PessoaIn
    usuario: UsuarioIn

class RegisterOut(BaseModel):
    pessoa: PessoaOut
    usuario: UsuarioOut
