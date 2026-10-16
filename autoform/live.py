"""Modo EN VIVO: la app mantiene abierta una ventana del navegador con el
formulario y pinta cada dato en cuanto se captura. Tambien detecta lo que la
persona cambia a mano en el navegador y lo regresa a la app.

Nunca envia (guard.py sigue activo). Guardar borrador es una accion explicita.

Piezas:
- `diff_plan`: compara el plan nuevo contra lo ya pintado y devuelve solo lo que cambio.
- `same_value`: compara un valor del plan con lo que se lee del formulario.
- `LiveSession` (QThread): duena de Playwright; recibe comandos por una cola.
"""
from __future__ import annotations

import queue
import traceback

from PySide6.QtCore import QThread, Signal

from .filler import Action, Filler
from .paths import PROFILE
from .textnorm import norm_loose

Key = tuple[str, int]          # (ruta del campo o repeat, instancia)


def key_of(a: Action) -> Key:
    return (a.path, a.index)


def _as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return [str(v)]


def same_value(value, labels: list[str], kind: str = "") -> bool:
    """¿El valor del plan equivale a lo que muestra el formulario?"""
    want = _as_list(value)
    got = [str(x) for x in (labels or [])]
    if not want and not got:
        return True
    if len(want) != len(got):
        return False
    if kind == "number":
        try:
            return all(float(a) == float(b) for a, b in zip(sorted(want), sorted(got)))
        except ValueError:
            pass
    if kind == "time":
        return want[0][:5] == got[0][:5]
    if kind == "geopoint":
        return want[0].split()[:2] == got[0].split()[:2]
    nw = sorted(norm_loose(x) for x in want)
    ng = sorted(norm_loose(x) for x in got)
    if nw == ng:
        return True
    # etiquetas largas: basta el prefijo (igual que el llenador)
    return all(any(g.startswith(w) and len(w) >= 6 for g in ng) for w in nw)


def diff_plan(actions: list[Action], painted: dict[Key, object], paint_template: bool = True) -> list[Action]:
    """Acciones nuevas o modificadas respecto a lo pintado (en orden del formulario).
    Un valor que paso a vacio se manda como borrado (op 'clear')."""
    out: list[Action] = []
    seen: set[Key] = set()
    for a in actions:
        k = key_of(a)
        seen.add(k)
        if not paint_template and a.source == "plantilla" and k not in painted:
            continue
        if a.op == "repeat":
            if painted.get(k) != a.value:
                out.append(a)
            continue
        if a.op == "matrix" and not a.extra.get("row_path"):
            continue
        if a.pending:
            if painted.get(k) not in (None, "", []):
                out.append(Action("clear", a.path, None, label=a.label, source=a.source, repeat=a.repeat,
                                  index=a.index, kind=a.kind, widget=a.widget, extra=a.extra))
            continue
        if k not in painted or not same_value(a.value, _as_list(painted[k]), a.kind):
            out.append(a)
    # campos de instancias que ya no existen en el plan: nada que hacer (se quitan con el repeat)
    return out


