from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.database.connection import get_db
from app.models.regra_documento import RegraDocumento, RegraDocumentoCampo
from app.schemas.regra_documento import (
    RegraDocumentoCampoCreate,
    RegraDocumentoCampoOut,
    RegraDocumentoCampoUpdate,
    RegraDocumentoCreate,
    RegraDocumentoDetalheOut,
    RegraDocumentoOut,
    RegraDocumentoUpdate,
)

router = APIRouter(prefix="/regras", tags=["Regras"])


@router.post("/", response_model=RegraDocumentoDetalheOut, status_code=status.HTTP_201_CREATED)
def create_regra(payload: RegraDocumentoCreate, db: Session = Depends(get_db)) -> Any:
    regra_existente = db.query(RegraDocumento).filter(
        RegraDocumento.cliente_id == payload.cliente_id,
        RegraDocumento.nome == payload.nome
    ).first()

    if regra_existente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Já existe uma regra com esse nome para este cliente."
        )

    regra = RegraDocumento(
        cliente_id=payload.cliente_id,
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
                placeholder=campo.placeholder,
                mascara=campo.mascara,
            )
        )

    db.commit()
    db.refresh(regra)

    regra = db.query(RegraDocumento).options(
        joinedload(RegraDocumento.campos)
    ).filter(RegraDocumento.id == regra.id).first()

    return regra


@router.get("/", response_model=List[RegraDocumentoOut])
def list_regras(
    cliente_id: Optional[int] = Query(default=None),
    nome: Optional[str] = Query(default=None),
    ativo: Optional[bool] = Query(default=None),
    db: Session = Depends(get_db),
) -> Any:
    query = db.query(RegraDocumento)

    if cliente_id is not None:
        query = query.filter(RegraDocumento.cliente_id == cliente_id)

    if nome:
        query = query.filter(RegraDocumento.nome.ilike(f"%{nome}%"))

    if ativo is not None:
        query = query.filter(RegraDocumento.ativo == ativo)

    query = query.order_by(RegraDocumento.nome.asc())

    return query.all()


@router.get("/{regra_id}", response_model=RegraDocumentoDetalheOut)
def get_regra(regra_id: int, db: Session = Depends(get_db)) -> Any:
    regra = db.query(RegraDocumento).options(
        joinedload(RegraDocumento.campos)
    ).filter(RegraDocumento.id == regra_id).first()

    if not regra:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Regra não encontrada."
        )

    regra.campos.sort(key=lambda x: (x.ordem, x.id))
    return regra


@router.put("/{regra_id}", response_model=RegraDocumentoOut)
def update_regra(regra_id: int, payload: RegraDocumentoUpdate, db: Session = Depends(get_db)) -> Any:
    regra = db.query(RegraDocumento).filter(RegraDocumento.id == regra_id).first()

    if not regra:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Regra não encontrada."
        )

    if payload.cliente_id is not None:
        regra.cliente_id = payload.cliente_id

    if payload.nome is not None:
        regra_com_mesmo_nome = db.query(RegraDocumento).filter(
            RegraDocumento.id != regra.id,
            RegraDocumento.cliente_id == (
                payload.cliente_id if payload.cliente_id is not None else regra.cliente_id
            ),
            RegraDocumento.nome == payload.nome
        ).first()

        if regra_com_mesmo_nome:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Já existe outra regra com esse nome para este cliente."
            )
        regra.nome = payload.nome

    if payload.descricao is not None:
        regra.descricao = payload.descricao

    if payload.ativo is not None:
        regra.ativo = payload.ativo

    db.commit()
    db.refresh(regra)
    return regra


@router.delete("/{regra_id}")
def delete_regra(regra_id: int, db: Session = Depends(get_db)) -> Any:
    regra = db.query(RegraDocumento).filter(RegraDocumento.id == regra_id).first()

    if not regra:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Regra não encontrada."
        )

    db.delete(regra)
    db.commit()

    return {"message": "Regra removida com sucesso."}


@router.post("/{regra_id}/campos", response_model=RegraDocumentoCampoOut, status_code=status.HTTP_201_CREATED)
def create_regra_campo(
    regra_id: int,
    payload: RegraDocumentoCampoCreate,
    db: Session = Depends(get_db),
) -> Any:
    regra = db.query(RegraDocumento).filter(RegraDocumento.id == regra_id).first()

    if not regra:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Regra não encontrada."
        )

    campo = RegraDocumentoCampo(
        regra_id=regra_id,
        nome_campo=payload.nome_campo,
        chave_tag=payload.chave_tag,
        tipo=payload.tipo,
        obrigatorio=payload.obrigatorio,
        ordem=payload.ordem,
        placeholder=payload.placeholder,
        mascara=payload.mascara,
    )

    db.add(campo)
    db.commit()
    db.refresh(campo)

    return campo


@router.get("/{regra_id}/campos", response_model=List[RegraDocumentoCampoOut])
def list_regra_campos(regra_id: int, db: Session = Depends(get_db)) -> Any:
    regra = db.query(RegraDocumento).filter(RegraDocumento.id == regra_id).first()

    if not regra:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Regra não encontrada."
        )

    campos = db.query(RegraDocumentoCampo).filter(
        RegraDocumentoCampo.regra_id == regra_id
    ).order_by(
        RegraDocumentoCampo.ordem.asc(),
        RegraDocumentoCampo.id.asc()
    ).all()

    return campos


@router.put("/campos/{campo_id}", response_model=RegraDocumentoCampoOut)
def update_regra_campo(
    campo_id: int,
    payload: RegraDocumentoCampoUpdate,
    db: Session = Depends(get_db),
) -> Any:
    campo = db.query(RegraDocumentoCampo).filter(RegraDocumentoCampo.id == campo_id).first()

    if not campo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campo da regra não encontrado."
        )

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(campo, field, value)

    db.commit()
    db.refresh(campo)

    return campo

@router.delete("/campos/{campo_id}")
def delete_regra_campo(campo_id: int, db: Session = Depends(get_db)) -> Any:
    campo = db.query(RegraDocumentoCampo).filter(RegraDocumentoCampo.id == campo_id).first()

    if not campo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campo da regra não encontrado."
        )

    db.delete(campo)
    db.commit()

    return {"message": "Campo removido com sucesso."}