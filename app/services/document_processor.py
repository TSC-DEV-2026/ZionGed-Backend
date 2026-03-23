import os
import re
import shutil
from typing import Dict, List, Optional


def normalize_spaces(texto: str) -> str:
    return re.sub(r"[ \t]+", " ", texto or "").strip()


def extrair_texto_arquivo(caminho_arquivo: str) -> str:
    ext = os.path.splitext(caminho_arquivo)[1].lower()

    if ext == ".txt":
        with open(caminho_arquivo, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(caminho_arquivo)
            partes = []
            for page in reader.pages:
                partes.append(page.extract_text() or "")
            return "\n".join(partes)
        except Exception:
            return ""

    return ""


def extract_text_from_file(caminho_arquivo: str) -> str:
    return extrair_texto_arquivo(caminho_arquivo)


def extrair_cpf(texto: str) -> Optional[str]:
    m = re.search(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", texto or "")
    return m.group(0) if m else None


def extrair_cnpj(texto: str) -> Optional[str]:
    m = re.search(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b", texto or "")
    return m.group(0) if m else None


def extrair_data(texto: str) -> Optional[str]:
    padroes = [
        r"\b\d{2}/\d{2}/\d{4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{2}/\d{4}\b",
        r"\b\d{6}\b",
    ]
    for p in padroes:
        m = re.search(p, texto or "")
        if m:
            return m.group(0)
    return None


def extrair_por_label(texto: str, labels: List[str]) -> Optional[str]:
    if not texto:
        return None

    linhas = [normalize_spaces(l) for l in texto.splitlines() if normalize_spaces(l)]
    labels_norm = [l.lower().strip() for l in labels if l]

    for linha in linhas:
        linha_lower = linha.lower()
        for label in labels_norm:
            if label and label in linha_lower:
                partes = re.split(r":|\-", linha, maxsplit=1)
                if len(partes) > 1:
                    valor = normalize_spaces(partes[1])
                    if valor:
                        return valor

    return None


def extrair_nome(texto: str, campo: dict) -> Optional[str]:
    labels = [
        campo.get("nome_campo") or "",
        campo.get("placeholder") or "",
        "nome",
        "nome do colaborador",
        "funcionário",
        "funcionario",
        "empregado",
    ]
    return extrair_por_label(texto, labels)


def extrair_valor_campo(texto: str, campo: dict) -> Optional[str]:
    chave = (campo.get("chave_tag") or "").lower().strip()
    tipo = (campo.get("tipo") or "").lower().strip()

    if chave == "cpf" or tipo == "cpf":
        return extrair_cpf(texto)

    if chave == "cnpj" or tipo == "cnpj":
        return extrair_cnpj(texto)

    if chave in ("competencia", "data", "dt_documento") or tipo == "date":
        valor = extrair_por_label(
            texto,
            [
                campo.get("nome_campo") or "",
                campo.get("placeholder") or "",
                "competência",
                "competencia",
                "referência",
                "referencia",
                "data",
                "período",
                "periodo",
            ]
        )
        return valor or extrair_data(texto)

    if chave == "nome" or "nome" in chave:
        return extrair_nome(texto, campo)

    return extrair_por_label(
        texto,
        [
            campo.get("nome_campo") or "",
            campo.get("placeholder") or "",
            chave,
        ]
    )


def merge_tags(regra_campos: List[dict], tags_extraidas: Dict[str, str], tags_manuais: List[dict], modo: str):
    manuais = {t["chave"]: t["valor"] for t in tags_manuais if t.get("chave") and t.get("valor")}
    resultado = {}

    for campo in regra_campos:
        chave = campo["chave_tag"]

        if modo == "manual":
            if chave in manuais:
                resultado[chave] = manuais[chave]
        elif modo == "automatico":
            if chave in tags_extraidas and tags_extraidas[chave]:
                resultado[chave] = tags_extraidas[chave]
        else:
            if chave in tags_extraidas and tags_extraidas[chave]:
                resultado[chave] = tags_extraidas[chave]
            elif chave in manuais and manuais[chave]:
                resultado[chave] = manuais[chave]

    return resultado


def validar_obrigatorios(regra_campos: List[dict], tags_final: Dict[str, str]) -> List[str]:
    faltantes = []
    for campo in regra_campos:
        if campo.get("obrigatorio") and not tags_final.get(campo["chave_tag"]):
            faltantes.append(campo["chave_tag"])
    return faltantes


def mover_para_falha(caminho_origem: str, cliente_id: int) -> str:
    pasta_falha = os.path.join("storage", "falha_processar", f"cliente_{cliente_id}")
    os.makedirs(pasta_falha, exist_ok=True)

    destino = os.path.join(pasta_falha, os.path.basename(caminho_origem))
    shutil.copy2(caminho_origem, destino)
    return destino