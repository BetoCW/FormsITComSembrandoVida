"""Utilidades comunes para leer los Excel."""
from __future__ import annotations

import math
import re
from pathlib import Path

import pandas as pd

from .textnorm import norm


def read_with_header(path: str | Path, must_have: list[str], sheet=0, max_scan: int = 15) -> tuple[pd.DataFrame, int]:
    """Lee una hoja detectando la fila de encabezado (la primera que contenga
    alguna de las columnas `must_have`). Devuelve (DataFrame, fila_encabezado 1-based)."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        raw = pd.read_csv(path, header=None, dtype=object, encoding="utf-8-sig")
    else:
        raw = pd.read_excel(path, header=None, dtype=object, sheet_name=sheet)
    wanted = {norm(x) for x in must_have}
    hdr = None
    for i in range(min(max_scan, len(raw))):
        cells = {norm(c) for c in raw.iloc[i].tolist() if not _empty(c)}
        if cells & wanted:
            hdr = i
            break
    if hdr is None:
        raise ValueError(f"No se encontro el encabezado en {path.name} (se buscaba: {', '.join(must_have)})")
    cols = []
    for j, c in enumerate(raw.iloc[hdr].tolist()):
        name = str(c).strip() if not _empty(c) else f"col_{j}"
        while name in cols:
            name += "_"
        cols.append(name)
    df = raw.iloc[hdr + 1:].copy()
    df.columns = cols
    df = df.dropna(how="all").reset_index(drop=True)
    df["_fila_excel"] = range(hdr + 2, hdr + 2 + len(df))
    return df, hdr + 1


def _empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return isinstance(v, str) and not v.strip()


def find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    by_norm = {norm(c): c for c in df.columns}
    for c in candidates:
        if norm(c) in by_norm:
            return by_norm[norm(c)]
    return None


def cell_str(v) -> str:
    if _empty(v):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return re.sub(r"\s+", " ", str(v)).strip()


def cell_num(v) -> float | None:
    """'.20' -> 0.2 ; '1,5' -> 1.5 ; vacio -> None (nunca 0)."""
    if _empty(v):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "")
    if s.count(",") == 1 and "." not in s:
        s = s.replace(",", ".")
    s = s.replace(",", "")
    if s.startswith("."):
        s = "0" + s
    try:
        return float(s)
    except ValueError:
        return None


def full_name_key(*parts) -> str:
    return norm(" ".join(cell_str(p) for p in parts if cell_str(p)))
