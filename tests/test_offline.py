"""Pruebas sin navegador: lectura de Excel, limpieza, especies y plan.
Uso: python tests/test_offline.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from autoform import guard  # noqa: E402
from autoform.batch import cargar, validar  # noqa: E402
from autoform.especies import Catalogo  # noqa: E402
from autoform.excel_common import cell_num  # noqa: E402
from autoform.template import PlanBuilder  # noqa: E402

D = Path(__file__).parent / "datos"
fails = 0


def check(cond, msg):
    global fails
    print(("OK   " if cond else "FAIL ") + msg)
    fails += 0 if cond else 1


# limpieza numerica
check(cell_num(".20") == 0.2, "'.20' -> 0.2")
check(cell_num("1,5") == 1.5, "'1,5' -> 1.5")
check(cell_num("") is None and cell_num(None) is None, "vacio -> None (no 0)")

# guardia
try:
    guard.check_selector("#submit-form")
    check(False, "guardia bloquea #submit-form")
except guard.SubmitForbidden:
    check(True, "guardia bloquea #submit-form")

lote = cargar(str(D / "padron_ejemplo.xlsx"), str(D / "inventario_ejemplo.xlsx"))
check(len(lote.sembradores) == 3, "3 sembradores en el padron")
juan, maria, pedro = lote.sembradores
check(maria.latitud == 21.4801, "coordenadas desde ID_PREDIO cuando faltan")
check(len(lote.inventario[juan.uid]) == 8, "inventario de Juan: 8 filas tras deduplicar")
check(any("identica" in v for v in lote.validacion), "duplicado reportado")
check(any("FANTASMA" in v for v in lote.validacion), "inventario sin sembrador reportado")
check(any("sin inventario" in v and "PEDRO" in v for v in lote.validacion), "sembrador sin inventario reportado")
alt = [f.altura_cm for f in lote.inventario[juan.uid] if f.comun == "MANGO"][0]
check(alt == 20, "altura .20 m -> 20 cm")

cat = Catalogo()
m = cat.match("FRESNO", "FFRAXINUS UHDEI")
check(m.label == "FRESNO, MADRE DE AGUA (FRAXINUS UHDEI)", "FFRAXINUS UHDEI corregido")
m = cat.match("PINO OCOTE", "PINUS OOCARPA")
check(m.metodo == "otra" and m.otra_texto == "PINUS OOCARPA", "especie sin match -> Otra + texto")

b = PlanBuilder()
b.dia = {"fecha": "2026-10-15", "hora_inicio": "", "hora_termino": "", "curp_tecnico": "",
         "calidad_entrevista": None}   # independiente del dia.yaml local
planes, avisos = validar(lote, b)
p = planes[0]
labels = {a.label: a for a in p.actions}
check(labels["Ruta"].value == "RUTA ZONA 7", "ruta 300 -> RUTA ZONA 7")
check(labels["Registra el centroide del predio"].value == "21.5123 -104.8941 0 0", "geopoint lat lon alt acc")
naranja = [c for c in p.eje if "NARANJA" in c.match.label][0]
check(naranja.plantas == 60 and naranja.altura_cm == round((120 * 40 + 80 * 20) / 60, 2), "eje: suma y promedio ponderado")
check(all(not a.pending for a in p.actions if a.source == "padron"), "datos del padron completos para Juan")
check(any(a.pending and "Calidad" in a.label for a in p.actions), "calidad sin definir queda PENDIENTE")
order = [a.op for a in p.actions]
rep_idx = next(i for i, a in enumerate(p.actions) if a.op == "repeat" and a.path.endswith("Frutales_saf"))
first_fr = next(i for i, a in enumerate(p.actions) if a.repeat.endswith("Frutales_saf"))
check(rep_idx < first_fr, "el repeat se crea antes de llenar sus campos")
print(f"\n{'TODO OK' if not fails else f'{fails} FALLAS'}")
sys.exit(1 if fails else 0)
