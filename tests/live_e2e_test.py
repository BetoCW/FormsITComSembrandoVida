"""Prueba completa en vivo con datos ficticios, en un perfil de prueba aislado.
Llena el plan del primer sembrador de ejemplo y guarda el borrador LOCAL
(IndexedDB del perfil de prueba). Nunca envia: la red bloquea todo POST.
Uso: python tests/live_e2e_test.py [--show] [--no-guardar]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from autoform import guard  # noqa: E402
from autoform.batch import cargar, validar  # noqa: E402
from autoform.filler import Filler  # noqa: E402
from autoform.paths import DATA  # noqa: E402
from autoform.report import write_report  # noqa: E402
from autoform.template import PlanBuilder  # noqa: E402

D = Path(__file__).parent / "datos"
lote = cargar(str(D / "padron_ejemplo.xlsx"), str(D / "inventario_ejemplo.xlsx"))
b = PlanBuilder()
b.dia.update(hora_inicio="09:00", hora_termino="10:00", calidad_entrevista="Completa")
planes, avisos = validar(lote, b)
plan = planes[0]
with Filler(headless="--show" not in sys.argv, profile=DATA / "probe_profile") as f:
    res = f.fill(plan.sembrador.curp, plan.actions, "PRUEBA - " + plan.sembrador.draft_name,
                 save="--no-guardar" not in sys.argv)
    for r in res.fields:
        if r.status not in ("ok", "pendiente"):
            print(f"{r.status:9} {r.action.label[:70]:70} {r.detail[:200]}")
    print("estado:", res.status, res.error)
    print("ok:", sum(r.status == "ok" for r in res.fields), "fallo:", sum(r.status == "fallo" for r in res.fields),
          "pendiente:", sum(r.status == "pendiente" for r in res.fields),
          "no_aplica:", sum(r.status == "no_aplica" for r in res.fields))
    print("obligatorios vacios:", [x["label"] for x in res.required_empty])
    print("autosave:", f.autosave_events, "| bloqueadas:", res.blocked_requests)
    if res.status == "borrador_guardado":
        f.page.wait_for_timeout(1500)
        f.page.locator(".offline-enabled__queue-length, .queue-length").first.wait_for(timeout=5000)
        print("borradores en el perfil:", f.page.evaluate(
            "() => [...document.querySelectorAll('.record-list__records li')].map(li => li.innerText.trim())"))
print("reporte:", write_report([{"plan": plan, "result": res}], avisos, []))
