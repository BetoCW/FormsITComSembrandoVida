"""Descubrimiento del formulario Enketo.

Descarga (solo lectura) la definicion del formulario desde el endpoint
`/transform/xform/<id>` de Enketo Express y la convierte en `form_schema.json`:
ruta, tipo, etiqueta, opciones (value + texto), obligatorio, relevancia,
repeat/matriz y catalogos externos (CSV de especies, rutas, personal).

Nada de esto envia datos: es la misma peticion que hace el navegador al abrir
el formulario.
"""
from __future__ import annotations

import csv
import io
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from .paths import FORM_CACHE, OUTPUT

BASE_URL = "https://ee.sembrandodatos.com"
ENKETO_ID = "7kMmQETh"


# ---------------------------------------------------------------- descarga
def download_form(enketo_id: str = ENKETO_ID, base_url: str = BASE_URL,
                  cache: Path = FORM_CACHE) -> Path:
    """Descarga form.html, model.xml y los CSV externos al cache local."""
    cache.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(f"{base_url}/transform/xform/{enketo_id}", method="POST",
                                 data=b"", headers={"User-Agent": "AutoFormPSV/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode("utf-8"))
    (cache / "transform.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (cache / "form.html").write_text(data["form"], encoding="utf-8")
    (cache / "model.xml").write_text(data["model"], encoding="utf-8")
    media = data.get("media") or {}
    (cache / "media").mkdir(exist_ok=True)
    for name, url in media.items():
        with urllib.request.urlopen(base_url + urllib.parse.quote(url), timeout=120) as r:
            (cache / "media" / name).write_bytes(r.read())
    return cache


# ---------------------------------------------------------------- modelo
@dataclass
class Option:
    value: str
    label: str


@dataclass
class Field:
    path: str                      # /aofp.../up/sistema
    name: str                      # sistema
    kind: str                      # text, number, date, time, select_one, select_multiple, geopoint, note, calculate
    widget: str                    # radio, checkbox, select, autocomplete, input, readonly, hidden
    label: str
    hint: str = ""
    xml_type: str = ""
    required: bool = False
    required_expr: str = ""
    relevant: list[str] = field(default_factory=list)   # propia + ancestros
    constraint: str = ""
    calculate: str = ""
    readonly: bool = False
    options: list[Option] = field(default_factory=list)
    itemset: str = ""              # instance('frutales')/root/item...
    itemset_source: str = ""       # frutales
    repeat: str = ""               # ruta del repeat mas cercano
    groups: list[str] = field(default_factory=list)      # titulos de grupos
    matrix: dict | None = None     # {"id","title","row","row_index","columns":[A..]}


def _txt(el: Tag | None) -> str:
    if el is None:
        return ""
    # ignora spans ocultos (etiquetas internas de matrices)
    clone = BeautifulSoup(str(el), "lxml")
    for hidden in clone.select('[style*="display:none"]'):
        hidden.decompose()
    return re.sub(r"\s+", " ", clone.get_text(" ", strip=True)).strip()


def _short(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _ancestor_relevants(el: Tag) -> list[str]:
    out = []
    for anc in el.parents:
        if isinstance(anc, Tag) and anc.get("data-relevant"):
            out.append(anc["data-relevant"].strip())
    return out[::-1]


def _group_titles(el: Tag) -> list[str]:
    titles = []
    for anc in el.parents:
        if not isinstance(anc, Tag) or anc.name != "section":
            continue
        h = anc.find(["h4"], recursive=False)
        if h is not None:
            t = _txt(h)
            if t:
                titles.append(t)
    return titles[::-1]


def _repeat_of(el: Tag) -> str:
    r = el.find_parent("section", class_="or-repeat")
    return r.get("name", "") if r else ""


_MATRIX_RE = re.compile(r"/(group_[a-z0-9]+)_((?:fila|evento)(?:_\d+)?)/")


def _matrix_info(path: str, el: Tag, soup_cache: dict) -> dict | None:
    m = _MATRIX_RE.search(path + "/")
    if not m:
        return None
    mid, row = m.group(1), m.group(2)
    row_sec = el.find_parent("section", attrs={"name": re.compile(rf"/{mid}_{row}$")})
    if row_sec is None:
        return None
    row_label = _txt(row_sec.find("label", class_="question"))
    parent = row_sec.parent
    header = parent.find("section", attrs={"name": re.compile(rf"/{mid}_header$")}) if parent else None
    col_title = ""
    if header is not None:
        labels = header.find_all("label", class_="question")
        if len(labels) > 1:
            col_title = _txt(labels[1].find(class_="question-label"))
    # titulo de la pregunta: nota/label que precede al bloque de la matriz
    title = soup_cache.get(mid)
    if title is None:
        title = ""
        anchor = header if header is not None else row_sec
        for sib in anchor.find_all_previous(["label", "h4"], limit=40):
            t = _txt(sib.find(class_="question-label") if sib.name == "label" else sib)
            if t and t.startswith("¿"):
                title = t
                break
        soup_cache[mid] = title
    rows = [s for s in parent.find_all("section", recursive=False)
            if re.search(rf"/{mid}_(?:fila|evento)(?:_\d+)?$", s.get("name", ""))] if parent else []
    row_index = rows.index(row_sec) if row_sec in rows else -1
    return {"id": mid, "title": title, "column_title": col_title, "row": row_label,
            "row_index": row_index}


def _kind_widget(inputs: list[Tag]) -> tuple[str, str]:
    first = inputs[0]
    if first.name == "select":
        return ("select_multiple" if first.has_attr("multiple") else "select_one", "select")
    if first.name == "textarea":
        return "text", "input"
    t = first.get("type", "text")
    xml = first.get("data-type-xml", "")
    if t == "radio":
        return "select_one", "radio"
    if t == "checkbox":
        return "select_multiple", "checkbox"
    if xml == "geopoint":
        return "geopoint", "geopoint"
    if first.has_attr("list"):
        return "select_one", "autocomplete"
    if first.has_attr("readonly") and not first.get("data-calculate"):
        return "note", "readonly"
    if t == "number" or xml in ("int", "decimal"):
        return "number", "input"
    if t in ("date", "time"):
        return t, "input"
    return "text", "input"


def parse_form(cache: Path = FORM_CACHE) -> dict:
    html = (cache / "form.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form")
    root = "/" + form.get("data-form-id", "data")
    title = _txt(soup.find(id="form-title")) or ""
    fields: list[Field] = []
    seen: set[str] = set()
    mcache: dict = {}

    for q in soup.select(".question"):
        inputs = [i for i in q.select("input,select,textarea")
                  if (i.get("name") or i.get("data-name")) and i.get("type") != "hidden"]
        if not inputs:
            continue
        path = inputs[0].get("data-name") or inputs[0].get("name")
        if path in seen or not path.startswith(root):
            continue
        seen.add(path)
        kind, widget = _kind_widget(inputs)
        label_el = q.find(class_="question-label")
        f = Field(
            path=path, name=_short(path), kind=kind, widget=widget,
            label=_txt(label_el), hint=_txt(q.find(class_="or-hint")),
            xml_type=inputs[0].get("data-type-xml", ""),
            required_expr=(inputs[0].get("data-required") or "").strip(),
            constraint=(inputs[0].get("data-constraint") or "").strip(),
            readonly=inputs[0].has_attr("readonly"),
            repeat=_repeat_of(q), groups=_group_titles(q),
        )
        f.required = bool(f.required_expr) and f.required_expr not in ("false()",)
        own_rel = (inputs[0].get("data-relevant") or "").strip()
        f.relevant = _ancestor_relevants(q) + ([own_rel] if own_rel else [])
        if widget in ("radio", "checkbox"):
            for i in inputs:
                if i.get("value") is None:
                    continue
                lab = i.find_next_sibling(class_="option-label")
                f.options.append(Option(i["value"], _txt(lab)))
        elif widget == "select":
            for o in inputs[0].find_all("option"):
                if o.get("value"):
                    f.options.append(Option(o["value"], _txt(o)))
        tmpl = q.select_one(".itemset-template")
        if tmpl is not None:
            f.itemset = tmpl.get("data-items-path", "")
            m = re.search(r"instance\('([^']+)'\)", f.itemset)
            f.itemset_source = m.group(1) if m else ""
            f.options = [o for o in f.options if o.value]
        f.matrix = _matrix_info(path, q, mcache)
        fields.append(f)

    for calc in soup.select("[data-calculate]"):
        path = calc.get("name")
        if path in seen:
            continue
        seen.add(path)
        fields.append(Field(path=path, name=_short(path), kind="calculate", widget="hidden",
                            label="", calculate=calc["data-calculate"].strip(),
                            xml_type=calc.get("data-type-xml", ""), repeat=_repeat_of(calc)))

    repeats = []
    for r in soup.select("section.or-repeat"):
        repeats.append({"path": r.get("name"), "title": _txt(r.find_previous("h4")),
                        "relevant": _ancestor_relevants(r) + ([r["data-relevant"]] if r.get("data-relevant") else [])})
    matrices = {}
    for f in fields:
        if f.matrix and f.kind != "note":
            m = matrices.setdefault(f.matrix["id"], {"id": f.matrix["id"], "title": f.matrix["title"],
                                                     "column_title": f.matrix["column_title"],
                                                     "columns": [o.label for o in f.options], "rows": []})
            m["rows"].append({"row": f.matrix["row"], "path": f.path})

    return {
        "form_id": form.get("data-form-id"),
        "root": root,
        "title": title,
        "enketo_url": f"{BASE_URL}/x/{ENKETO_ID}",
        "fields": [asdict(f) for f in fields],
        "repeats": repeats,
        "matrices": list(matrices.values()),
        "catalogs": load_catalogs(cache),
    }


# ---------------------------------------------------------------- catalogos
SPECIES_LISTS = ("frutales", "forestales", "agroindustriales", "agroindustriales_fix",
                 "especias", "PERENNES", "anuales", "cientificos_Cykb1OA")


def load_catalogs(cache: Path = FORM_CACHE) -> dict:
    out = {}
    for name in SPECIES_LISTS:
        p = cache / "media" / f"{name}.csv"
        if not p.exists():
            continue
        rows = list(csv.DictReader(io.StringIO(p.read_text(encoding="utf-8-sig"))))
        out[name] = [{"value": r.get("name", ""), "label": r.get("label", ""),
                      "list": r.get("list_name", "")} for r in rows]
    return out


def load_media_csv(name: str, cache: Path = FORM_CACHE) -> list[dict]:
    p = cache / "media" / f"{name}.csv"
    return list(csv.DictReader(io.StringIO(p.read_text(encoding="utf-8-sig")))) if p.exists() else []


def load_schema(path: Path | None = None) -> dict:
    path = path or (OUTPUT / "form_schema.json")
    if not path.exists():
        schema = parse_form()
        save_schema(schema, path)
        return schema
    return json.loads(path.read_text(encoding="utf-8"))


def save_schema(schema: dict, path: Path | None = None) -> Path:
    path = path or (OUTPUT / "form_schema.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def required_summary(schema: dict) -> str:
    """Texto legible con los obligatorios agrupados por seccion."""
    lines = []
    for f in schema["fields"]:
        if not f["required"]:
            continue
        cond = " Y ".join(f["relevant"]) if f["relevant"] else "siempre"
        cond = cond.replace(schema["root"] + "/", "")
        opts = ", ".join(o["label"] for o in f["options"][:8])
        if f["itemset_source"]:
            opts = f"(catalogo {f['itemset_source']})"
        lines.append(f"- [{f['kind']}] {f['label'] or f['name']}  <{f['path'].replace(schema['root'], '')}>"
                     f"\n    visible si: {cond}" + (f"\n    opciones: {opts}" if opts else "")
                     + (f"\n    repeat: {f['repeat'].replace(schema['root'], '')}" if f["repeat"] else ""))
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if "--download" in sys.argv:
        download_form()
    s = parse_form()
    p = save_schema(s)
    print(f"{len(s['fields'])} campos, {sum(f['required'] for f in s['fields'])} obligatorios, "
          f"{len(s['repeats'])} repeats, {len(s['matrices'])} matrices -> {p}")
