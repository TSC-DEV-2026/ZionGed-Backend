from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, EmailStr


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
    login_token: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UsuarioIn(BaseModel):
    email: EmailStr
    senha: str


class UsuarioOut(BaseModel):
    id: int
    pessoa_id: int
    email: EmailStr
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RegisterIn(BaseModel):
    pessoa: PessoaIn
    usuario: UsuarioIn


class RegisterOut(BaseModel):
    pessoa: PessoaOut
    usuario: UsuarioOut


class LoginInput(BaseModel):
    usuario: str
    senha: str


class LoginExecutavelInput(BaseModel):
    token: str