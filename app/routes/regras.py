from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.database.connection import get_db
from app.models.regra_documento import RegraDocumento, RegraDocumentoCampo
from app.schemas.regra_documento import (
    RegraDocumentoCreate,
    RegraDocumentoDetalheOut,
    RegraDocumentoOut,
    RegraDocumentoUpdate,
)

router = APIRouter(prefix="/regras", tags=["Regras"])


@router.post("/", response_model=RegraDocumentoDetalheOut, status_code=status.HTTP_201_CREATED)
def create_regra(payload: RegraDocumentoCreate, db: Session = Depends(get_db)) -> Any:
    regra = RegraDocumento(
        user_id=payload.user_id,
        nome=payload.nome,
        descricao=payload.descricao,
        ativo=payload.ativo,
    )
    db.add(regra)
    db.flush()

    for campo in payload.campos:
        db.add(
            RegraDocumentoCampo(
                regra_id=regra.id,
                nome_campo=campo.nome_campo,
                chave_tag=campo.chave_tag,
                tipo=campo.tipo,
                obrigatorio=campo.obrigatorio,
                ordem=campo.ordem,
                posicao_nome=campo.posicao_nome,
                placeholder=campo.placeholder,
                mascara=campo.mascara,
            )
        )

    db.commit()

    regra = (
        db.query(RegraDocumento)
        .options(joinedload(RegraDocumento.campos))
        .filter(RegraDocumento.id == regra.id)
        .first()
    )
    return regra


@router.get("/", response_model=List[RegraDocumentoOut])
def list_regras(
    user_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(RegraDocumento)

    if user_id is not None:
        query = query.filter(RegraDocumento.user_id == user_id)

    return query.order_by(RegraDocumento.id.desc()).all()


@router.get("/{regra_id}", response_model=RegraDocumentoDetalheOut)
def get_regra(regra_id: int, db: Session = Depends(get_db)):
    regra = (
        db.query(RegraDocumento)
        .options(joinedload(RegraDocumento.campos))
        .filter(RegraDocumento.id == regra_id)
        .first()
    )

    if not regra:
        raise HTTPException(status_code=404, detail="Regra não encontrada.")

    return regra


@router.put("/{regra_id}", response_model=RegraDocumentoDetalheOut)
def update_regra(
    regra_id: int,
    payload: RegraDocumentoUpdate,
    db: Session = Depends(get_db),
):
    regra = (
        db.query(RegraDocumento)
        .options(joinedload(RegraDocumento.campos))
        .filter(RegraDocumento.id == regra_id)
        .first()
    )

    if not regra:
        raise HTTPException(status_code=404, detail="Regra não encontrada.")

    data = payload.model_dump(exclude_unset=True)

    for field in ["user_id", "nome", "descricao", "ativo"]:
        if field in data:
            setattr(regra, field, data[field])

    if "campos" in data:
        db.query(RegraDocumentoCampo).filter(RegraDocumentoCampo.regra_id == regra.id).delete()

        for campo in data["campos"]:
            db.add(
                RegraDocumentoCampo(
                    regra_id=regra.id,
                    nome_campo=campo["nome_campo"],
                    chave_tag=campo["chave_tag"],
                    tipo=campo.get("tipo", "text"),
                    obrigatorio=campo.get("obrigatorio", True),
                    ordem=campo.get("ordem", 0),
                    posicao_nome=campo.get("posicao_nome"),
                    placeholder=campo.get("placeholder"),
                    mascara=campo.get("mascara"),
                )
            )

    db.commit()

    regra = (
        db.query(RegraDocumento)
        .options(joinedload(RegraDocumento.campos))
        .filter(RegraDocumento.id == regra.id)
        .first()
    )

    return regra


@router.delete("/{regra_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_regra(regra_id: int, db: Session = Depends(get_db)):
    regra = db.query(RegraDocumento).filter(RegraDocumento.id == regra_id).first()

    if not regra:
        raise HTTPException(status_code=404, detail="Regra não encontrada.")

    db.delete(regra)
    db.commit()