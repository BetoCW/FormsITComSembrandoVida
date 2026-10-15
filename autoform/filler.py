"""Llenado del formulario Enketo con Playwright.

Recibe un *plan* (lista de acciones generadas por plan.py) y lo aplica en
orden sobre el formulario abierto en un perfil persistente propio. Verifica
cada campo leyendo de vuelta el valor del modelo. Nunca presiona Enviar
(ver guard.py): al final solo guarda el borrador con el nombre "CURP - Nombre".
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from playwright.sync_api import BrowserContext, Page, sync_playwright, TimeoutError as PWTimeout

from . import guard
from .paths import PROFILE, OUTPUT
from .textnorm import norm_loose

log = logging.getLogger("autoform.filler")

FORM_URL = "https://ee.sembrandodatos.com/x/7kMmQETh"

# Muestra todas las paginas a la vez para poder interactuar con cualquier campo.
SHOW_ALL_PAGES_CSS = """
.or [role="page"], .or .or-group[role="page"], .or .or-repeat[role="page"] { display: block !important; }
.form-footer .next-page, .form-footer .previous-page, .form-footer .first-page, .form-footer .last-page { display: none !important; }
"""

JS_HELPERS = r"""
window.__af = {
  norm(s) {
    return (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/×/g, 'X')
      .toUpperCase().replace(/[^A-Z0-9% ]+/g, '').replace(/\s+/g, ' ').trim();
  },
  scope(repeatPath, idx) {
    if (!repeatPath) return document.querySelector('form.or');
    const inst = document.querySelectorAll(`section.or-repeat[name="${repeatPath}"]`);
    return inst[idx] || null;
  },
  inputs(path, repeatPath, idx) {
    const sc = this.scope(repeatPath, idx);
    if (!sc) return [];
    return [...sc.querySelectorAll(`[name="${path}"], [data-name="${path}"]`)]
      .filter(e => e.type !== 'hidden' || e.dataset.calculate === undefined);
  },
  question(el) { return el.closest('.question') || el.parentElement; },
  isDisabled(el) { return !!el.closest('.disabled') || el.disabled; },
  read(path, repeatPath, idx) {
    const els = this.inputs(path, repeatPath, idx);
    if (!els.length) return {found: false};
    const el = els[0];
    const q = this.question(el);
    const res = {found: true, disabled: this.isDisabled(el), tag: el.tagName, type: el.type};
    if (el.tagName === 'SELECT') {
      const sel = [...el.selectedOptions].filter(o => o.value);
      res.values = sel.map(o => o.value); res.labels = sel.map(o => o.textContent.trim());
    } else if (el.type === 'radio' || el.type === 'checkbox') {
      const sel = els.filter(e => e.checked);
      res.values = sel.map(e => e.value);
      res.labels = sel.map(e => (e.parentElement.querySelector('.option-label') || {}).textContent || '').map(s => s.trim());
    } else {
      res.values = el.value ? [el.value] : []; res.labels = res.values;
      if (el.list) {   // autocomplete: etiqueta visible
        const w = q.querySelector('input.autocomplete'); res.labels = w && w.value ? [w.value] : res.values;
      }
    }
    return res;
  },
  setPlain(path, repeatPath, idx, value) {
    const el = this.inputs(path, repeatPath, idx)[0];
    if (!el) return false;
    el.value = value;
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
  },
  match(w, g) {
    const a = this.norm(w), b = this.norm(g);
    return a === b || (a.length >= 6 && b.startsWith(a));
  },
  bsSet(path, repeatPath, idx, wanted, multi) {
    const el = this.inputs(path, repeatPath, idx)[0];
    if (!el) return {error: 'no encontrado'};
    const bs = this.question(el).querySelector('.bootstrap-select');
    if (!bs) {   // <select> nativo visible
      const found = [];
      for (const o of el.options) {
        if (!o.value) { o.selected = false; continue; }
        const w = wanted.find(x => this.match(x, o.textContent));
        if (w !== undefined) found.push(w);
        if (w !== undefined) { o.selected = true; if (!multi) { break; } }
        else if (multi) o.selected = false;
      }
      el.dispatchEvent(new Event('change', {bubbles: true}));
      return {found, native: true};
    }
    const found = [];
    for (const li of bs.querySelectorAll('.dropdown-menu li')) {
      const lab = li.querySelector('.option-label'); const inp = li.querySelector('input');
      if (!lab || !inp) continue;
      const w = wanted.find(x => this.match(x, lab.textContent));
      if (w !== undefined) found.push(w);
      const want = w !== undefined;
      if (want !== inp.checked && (want || multi)) {
        (li.querySelector('a') || li).click();
        if (want && !multi) break;
      }
    }
    bs.classList.remove('open');
    return {found};
  },
  requiredEmpty() {
    const out = [];
    document.querySelectorAll('form.or [data-required]').forEach(el => {
      if (el.closest('.disabled') || el.closest('.or-repeat-info')) return;
      const expr = (el.dataset.required || '').trim();
      if (!expr || expr === 'false()') return;
      const q = this.question(el);
      const name = el.getAttribute('name') || el.dataset.name;
      let filled;
      if (el.type === 'radio' || el.type === 'checkbox') {
        filled = [...q.querySelectorAll(`[data-name="${name}"],[name="${name}"]`)].some(e => e.checked);
      } else if (el.tagName === 'SELECT') {
        filled = [...el.selectedOptions].some(o => o.value);
      } else filled = !!el.value;
      if (!filled) {
        const lab = (q.querySelector('.question-label') || {}).textContent || '';
        const key = name + '|' + lab;
        if (!out.some(o => o.key === key)) out.push({key, path: name, label: lab.trim()});
      }
    });
    return out;
  }
};
"""


@dataclass
class Action:
    """Una instruccion del plan."""
    op: str                       # set | repeat | matrix
    path: str = ""                # ruta completa del campo (o del repeat)
    value: object = None          # texto visible, lista de textos, numero...
    label: str = ""               # etiqueta legible
    source: str = ""              # plantilla | dia | padron | inventario | calculado
    repeat: str = ""              # ruta del repeat que contiene el campo
    index: int = 0                # instancia del repeat
    kind: str = ""                # tipo del schema
    widget: str = ""
    pending: bool = False         # obligatorio sin dato
    note: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class FieldResult:
    action: Action
    status: str                   # ok | fallo | no_aplica | pendiente | omitido
    detail: str = ""
    read_back: list = field(default_factory=list)


@dataclass
class FillResult:
    key: str
    status: str = "pendiente"
    fields: list[FieldResult] = field(default_factory=list)
    required_empty: list[dict] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    draft_name: str = ""
    error: str = ""
    blocked_requests: list[str] = field(default_factory=list)


class Filler:
    def __init__(self, headless: bool = False, profile: Path = PROFILE, url: str = FORM_URL,
                 slow_ms: int = 0, settle_ms: int = 400, logger: Callable[[str], None] | None = None,
                 on_autosave: str = "descartar", ask_autosave: Callable[[str], str] | None = None):
        self.headless, self.profile, self.url = headless, profile, url
        self.on_autosave = on_autosave          # descartar | cargar | preguntar
        self.ask_autosave = ask_autosave        # callback(texto) -> "descartar" | "cargar" | "detener"
        self.autosave_events: list[str] = []
        self.slow_ms, self.settle_ms = slow_ms, settle_ms
        self.say = logger or (lambda m: log.info(m))
        self._pw = None
        self.ctx: BrowserContext | None = None
        self.page: Page | None = None

    # ------------------------------------------------------------ navegador
    def start(self):
        self.profile.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self.ctx = self._pw.chromium.launch_persistent_context(
            str(self.profile), headless=self.headless, slow_mo=self.slow_ms,
            viewport={"width": 1366, "height": 860}, locale="es-MX")
        guard.install(self.ctx)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self

    def stop(self):
        try:
            if self.ctx:
                self.ctx.close()
        finally:
            if self._pw:
                self._pw.stop()
            self.ctx = self._pw = self.page = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *a):
        self.stop()

    def open_form(self):
        p = self.page
        p.goto(self.url, wait_until="domcontentloaded", timeout=120_000)
        p.wait_for_selector("form.or", state="attached", timeout=120_000)
        # Enketo puede preguntar por un registro auto-guardado sin terminar
        deadline = time.time() + 90
        while time.time() < deadline:
            if p.locator("form.or").is_visible() and not p.locator(".vex").count():
                break
            dlg = p.locator(".vex .vex-dialog-buttons")
            if dlg.count() and dlg.is_visible():
                text = p.locator(".vex").inner_text()
                if "sin guardar" in text.lower() or "sin grabar" in text.lower() or "unsaved" in text.lower():
                    policy = self.on_autosave
                    if policy == "preguntar":
                        policy = self.ask_autosave(text) if self.ask_autosave else "detener"
                    if policy == "detener":
                        raise RuntimeError("Enketo tiene un registro auto-guardado sin terminar; "
                                           "revisalo en el navegador antes de continuar.")
                    choice = "Descartar" if policy == "descartar" else "Cargar"
                    self.autosave_events.append(f"registro auto-guardado encontrado -> {choice}")
                    self.say(f"Enketo encontro un registro auto-guardado; se elige '{choice}'.")
                    p.locator(".vex-dialog-buttons button", has_text=re.compile(choice, re.I)).first.click()
                else:
                    raise RuntimeError(f"Dialogo inesperado al abrir el formulario: {text[:200]}")
            p.wait_for_timeout(500)
        p.wait_for_selector("form.or", state="visible", timeout=30_000)
        p.wait_for_function("document.querySelectorAll('.bootstrap-select').length > 10", timeout=60_000)
        p.add_style_tag(content=SHOW_ALL_PAGES_CSS)
        p.evaluate(JS_HELPERS)
        p.wait_for_timeout(800)

    # ------------------------------------------------------------ utilidades
    def _q(self, a: Action):
        """Locator de la pregunta (.question) del campo dentro de su instancia."""
        scope = self.page.locator(f'section.or-repeat[name="{a.repeat}"]').nth(a.index) if a.repeat \
            else self.page.locator("form.or")
        el = scope.locator(f'[name="{a.path}"], [data-name="{a.path}"]').first
        return el.locator("xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' question ')][1]")

    def read(self, a: Action) -> dict:
        return self.page.evaluate("([p, r, i]) => __af.read(p, r, i)", [a.path, a.repeat or "", a.index])

    def settle(self, ms: int | None = None):
        self.page.wait_for_timeout(self.settle_ms if ms is None else ms)

    # ------------------------------------------------------------ setters
    def _labels_match(self, wanted: str, got: str) -> bool:
        w, g = norm_loose(wanted), norm_loose(got)
        return w == g or (w and g.startswith(w) and len(w) >= 6)

    def set_choice(self, a: Action, wanted: list[str], multi: bool):
        """Radios / checkboxes nativos de Enketo (seleccion por texto)."""
        q = self._q(a)
        labels = q.locator(".option-wrapper > label")
        n = labels.count()
        found = set()
        for i in range(n):
            lab = labels.nth(i)
            text = lab.locator(".option-label").first.inner_text().strip()
            inp = lab.locator("input").first
            want = any(self._labels_match(w, text) for w in wanted)
            if want:
                found.add(next(w for w in wanted if self._labels_match(w, text)))
            checked = inp.is_checked()
            if want and not checked:
                lab.click()
            elif multi and checked and not want:
                lab.click()
        missing = [w for w in wanted if w not in found]
        if missing:
            raise ValueError(f"opcion no encontrada: {missing}")

    def set_bootstrap(self, a: Action, wanted: list[str], multi: bool):
        """bootstrap-select: se hace click (via DOM) en la opcion cuyo texto coincide.
        Funciona aunque el menu sea largo o este fuera de pantalla."""
        r = self.page.evaluate("([p, r, i, w, m]) => __af.bsSet(p, r, i, w, m)",
                               [a.path, a.repeat or "", a.index, wanted, multi])
        if r.get("error"):
            raise ValueError(r["error"])
        missing = [w for w in wanted if w not in r.get("found", [])]
        if missing:
            raise ValueError(f"opcion no encontrada: {missing}")

    def set_autocomplete(self, a: Action, text: str):
        q = self._q(a)
        w = q.locator("input.autocomplete").first
        w.fill("")
        w.fill(text)
        w.dispatch_event("change")
        w.press("Tab")

    def set_widget_text(self, a: Action, selector: str, text: str):
        q = self._q(a)
        w = q.locator(selector).first
        w.fill(text)
        w.dispatch_event("change")
        w.press("Tab")

    def set_geopoint(self, a: Action, value):
        lat, lon, alt, acc = (list(value) + [0, 0, 0, 0])[:4] if isinstance(value, (list, tuple)) \
            else (str(value).split() + ["0", "0", "0", "0"])[:4]
        q = self._q(a)
        for name, v in (("lat", lat), ("long", lon), ("alt", alt), ("acc", acc)):
            inp = q.locator(f'.geopicker input[name="{name}"]').first
            if inp.count():
                inp.fill(str(v))
                inp.dispatch_event("change")
        q.locator('.geopicker input[name="acc"]').first.press("Tab")

    def set_text(self, a: Action, text: str):
        q = self._q(a)
        inp = q.locator(f'[name="{a.path}"]').first
        if inp.is_visible():
            inp.fill(text)
            inp.dispatch_event("change")
        else:
            self.page.evaluate("([p, r, i, v]) => __af.setPlain(p, r, i, v)", [a.path, a.repeat or "", a.index, text])

    # ------------------------------------------------------------ acciones
    def apply(self, a: Action) -> FieldResult:
        if a.pending:
            return FieldResult(a, "pendiente", "sin dato (obligatorio o plantilla PENDIENTE)")
        if a.op == "repeat":
            return self.ensure_repeat(a)
        if a.op == "matrix":
            return self.set_matrix(a)
        state = self.read(a)
        if not state.get("found"):
            return FieldResult(a, "fallo", "campo no encontrado en el formulario")
        if state.get("disabled"):
            return FieldResult(a, "no_aplica", "campo no visible por la logica del formulario")
        value = a.value
        values = [str(v) for v in value] if isinstance(value, (list, tuple)) else [str(value)]
        last_err = ""
        for attempt in range(3):
            try:
                self._set(a, values)
                self.settle()
                ok, rb = self._verify(a, values)
                if ok:
                    return FieldResult(a, "ok", "", rb)
                last_err = f"verificacion: se esperaba {values}, el formulario tiene {rb}"
            except PWTimeout as e:
                last_err = f"timeout: {e.message.splitlines()[0] if e.message else e}"
            except Exception as e:  # noqa: BLE001 - se reporta y se continua
                last_err = f"{type(e).__name__}: {e}"
            self.settle(600 * (attempt + 1))
        return FieldResult(a, "fallo", last_err)

    def _set(self, a: Action, values: list[str]):
        w = a.widget
        if w == "radio":
            self.set_choice(a, values[:1], multi=False)
        elif w == "checkbox":
            self.set_choice(a, values, multi=True)
        elif w == "select":
            self.set_bootstrap(a, values, multi=(a.kind == "select_multiple"))
        elif w == "autocomplete":
            self.set_autocomplete(a, values[0])
        elif w == "geopoint":
            self.set_geopoint(a, a.value)
        elif a.kind == "date":
            self.set_widget_text(a, ".widget.date input", values[0])
        elif a.kind == "time":
            self.set_widget_text(a, ".timepicker input, .widget.timepicker input", values[0])
        else:
            self.set_text(a, values[0])

    def _verify(self, a: Action, values: list[str]) -> tuple[bool, list]:
        st = self.read(a)
        got_labels, got_values = st.get("labels") or [], st.get("values") or []
        if a.widget in ("radio", "checkbox", "select"):
            ok = all(any(self._labels_match(v, g) for g in got_labels) for v in values) \
                and len(got_labels) == len(values)
            return ok, got_labels
        if a.widget == "autocomplete":
            return bool(got_values) and any(self._labels_match(values[0], g) for g in got_labels + got_values), \
                got_labels
        if a.widget == "geopoint":
            return bool(got_values) and got_values[0].split()[:2] == str(a.value).split()[:2] \
                if not isinstance(a.value, (list, tuple)) else bool(got_values), got_values
        if a.kind == "number":
            try:
                return bool(got_values) and float(got_values[0]) == float(values[0]), got_values
            except ValueError:
                return False, got_values
        if a.kind == "time":
            return bool(got_values) and got_values[0][:5] == values[0][:5], got_values
        return bool(got_values) and got_values[0].strip() == values[0].strip(), got_values

    def ensure_repeat(self, a: Action) -> FieldResult:
        """Garantiza que existan `a.value` instancias del repeat `a.path`."""
        want = int(a.value or 1)
        inst = self.page.locator(f'section.or-repeat[name="{a.path}"]')
        for _ in range(want + 2):
            if inst.count() >= want:
                return FieldResult(a, "ok", f"{inst.count()} instancias")
            btn = self.page.locator(f'.or-repeat-info[data-name="{a.path}"] .add-repeat-btn')
            if not btn.count():
                btn = inst.last.locator(":scope > .repeat-buttons .add-repeat-btn")
            if not btn.count():
                return FieldResult(a, "fallo", "no se encontro el boton para agregar instancias")
            btn.first.scroll_into_view_if_needed()
            btn.first.click()
            self.settle(700)
        return FieldResult(a, "fallo", f"solo hay {inst.count()} de {want} instancias")

    def set_matrix(self, a: Action) -> FieldResult:
        """a.extra = {"row_path": ruta del campo de la fila}; a.value = columnas (letras) o numero."""
        sub = Action(op="set", path=a.extra["row_path"], value=a.value, repeat=a.repeat, index=a.index,
                     kind=a.kind, widget=a.widget, label=a.label)
        r = self.apply(sub)
        r.action = a
        return r

    # ------------------------------------------------------------ borrador
    def required_empty(self) -> list[dict]:
        return self.page.evaluate("() => __af.requiredEmpty()")

    def save_draft(self, name: str) -> str:
        p = self.page
        guard.check_selector("#save-draft")
        p.locator("#save-draft").click()
        dlg_input = p.locator(".vex-dialog-prompt-input, .vex-dialog-input input[type=text], input[name='record-name']").first
        dlg_input.wait_for(state="visible", timeout=10_000)
        dlg_input.fill(name)
        ok = p.locator(".vex-dialog-button-primary, .vex-dialog-buttons .btn-primary").first
        txt = (ok.inner_text() or "").strip().lower()
        if txt in ("enviar", "submit"):
            raise guard.SubmitForbidden("El dialogo de borrador muestra un boton 'Enviar'")
        ok.click()
        p.wait_for_timeout(1500)
        return name

    def screenshot(self, tag: str) -> str:
        d = OUTPUT / "capturas"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{time.strftime('%Y%m%d_%H%M%S')}_{tag}.png"
        self.page.screenshot(path=str(path), full_page=False)
        return str(path)

    # ------------------------------------------------------------ flujo
    def fill(self, key: str, plan: list[Action], draft_name: str, pause_before_save: Callable[[], bool] | None = None,
             save: bool = True, progress: Callable[[int, int, FieldResult], None] | None = None) -> FillResult:
        res = FillResult(key=key, draft_name=draft_name)
        guard.blocked_requests.clear()
        try:
            self.open_form()
            for i, a in enumerate(plan):
                r = self.apply(a)
                res.fields.append(r)
                if progress:
                    progress(i + 1, len(plan), r)
                if r.status == "fallo":
                    self.say(f"  ✗ {a.label or a.path}: {r.detail}")
            res.required_empty = self.required_empty()
            if any(r.status == "fallo" for r in res.fields):
                res.screenshots.append(self.screenshot(f"{_safe(key)}_fallos"))
            if pause_before_save is not None and not pause_before_save():
                res.status = "llenado_sin_guardar"
                return res
            if save:
                self.save_draft(draft_name)
                res.status = "borrador_guardado"
            else:
                res.status = "llenado_sin_guardar"
        except guard.SubmitForbidden:
            raise
        except Exception as e:  # noqa: BLE001
            res.status = "error"
            res.error = f"{type(e).__name__}: {e}"
            try:
                res.screenshots.append(self.screenshot(f"{_safe(key)}_error"))
            except Exception:  # noqa: BLE001
                pass
        finally:
            res.blocked_requests = list(guard.blocked_requests)
        return res


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:60]


def dump_result(res: FillResult) -> dict:
    return json.loads(json.dumps(res, default=lambda o: o.__dict__, ensure_ascii=False))
