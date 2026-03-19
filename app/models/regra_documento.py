from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from app.database.connection import Base


class RegraDocumento(Base):
    __tablename__ = "tb_regra_documento"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id = Column(BigInteger, nullable=False, index=True)
    nome = Column(String(150), nullable=False)
    descricao = Column(Text, nullable=True)
    ativo = Column(Boolean, nullable=False, default=True)
    criado_em = Column(DateTime, nullable=False, server_default=func.now())
    atualizado_em = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    campos = relationship(
        "RegraDocumentoCampo",
        back_populates="regra",
        cascade="all, delete-orphan"
    )


class RegraDocumentoCampo(Base):
    __tablename__ = "tb_regra_documento_campo"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    regra_id = Column(BigInteger, ForeignKey("tb_regra_documento.id", ondelete="CASCADE"), nullable=False, index=True)
    nome_campo = Column(String(100), nullable=False)
    chave_tag = Column(String(100), nullable=False)
    tipo = Column(String(30), nullable=False, default="text")
    obrigatorio = Column(Boolean, nullable=False, default=True)
    ordem = Column(Integer, nullable=False, default=0)
    placeholder = Column(String(255), nullable=True)
    mascara = Column(String(50), nullable=True)
    criado_em = Column(DateTime, nullable=False, server_default=func.now())
    atualizado_em = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    regra = relationship("RegraDocumento", back_populates="campos")