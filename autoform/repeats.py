"""Vuelca el inventario a los repeats del formulario:

- "Planta establecida en parcela": una instancia por especie (cientifico + ano)
  en la categoria correcta, dentro del bloque SAF o MIAF segun la regla.
- "Cultivos eje": los N cultivos con mas plantas por categoria
  (frutal / agroindustrial / especia) con promedios ponderados.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .especies import Catalogo, Match
from .excel_inventario import PlantaFila

ESTABLECIDA = {
    "SAF": {
        "Forestales": "up/group_dl45e64/forestal_saf",
        "Agroindustrial": "up/group_dl45e64/Agroindustrial_saf",
        "Frutales": "up/group_dl45e64/Frutales_saf",
        "Especias": "up/group_dl45e64/especias_saf",
    },
    "MIAF": {
        "Forestales": "up/group_dl45e64_001/Forestales_MIAF",
        "Agroindustrial": "up/group_dl45e64_001/Agroindustrial_miaf",
        "Frutales": "up/group_dl45e64_001/Frutales_miaf",
        "Especias": "up/group_dl45e64_001/especias_MIAF",
    },
}
EJE = {
    "Frutales": "group_vj6ie64/frutal_eje",
    "Agroindustrial": "group_vj6ie64/forestales",
    "Especias": "group_vj6ie64/forestales_001",
}


@dataclass
class GrupoEspecie:
    categoria: str
    match: Match
    anio: int | None
    comun: str
    numero: float = 0
    filas: list[PlantaFila] = field(default_factory=list)

    @property
    def clave(self):
        return (self.categoria, self.match.label, self.match.otra_texto, self.anio)


@dataclass
class CultivoEje:
    categoria: str
    match: Match
    comun: str
    plantas: float
    edad: float | None
    altura_cm: float | None
    diametro_cm: float | None
    filas: list[int]


def _wavg(pairs: list[tuple[float | None, float | None]]) -> float | None:
    vals = [(v, w) for v, w in pairs if v is not None and w]
    tot = sum(w for _, w in vals)
    return sum(v * w for v, w in vals) / tot if tot else None


def clasificar(filas: list[PlantaFila], cat: Catalogo) -> tuple[list[tuple[PlantaFila, Match]], list[str]]:
    out, issues = [], []
    cache: dict[tuple, Match] = {}
    for f in filas:
        k = (f.comun, f.cientifico)
        if k not in cache:
            cache[k] = cat.match(f.comun, f.cientifico)
        m = cache[k]
        out.append((f, m))
    for (comun, cient), m in cache.items():
        for a in m.avisos:
            issues.append(f"Especie '{comun}' / '{cient}': {a}")
    return out, issues


def planta_establecida(clasificadas: list[tuple[PlantaFila, Match]]) -> list[GrupoEspecie]:
    grupos: dict[tuple, GrupoEspecie] = {}
    for f, m in clasificadas:
        if not m.categoria or not m.especie:
            continue
        g = GrupoEspecie(m.categoria, m, f.anio, f.comun)
        g = grupos.setdefault(g.clave, g)
        g.numero += f.numero or 0
        g.filas.append(f)
    return list(grupos.values())


def cultivos_eje(clasificadas: list[tuple[PlantaFila, Match]], anio_actual: int, maximo: int = 3) -> list[CultivoEje]:
    por_especie: dict[tuple, list[tuple[PlantaFila, Match]]] = {}
    for f, m in clasificadas:
        if m.categoria in EJE and m.especie:
            por_especie.setdefault((m.categoria, m.label, m.otra_texto), []).append((f, m))
    res: list[CultivoEje] = []
    for (categoria, _label, _otra), items in por_especie.items():
        filas = [f for f, _ in items]
        plantas = sum(f.numero or 0 for f in filas)
        anio = _wavg([(f.anio, f.numero) for f in filas])
        res.append(CultivoEje(
            categoria=categoria, match=items[0][1], comun=filas[0].comun, plantas=plantas,
            edad=round(anio_actual - anio, 1) if anio is not None else None,
            altura_cm=_round(_wavg([(f.altura_cm, f.numero) for f in filas])),
            diametro_cm=_round(_wavg([(f.diametro_cm, f.numero) for f in filas])),
            filas=[x for f in filas for x in f.filas_origen]))
    top: list[CultivoEje] = []
    for categoria in EJE:
        cands = sorted((c for c in res if c.categoria == categoria), key=lambda c: -c.plantas)
        top.extend(cands[:maximo])
    return top


def _round(v):
    return round(v, 2) if v is not None else None
