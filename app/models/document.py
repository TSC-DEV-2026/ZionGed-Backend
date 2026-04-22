from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.connection import Base


class Documento(Base):
    __tablename__ = "tb_documento"

    id = Column(BigInteger, primary_key=True, index=True)
    uuid = Column(String(100), unique=True, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    bucket_key = Column(String(1000), nullable=False)
    filename = Column(String(1000), nullable=False)
    filepath = Column(String(2000), nullable=True)
    content_type = Column(String(255), nullable=True)
    tamanho_bytes = Column(BigInteger, nullable=True)
    hash_sha256 = Column(String(255), nullable=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    conteudo = relationship("DocumentoConteudo", back_populates="documento", uselist=False, cascade="all, delete-orphan")
    tags = relationship("Tag", back_populates="documento", cascade="all, delete-orphan")


class DocumentoConteudo(Base):
    __tablename__ = "tb_documento_conteudo"

    id = Column(BigInteger, primary_key=True, index=True)
    documento_id = Column(BigInteger, ForeignKey("tb_documento.id", ondelete="CASCADE"), nullable=False, index=True)
    texto_extraido = Column(Text, nullable=True)
    texto_normalizado = Column(Text, nullable=True)
    total_paginas = Column(Integer, nullable=True)
    ocr_aplicado = Column(Boolean, nullable=True, default=False)
    status_processamento = Column(Boolean, nullable=True, default=False)
    erro_processamento = Column(Text, nullable=True)
    processado_em = Column(DateTime(timezone=True), nullable=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    atualizado_em = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    documento = relationship("Documento", back_populates="conteudo")


class Tag(Base):
    __tablename__ = "tb_tags"

    id = Column(BigInteger, primary_key=True, index=True)
    documento_id = Column(BigInteger, ForeignKey("tb_documento.id", ondelete="CASCADE"), nullable=False, index=True)
    chave = Column(String(255), nullable=False, index=True)
    valor = Column(Text, nullable=True)

    documento = relationship("Documento", back_populates="tags")