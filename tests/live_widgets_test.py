"""Prueba en vivo de cada tipo de widget (headless, NO guarda ni envia).
Uso: python tests/live_widgets_test.py [--show]"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from autoform.filler import Filler, Action  # noqa: E402
from autoform.paths import DATA, FORM_CACHE  # noqa: E402
from autoform import guard  # noqa: E402

R = "/aofpSYF3s4WGcra4oLPYev"
UP = R + "/up"
# Personal_op.csv no se versiona (datos personales); se baja con: python -m autoform descubrir --descargar
_po = FORM_CACHE / "media/Personal_op.csv"
tec = next((r for r in csv.DictReader(open(_po, encoding="utf-8-sig")) if "JALISCO" in r["terri"].upper()),
           None) if _po.exists() else None
tec = tec or {"curp": "TEDE850101MNTRRR05"}

plan = [
    Action("set", R + "/Fecha_de_la_entrevista", "2026-10-15", kind="date", widget="input"),
    Action("set", R + "/Hora_de_inicio_de_la_entrevista", "09:30", kind="time", widget="input"),
    Action("set", R + "/datos_curp/curp_ingresado", tec["curp"], kind="text", widget="input"),
    Action("set", R + "/group_eq6af71/territorios", "JALISCO-NAYARIT", kind="select_one", widget="select"),
    Action("set", R + "/group_eq6af71/ruta_otro_op", "Si", kind="select_one", widget="select"),
    Action("set", R + "/group_eq6af71/ruta", "RUTA ZONA 7", kind="select_one", widget="autocomplete"),
    Action("set", R + "/group_eq6af71/curp", "XAXX010101HNTRRR09", kind="text", widget="input"),
    Action("set", R + "/group_eq6af71/A_o_de_ingreso", 2020, kind="number", widget="input"),
    Action("set", UP + "/num_up_txt", "21.5,-104.9", kind="text", widget="input", repeat=UP),
    Action("set", UP + "/Registra_el_centroide_del_predio", "21.5 -104.9 0 0", kind="geopoint", widget="geopoint", repeat=UP),
    Action("set", UP + "/Uso_de_suelo_inicial", "Cultivo de milpa", kind="select_one", widget="select", repeat=UP),
    Action("set", UP + "/sistema", "SAF y MIAF", kind="select_one", widget="select", repeat=UP),
    Action("set", UP + "/Total_de_Hect_reas_SAF", 1, kind="number", widget="input", repeat=UP),
    Action("set", UP + "/_La_UP_tiene_problemas_del_suelo", ["deficiencia de materia orgánica", "poca fertilidad"],
           kind="select_multiple", widget="select", repeat=UP),
    Action("set", UP + "/_La_UP_tiene_alta_mortandad_de", "Sí", kind="select_one", widget="radio", repeat=UP),
    Action("set", UP + "/Tasa_de_mortandad", 60, kind="number", widget="input", repeat=UP),
    Action("set", UP + "/disp_agua", ["Temporal de lluvia", "Manantial"], kind="select_multiple", widget="select", repeat=UP),
    Action("repeat", UP + "/group_dl45e64/Frutales_saf", 2),
    Action("set", UP + "/group_dl45e64/Frutales_saf/Nombre_cient_fico_004", "NARANJA DULCE (CITRUS SINENSIS)",
           kind="select_one", widget="select", repeat=UP + "/group_dl45e64/Frutales_saf", index=1),
    Action("set", UP + "/group_dl45e64/Frutales_saf/N_mero_de_individuos_por_especie_002", 82,
           kind="number", widget="input", repeat=UP + "/group_dl45e64/Frutales_saf", index=1),
    Action("matrix", UP, ["B"], kind="select_multiple", widget="checkbox", repeat=UP,
           extra={"row_path": UP + "/group_bw7gj87/group_ln6jc59_fila_5/group_ln6jc59_fila_5_columna"}),
    Action("set", UP + "/Labranza", "Labranza cero", kind="select_one", widget="select", repeat=UP),
    Action("set", R + "/Hora_de_t_rmino_de_la_entrevista", "11:00", kind="time", widget="input"),
]

import json  # noqa: E402
from autoform.paths import OUTPUT  # noqa: E402
_sc = {f["path"]: f for f in json.load(open(OUTPUT / "form_schema.json", encoding="utf-8"))["fields"]}
for _a in plan:
    _f = _sc.get(_a.extra.get("row_path", _a.path))
    if _f and _a.op != "repeat":
        _a.kind, _a.widget = _f["kind"], _f["widget"]

with Filler(headless="--show" not in sys.argv, profile=DATA / "probe_profile") as f:
    f.open_form()
    for a in plan:
        r = f.apply(a)
        print(f"{r.status:9} {a.path.replace(R, '')[:70]:70} {r.detail[:150]} {r.read_back}")
    print("nombre tecnico:", f.page.evaluate(f"() => document.querySelector('[name=\"{R}/datos_curp/nombre_beneficiario\"]').value"))
    print("obligatorios vacios:", [x["label"] for x in f.required_empty()])
    print("VISUAL:", f.page.evaluate("""() => {
      const v = n => { const e = document.querySelector(`[name$="${n}"]`); const q = e.closest('.question');
        const bs = q.querySelector('.bootstrap-select .selected'); const ac = q.querySelector('input.autocomplete');
        const dw = q.querySelector('.widget input'); return n + '=' + (bs ? bs.textContent : ac ? ac.value : dw ? dw.value : e.value); };
      return ['territorios','/ruta','disp_agua','_La_UP_tiene_problemas_del_suelo','Fecha_de_la_entrevista','Hora_de_inicio_de_la_entrevista'].map(v).join(' | ');
    }"""))
    sp = f.page.locator('section.or-repeat[name$="Frutales_saf"]').nth(1).locator('input.autocomplete').first
    print("ESPECIE visible:", sp.input_value())
    sp.scroll_into_view_if_needed(); f.screenshot("live_test_especie")
    # inspeccionar el dialogo de borrador SIN guardar
    f.page.locator("#save-draft").click()
    f.page.wait_for_timeout(1500)
    print("DIALOGO:", f.page.evaluate("() => (document.querySelector('.vex, .modal, dialog') || {}).outerHTML?.slice(0, 2500)"))
    print("bloqueadas:", guard.blocked_requests)
