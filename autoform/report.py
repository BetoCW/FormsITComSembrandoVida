"""Reporte Excel por lote: estado de cada sembrador, pendientes, fallos,
especies corregidas o enviadas como "Otra", validacion y log."""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from .filler import FillResult
from .paths import OUTPUT


def _val(v):
    if isinstance(v, list):
        return ", ".join(map(str, v))
    return "" if v is None else v


def write_report(entries: list[dict], validation: list[str], log_lines: list[str], path: Path | None = None) -> Path:
    """entries: [{"plan": Plan, "result": FillResult | None}]"""
    path = path or OUTPUT / f"reporte_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    resumen, detalle, pendientes, especies = [], [], [], []
    for e in entries:
        plan, res = e["plan"], e.get("result")
        s = plan.sembrador
        fields = {(fr.action.path, fr.action.index): fr for fr in (res.fields if res else [])}
        req_empty = res.required_empty if res else []
        resumen.append({
            "CURP": s.curp, "Sembrador": s.nombre_completo, "Estado": res.status if res else "solo_plan",
            "Borrador": res.draft_name if res else s.draft_name,
            "Campos OK": sum(f.status == "ok" for f in fields.values()),
            "Campos fallidos": sum(f.status == "fallo" for f in fields.values()),
            "No aplica": sum(f.status == "no_aplica" for f in fields.values()),
            "Pendientes (plan)": len(plan.pendientes),
            "Obligatorios vacios (formulario)": len(req_empty),
            "Avisos": len(plan.issues),
            "Error": res.error if res else "",
            "Capturas": "; ".join(res.screenshots) if res else "",
            **{f"Solo reporte: {k}": v for k, v in plan.solo_reporte.items()},
        })
        for a in plan.actions:
            fr = fields.get((a.path, a.index))
            detalle.append({
                "CURP": s.curp, "Sembrador": s.nombre_completo, "Campo": a.label,
                "Ruta": a.path.split("/", 2)[-1], "Instancia": a.index + 1, "Valor": _val(a.value),
                "Origen del dato": a.source, "Estado": fr.status if fr else ("pendiente" if a.pending else "no_ejecutado"),
                "Detalle": fr.detail if fr else "", "Leido del formulario": _val(fr.read_back) if fr else "",
            })
        for a in plan.pendientes:
            pendientes.append({"CURP": s.curp, "Sembrador": s.nombre_completo, "Campo": a.label,
                               "Origen": a.source, "Tipo": "plan (sin dato)"})
        for r in req_empty:
            pendientes.append({"CURP": s.curp, "Sembrador": s.nombre_completo, "Campo": r["label"],
                               "Origen": "formulario", "Tipo": "obligatorio vacio al guardar"})
        for g in plan.establecida:
            m = g.match
            if m.avisos or m.metodo in ("otra", "sin_categoria"):
                especies.append({"CURP": s.curp, "Sembrador": s.nombre_completo, "Nombre comun": m.entrada_comun,
                                 "Nombre cientifico (inventario)": m.entrada_cientifico, "Categoria": m.categoria,
                                 "Especie del catalogo": m.label, "Otra (texto)": m.otra_texto,
                                 "Similitud": round(m.score), "Metodo": m.metodo, "Avisos": " | ".join(m.avisos)})
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, rows in (("Resumen", resumen), ("Detalle", detalle), ("Pendientes", pendientes),
                           ("Especies", especies), ("Validacion", [{"Aviso": v} for v in validation]),
                           ("Log", [{"Linea": x} for x in log_lines])):
            df = pd.DataFrame(rows or [{}])
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            for col in ws.columns:
                width = min(80, max((len(str(c.value)) for c in col if c.value is not None), default=8) + 2)
                ws.column_dimensions[col[0].column_letter].width = width
            ws.freeze_panes = "A2"
    return path
