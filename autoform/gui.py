"""AutoForm PSV - interfaz de escritorio (PySide6).

Flujo del dia:
  1. Pestana "Hoy": fecha, horas, tecnico y calidad (una vez al dia).
  2. Pestana "Sembradores": cargar padron/inventario o capturar a mano los
     pocos datos que cambian (CURP, nombre, CAC, coordenadas, inventario).
  3. "Vista previa": revisar/editar lo que se llenara.
  4. "Llenado": Prellenar -> el navegador llena y guarda el BORRADOR.
     La app nunca presiona Enviar; eso se hace a mano en "Revisar / enviar".
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import threading
import traceback
from pathlib import Path

import yaml
from PySide6.QtCore import Qt, QThread, Signal, QDate, QTime
from PySide6.QtGui import QColor, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QDateEdit, QTimeEdit, QCheckBox, QSpinBox, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox, QPlainTextEdit, QProgressBar, QSplitter,
    QGroupBox, QListWidget, QListWidgetItem, QAbstractItemView, QStyledItemDelegate,
)

from . import session
from .batch import llenar, validar, Lote
from .excel_inventario import read_inventario, unir, PlantaFila
from .excel_padron import read_padron, Sembrador
from .form_schema import download_form, parse_form, save_schema, required_summary
from .paths import OUTPUT, PROFILE, CONFIG
from .report import write_report
from .schema_index import Schema
from .template import PlanBuilder, load_yaml, save_yaml

APP_TITLE = "AutoForm PSV"
CALIDADES = ["(pendiente)", "Completa", "Incompleta", "Se negó a dar información", "Informante inadecuado"]

SEMB_COLS = [("✓", None), ("CURP", "curp"), ("Nombre(s)", "nombre"), ("Ap. paterno", "apellido_p"),
             ("Ap. materno", "apellido_m"), ("ID CAC", "cac_id"), ("Nombre CAC", "cac_nombre"),
             ("Latitud", "latitud"), ("Longitud", "longitud"), ("ID predio", "id_predio"),
             ("CURP técnica", "curp_tecnica"), ("Plantas", None), ("Estado", None)]
INV_COLS = [("Año", "anio"), ("Nombre común", "comun"), ("Nombre científico", "cientifico"),
            ("Número", "numero"), ("Diámetro (cm)", "diametro_cm"), ("Altura (cm)", "altura_cm")]


def _to_num(text: str):
    t = (text or "").strip().replace(",", ".")
    if not t:
        return None
    if t.startswith("."):
        t = "0" + t
    try:
        v = float(t)
        return int(v) if v.is_integer() else v
    except ValueError:
        return None


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return " ; ".join(map(str, v))
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def open_path(p: Path):
    if sys.platform == "win32":
        os.startfile(str(p))  # noqa: S606
    else:
        import subprocess
        subprocess.Popen(["xdg-open", str(p)])


# =============================================================== hilos
class FillWorker(QThread):
    log = Signal(str)
    progress = Signal(int, int, int, str, str)       # sembrador, i, n, campo, estado
    ask_pause = Signal(str)
    ask_autosave = Signal(str)
    finished_entries = Signal(list)

    def __init__(self, planes, opts: dict):
        super().__init__()
        self.planes, self.opts = planes, opts
        self._answer = None
        self._event = threading.Event()
        self._stop = False

    def answer(self, value):
        self._answer = value
        self._event.set()

    def stop(self):
        self._stop = True
        self.answer(False)

    def _wait(self, signal, payload):
        self._event.clear()
        signal.emit(payload)
        self._event.wait()
        return self._answer

    def run(self):
        entries = []
        try:
            entries = llenar(
                self.planes, headless=not self.opts["visible"], guardar=self.opts["guardar"],
                pausa=(lambda p: self._wait(self.ask_pause, p.sembrador.draft_name)) if self.opts["pausa"] else None,
                log=self.log.emit,
                progreso=lambda k, i, n, r: self.progress.emit(k, i, n, r.action.label, r.status),
                detener=lambda: self._stop, on_autosave=self.opts["autosave"],
                ask_autosave=lambda text: self._wait(self.ask_autosave, text))
        except Exception as e:  # noqa: BLE001
            self.log.emit(f"ERROR: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        self.finished_entries.emit(entries)


class ReviewWorker(QThread):
    """Abre el navegador del perfil de la app para revisar o ENVIAR a mano."""
    log = Signal(str)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=False, no_viewport=True,
                                                           locale="es-MX", args=["--start-maximized"])
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(self.url)
                self.log.emit("Navegador de revision abierto. Los borradores estan en el icono de la cola "
                              "(arriba a la izquierda). Cierralo para volver a prellenar.")
                while ctx.pages:
                    try:
                        ctx.pages[0].wait_for_timeout(1000)
                    except Exception:  # noqa: BLE001
                        break
                ctx.close()
        except Exception as e:  # noqa: BLE001
            self.log.emit(f"No se pudo abrir el navegador: {e}")
        self.log.emit("Navegador de revision cerrado.")


class SimpleWorker(QThread):
    done = Signal(object, str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(), "")
        except Exception as e:  # noqa: BLE001
            self.done.emit(None, f"{type(e).__name__}: {e}")


# =============================================================== delegado
class OptionsDelegate(QStyledItemDelegate):
    """Combo editable con las opciones del campo (columna Valor de la plantilla)."""

    def __init__(self, options_for_row, parent=None):
        super().__init__(parent)
        self.options_for_row = options_for_row

    def createEditor(self, parent, option, index):
        opts = self.options_for_row(index.row())
        if not opts:
            return super().createEditor(parent, option, index)
        cb = QComboBox(parent)
        cb.setEditable(True)
        cb.addItems([""] + opts)
        return cb

    def setEditorData(self, editor, index):
        if isinstance(editor, QComboBox):
            editor.setCurrentText(index.data() or "")
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText())
        else:
            super().setModelData(editor, model, index)


# =============================================================== ventana
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1320, 820)
        self.schema = Schema()
        self.builder = PlanBuilder(self.schema)
        st = session.load()
        self.sembradores: list[Sembrador] = st["sembradores"]
        self.inventario: dict[str, list[PlantaFila]] = st["inventario"]
        self.overrides: dict[str, dict] = st["overrides"]
        self.seleccion: set[str] = set(st["seleccion"])
        self.archivos: dict = st["archivos"]
        self.estados: dict[str, str] = {}
        self.validacion: list[str] = list(st.get("validacion", []))
        self.last_entries: list[dict] = []
        self.last_report: Path | None = None
        self.worker: FillWorker | None = None
        self.review: ReviewWorker | None = None
        self._loading = False

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.addTab(self._tab_hoy(), "1. Hoy")
        self.tabs.addTab(self._tab_sembradores(), "2. Sembradores")
        self.tabs.addTab(self._tab_preview(), "3. Vista previa")
        self.tabs.addTab(self._tab_llenado(), "4. Llenado")
        self.tabs.addTab(self._tab_plantilla(), "Plantilla fija")
        self.tabs.addTab(self._tab_validacion(), "Validación")
        self.tabs.currentChanged.connect(self._on_tab)
        self._refresh_sembradores()
        self.statusBar().showMessage("La app solo guarda BORRADORES. El envío siempre es manual.")

    # ----------------------------------------------------------- pestaña Hoy
    def _tab_hoy(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        g = QGroupBox("Datos del día (se capturan una vez y aplican a todos los formularios de hoy)")
        f = QFormLayout(g)
        dia = self.builder.dia
        self.e_fecha = QDateEdit(calendarPopup=True)
        self.e_fecha.setDisplayFormat("yyyy-MM-dd")
        saved = (dia.get("fecha") or "").strip()
        self.e_fecha.setDate(QDate.fromString(saved, "yyyy-MM-dd") if saved == dt.date.today().isoformat()
                             else QDate.currentDate())
        self.e_ini = QTimeEdit(displayFormat="HH:mm")
        self.e_fin = QTimeEdit(displayFormat="HH:mm")
        self.c_ini = QCheckBox("capturar")
        self.c_fin = QCheckBox("capturar")
        for edit, chk, key in ((self.e_ini, self.c_ini, "hora_inicio"), (self.e_fin, self.c_fin, "hora_termino")):
            v = (dia.get(key) or "").strip()
            chk.setChecked(bool(v))
            edit.setTime(QTime.fromString(v, "HH:mm") if v else QTime(9, 0))
        self.c_auto = QCheckBox("Horas automáticas: cada sembrador empieza al terminar el anterior")
        auto = dia.get("auto_horas") or {}
        self.c_auto.setChecked(bool(auto.get("activo")))
        self.s_dur = QSpinBox(suffix=" min", maximum=600, value=int(auto.get("duracion_min", 60)))
        self.s_desc = QSpinBox(suffix=" min", maximum=600, value=int(auto.get("descanso_min", 0)))
        self.e_curp_tec = QLineEdit(dia.get("curp_tecnico") or "")
        self.e_curp_tec.setPlaceholderText("se usa si el padrón no trae la CURP de la técnica")
        self.cb_calidad = QComboBox()
        self.cb_calidad.addItems(CALIDADES)
        self.cb_calidad.setCurrentText(dia.get("calidad_entrevista") or "(pendiente)")
        hi = QHBoxLayout(); hi.addWidget(self.e_ini); hi.addWidget(self.c_ini); hi.addStretch()
        hf = QHBoxLayout(); hf.addWidget(self.e_fin); hf.addWidget(self.c_fin); hf.addStretch()
        ha = QHBoxLayout(); ha.addWidget(QLabel("duración")); ha.addWidget(self.s_dur)
        ha.addWidget(QLabel("descanso")); ha.addWidget(self.s_desc); ha.addStretch()
        f.addRow("Fecha de la entrevista", self.e_fecha)
        f.addRow("Hora de inicio", hi)
        f.addRow("Hora de término", hf)
        f.addRow(self.c_auto)
        f.addRow("", ha)
        f.addRow("CURP del técnico", self.e_curp_tec)
        f.addRow("Calidad de la entrevista", self.cb_calidad)
        b = QPushButton("Guardar datos del día")
        b.clicked.connect(self._save_dia)
        f.addRow(b)
        lay.addWidget(g)

        g2 = QGroupBox("Formulario")
        v2 = QVBoxLayout(g2)
        n_req = sum(1 for x in self.schema.fields if x["required"])
        self.l_form = QLabel(f"{self.schema.raw.get('title') or 'Información de Unidades Productivas y Especies PSV'}\n"
                             f"{len(self.schema.fields)} campos · {n_req} obligatorios · "
                             f"{len(self.schema.repeats)} repeats · {len(self.schema.matrices)} matrices")
        v2.addWidget(self.l_form)
        h = QHBoxLayout()
        b1 = QPushButton("Ver campos obligatorios")
        b1.clicked.connect(self._show_required)
        b2 = QPushButton("Actualizar formulario (descargar definición)")
        b2.clicked.connect(self._refresh_form)
        b3 = QPushButton("Abrir carpeta de resultados")
        b3.clicked.connect(lambda: (OUTPUT.mkdir(exist_ok=True), open_path(OUTPUT)))
        for x in (b1, b2, b3):
            h.addWidget(x)
        h.addStretch()
        v2.addLayout(h)
        lay.addWidget(g2)
        lay.addStretch()
        return w

    def _save_dia(self):
        d = self.builder.dia
        d["fecha"] = self.e_fecha.date().toString("yyyy-MM-dd")
        d["hora_inicio"] = self.e_ini.time().toString("HH:mm") if self.c_ini.isChecked() else ""
        d["hora_termino"] = self.e_fin.time().toString("HH:mm") if self.c_fin.isChecked() else ""
        d["auto_horas"] = {"activo": self.c_auto.isChecked(), "duracion_min": self.s_dur.value(),
                           "descanso_min": self.s_desc.value()}
        d["curp_tecnico"] = self.e_curp_tec.text().strip().upper()
        cal = self.cb_calidad.currentText()
        d["calidad_entrevista"] = None if cal.startswith("(") else cal
        save_yaml("dia.yaml", d, "# DATOS DEL DIA - editados desde la app (pestana Hoy)\n")
        self.statusBar().showMessage("Datos del día guardados.", 4000)

    def _show_required(self):
        dlg = QPlainTextEdit()
        dlg.setReadOnly(True)
        dlg.setPlainText(required_summary(self.schema.raw))
        dlg.setWindowTitle("Campos obligatorios del formulario")
        dlg.resize(900, 700)
        dlg.show()
        self._req_dlg = dlg

    def _refresh_form(self):
        self.statusBar().showMessage("Descargando definición del formulario…")

        def job():
            download_form()
            s = parse_form()
            save_schema(s)
            return s
        self._sw = SimpleWorker(job)
        self._sw.done.connect(self._on_form_refreshed)
        self._sw.start()

    def _on_form_refreshed(self, s, err):
        if err:
            QMessageBox.warning(self, APP_TITLE, f"No se pudo actualizar: {err}")
            return
        self.schema = Schema(s)
        self.builder = PlanBuilder(self.schema)
        n_req = sum(1 for x in s["fields"] if x["required"])
        self.l_form.setText(f"{len(s['fields'])} campos · {n_req} obligatorios · {len(s['repeats'])} repeats · "
                            f"{len(s['matrices'])} matrices (actualizado)")
        self.statusBar().showMessage("Formulario actualizado.", 5000)

    # ----------------------------------------------------- pestaña Sembradores
    def _tab_sembradores(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        h = QHBoxLayout()
        for text, fn in (("Cargar padrón…", self._load_padron), ("Cargar inventario…", self._load_inventario),
                         ("Agregar sembrador", self._add_sembrador), ("Quitar seleccionado", self._del_sembrador),
                         ("Marcar todos", lambda: self._check_all(True)), ("Desmarcar", lambda: self._check_all(False))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            h.addWidget(b)
        h.addStretch()
        self.l_files = QLabel()
        h.addWidget(self.l_files)
        lay.addLayout(h)
        split = QSplitter(Qt.Vertical)
        self.t_semb = QTableWidget(0, len(SEMB_COLS))
        self.t_semb.setHorizontalHeaderLabels([c for c, _ in SEMB_COLS])
        self.t_semb.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.t_semb.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t_semb.setSelectionMode(QAbstractItemView.SingleSelection)
        self.t_semb.itemChanged.connect(self._on_semb_edit)
        self.t_semb.itemSelectionChanged.connect(self._refresh_inv)
        split.addWidget(self.t_semb)
        box = QWidget()
        bl = QVBoxLayout(box)
        hh = QHBoxLayout()
        self.l_inv = QLabel("Inventario del sembrador seleccionado")
        hh.addWidget(self.l_inv)
        hh.addStretch()
        for text, fn in (("Agregar planta", self._add_inv), ("Quitar planta", self._del_inv)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            hh.addWidget(b)
        bl.addLayout(hh)
        self.t_inv = QTableWidget(0, len(INV_COLS))
        self.t_inv.setHorizontalHeaderLabels([c for c, _ in INV_COLS])
        self.t_inv.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.t_inv.itemChanged.connect(self._on_inv_edit)
        bl.addWidget(self.t_inv)
        split.addWidget(box)
        split.setSizes([450, 300])
        lay.addWidget(split)
        return w

    def _files_label(self):
        p, i = self.archivos.get("padron"), self.archivos.get("inventario")
        self.l_files.setText(f"Padrón: {Path(p).name if p else '—'}   Inventario: {Path(i).name if i else '—'}")

    def _load_padron(self):
        path, _ = QFileDialog.getOpenFileName(self, "Padrón", self.archivos.get("dir", ""), "Excel/CSV (*.xlsx *.xls *.csv)")
        if not path:
            return
        try:
            nuevos, issues = read_padron(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP_TITLE, f"No se pudo leer el padrón:\n{e}")
            return
        if self.sembradores and QMessageBox.question(
                self, APP_TITLE, "¿Reemplazar la lista actual de sembradores?") != QMessageBox.Yes:
            return
        self.sembradores, self.overrides, self.estados = nuevos, {}, {}
        self.seleccion = {s.uid for s in nuevos}
        self.archivos.update(padron=path, dir=str(Path(path).parent))
        self.validacion = issues
        if self.archivos.get("inventario"):
            self._read_inv(self.archivos["inventario"], quiet=True)
        else:
            self.inventario = {s.uid: [] for s in nuevos}
        self._after_data_change()

    def _load_inventario(self):
        path, _ = QFileDialog.getOpenFileName(self, "Inventario", self.archivos.get("dir", ""), "Excel/CSV (*.xlsx *.xls *.csv)")
        if path:
            self._read_inv(path)
            self._after_data_change()

    def _read_inv(self, path, quiet=False):
        try:
            filas, issues = read_inventario(path)
        except Exception as e:  # noqa: BLE001
            if not quiet:
                QMessageBox.warning(self, APP_TITLE, f"No se pudo leer el inventario:\n{e}")
            return
        self.inventario, iss2 = unir(self.sembradores, filas)
        self.archivos.update(inventario=path, dir=str(Path(path).parent))
        self.validacion = [v for v in self.validacion if not v.startswith("Inventario")] + issues + iss2

    def _add_sembrador(self):
        s = Sembrador()
        self.sembradores.append(s)
        self.inventario[s.uid] = []
        self.seleccion.add(s.uid)
        self._after_data_change()
        self.t_semb.selectRow(len(self.sembradores) - 1)
        self.t_semb.editItem(self.t_semb.item(len(self.sembradores) - 1, 1))

    def _del_sembrador(self):
        r = self.t_semb.currentRow()
        if r < 0:
            return
        s = self.sembradores[r]
        if QMessageBox.question(self, APP_TITLE, f"¿Quitar a {s.nombre_completo or s.curp}?") != QMessageBox.Yes:
            return
        self.sembradores.pop(r)
        self.inventario.pop(s.uid, None)
        self.seleccion.discard(s.uid)
        self._after_data_change()

    def _check_all(self, on: bool):
        self.seleccion = {s.uid for s in self.sembradores} if on else set()
        self._after_data_change()

    def _after_data_change(self):
        self._files_label()
        self._refresh_sembradores()
        self._save_session()

    def _save_session(self):
        session.save(self.sembradores, self.inventario, self.overrides, sorted(self.seleccion), self.archivos)

    def _refresh_sembradores(self):
        self._loading = True
        t = self.t_semb
        t.setRowCount(len(self.sembradores))
        for r, s in enumerate(self.sembradores):
            for c, (_, attr) in enumerate(SEMB_COLS):
                if c == 0:
                    it = QTableWidgetItem()
                    it.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    it.setCheckState(Qt.Checked if s.uid in self.seleccion else Qt.Unchecked)
                elif attr:
                    it = QTableWidgetItem(_fmt(getattr(s, attr)))
                elif SEMB_COLS[c][0] == "Plantas":
                    n = sum(f.numero or 0 for f in self.inventario.get(s.uid, []))
                    it = QTableWidgetItem(_fmt(n))
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                else:
                    it = QTableWidgetItem(self.estados.get(s.uid, ""))
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    est = self.estados.get(s.uid, "")
                    if est.startswith("borrador"):
                        it.setBackground(QColor("#d8f5d0"))
                    elif est.startswith(("error", "fallos")):
                        it.setBackground(QColor("#f8d0d0"))
                if s.avisos and c == 1:
                    it.setToolTip("\n".join(s.avisos))
                    it.setForeground(QColor("#b06000"))
                t.setItem(r, c, it)
        self._loading = False
        self._files_label()
        self._refresh_inv()

    def _on_semb_edit(self, it: QTableWidgetItem):
        if self._loading:
            return
        s = self.sembradores[it.row()]
        col = it.column()
        if col == 0:
            (self.seleccion.add if it.checkState() == Qt.Checked else self.seleccion.discard)(s.uid)
        else:
            attr = SEMB_COLS[col][1]
            if not attr:
                return
            txt = it.text().strip()
            if attr in ("latitud", "longitud"):
                setattr(s, attr, _to_num(txt))
            elif attr in ("curp", "curp_tecnica", "nombre", "apellido_p", "apellido_m"):
                setattr(s, attr, txt.upper())
            else:
                setattr(s, attr, txt)
            if attr == "id_predio" and "," in txt and (s.latitud is None or s.longitud is None):
                a, b = (_to_num(x) for x in txt.split(",", 1))
                s.latitud, s.longitud = a, b
                self._refresh_sembradores()
        self._save_session()

    def _cur_semb(self) -> Sembrador | None:
        r = self.t_semb.currentRow()
        return self.sembradores[r] if 0 <= r < len(self.sembradores) else None

    def _refresh_inv(self):
        s = self._cur_semb()
        self._loading = True
        rows = self.inventario.get(s.uid, []) if s else []
        self.l_inv.setText(f"Inventario de {s.nombre_completo or s.curp or '(nuevo)'} — {len(rows)} filas"
                           if s else "Selecciona un sembrador para ver/capturar su inventario")
        self.t_inv.setRowCount(len(rows))
        for r, f in enumerate(rows):
            for c, (_, attr) in enumerate(INV_COLS):
                self.t_inv.setItem(r, c, QTableWidgetItem(_fmt(getattr(f, attr))))
        self._loading = False

    def _add_inv(self):
        s = self._cur_semb()
        if not s:
            return
        self.inventario.setdefault(s.uid, []).append(PlantaFila(
            id_sembrador=s.id_sembrador, nombre_sembrador=s.nombre_completo, cac=s.cac_nombre, poligono=s.poligono,
            ha=None, anio=None, comun="", cientifico="", numero=None, diametro_cm=None, altura_cm=None, fila_excel=0))
        self._refresh_inv()
        self.t_inv.editItem(self.t_inv.item(self.t_inv.rowCount() - 1, 1))
        self._save_session()

    def _del_inv(self):
        s = self._cur_semb()
        r = self.t_inv.currentRow()
        if s and r >= 0:
            self.inventario[s.uid].pop(r)
            self._refresh_inv()
            self._refresh_sembradores()
            self._save_session()

    def _on_inv_edit(self, it):
        if self._loading:
            return
        s = self._cur_semb()
        if not s:
            return
        f = self.inventario[s.uid][it.row()]
        attr = INV_COLS[it.column()][1]
        txt = it.text().strip()
        if attr in ("comun", "cientifico"):
            setattr(f, attr, txt.upper())
        elif attr == "anio":
            v = _to_num(txt)
            f.anio = int(v) if v is not None else None
        else:
            setattr(f, attr, _to_num(txt))
        self._save_session()

    # ------------------------------------------------------ pestaña Vista previa
    def _tab_preview(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        h = QHBoxLayout()
        h.addWidget(QLabel("Sembrador:"))
        self.cb_prev = QComboBox()
        self.cb_prev.currentIndexChanged.connect(self._refresh_preview)
        h.addWidget(self.cb_prev, 1)
        self.c_only_pend = QCheckBox("solo pendientes")
        self.c_only_pend.toggled.connect(self._refresh_preview)
        h.addWidget(self.c_only_pend)
        b = QPushButton("Quitar ediciones manuales")
        b.clicked.connect(self._reset_overrides)
        h.addWidget(b)
        lay.addLayout(h)
        self.l_prev = QLabel()
        lay.addWidget(self.l_prev)
        self.t_prev = QTableWidget(0, 5)
        self.t_prev.setHorizontalHeaderLabels(["Campo", "Valor (editable)", "Origen", "Estado", "Ruta"])
        hdr = self.t_prev.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        self.t_prev.setColumnWidth(0, 420)
        self.t_prev.itemChanged.connect(self._on_prev_edit)
        lay.addWidget(self.t_prev)
        return w

    def _refresh_preview_combo(self):
        cur = self.cb_prev.currentData()
        self.cb_prev.blockSignals(True)
        self.cb_prev.clear()
        for s in self.sembradores:
            self.cb_prev.addItem(s.draft_name or "(sin nombre)", s.uid)
        idx = max(0, self.cb_prev.findData(cur))
        self.cb_prev.setCurrentIndex(idx)
        self.cb_prev.blockSignals(False)
        self._refresh_preview()

    def _plan_for(self, s: Sembrador, n: int = 0):
        return self.builder.build(s, self.inventario.get(s.uid, []), n, self.overrides.get(s.uid))

    def _refresh_preview(self):
        uid = self.cb_prev.currentData()
        s = next((x for x in self.sembradores if x.uid == uid), None)
        self._loading = True
        self.t_prev.setRowCount(0)
        self._prev_actions = []
        if not s:
            self._loading = False
            return
        self.builder.reload()
        n = self.sembradores.index(s)
        plan = self._plan_for(s, n)
        acts = [a for a in plan.actions if a.op != "repeat"]
        if self.c_only_pend.isChecked():
            acts = [a for a in acts if a.pending]
        self._prev_actions = acts
        self.t_prev.setRowCount(len(acts))
        for r, a in enumerate(acts):
            vals = [a.label, _fmt(a.value), a.source, "PENDIENTE" if a.pending else "", self.schema.rel(a.path)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c != 1:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if a.pending:
                    it.setBackground(QColor("#fff2c6"))
                if a.source == "manual":
                    it.setForeground(QColor("#0050b0"))
                self.t_prev.setItem(r, c, it)
        self.l_prev.setText(f"{len(plan.actions)} acciones · {len(plan.pendientes)} pendientes · "
                            f"{len(plan.issues)} avisos  —  los valores en azul fueron editados a mano")
        self._loading = False

    def _on_prev_edit(self, it):
        if self._loading or it.column() != 1:
            return
        a = self._prev_actions[it.row()]
        uid = self.cb_prev.currentData()
        txt = it.text().strip()
        if isinstance(a.value, list) or a.kind == "select_multiple":
            val = [x.strip() for x in txt.split(";") if x.strip()]
        elif a.kind == "number":
            val = _to_num(txt)
        else:
            val = txt or None
        self.overrides.setdefault(uid, {})[(a.path, a.index)] = val
        self._save_session()
        self._refresh_preview()

    def _reset_overrides(self):
        self.overrides.pop(self.cb_prev.currentData(), None)
        self._save_session()
        self._refresh_preview()

    # ---------------------------------------------------------- pestaña Llenado
    def _tab_llenado(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        g = QGroupBox("Opciones")
        gl = QGridLayout(g)
        self.c_pausa = QCheckBox("Pausa antes de guardar cada borrador (revisar en el navegador)")
        self.c_pausa.setChecked(True)
        self.c_guardar = QCheckBox("Guardar borrador \"CURP - Nombre\" al terminar")
        self.c_guardar.setChecked(True)
        self.c_visible = QCheckBox("Mostrar el navegador mientras llena")
        self.c_visible.setChecked(True)
        self.cb_autosave = QComboBox()
        self.cb_autosave.addItems(["preguntar", "descartar", "cargar"])
        gl.addWidget(self.c_pausa, 0, 0)
        gl.addWidget(self.c_guardar, 1, 0)
        gl.addWidget(self.c_visible, 2, 0)
        gl.addWidget(QLabel("Si Enketo encuentra un registro auto-guardado sin terminar:"), 0, 1)
        gl.addWidget(self.cb_autosave, 1, 1)
        lay.addWidget(g)
        h = QHBoxLayout()
        self.b_fill = QPushButton("▶  Prellenar sembradores marcados")
        self.b_fill.setStyleSheet("font-weight:bold; padding:8px 16px;")
        self.b_fill.clicked.connect(self._start_fill)
        self.b_stop = QPushButton("Detener")
        self.b_stop.setEnabled(False)
        self.b_stop.clicked.connect(self._stop_fill)
        self.b_review = QPushButton("Abrir navegador para revisar / ENVIAR a mano")
        self.b_review.clicked.connect(self._open_review)
        self.b_report = QPushButton("Abrir último reporte")
        self.b_report.clicked.connect(lambda: self.last_report and open_path(self.last_report))
        for b in (self.b_fill, self.b_stop, self.b_review, self.b_report):
            h.addWidget(b)
        h.addStretch()
        lay.addLayout(h)
        self.pbar = QProgressBar()
        self.l_cur = QLabel()
        lay.addWidget(self.pbar)
        lay.addWidget(self.l_cur)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log)
        return w

    def _log(self, m: str):
        self.log.appendPlainText(m)
        self._log_lines.append(m)

    def _start_fill(self):
        if self.review and self.review.isRunning():
            QMessageBox.information(self, APP_TITLE, "Cierra primero el navegador de revisión.")
            return
        marcados = [s for s in self.sembradores if s.uid in self.seleccion]
        if not marcados:
            QMessageBox.information(self, APP_TITLE, "Marca al menos un sembrador en la pestaña Sembradores.")
            return
        self._save_dia()
        self.builder.reload()
        planes = [self._plan_for(s, self.sembradores.index(s)) for s in marcados]
        sin_curp = [p.sembrador for p in planes if not p.sembrador.curp]
        if sin_curp and QMessageBox.question(
                self, APP_TITLE, f"{len(sin_curp)} sembrador(es) sin CURP. ¿Continuar?") != QMessageBox.Yes:
            return
        self._log_lines = []
        self.log.clear()
        self._plan_avisos = [i for p in planes for i in p.issues]
        self.worker = FillWorker(planes, {"pausa": self.c_pausa.isChecked(), "guardar": self.c_guardar.isChecked(),
                                          "visible": self.c_visible.isChecked() or self.c_pausa.isChecked(),
                                          "autosave": self.cb_autosave.currentText()})
        self.worker.log.connect(self._log)
        self.worker.progress.connect(self._on_progress)
        self.worker.ask_pause.connect(self._on_ask_pause)
        self.worker.ask_autosave.connect(self._on_ask_autosave)
        self.worker.finished_entries.connect(self._on_fill_done)
        self._n_planes = len(planes)
        self.b_fill.setEnabled(False)
        self.b_stop.setEnabled(True)
        self.b_review.setEnabled(False)
        self.worker.start()

    def _stop_fill(self):
        if self.worker:
            self.worker.stop()
            self._log("Deteniendo al terminar el sembrador actual…")

    def _on_progress(self, k, i, n, label, status):
        self.pbar.setMaximum(n * self._n_planes)
        self.pbar.setValue(k * n + i)
        self.l_cur.setText(f"Sembrador {k + 1}/{self._n_planes} · campo {i}/{n}: {label} → {status}")

    def _on_ask_pause(self, name):
        r = QMessageBox.question(self, "Pausa antes de guardar",
                                 f"Revisa el formulario en el navegador.\n\n¿Guardar el borrador\n\"{name}\"?\n\n"
                                 "(Sí = guardar borrador · No = dejarlo sin guardar)",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        self.worker.answer(r == QMessageBox.Yes)

    def _on_ask_autosave(self, text):
        box = QMessageBox(self)
        box.setWindowTitle("Registro auto-guardado")
        box.setText("Enketo encontró un registro sin guardar (puede ser trabajo manual a medias):\n\n"
                    f"{text[:300]}\n\n¿Qué hago?")
        bd = box.addButton("Descartarlo y seguir", QMessageBox.DestructiveRole)
        bc = box.addButton("Cargarlo (llenar encima)", QMessageBox.AcceptRole)
        box.addButton("Detener", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        self.worker.answer("descartar" if clicked is bd else "cargar" if clicked is bc else "detener")

    def _on_fill_done(self, entries):
        self.b_fill.setEnabled(True)
        self.b_stop.setEnabled(False)
        self.b_review.setEnabled(True)
        for e in entries:
            res, s = e["result"], e["plan"].sembrador
            bad = sum(r.status == "fallo" for r in res.fields)
            self.estados[s.uid] = (f"{res.status}" + (f" · {bad} fallos" if bad else "")
                                   + (f" · {len(res.required_empty)} obligatorios vacíos" if res.required_empty else ""))
        self.last_entries = entries
        if entries:
            try:
                self.last_report = write_report(entries, list(dict.fromkeys(self.validacion + self._plan_avisos)),
                                                self._log_lines)
                self._log(f"Reporte: {self.last_report}")
            except Exception as e:  # noqa: BLE001
                self._log(f"No se pudo escribir el reporte: {e}")
        self._refresh_sembradores()

    def _open_review(self):
        if self.worker and self.worker.isRunning():
            return
        self.review = ReviewWorker(self.builder_url())
        self.review.log.connect(self._log_safe)
        self.review.start()

    def _log_safe(self, m):
        if not hasattr(self, "_log_lines"):
            self._log_lines = []
        self._log(m)

    def builder_url(self) -> str:
        return self.schema.raw.get("enketo_url") or "https://ee.sembrandodatos.com/x/7kMmQETh"

    # --------------------------------------------------------- pestaña Plantilla
    def _tab_plantilla(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        sub = QTabWidget()
        # campos simples
        cw = QWidget()
        cl = QVBoxLayout(cw)
        cl.addWidget(QLabel("Respuestas iguales para todos. Valor = texto visible de la opción; "
                            "varias opciones separadas con ';'. Vacío = PENDIENTE."))
        self.t_tpl = QTableWidget(0, 3)
        self.t_tpl.setHorizontalHeaderLabels(["Pregunta", "Valor", "Ruta"])
        self.t_tpl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.t_tpl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.t_tpl.setColumnWidth(0, 460)
        self.t_tpl.setItemDelegateForColumn(1, OptionsDelegate(self._tpl_options, self.t_tpl))
        cl.addWidget(self.t_tpl)
        h = QHBoxLayout()
        b = QPushButton("Guardar plantilla")
        b.clicked.connect(self._save_tpl_table)
        h.addWidget(b)
        h.addStretch()
        cl.addLayout(h)
        sub.addTab(cw, "Campos")
        # yaml completo
        yw = QWidget()
        yl = QVBoxLayout(yw)
        yl.addWidget(QLabel("Edición completa (matrices, especies tolerantes, biocultural, cultivos eje, cultivo anual…)"))
        self.y_tpl = QPlainTextEdit()
        self.y_tpl.setStyleSheet("font-family: Consolas, monospace;")
        yl.addWidget(self.y_tpl)
        h2 = QHBoxLayout()
        b2 = QPushButton("Guardar YAML")
        b2.clicked.connect(self._save_tpl_yaml)
        b3 = QPushButton("Recargar")
        b3.clicked.connect(self._load_tpl)
        h2.addWidget(b2)
        h2.addWidget(b3)
        h2.addStretch()
        yl.addLayout(h2)
        sub.addTab(yw, "YAML completo")
        lay.addWidget(sub)
        self._load_tpl()
        return w

    def _tpl_rows(self):
        tpl = self.builder.plantilla
        rows = list((tpl.get("campos") or {}).items()) + list((tpl.get("cultivo_anual_1") or {}).items())
        return rows

    def _tpl_options(self, row):
        rel = self.t_tpl.item(row, 2).text() if self.t_tpl.item(row, 2) else ""
        f = self.schema.get(rel)
        if not f:
            return []
        if f["itemset_source"]:
            from .form_schema import load_media_csv
            return [r["label"] for r in load_media_csv(f["itemset_source"])][:2000]
        return [o["label"] for o in f["options"]]

    def _load_tpl(self):
        self.builder.reload()
        self._loading = True
        rows = self._tpl_rows()
        self.t_tpl.setRowCount(len(rows))
        for r, (rel, val) in enumerate(rows):
            f = self.schema.get(rel)
            lab = (f["label"] if f else "¿campo inexistente?") + (" *" if f and f["required"] else "")
            items = [QTableWidgetItem(lab), QTableWidgetItem(_fmt(val)), QTableWidgetItem(rel)]
            items[0].setFlags(items[0].flags() & ~Qt.ItemIsEditable)
            items[2].setFlags(items[2].flags() & ~Qt.ItemIsEditable)
            if val is None:
                items[1].setBackground(QColor("#fff2c6"))
            for c, it in enumerate(items):
                self.t_tpl.setItem(r, c, it)
        self.y_tpl.setPlainText((CONFIG / "plantilla.yaml").read_text(encoding="utf-8"))
        self._loading = False

    def _save_tpl_table(self):
        tpl = self.builder.plantilla
        for r in range(self.t_tpl.rowCount()):
            rel = self.t_tpl.item(r, 2).text()
            txt = (self.t_tpl.item(r, 1).text() or "").strip()
            f = self.schema.get(rel)
            if not txt:
                val = None
            elif f and f["kind"] == "select_multiple":
                val = [x.strip() for x in txt.split(";") if x.strip()]
            elif f and f["kind"] == "number":
                val = _to_num(txt)
            else:
                val = txt
            sec = "cultivo_anual_1" if rel in (tpl.get("cultivo_anual_1") or {}) else "campos"
            tpl.setdefault(sec, {})[rel] = val
        self._write_tpl(tpl)

    def _save_tpl_yaml(self):
        try:
            data = yaml.safe_load(self.y_tpl.toPlainText())
            assert isinstance(data, dict), "el YAML debe ser un diccionario"
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP_TITLE, f"YAML inválido:\n{e}")
            return
        p = CONFIG / "plantilla.yaml"
        self._backup(p)
        p.write_text(self.y_tpl.toPlainText(), encoding="utf-8")
        self._load_tpl()
        self.statusBar().showMessage("Plantilla guardada.", 4000)

    def _write_tpl(self, tpl):
        p = CONFIG / "plantilla.yaml"
        self._backup(p)
        save_yaml("plantilla.yaml", tpl, "# PLANTILLA FIJA - guardada desde la app. Valor = texto visible; null = PENDIENTE.\n")
        self._load_tpl()
        self.statusBar().showMessage("Plantilla guardada.", 4000)

    @staticmethod
    def _backup(p: Path):
        if p.exists():
            bk = p.with_suffix(f".{dt.datetime.now():%Y%m%d_%H%M%S}.bak")
            bk.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")

    # -------------------------------------------------------- pestaña Validación
    def _tab_validacion(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        h = QHBoxLayout()
        b = QPushButton("Validar todo (plantilla + padrón + inventario)")
        b.clicked.connect(self._run_validation)
        h.addWidget(b)
        b2 = QPushButton("Exportar reporte de validación")
        b2.clicked.connect(self._export_validation)
        h.addWidget(b2)
        h.addStretch()
        lay.addLayout(h)
        split = QSplitter(Qt.Vertical)
        self.l_val = QListWidget()
        split.addWidget(self.l_val)
        box = QWidget()
        bl = QVBoxLayout(box)
        hh = QHBoxLayout()
        hh.addWidget(QLabel("Especies del inventario → catálogo del formulario. Cambia la especie si hace falta y "
                            "presiona Aprobar: se guarda en alias_especies.yaml y se usa en adelante."))
        hh.addStretch()
        b3 = QPushButton("Aprobar fila seleccionada")
        b3.clicked.connect(self._approve_alias)
        hh.addWidget(b3)
        bl.addLayout(hh)
        self.t_esp = QTableWidget(0, 6)
        self.t_esp.setHorizontalHeaderLabels(["Nombre común", "Nombre científico (inventario)", "Categoría",
                                              "Especie del catálogo", "Similitud", "Método"])
        self.t_esp.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.t_esp.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.t_esp.setSelectionBehavior(QAbstractItemView.SelectRows)
        bl.addWidget(self.t_esp)
        split.addWidget(box)
        lay.addWidget(split)
        return w

    def _refresh_especies(self):
        from .especies import CATEGORIAS
        cat = self.builder.cat
        vistos = {}
        for filas in self.inventario.values():
            for f in filas:
                if (f.comun or f.cientifico) and (f.comun, f.cientifico) not in vistos:
                    vistos[(f.comun, f.cientifico)] = cat.match(f.comun, f.cientifico)
        rows = sorted(vistos.values(), key=lambda m: (m.metodo == "alias", m.score))
        self.t_esp.clearContents()
        self.t_esp.setRowCount(0)
        self.t_esp.setRowCount(len(rows))
        self._esp_rows = rows
        for r, m in enumerate(rows):
            vals = [m.entrada_comun, m.entrada_cientifico, m.categoria or "", m.label, f"{m.score:.0f}", m.metodo]
            for c, v in enumerate(vals):
                it = QTableWidgetItem("" if c in (2, 3) else v)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if m.metodo in ("otra", "sin_categoria"):
                    it.setBackground(QColor("#f8d0d0"))
                elif m.avisos:
                    it.setBackground(QColor("#fff2c6"))
                if m.avisos:
                    it.setToolTip(chr(10).join(m.avisos))
                self.t_esp.setItem(r, c, it)
            cb_cat = QComboBox()
            cb_cat.addItems(list(CATEGORIAS))
            if m.categoria:
                cb_cat.setCurrentText(m.categoria)
            cb = QComboBox()
            cb.setEditable(True)

            def fill(_=None, cb=cb, cb_cat=cb_cat, m=m):
                cb.clear()
                cb.addItems([e.label for e in cat.catalogos[cb_cat.currentText()]])
                cb.setCurrentText(m.label if m.categoria == cb_cat.currentText() else "")
            cb_cat.currentIndexChanged.connect(fill)
            fill()
            self.t_esp.setCellWidget(r, 2, cb_cat)
            self.t_esp.setCellWidget(r, 3, cb)

    def _approve_alias(self):
        r = self.t_esp.currentRow()
        if r < 0:
            return
        m = self._esp_rows[r]
        categoria = self.t_esp.cellWidget(r, 2).currentText()
        label = self.t_esp.cellWidget(r, 3).currentText().strip()
        if label not in [e.label for e in self.builder.cat.catalogos[categoria]]:
            QMessageBox.warning(self, APP_TITLE, "Elige una especie que exista en el catálogo.")
            return
        entrada = m.entrada_cientifico or m.entrada_comun
        self.builder.cat.save_alias(entrada, categoria, label)
        self.statusBar().showMessage(f"Alias guardado: {entrada} → {label}", 5000)
        self._run_validation()

    def _run_validation(self):
        self.builder.reload()
        lote = Lote(self.sembradores, self.inventario, list(self.validacion))
        self._val_planes, avisos = validar(lote, self.builder)
        self.l_val.clear()
        for a in avisos:
            it = QListWidgetItem(a)
            low = a.lower()
            if "sin coincidencia" in low or "sin categoria" in low or "no existe" in low or "no es una opcion" in low \
                    or "sin inventario" in low or "sin sembrador" in low or "invalido" in low:
                it.setBackground(QColor("#f8d0d0"))
            elif "pendientes" in low or "sugerencia" in low or "corregido" in low or "emparejado" in low:
                it.setBackground(QColor("#fff2c6"))
            self.l_val.addItem(it)
        self._val_avisos = avisos
        self._refresh_especies()

    def _export_validation(self):
        if not getattr(self, "_val_planes", None):
            self._run_validation()
        self.last_report = write_report([{"plan": p, "result": None} for p in self._val_planes], self._val_avisos, [])
        open_path(self.last_report)

    # ------------------------------------------------------------------ otros
    def _on_tab(self, i):
        name = self.tabs.tabText(i)
        if "Vista previa" in name:
            self._refresh_preview_combo()
        elif "Validación" in name:
            self._run_validation()

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            if QMessageBox.question(self, APP_TITLE, "Hay un llenado en curso. ¿Salir de todos modos?") != QMessageBox.Yes:
                e.ignore()
                return
            self.worker.stop()
            self.worker.wait(5000)
        self._save_session()
        e.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
