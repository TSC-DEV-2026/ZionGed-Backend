from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from app.database.connection import Base


class Documento(Base):
    __tablename__ = "tb_documento"

    id = Column(BigInteger, primary_key=True, index=True)
    uuid = Column(String(12), unique=True, nullable=False, index=True)
    cliente_id = Column(BigInteger, nullable=False, index=True)
    bucket_key = Column(Text, nullable=False)
    filename = Column(Text, nullable=False)
    content_type = Column(String(100), nullable=False)
    tamanho_bytes = Column(BigInteger, nullable=False)
    hash_sha256 = Column(String(64), nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)

    tags = relationship(
        "Tag",
        back_populates="documento",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    conteudo = relationship(
        "DocumentoConteudo",
        back_populates="documento",
        cascade="all, delete-orphan",
        uselist=False,
    )


class Tag(Base):
    __tablename__ = "tb_tags"

    id = Column(BigInteger, primary_key=True, index=True)
    documento_id = Column(
        BigInteger,
        ForeignKey("tb_documento.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chave = Column(String(100), nullable=False, index=True)
    valor = Column(Text, nullable=False, index=True)

    documento = relationship("Documento", back_populates="tags")


class DocumentoConteudo(Base):
    __tablename__ = "tb_documento_conteudo"

    id = Column(BigInteger, primary_key=True, index=True)
    documento_id = Column(
        BigInteger,
        ForeignKey("tb_documento.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    texto_extraido = Column(Text, nullable=True)
    texto_normalizado = Column(Text, nullable=True)
    total_paginas = Column(Integer, nullable=True)
    ocr_aplicado = Column(Boolean, nullable=False, default=False)
    status_processamento = Column(Boolean, nullable=False)
    erro_processamento = Column(Text, nullable=True)
    processado_em = Column(DateTime, nullable=True)
    criado_em = Column(DateTime, server_default=func.now(), nullable=False)
    atualizado_em = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    documento = relationship("Documento", back_populates="conteudo")