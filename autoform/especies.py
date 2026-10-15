"""Catalogo de especies del formulario, emparejamiento difuso y categorias.

Los catalogos salen de los CSV externos del formulario (frutales.csv,
forestales.csv, ...). Cada etiqueta tiene la forma
"NOMBRE COMUN, OTRO NOMBRE (NOMBRE CIENTIFICO)".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml
from rapidfuzz import fuzz, process

from .form_schema import load_media_csv
from .paths import CONFIG
from .textnorm import norm

# categoria -> (catalogo de "planta establecida", catalogo de "cultivos eje", valor "Otra")
CATEGORIAS = {
    "Forestales": {"catalogo": "forestales", "otra": "FORESTALES_501"},
    "Agroindustrial": {"catalogo": "agroindustriales", "otra": "AGROINDUSTRIALES_79"},
    "Frutales": {"catalogo": "frutales", "otra": "Otra"},
    "Especias": {"catalogo": "especias", "otra": "ESPECIAS_14"},
}
CATALOGO_PERENNES = "PERENNES"
CATALOGO_ANUALES = "anuales"


@dataclass
class Especie:
    value: str
    label: str
    comunes: list[str]
    cientifico: str

    @property
    def es_otra(self) -> bool:
        return norm(self.label) in ("OTRA", "OTRO")


@dataclass
class Match:
    entrada_comun: str
    entrada_cientifico: str
    categoria: str | None
    especie: Especie | None
    score: float
    metodo: str                     # alias | cientifico | comun | otra | sin_categoria
    otra_texto: str = ""
    avisos: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.especie.label if self.especie else ""


_PAREN = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")


def parse_label(label: str) -> tuple[list[str], str]:
    m = _PAREN.match(label.strip())
    if not m:
        return [label.strip()], ""
    comunes = [c.strip() for c in m.group(1).split(",") if c.strip()]
    return comunes, m.group(2).strip()


def load_catalog(name: str) -> list[Especie]:
    out = []
    for r in load_media_csv(name):
        comunes, cient = parse_label(r["label"])
        out.append(Especie(r["name"], r["label"], comunes, cient))
    return out


def _yaml(name: str) -> dict:
    p = CONFIG / name
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _clean_cientifico(s: str) -> str:
    s = norm(s)
    s = re.sub(r"\b(SP|SPP|VAR|SSP|SUBSP)\b\.?", "", s)
    s = re.sub(r"(.)\1{2,}", r"\1", s)            # "FFRAXINUS" -> sigue igual, "AAA" -> "A"
    s = re.sub(r"^([A-Z])\1", r"\1", s)            # "FFRAXINUS" -> "FRAXINUS"
    return re.sub(r"\s+", " ", s).strip()


class Catalogo:
    def __init__(self, umbral: float | None = None):
        cfg = _yaml("inventario.yaml")
        self.umbral = float(umbral if umbral is not None else cfg.get("umbral_fuzzy", 85))
        self.catalogos = {c: load_catalog(v["catalogo"]) for c, v in CATEGORIAS.items()}
        self.perennes = load_catalog(CATALOGO_PERENNES)
        self.anuales = load_catalog(CATALOGO_ANUALES)
        self.reload_config()

    def reload_config(self):
        cat_cfg = _yaml("categorias_especies.yaml")
        self.categoria_por_nombre: dict[str, str] = {}
        for categoria, nombres in (cat_cfg.get("categorias") or {}).items():
            for n in nombres or []:
                self.categoria_por_nombre[norm(n)] = categoria
        self.alias: dict[str, dict] = {norm(k): v for k, v in (_yaml("alias_especies.yaml").get("alias") or {}).items()}

    # ------------------------------------------------------------ categoria
    def categoria(self, comun: str, cientifico: str = "") -> str | None:
        keys = [norm(cientifico), norm(comun)] + [norm(x) for x in re.split(r"[,/;]", comun or "") if x.strip()]
        for k in keys:
            if k and k in self.categoria_por_nombre:
                return self.categoria_por_nombre[k]
        # coincidencia por palabra clave (p. ej. "PINO OCOTE" contiene "PINO")
        for k in keys:
            for nombre, cat in sorted(self.categoria_por_nombre.items(), key=lambda x: -len(x[0])):
                if k and re.search(rf"\b{re.escape(nombre)}\b", k):
                    return cat
        return None

    # ------------------------------------------------------------ busqueda
    def _best(self, catalogo: list[Especie], comun: str, cientifico: str) -> tuple[Especie | None, float, str]:
        validos = [e for e in catalogo if not e.es_otra]
        best, score, metodo = None, 0.0, ""
        c = _clean_cientifico(cientifico)
        if c:
            choices = {i: _clean_cientifico(e.cientifico) for i, e in enumerate(validos) if e.cientifico}
            r = process.extractOne(c, choices, scorer=fuzz.token_sort_ratio)
            if r:
                best, score, metodo = validos[r[2]], r[1], "cientifico"
                # varias especies con el mismo cientifico: desempatar por nombre comun
                same = [validos[i] for i, v in choices.items() if v == choices[r[2]]]
                if len(same) > 1 and comun:
                    best = max(same, key=lambda e: max(fuzz.token_set_ratio(norm(comun), norm(x)) for x in e.comunes))
        if comun and score < self.umbral:
            partes = [norm(x) for x in re.split(r"[,/;]", comun) if x.strip()] or [norm(comun)]
            for parte in partes:
                for e in validos:
                    s = max(fuzz.token_sort_ratio(parte, norm(x)) for x in e.comunes)
                    if s > score:
                        best, score, metodo = e, s, "comun"
        return best, score, metodo

    def match(self, comun: str, cientifico: str = "", categoria: str | None = None) -> Match:
        comun, cientifico = (comun or "").strip(), (cientifico or "").strip()
        avisos = []
        alias = self.alias.get(norm(cientifico)) or self.alias.get(norm(comun))
        if alias:
            cat = alias.get("categoria") or categoria or self.categoria(comun, cientifico)
            cat_list = self.catalogos.get(cat, [])
            esp = next((e for e in cat_list if norm(e.label) == norm(alias.get("label", ""))), None)
            if esp:
                return Match(comun, cientifico, cat, esp, 100, "alias")
            avisos.append(f"alias '{alias.get('label')}' no existe en el catalogo {cat}")
        cat = categoria or self.categoria(comun, cientifico)
        if not cat:
            # sin categoria configurada: buscar en todos e informar
            mejores = [(c, *self._best(lst, comun, cientifico)) for c, lst in self.catalogos.items()]
            c, esp, score, metodo = max(mejores, key=lambda x: x[2])
            avisos.append(f"especie sin categoria en categorias_especies.yaml (sugerida: {c}, {esp.label if esp else '-'}, {score:.0f})")
            return Match(comun, cientifico, None, esp if score >= self.umbral else None, score, "sin_categoria",
                         avisos=avisos)
        esp, score, metodo = self._best(self.catalogos[cat], comun, cientifico)
        if esp is not None and score >= self.umbral:
            if metodo == "comun" and cientifico:
                avisos.append(f"el cientifico '{cientifico}' no esta en el catalogo {cat}; "
                              f"emparejado por nombre comun -> '{esp.label}' ({score:.0f})")
            elif score < 100 or (cientifico and norm(cientifico) != norm(esp.cientifico)):
                avisos.append(f"corregido por similitud ({score:.0f}): '{cientifico or comun}' -> '{esp.label}'")
            return Match(comun, cientifico, cat, esp, score, metodo, avisos=avisos)
        otra = next(e for e in self.catalogos[cat] if e.value == CATEGORIAS[cat]["otra"] or e.es_otra)
        avisos.append(f"sin coincidencia >= {self.umbral:.0f} (mejor: {esp.label if esp else '-'} {score:.0f}); se usa 'Otra'")
        for otra_cat, lst in self.catalogos.items():
            if otra_cat == cat:
                continue
            e2, s2, _ = self._best(lst, comun, cientifico)
            if e2 is not None and s2 >= self.umbral:
                avisos.append(f"SUGERENCIA: existe en el catalogo {otra_cat}: '{e2.label}' ({s2:.0f}). "
                              f"Si es correcto, cambia su categoria en categorias_especies.yaml")
        return Match(comun, cientifico, cat, otra, score, "otra",
                     otra_texto=(cientifico or comun).upper(), avisos=avisos)

    def match_in(self, catalogo: list[Especie], comun: str, cientifico: str = "") -> Match:
        esp, score, metodo = self._best(catalogo, comun, cientifico)
        if esp and score >= self.umbral:
            return Match(comun, cientifico, None, esp, score, metodo)
        otra = next((e for e in catalogo if e.es_otra), None)
        return Match(comun, cientifico, None, otra, score, "otra", otra_texto=(cientifico or comun).upper(),
                     avisos=[f"sin coincidencia en catalogo (mejor {esp.label if esp else '-'} {score:.0f})"])

    def save_alias(self, entrada: str, categoria: str, label: str):
        p = CONFIG / "alias_especies.yaml"
        data = _yaml("alias_especies.yaml") or {}
        data.setdefault("alias", {})[entrada.upper()] = {"categoria": categoria, "label": label}
        p.write_text("# Correcciones aprobadas: entrada del inventario -> especie del catalogo\n"
                     + yaml.safe_dump(data, allow_unicode=True, sort_keys=True), encoding="utf-8")
        self.reload_config()