class LiveSession(QThread):
    status = Signal(str, bool)                       # texto, conectado
    log = Signal(str)
    field_done = Signal(str, int, str, str, object)  # ruta, instancia, estado, detalle, valor leido
    browser_change = Signal(str, int, object)        # ruta, instancia, etiquetas nuevas
    ask_autosave = Signal(str)
    draft_saved = Signal(str)
    form_ready = Signal()

    POLL_S = 0.8
    HEADLESS = False          # solo para pruebas automaticas
    PROFILE_DIR = PROFILE

    def __init__(self, window_args: list[str] | None = None):
        super().__init__()
        self.q: queue.Queue = queue.Queue()
        self.window_args = window_args if window_args is not None else ["--window-position=640,0",
                                                                         "--window-size=1280,1020"]
        self._answer = None
        self._event = __import__("threading").Event()
        self.expected: dict[Key, tuple[Action, list[str]]] = {}   # lo que la app pinto y deberia verse
        self.running = False

    # ---------------------------------------------------- API (hilo de la GUI)
    def send(self, cmd: str, payload=None):
        self.q.put((cmd, payload))

    def answer(self, value):
        self._answer = value
        self._event.set()

    def _ask(self, text: str) -> str:
        self._event.clear()
        self.ask_autosave.emit(text)
        self._event.wait()
        return self._answer

    # ---------------------------------------------------- hilo del navegador
    def run(self):
        self.running = True
        f = Filler(headless=self.HEADLESS, profile=self.PROFILE_DIR, on_autosave="preguntar", ask_autosave=self._ask,
                   logger=self.log.emit, window_args=self.window_args, settle_ms=250)
        try:
            self.status.emit("Abriendo navegador…", False)
            f.start()
            self._open(f)
            while self.running:
                try:
                    cmd, payload = self.q.get(timeout=self.POLL_S)
                except queue.Empty:
                    if f.page is None or f.page.is_closed():
                        break
                    self._poll(f)
                    continue
                if cmd == "stop":
                    break
                try:
                    self._handle(f, cmd, payload)
                except Exception as e:  # noqa: BLE001
                    if f.page is None or f.page.is_closed():
                        break
                    self.log.emit(f"Error en '{cmd}': {type(e).__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            self.log.emit(f"Error del navegador: {type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}")
        finally:
            try:
                f.stop()
            except Exception:  # noqa: BLE001
                pass
            self.running = False
            self.status.emit("Navegador cerrado", False)

    def _open(self, f: Filler):
        self.status.emit("Cargando formulario…", False)
        f.open_form()
        self.expected.clear()
        self.status.emit("Conectado al formulario (en vivo)", True)
        self.form_ready.emit()

    def _handle(self, f: Filler, cmd: str, payload):
        if cmd == "apply":
            for a in payload:
                self._apply_one(f, a)
        elif cmd == "new_form":
            f.on_autosave = payload or "descartar"
            self._open(f)
            f.on_autosave = "preguntar"
        elif cmd == "save_draft":
            name = f.save_draft(payload)
            self.draft_saved.emit(name)
            # lo auto-guardado en este momento es el mismo formulario recien guardado como borrador
            f.on_autosave = "descartar"
            self._open(f)
            f.on_autosave = "preguntar"
        elif cmd == "js":            # usado por las pruebas automaticas
            f.page.evaluate(payload)
        elif cmd == "required":
            empty = f.required_empty()
            self.log.emit("Obligatorios vacíos: " + (", ".join(x["label"] for x in empty) if empty else "ninguno"))

    def _apply_one(self, f: Filler, a: Action):
        k = key_of(a)
        if a.op == "repeat":
            inst = f.page.locator(f'section.or-repeat[name="{a.path}"]')
            want = int(a.value or 1)
            if inst.count() > want:
                n = f.remove_repeat_instances(a.path, want)
                # las instancias quitadas ya no se vigilan
                for kk in [kk for kk in self.expected if self.expected[kk][0].repeat == a.path and kk[1] >= want]:
                    self.expected.pop(kk, None)
                self.field_done.emit(a.path, a.index, "ok", f"{n} instancias quitadas", a.value)
                return
            r = f.ensure_repeat(a)
            self.field_done.emit(a.path, a.index, r.status, r.detail, a.value)
            return
        if a.op == "clear":
            r = f.clear(a)
            if r.status == "ok":
                self.expected[k] = (a, [])
            self.field_done.emit(a.path, a.index, r.status, r.detail, [])
            return
        r = f.apply(a)
        if r.status == "ok":
            labels = f.read(a).get("labels") or []
            self.expected[k] = (a, labels)
        self.field_done.emit(a.path, a.index, r.status, r.detail, r.read_back)

    def _poll(self, f: Filler):
        """Detecta cambios hechos a mano en el navegador."""
        if not self.expected:
            return
        items = list(self.expected.items())
        keys = [[a.path, a.repeat or "", a.index] for _, (a, _) in items]
        try:
            states = f.page.evaluate("(k) => __af.readMany(k)", keys)
        except Exception:  # noqa: BLE001
            return
        for (k, (a, labels)), st in zip(items, states):
            if not st.get("found") or st.get("disabled"):
                continue
            now = st.get("labels") or []
            if a.kind == "number" or a.widget == "geopoint":
                now = st.get("values") or []
            if not same_value(labels, now, a.kind):
                self.expected[k] = (a, now)
                self.browser_change.emit(a.path, a.index, now)
