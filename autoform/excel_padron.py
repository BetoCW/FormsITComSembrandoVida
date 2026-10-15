"""Lector del PADRON (una fila = un sembrador)."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .excel_common import read_with_header, find_col, cell_str, cell_num, full_name_key
from .paths import CONFIG

CURP_RE = re.compile(r"^[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d$")


@dataclass
class Sembrador:
    curp: str = ""
    nombre: str = ""
    apellido_p: str = ""
    apellido_m: str = ""
    cac_id: str = ""
    cac_nombre: str = ""
    poligono: str = ""
    latitud: float | None = None
    longitud: float | None = None
    id_predio: str = ""
    tecnica: str = ""
    curp_tecnica: str = ""
    id_sembrador: str = ""
    fila_excel: int = 0
    avisos: list[str] = field(default_factory=list)
    uid: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def nombre_completo(self) -> str:
        return " ".join(x for x in (self.nombre, self.apellido_p, self.apellido_m) if x)

    @property
    def key(self) -> str:
        return full_name_key(self.nombre, self.apellido_p, self.apellido_m)

    @property
    def draft_name(self) -> str:
        return f"{self.curp} - {self.nombre_completo}".strip(" -")

    @property
    def centroide(self) -> str:
        if self.latitud is None or self.longitud is None:
            return ""
        return f"{self.latitud} {self.longitud} 0 0"


def load_mapeo() -> dict:
    return yaml.safe_load((CONFIG / "mapeo_padron.yaml").read_text(encoding="utf-8"))


def read_padron(path: str | Path) -> tuple[list[Sembrador], list[str]]:
    mapeo = load_mapeo()["columnas"]
    df, hdr = read_with_header(path, mapeo["curp"] + mapeo["nombre"])
    cols = {k: find_col(df, v) for k, v in mapeo.items()}
    issues = [f"Padron: encabezado en la fila {hdr}"]
    for k in ("curp", "nombre", "apellido_p"):
        if not cols[k]:
            issues.append(f"Padron: falta la columna para '{k}' (se buscaba {mapeo[k]})")
    out: list[Sembrador] = []
    seen: dict[str, int] = {}
    for _, row in df.iterrows():
        g = lambda k: row[cols[k]] if cols.get(k) else None  # noqa: E731
        s = Sembrador(
            curp=cell_str(g("curp")).upper(), nombre=cell_str(g("nombre")).upper(),
            apellido_p=cell_str(g("apellido_p")).upper(), apellido_m=cell_str(g("apellido_m")).upper(),
            cac_id=cell_str(g("cac_id")), cac_nombre=cell_str(g("cac_nombre")),
            poligono=cell_str(g("poligono")), latitud=cell_num(g("latitud")), longitud=cell_num(g("longitud")),
            id_predio=cell_str(g("id_predio")), tecnica=cell_str(g("tecnica")),
            curp_tecnica=cell_str(g("curp_tecnica")).upper(), id_sembrador=cell_str(g("id_sembrador")),
            fila_excel=int(row["_fila_excel"]),
        )
        if not (s.curp or s.nombre):
            continue
        # ID_PREDIO "lat,lon" sirve de respaldo para las coordenadas
        if (s.latitud is None or s.longitud is None) and "," in s.id_predio:
            a, b = (cell_num(x) for x in s.id_predio.split(",", 1))
            if a is not None and b is not None:
                s.latitud, s.longitud = a, b
                s.avisos.append("coordenadas tomadas de ID_PREDIO")
        if s.curp and not CURP_RE.match(s.curp):
            s.avisos.append(f"CURP con formato invalido: {s.curp}")
        if not s.curp:
            s.avisos.append("sin CURP")
        if s.curp_tecnica and not CURP_RE.match(s.curp_tecnica):
            s.avisos.append(f"CURP de la tecnica con formato invalido: {s.curp_tecnica}")
        if s.latitud is None or s.longitud is None:
            s.avisos.append("sin coordenadas del centroide")
        elif not (14 <= s.latitud <= 33 and -118 <= s.longitud <= -86):
            s.avisos.append(f"coordenadas fuera de Mexico: {s.latitud}, {s.longitud}")
        if s.curp in seen:
            s.avisos.append(f"CURP repetido (fila {seen[s.curp]})")
        seen.setdefault(s.curp, s.fila_excel)
        out.append(s)
    for s in out:
        for a in s.avisos:
            issues.append(f"Padron fila {s.fila_excel} ({s.nombre_completo}): {a}")
    return out, issues
