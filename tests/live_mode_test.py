"""Prueba del modo EN VIVO (headless, perfil de prueba). Simula a una persona que
escribe en la app y a otra que cambia un campo a mano en el navegador.
Guarda un borrador LOCAL en el perfil de prueba. Nunca envia.
Uso: python tests/live_mode_test.py"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtWidgets import QApplication  # noqa: E402

from autoform import session  # noqa: E402
from autoform.live import LiveSession  # noqa: E402
from autoform.paths import DATA  # noqa: E402

LiveSession.HEADLESS = True
LiveSession.PROFILE_DIR = DATA / "probe_profile"
session.SESSION = DATA / "sesion_prueba.json"
app = QApplication(sys.argv)
from autoform.gui import MainWindow  # noqa: E402

w = MainWindow()
# en la prueba, el aviso de "registro auto-guardado" se contesta solo
w._live_on_autosave = lambda text: (print("aviso auto-guardado -> descartar"), w.live.answer("descartar"))
w.sembradores.clear()
w.inventario.clear()
w.builder.dia.update(hora_inicio="09:00", hora_termino="10:00", calidad_entrevista="Completa")
w.save_dia_backup = None


def pump(sec, until=None):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.05)
        if until and until():
            return True
    return False


def type_field(attr, text):
    w.live_edits[attr].setText(text)
    w._live_field_edited(attr)


w._live_new_semb()
w._live_open()
w.live.ask_autosave.disconnect()
w.live.ask_autosave.connect(w._live_on_autosave)
assert pump(120, lambda: w._live_connected()), "no conecto"
print("conectado:", w.l_live.text())
pump(3)
type_field("curp", "PEGJ800101HNTRRN01")
type_field("nombre", "Juan")
type_field("apellido_p", "Perez")
type_field("apellido_m", "Garcia")
type_field("cac_id", "CAC-101")
type_field("id_predio", "21.5123,-104.8941")
# esperar a que se pinte todo (plantilla incluida)
pump(150, lambda: w.live.q.empty() and len(w.painted) > 60 and w.t_live_act.rowCount() > 60)
pump(5)
act = [(w.t_live_act.item(r, 1).text(), w.t_live_act.item(r, 3).text()) for r in range(w.t_live_act.rowCount())]
print("acciones pintadas:", len(act), "fallos:", [a for a in act if "fallo" in a[1]])
print("marcas:", {k: m.text() for k, m in w.live_marks.items()})
# cambio a mano en el navegador -> debe regresar a la app
R = w.schema.root
w.live.send("js", f"__af.setPlain('{R}/group_eq6af71/nombre', '', 0, 'JUAN CARLOS')")
pump(10, lambda: w.live_edits["nombre"].text() == "JUAN CARLOS")
print("regreso del navegador ->", w.live_edits["nombre"].text())
# editar en la app un dato ya pintado
type_field("cac_id", "CAC-202")
pump(8, lambda: any("CAC-202" in (w.t_live_act.item(r, 2).text() or "") for r in range(min(5, w.t_live_act.rowCount()))))
print("ultima actividad:", [(w.t_live_act.item(r, 1).text(), w.t_live_act.item(r, 2).text(), w.t_live_act.item(r, 3).text()) for r in range(3)])
# guardar borrador y pasar al siguiente
w._live_save()
pump(60, lambda: w._live_connected() and len(w.sembradores) == 2)
pump(4)
print("tras guardar:", w.cb_live.currentText(), "| sembradores:", [s.draft_name for s in w.sembradores],
      "| estado:", w.estados)
w._live_stop()
os.remove(session.SESSION) if session.SESSION.exists() else None
print("OK")
