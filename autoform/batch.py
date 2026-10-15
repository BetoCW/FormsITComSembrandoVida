"""Orquestacion: validar, construir planes y llenar por lotes (sin GUI).

Uso por linea de comandos:
    python -m autoform.batch validar  --padron P.xlsx --inventario I.xlsx
    python -m autoform.batch llenar   --padron P.xlsx --inventario I.xlsx [--curp X ...] [--pausa] [--headless] [--no-guardar]
    python -m autoform.batch descubrir [--descargar]
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field
from typing import Callable

from .excel_inventario import read_inventario, unir, PlantaFila
from .excel_padron import read_padron, Sembrador
from .filler import Filler
from .report import write_report
from .template import PlanBuilder, Plan


@dataclass
class Lote:
    sembradores: list[Sembrador] = field(default_factory=list)
    inventario: dict[str, list[PlantaFila]] = field(default_factory=dict)
    validacion: list[str] = field(default_factory=list)


def cargar(padron: str | None, inventario: str | None) -> Lote:
    lote = Lote()
    if padron:
        lote.sembradores, iss = read_padron(padron)
        lote.validacion += iss
    filas: list[PlantaFila] = []
    if inventario:
        filas, iss = read_inventario(inventario)
        lote.validacion += iss
    if lote.sembradores:
        lote.inventario, iss = unir(lote.sembradores, filas)
        lote.validacion += iss
    return lote


def validar(lote: Lote, builder: PlanBuilder) -> tuple[list[Plan], list[str]]:
    """Construye todos los planes y junta los avisos (validacion previa)."""
    planes, avisos = [], list(lote.validacion)
    for n, s in enumerate(lote.sembradores):
        p = builder.build(s, lote.inventario.get(s.uid, []), n)
        planes.append(p)
        for i in p.issues:
            if i not in s.avisos:
                avisos.append(f"{s.nombre_completo}: {i}")
    # resumen de pendientes de la plantilla (iguales para todos)
    if planes:
        comunes = {a.label for a in planes[0].pendientes if a.source in ("plantilla", "dia")}
        if comunes:
            avisos.append(f"Pendientes de plantilla/dia ({len(comunes)}): " + "; ".join(sorted(comunes)))
    return planes, list(dict.fromkeys(avisos))


def llenar(planes: list[Plan], headless: bool = False, guardar: bool = True,
           pausa: Callable[[Plan], bool] | None = None, log: Callable[[str], None] = print,
           progreso: Callable | None = None, detener: Callable[[], bool] = lambda: False,
           on_autosave: str = "descartar", ask_autosave: Callable[[str], str] | None = None) -> list[dict]:
    entries = []
    with Filler(headless=headless, logger=log, on_autosave=on_autosave, ask_autosave=ask_autosave) as f:
        for k, plan in enumerate(planes):
            if detener():
                log("Detenido por el usuario.")
                break
            s = plan.sembrador
            log(f"[{k + 1}/{len(planes)}] {s.draft_name}")
            t0 = time.time()
            res = f.fill(s.curp or s.key, plan.actions, s.draft_name, save=guardar,
                         pause_before_save=(lambda p=plan: pausa(p)) if pausa else None,
                         progress=(lambda i, n, r, kk=k: progreso(kk, i, n, r)) if progreso else None)
            ok = sum(r.status == "ok" for r in res.fields)
            bad = sum(r.status == "fallo" for r in res.fields)
            log(f"    {res.status}: {ok} ok, {bad} fallidos, {len(res.required_empty)} obligatorios vacios "
                f"({time.time() - t0:.0f}s)")
            if f.autosave_events:
                log("    " + "; ".join(f.autosave_events))
                f.autosave_events.clear()
            entries.append({"plan": plan, "result": res})
            if "auto-guardado" in (res.error or ""):
                log("Lote detenido: hay un registro auto-guardado pendiente en el navegador.")
                break
    return entries


def main(argv=None):
    ap = argparse.ArgumentParser(prog="autoform")
    ap.add_argument("accion", choices=["validar", "llenar", "descubrir"])
    ap.add_argument("--padron")
    ap.add_argument("--inventario")
    ap.add_argument("--curp", nargs="*")
    ap.add_argument("--pausa", action="store_true", help="pausa antes de guardar cada borrador")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--no-guardar", action="store_true")
    ap.add_argument("--descargar", action="store_true")
    a = ap.parse_args(argv)
    if a.accion == "descubrir":
        from .form_schema import download_form, parse_form, save_schema, required_summary
        if a.descargar:
            download_form()
        s = parse_form()
        print(save_schema(s))
        print(required_summary(s))
        return
    lote = cargar(a.padron, a.inventario)
    if a.curp:
        lote.sembradores = [s for s in lote.sembradores if s.curp in a.curp]
    builder = PlanBuilder()
    planes, avisos = validar(lote, builder)
    print("\n".join(avisos))
    logs: list[str] = []
    entries = [{"plan": p, "result": None} for p in planes]
    if a.accion == "llenar":
        def pausa(p):
            return input(f"Revisa el navegador. ¿Guardar borrador de {p.sembrador.draft_name}? [s/N] ").strip().lower() == "s"
        entries = llenar(planes, headless=a.headless, guardar=not a.no_guardar, pausa=pausa if a.pausa else None,
                         log=lambda m: (print(m), logs.append(m)))
    print("Reporte:", write_report(entries, avisos, logs))


if __name__ == "__main__":
    main()
