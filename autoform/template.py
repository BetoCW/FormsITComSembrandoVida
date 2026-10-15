"""Construye el plan de llenado de un sembrador.

plantilla (fija) + datos del dia + padron + inventario  ->  lista de Action
en el orden del formulario. Los obligatorios sin dato quedan `pending` y se
reportan; nunca se inventan valores.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import yaml

from . import repeats as rp
from .especies import Catalogo, CATEGORIAS
from .excel_inventario import PlantaFila
from .excel_padron import Sembrador, load_mapeo
from .filler import Action
from .matrix import matrix_actions
from .paths import CONFIG
from .schema_index import Schema


def load_yaml(name: str) -> dict:
    p = CONFIG / name
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def save_yaml(name: str, data: dict, header: str = ""):
    (CONFIG / name).write_text(header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120),
                               encoding="utf-8")


@dataclass
class Plan:
    sembrador: Sembrador
    actions: list[Action]
    issues: list[str] = field(default_factory=list)
    establecida: list = field(default_factory=list)
    eje: list = field(default_factory=list)
    solo_reporte: dict = field(default_factory=dict)

    @property
    def pendientes(self) -> list[Action]:
        return [a for a in self.actions if a.pending]


class PlanBuilder:
    def __init__(self, schema: Schema | None = None, catalogo: Catalogo | None = None):
        self.schema = schema or Schema()
        self.cat = catalogo or Catalogo()
        self.reload()

    def reload(self):
        self.plantilla = load_yaml("plantilla.yaml")
        self.dia = load_yaml("dia.yaml")
        self.reglas = load_yaml("inventario.yaml")
        self.mapeo = load_mapeo()["campos"]
        self.cat.reload_config()

    # ------------------------------------------------------------ helpers
    def _act(self, rel: str, value, source: str, label: str = "", repeat_index: int = 0,
             issues: list | None = None) -> Action | None:
        f = self.schema.get(rel)
        if f is None:
            if issues is not None:
                issues.append(f"La plantilla menciona un campo que no existe en el formulario: {rel}")
            return None
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if f["xml_type"] == "int" and isinstance(value, float):
            value = int(round(value))
        return Action("set", f["path"], value, label=label or f["label"] or f["name"], source=source,
                      repeat=f["repeat"], index=repeat_index, kind=f["kind"], widget=f["widget"],
                      pending=value is None or value == "")

    def _check_options(self, a: Action, issues: list):
        """Avisa si un valor de la plantilla no existe entre las opciones del campo."""
        f = self.schema.by_path.get(a.path)
        if not f or a.pending or not f["options"] or f["itemset_source"]:
            return
        from .textnorm import norm_loose
        opts = {norm_loose(o["label"]) for o in f["options"]}
        vals = a.value if isinstance(a.value, list) else [a.value]
        for v in vals:
            if norm_loose(v) not in opts and not any(o.startswith(norm_loose(v)) for o in opts if len(norm_loose(v)) >= 6):
                issues.append(f"'{v}' no es una opcion de '{a.label}'. Opciones: {', '.join(o['label'] for o in f['options'])}")

    def fecha(self) -> str:
        return (self.dia.get("fecha") or "").strip() or dt.date.today().isoformat()

    def horas(self, n: int) -> tuple[str, str]:
        ini, fin = (self.dia.get("hora_inicio") or "").strip(), (self.dia.get("hora_termino") or "").strip()
        auto = self.dia.get("auto_horas") or {}
        if auto.get("activo") and ini:
            h, m = map(int, ini.split(":")[:2])
            dur, desc = int(auto.get("duracion_min", 60)), int(auto.get("descanso_min", 0))
            start = dt.datetime(2000, 1, 1, h, m) + dt.timedelta(minutes=n * (dur + desc))
            return start.strftime("%H:%M"), (start + dt.timedelta(minutes=dur)).strftime("%H:%M")
        return ini, fin

    # ------------------------------------------------------------ plan
    def build(self, s: Sembrador, filas: list[PlantaFila], n: int = 0, overrides: dict | None = None) -> Plan:
        issues: list[str] = list(s.avisos)
        acts: list[Action] = []
        add = lambda a: a and acts.append(a)  # noqa: E731
        ini, fin = self.horas(n)

        # --- encabezado y datos del dia
        add(self._act("Fecha_de_la_entrevista", self.fecha(), "dia"))
        add(self._act("Hora_de_inicio_de_la_entrevista", ini or None, "dia"))
        add(self._act(self.mapeo["curp_tecnica"], s.curp_tecnica or (self.dia.get("curp_tecnico") or "").upper() or None,
                      "padron" if s.curp_tecnica else "dia"))
        add(self._act("Calidad_de_la_entrevista", self.dia.get("calidad_entrevista"), "dia"))
        add(self._act("Hora_de_t_rmino_de_la_entrevista", fin or None, "dia"))

        # --- padron
        for k in ("curp", "nombre", "apellido_p", "apellido_m", "cac_id", "cac_nombre", "id_predio"):
            add(self._act(self.mapeo[k], getattr(s, k) or None, "padron", issues=issues))
        add(self._act(self.mapeo["centroide"], s.centroide or None, "padron"))

        # --- plantilla fija
        for rel, val in (self.plantilla.get("campos") or {}).items():
            a = self._act(rel, val, "plantilla", issues=issues)
            if a:
                self._check_options(a, issues)
                acts.append(a)
        for rel, val in (self.plantilla.get("cultivo_anual_1") or {}).items():
            add(self._act(rel, val, "plantilla", issues=issues))

        # --- repeats fijos de la plantilla
        acts += self._repeat_from_list("up/sp_tolerantes_e_climaticos", self.plantilla.get("especies_tolerantes"), issues)
        acts += self._repeat_from_list("up/sp_biocultural", self.plantilla.get("especies_bioculturales"), issues)

        # --- matrices
        for mid, rows in (self.plantilla.get("matrices") or {}).items():
            ma, mi = matrix_actions(self.schema, mid, rows)
            acts += ma
            issues += mi

        # --- inventario
        clasificadas, ci = rp.clasificar(filas, self.cat)
        issues += ci
        est = rp.planta_establecida(clasificadas)
        acts += self._establecida(est, issues)
        anio = int(self.fecha()[:4])
        eje = rp.cultivos_eje(clasificadas, anio, int(self.reglas.get("max_cultivos_eje", 3)))
        acts += self._eje(eje, issues)

        # --- ediciones manuales (vista previa)
        if overrides:
            for a in acts:
                k = (a.path, a.index)
                if k in overrides:
                    a.value = overrides[k]
                    a.pending = a.value in (None, "", [])
                    a.source = "manual"

        acts = self._sort(acts)
        return Plan(s, acts, issues, est, eje, self.plantilla.get("solo_reporte") or {})

    def _repeat_from_list(self, repeat_rel: str, items: list | None, issues: list) -> list[Action]:
        if not items:
            return []
        rep_full = self.schema.full(repeat_rel)
        acts = [Action("repeat", rep_full, len(items), label=f"Instancias de {repeat_rel.split('/')[-1]}",
                       source="plantilla")]
        for i, item in enumerate(items):
            for name, val in item.items():
                a = self._act(f"{repeat_rel}/{name}", val, "plantilla", repeat_index=i, issues=issues)
                if a:
                    a.label = f"{a.label} #{i + 1}"
                    self._check_options(a, issues)
                    acts.append(a)
        return acts

    def _establecida(self, grupos: list[rp.GrupoEspecie], issues: list) -> list[Action]:
        sistema = str(self.reglas.get("sistema_planta_establecida", "SAF")).upper()
        sistema = sistema if sistema in rp.ESTABLECIDA else "SAF"
        fijos = self.plantilla.get("planta_establecida") or {}
        acts: list[Action] = []
        for categoria, rep_rel in rp.ESTABLECIDA[sistema].items():
            gs = [g for g in grupos if g.categoria == categoria]
            if not gs:
                continue
            rep_full = self.schema.full(rep_rel)
            acts.append(Action("repeat", rep_full, len(gs), label=f"Planta establecida {categoria} ({sistema})",
                               source="inventario"))
            for i, g in enumerate(gs):
                tag = f" [{categoria} #{i + 1}]"
                def fld(label, val, src="inventario", starts=False):
                    f = self.schema.find_label(rep_rel, label, startswith=starts)
                    if f is None:
                        issues.append(f"No se encontro '{label}' en {rep_rel}")
                        return None
                    a = self._act(self.schema.rel(f["path"]), val, src, repeat_index=i)
                    if a:
                        a.label = f"{f['label']}{tag}"
                    return a
                for a in (fld("Nombre común", g.comun),
                          fld("Nombre científico", g.match.label),
                          fld("Especifique otro nombre científico", g.match.otra_texto) if g.match.otra_texto else None,
                          fld("Número de individuos por especie", g.numero),
                          fld("Año de establecimiento", g.anio),
                          fld("Origen", fijos.get("Origen"), "plantilla"),
                          fld("Tasa de supervivencia promedio", fijos.get("Tasa_de_supervivencia"), "plantilla", True)):
                    if a:
                        acts.append(a)
        return acts

    def _eje(self, cultivos: list[rp.CultivoEje], issues: list) -> list[Action]:
        sistema = str(self.reglas.get("sistema_planta_establecida", "SAF")).upper()
        fijos = self.plantilla.get("cultivos_eje") or {}
        acts: list[Action] = []
        for categoria, rep_rel in rp.EJE.items():
            cs = [c for c in cultivos if c.categoria == categoria]
            rep_full = self.schema.full(rep_rel)
            n = max(1, len(cs))
            if len(cs) > 1:
                acts.append(Action("repeat", rep_full, len(cs), label=f"Cultivos eje {categoria}", source="inventario"))
            for i in range(n):
                c = cs[i] if i < len(cs) else None
                tag = f" [eje {categoria} #{i + 1}]"

                def fld(label, val, src="calculado", starts=False):
                    f = self.schema.find_label(rep_rel, label, startswith=starts)
                    if f is None:
                        return None
                    a = self._act(self.schema.rel(f["path"]), val, src, repeat_index=i)
                    if a:
                        a.label = f"{f['label']}{tag}"
                    return a
                if c is not None:
                    for a in (fld("Nombre común", c.comun, "inventario"),
                              fld("Nombre científico", c.match.label, "inventario"),
                              fld("Otro nombre científico", c.match.otra_texto, "inventario") if c.match.otra_texto else None,
                              fld("Sistema productivo", sistema),
                              fld("Número de plantas establecidas", c.plantas),
                              fld("Edad promedio", c.edad),
                              fld("Altura promedio (cm)", c.altura_cm),
                              fld("Diámetro promedio (cm)", c.diametro_cm)):
                        if a:
                            acts.append(a)
                # valores fijos (en la instancia vacia solo los obligatorios, p. ej. Unidad de medida)
                for label, val in fijos.items():
                    f = self.schema.find_label(rep_rel, label)
                    if f is None:
                        continue
                    if c is None and not f["required"]:
                        continue
                    a = fld(label, val, "plantilla")
                    if a:
                        acts.append(a)
        return acts

    def _sort(self, acts: list[Action]) -> list[Action]:
        order = self.schema.order

        def key(a: Action):
            if a.op == "repeat":
                return (self.schema.first_order(a.path) - 0.5, -1, 0)
            o = order.get(a.path)
            if o is None:   # matriz pendiente sin ruta exacta
                o = 10**6
            if a.repeat and a.repeat != self.schema.full("up"):
                return (self.schema.first_order(a.repeat), a.index, o)
            return (o, 0, 0)
        return sorted(acts, key=key)


def categorias_disponibles() -> list[str]:
    return list(CATEGORIAS)
