"""Matrices del formulario (eventos climaticos x columnas A, B, C...).

Fila = TEXTO del evento; columna = POSICION (A = 1.a casilla). Los values
internos (fila_1, opci_n_2, disminucion...) no tienen sentido, por eso se
traduce letra -> etiqueta de la opcion en esa posicion.
"""
from __future__ import annotations

import string

from .filler import Action
from .schema_index import Schema
from .textnorm import norm_loose

MATRICES = {
    "group_ln6jc59": "Afectaciones en la parcela",
    "group_ws5me30": "Acciones o medidas en la parcela",
    "group_fo7xr36": "CAC, vivero y biofabrica",
    "group_lw0iz81": "Hogar o comunidad",
    "group_pk1hx76": "Materia organica (kg/ano)",
}


def _row_field(schema: Schema, mid: str, row_text: str) -> dict | None:
    m = schema.matrices.get(mid)
    if not m:
        return None
    want = norm_loose(row_text)
    for r in m["rows"]:
        if norm_loose(r["row"]) == want:
            return schema.by_path[r["path"]]
    for r in m["rows"]:            # tolera "Nortes /Frentes Fríos" vs "Nortes/Frentes fríos"
        if norm_loose(r["row"]).replace(" ", "") == want.replace(" ", ""):
            return schema.by_path[r["path"]]
    return None


def matrix_actions(schema: Schema, mid: str, rows: dict | None, source: str = "plantilla") -> tuple[list[Action], list[str]]:
    issues: list[str] = []
    if rows is None:
        return [Action("matrix", schema.full(f"up/{mid}"), None, label=f"Matriz: {MATRICES.get(mid, mid)}",
                       source=source, pending=True, extra={"row_path": ""})], issues
    acts = []
    for row_text, val in rows.items():
        f = _row_field(schema, mid, row_text)
        if f is None:
            issues.append(f"Matriz {MATRICES.get(mid, mid)}: no existe la fila '{row_text}'")
            continue
        label = f"Matriz {MATRICES.get(mid, mid)} / {row_text}"
        if f["kind"] == "number" or f["widget"] == "input":
            value = val
        else:
            opts = [o["label"] for o in f["options"]]
            letras = val if isinstance(val, list) else [val]
            value = []
            for le in letras:
                pos = string.ascii_uppercase.find(str(le).strip().rstrip(".").upper())
                if 0 <= pos < len(opts):
                    value.append(opts[pos])
                else:
                    issues.append(f"{label}: la columna '{le}' no existe (hay {len(opts)})")
            if f["widget"] == "radio" or f["kind"] == "select_one":
                value = value[:1]
        acts.append(Action("matrix", f["path"], value, label=label, source=source, repeat=f["repeat"], index=0,
                           kind=f["kind"], widget=f["widget"], pending=val is None, extra={"row_path": f["path"]}))
    return acts, issues
