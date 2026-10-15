"""Lector del INVENTARIO de planta viva (varias filas por sembrador).

Limpieza (todo se reporta, nada se corrige en silencio):
- encabezado detectado automaticamente (normalmente la fila 2),
- filas consecutivas identicas: deduplicar | sumar | mantener,
- decimales tipo ".20" -> 0.20; diametro/altura vacios -> vacio (no 0),
- altura en metros -> cm.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .excel_common import read_with_header, find_col, cell_str, cell_num, full_name_key
from .paths import CONFIG

COLS = {
    "id_sembrador": ["ID DEL SEMBRADOR", "ID SEMBRADOR", "ID_SEMBRADOR"],
    "nombre_sembrador": ["NOMBRE SEMBRADOR", "NOMBRE DEL SEMBRADOR", "SEMBRADOR"],
    "cac": ["CAC"],
    "poligono": ["POLÍGONO", "POLIGONO"],
    "ha": ["HA", "HECTAREAS", "HECTÁREAS"],
    "anio": ["AÑO DE ESTABLECIMIENTO", "ANO DE ESTABLECIMIENTO", "AÑO"],
    "comun": ["NOMBRE COMÚN", "NOMBRE COMUN"],
    "cientifico": ["NOMBRE CIENTÍFICO", "NOMBRE CIENTIFICO"],
    "numero": ["NÚMERO", "NUMERO", "NÚMERO DE PLANTAS", "NUM", "No."],
    "diametro": ["CM DIÁMETRO", "CM DIAMETRO", "DIÁMETRO", "DIAMETRO"],
    "altura": ["M ALTURA", "ALTURA"],
}


@dataclass
class PlantaFila:
    id_sembrador: str
    nombre_sembrador: str
    cac: str
    poligono: str
    ha: float | None
    anio: int | None
    comun: str
    cientifico: str
    numero: float | None
    diametro_cm: float | None
    altura_cm: float | None
    fila_excel: int
    filas_origen: list[int] = field(default_factory=list)

    @property
    def key(self) -> str:
        return full_name_key(self.nombre_sembrador)

    def firma(self) -> tuple:
        return (self.key, self.id_sembrador, self.anio, self.comun.upper(), self.cientifico.upper(),
                self.numero, self.diametro_cm, self.altura_cm)


def load_reglas() -> dict:
    p = CONFIG / "inventario.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


def read_inventario(path: str | Path, reglas: dict | None = None) -> tuple[list[PlantaFila], list[str]]:
    reglas = reglas or load_reglas()
    df, hdr = read_with_header(path, COLS["nombre_sembrador"] + COLS["comun"] + COLS["cientifico"])
    cols = {k: find_col(df, v) for k, v in COLS.items()}
    issues = [f"Inventario: encabezado en la fila {hdr}"]
    for k in ("nombre_sembrador", "cientifico", "numero"):
        if not cols[k]:
            issues.append(f"Inventario: falta la columna '{COLS[k][0]}'")
    en_metros = reglas.get("altura_en_metros", True)
    filas: list[PlantaFila] = []
    ultimo = {"nombre": "", "id": "", "cac": "", "pol": ""}
    for _, row in df.iterrows():
        g = lambda k: row[cols[k]] if cols.get(k) else None  # noqa: E731
        fila = int(row["_fila_excel"])
        nombre = cell_str(g("nombre_sembrador")).upper()
        ident = cell_str(g("id_sembrador"))
        comun, cient = cell_str(g("comun")).upper(), cell_str(g("cientifico")).upper()
        if not (comun or cient):
            continue
        # celdas combinadas: el nombre del sembrador puede venir solo en la primera fila
        if not nombre and not ident and ultimo["nombre"]:
            nombre, ident = ultimo["nombre"], ultimo["id"]
        ultimo.update(nombre=nombre, id=ident)
        anio_n = cell_num(g("anio"))
        numero = cell_num(g("numero"))
        diam = cell_num(g("diametro"))
        alt = cell_num(g("altura"))
        raw_alt, raw_diam = cell_str(g("altura")), cell_str(g("diametro"))
        if raw_alt.startswith(".") or raw_diam.startswith("."):
            issues.append(f"Inventario fila {fila}: decimal sin cero inicial ('{raw_alt or raw_diam}') interpretado como {alt if raw_alt.startswith('.') else diam}")
        if numero is None:
            issues.append(f"Inventario fila {fila}: sin NUMERO de plantas ({comun} / {cient})")
        elif numero != int(numero):
            issues.append(f"Inventario fila {fila}: NUMERO no entero ({numero})")
        if anio_n is not None and not (1950 <= anio_n <= 2100):
            issues.append(f"Inventario fila {fila}: ano de establecimiento raro ({anio_n})")
        filas.append(PlantaFila(
            id_sembrador=ident, nombre_sembrador=nombre, cac=cell_str(g("cac")), poligono=cell_str(g("poligono")),
            ha=cell_num(g("ha")), anio=int(anio_n) if anio_n is not None else None, comun=comun, cientifico=cient,
            numero=numero, diametro_cm=diam,
            altura_cm=round(alt * 100, 2) if (alt is not None and en_metros) else alt,
            fila_excel=fila, filas_origen=[fila]))
    filas = _duplicados(filas, reglas.get("duplicados", "deduplicar"), issues)
    return filas, issues


def _duplicados(filas: list[PlantaFila], regla: str, issues: list[str]) -> list[PlantaFila]:
    out: list[PlantaFila] = []
    for f in filas:
        prev = out[-1] if out else None
        if prev is not None and prev.firma() == f.firma():
            if regla == "deduplicar":
                prev.filas_origen.append(f.fila_excel)
                issues.append(f"Inventario fila {f.fila_excel}: identica a la fila {prev.fila_excel} -> eliminada (deduplicar)")
                continue
            if regla == "sumar":
                prev.numero = (prev.numero or 0) + (f.numero or 0)
                prev.filas_origen.append(f.fila_excel)
                issues.append(f"Inventario fila {f.fila_excel}: identica a la fila {prev.fila_excel} -> sumada")
                continue
            issues.append(f"Inventario fila {f.fila_excel}: identica a la fila {prev.fila_excel} -> se mantiene")
        out.append(f)
    return out


def unir(sembradores, filas: list[PlantaFila]) -> tuple[dict[str, list[PlantaFila]], list[str]]:
    """Asocia filas de inventario a cada sembrador (llave: Sembrador.uid).
    Usa ID DEL SEMBRADOR si ambos lo traen; si no, el nombre completo normalizado."""
    issues = []
    by_id = {s.id_sembrador: s for s in sembradores if s.id_sembrador}
    by_name: dict[str, list] = {}
    for s in sembradores:
        by_name.setdefault(s.key, []).append(s)
    res: dict[str, list[PlantaFila]] = {s.uid: [] for s in sembradores}
    huerfanos: dict[str, int] = {}
    for f in filas:
        s = by_id.get(f.id_sembrador) if f.id_sembrador and by_id else None
        if s is None:
            cands = by_name.get(f.key, [])
            if len(cands) > 1:
                issues.append(f"Inventario fila {f.fila_excel}: nombre '{f.nombre_sembrador}' coincide con {len(cands)} sembradores; se usa el primero")
            s = cands[0] if cands else None
        if s is None:
            hk = f.nombre_sembrador or f.id_sembrador or "(sin nombre)"
            huerfanos[hk] = huerfanos.get(hk, 0) + 1
            continue
        res[s.uid].append(f)
    for nombre, n in huerfanos.items():
        issues.append(f"Inventario sin sembrador en el padron: {nombre} ({n} filas)")
    for s in sembradores:
        if not res[s.uid]:
            issues.append(f"Sembrador sin inventario: {s.nombre_completo} ({s.curp})")
    return res, issues
