from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
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
