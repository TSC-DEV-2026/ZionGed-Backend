from __future__ import annotations

from datetime import datetime, date

from sqlalchemy import String, Integer, Date, DateTime, ForeignKey, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base


class Pessoa(Base):
    __tablename__ = "tb_pessoa"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    cpf: Mapped[str | None] = mapped_column(String(14), unique=True, nullable=True)
    data_nascimento: Mapped[date | None] = mapped_column(Date, nullable=True)
    telefone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    login_token: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    usuarios: Mapped[list["Usuario"]] = relationship(
        "Usuario",
        back_populates="pessoa",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Usuario(Base):
    __tablename__ = "tb_usuario"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pessoa_id: Mapped[int] = mapped_column(ForeignKey("tb_pessoa.id", ondelete="CASCADE"), index=True, nullable=False)

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    pessoa: Mapped["Pessoa"] = relationship("Pessoa", back_populates="usuarios")


class TokenBlacklist(Base):
    __tablename__ = "tb_blacklist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jti: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    data_insercao: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )