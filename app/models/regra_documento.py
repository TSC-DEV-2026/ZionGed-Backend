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
)
from sqlalchemy.orm import relationship

from app.database.connection import Base


class RegraDocumento(Base):
    __tablename__ = "tb_regra_documento"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    nome = Column(String(255), nullable=False)
    descricao = Column(Text, nullable=True)
    ativo = Column(Boolean, nullable=False, default=True)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)
    atualizado_em = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    campos = relationship(
        "RegraDocumentoCampo",
        back_populates="regra",
        cascade="all, delete-orphan",
        order_by="RegraDocumentoCampo.ordem.asc()",
    )


class RegraDocumentoCampo(Base):
    __tablename__ = "tb_regra_documento_campo"

    id = Column(BigInteger, primary_key=True, index=True)
    regra_id = Column(
        BigInteger,
        ForeignKey("tb_regra_documento.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    nome_campo = Column(String(255), nullable=False)
    chave_tag = Column(String(100), nullable=False, index=True)
    tipo = Column(String(50), nullable=False, default="text")
    obrigatorio = Column(Boolean, nullable=False, default=True)
    ordem = Column(Integer, nullable=False, default=0)
    posicao_nome = Column(Integer, nullable=True)
    placeholder = Column(String(255), nullable=True)
    mascara = Column(String(100), nullable=True)

    regra = relationship("RegraDocumento", back_populates="campos")