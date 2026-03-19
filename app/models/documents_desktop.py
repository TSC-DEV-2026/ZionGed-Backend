from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from app.database.connection import Base


class DocumentoDesktop(Base):
    __tablename__ = "tb_documento_desktop"

    id = Column(BigInteger, primary_key=True, index=True)
    cliente_id = Column(BigInteger, nullable=False, index=True)
    regra_id = Column(BigInteger, ForeignKey("tb_regra_documento.id"), nullable=True, index=True)

    uuid = Column(String(12), unique=True, nullable=False, index=True)
    nome_original = Column(Text, nullable=False)
    nome_fisico = Column(Text, nullable=False)
    extensao = Column(String(20), nullable=True)

    content_type = Column(String(150), nullable=True)
    tamanho_bytes = Column(BigInteger, nullable=True)
    hash_sha256 = Column(String(64), nullable=True)

    caminho_arquivo = Column(Text, nullable=False)
    status_documento = Column(String(30), nullable=False, default="cadastrado")

    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)

    tags = relationship(
        "DocumentoDesktopTag",
        back_populates="documento",
        cascade="all, delete-orphan",
    )


class DocumentoDesktopTag(Base):
    __tablename__ = "tb_documento_desktop_tag"

    id = Column(BigInteger, primary_key=True, index=True)
    documento_id = Column(
        BigInteger,
        ForeignKey("tb_documento_desktop.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chave = Column(String(100), nullable=False, index=True)
    valor = Column(Text, nullable=False)

    documento = relationship("DocumentoDesktop", back_populates="tags")