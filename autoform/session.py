"""Sesion del dia: sembradores, inventario y ediciones manuales.
Se guarda en data/sesion.json para no recapturar si se cierra la app."""
from __future__ import annotations

import json
from dataclasses import asdict, fields

from .excel_inventario import PlantaFila
from .excel_padron import Sembrador
from .paths import DATA

SESSION = DATA / "sesion.json"


def _mk(cls, d: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in names})


def save(sembradores: list[Sembrador], inventario: dict[str, list[PlantaFila]], overrides: dict,
         seleccion: list[str], archivos: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    data = {
        "sembradores": [asdict(s) for s in sembradores],
        "inventario": {k: [asdict(f) for f in v] for k, v in inventario.items()},
        "overrides": {k: [[p, i, v] for (p, i), v in ov.items()] for k, ov in overrides.items()},
        "seleccion": seleccion,
        "archivos": archivos,
    }
    tmp = SESSION.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(SESSION)


def load() -> dict:
    if not SESSION.exists():
        return {"sembradores": [], "inventario": {}, "overrides": {}, "seleccion": [], "archivos": {}}
    d = json.loads(SESSION.read_text(encoding="utf-8"))
    return {
        "sembradores": [_mk(Sembrador, x) for x in d.get("sembradores", [])],
        "inventario": {k: [_mk(PlantaFila, f) for f in v] for k, v in d.get("inventario", {}).items()},
        "overrides": {k: {(p, i): v for p, i, v in ov} for k, ov in d.get("overrides", {}).items()},
        "seleccion": d.get("seleccion", []),
        "archivos": d.get("archivos", {}),
    }
