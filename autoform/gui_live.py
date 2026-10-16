"""Pestaña EN VIVO: capturas en la app y el formulario se pinta al instante
en la ventana del navegador que abre la app. Lo que cambies a mano en el
navegador regresa a la app. Nunca se envia."""
from __future__ import annotations

import datetime as dt
import re

from PySide6.QtCore import Qt, QTimer, QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QPushButton, QLabel, QLineEdit, QComboBox,
    QDateEdit, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QSplitter, QMessageBox,
)

from .excel_inventario import PlantaFila
from .excel_padron import Sembrador
from .live import LiveSession, diff_plan, key_of
from .template import save_yaml

# dato de la app -> ruta del campo (relativa) ; para pintar y para el regreso desde el navegador
SEMB_FIELDS = [
    ("curp", "CURP del sembrador", "group_eq6af71/curp"),
    ("nombre", "Nombre(s)", "group_eq6af71/nombre"),
    ("apellido_p", "Apellido paterno", "group_eq6af71/aPaterno"),
    ("apellido_m", "Apellido materno", "group_eq6af71/aMaterno"),
    ("cac_id", "ID de la CAC", "group_eq6af71/ID_de_la_CAC"),
    ("cac_nombre", "Nombre de la CAC", "group_eq6af71/Nombre_de_la_CAC"),
    ("id_predio", "ID del predio", "up/num_up_txt"),
    ("latitud", "Latitud del centroide", None),
    ("longitud", "Longitud del centroide", None),
    ("curp_tecnica", "CURP del técnico", "datos_curp/curp_ingresado"),
]
DIA_FIELDS = [
    ("hora_inicio", "Hora de inicio (HH:MM)", "Hora_de_inicio_de_la_entrevista"),
    ("hora_termino", "Hora de término (HH:MM)", "Hora_de_t_rmino_de_la_entrevista"),
]
CENTROIDE = "up/Registra_el_centroide_del_predio"
INV_COLS = [("Año", "anio"), ("Nombre común", "comun"), ("Nombre científico", "cientifico"),
            ("Número", "numero"), ("Diámetro (cm)", "diametro_cm"), ("Altura (cm)", "altura_cm")]
ICON = {"ok": "✓", "fallo": "✗", "no_aplica": "–", "omitido": "!", "pendiente": "…", "pintando": "⏳"}
COLOR = {"ok": "#d8f5d0", "fallo": "#f8d0d0", "omitido": "#fff2c6", "no_aplica": "#eeeeee", "pintando": "#e4eefc"}
HORA_RE = re.compile(r"^\d{1,2}:\d{2}$")


def _num(t: str):
    t = (t or "").strip().replace(",", ".")
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


class LiveTabMixin:
    """Se mezcla con MainWindow (usa self.sembradores, self.inventario, self.builder, ...)."""

    # ------------------------------------------------------------ construccion
    def _tab_live(self):
        self.live: LiveSession | None = None
        self.painted: dict = {}
        self.live_labels: dict = {}
        self._live_loading = False
        self._live_uid: str | None = None
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(350)
        self._sync_timer.timeout.connect(self._live_sync)

        w = QWidget()
        lay = QVBoxLayout(w)
        # barra superior
        top = QHBoxLayout()
        self.b_live_open = QPushButton("▶  Abrir formulario en vivo")
        self.b_live_open.setStyleSheet("font-weight:bold; padding:6px 14px;")
        self.b_live_open.clicked.connect(self._live_open)
        self.l_live = QLabel("○ Desconectado")
        self.l_live.setStyleSheet("color:#888; font-weight:bold;")
        top.addWidget(self.b_live_open)
        top.addWidget(self.l_live)
        top.addSpacing(20)
        top.addWidget(QLabel("Sembrador:"))
        self.cb_live = QComboBox()
        self.cb_live.setMinimumWidth(360)
        self.cb_live.activated.connect(self._live_pick)
        top.addWidget(self.cb_live, 1)
        b_new = QPushButton("+ Nuevo sembrador")
        b_new.clicked.connect(self._live_new_semb)
        top.addWidget(b_new)
        lay.addLayout(top)

        top2 = QHBoxLayout()
        self.b_live_save = QPushButton("💾  Guardar borrador y pasar al siguiente")
        self.b_live_save.clicked.connect(self._live_save)
        self.b_live_req = QPushButton("¿Qué obligatorios faltan?")
        self.b_live_req.clicked.connect(lambda: self.live and self.live.send("required"))
        self.b_live_repaint = QPushButton("Repintar todo")
        self.b_live_repaint.clicked.connect(self._live_repaint)
        self.c_live_tpl = QCheckBox("Pintar también la plantilla fija")
        self.c_live_tpl.setChecked(True)
        self.c_live_tpl.toggled.connect(self._live_changed)
        for x in (self.b_live_save, self.b_live_req, self.b_live_repaint):
            x.setEnabled(False)
            top2.addWidget(x)
        top2.addWidget(self.c_live_tpl)
        top2.addStretch()
        top2.addWidget(QLabel("La app NUNCA envía: el botón Enviar está bloqueado."))
        lay.addLayout(top2)

        split = QSplitter(Qt.Horizontal)
        # --- izquierda: captura
        left = QWidget()
        ll = QVBoxLayout(left)
        g = QGroupBox("Datos del sembrador (se pintan al escribir)")
        fl = QFormLayout(g)
        self.live_edits: dict[str, QLineEdit] = {}
        self.live_marks: dict[str, QLabel] = {}
        for attr, label, _ in SEMB_FIELDS + DIA_FIELDS:
            e = QLineEdit()
            e.textEdited.connect(lambda _t, a=attr: self._live_field_edited(a))
            mark = QLabel("")
            mark.setFixedWidth(18)
            row = QHBoxLayout()
            row.addWidget(e)
            row.addWidget(mark)
            fl.addRow(label, row)
            self.live_edits[attr] = e
            self.live_marks[attr] = mark
            if attr == "curp_tecnica":
                fl.addRow(QLabel("<b>Datos del día</b>"))
                self.live_fecha = QDateEdit(calendarPopup=True)
                self.live_fecha.setDisplayFormat("yyyy-MM-dd")
                self.live_fecha.dateChanged.connect(lambda _d: self._live_day_edited())
                fl.addRow("Fecha de la entrevista", self.live_fecha)
        self.live_calidad = QComboBox()
        self.live_calidad.addItems(["(pendiente)", "Completa", "Incompleta", "Se negó a dar información",
                                    "Informante inadecuado"])
        self.live_calidad.currentIndexChanged.connect(lambda _i: self._live_day_edited())
        fl.addRow("Calidad de la entrevista", self.live_calidad)
        ll.addWidget(g)
        gi = QGroupBox("Inventario de planta viva (planta establecida y cultivos eje se calculan solos)")
        il = QVBoxLayout(gi)
        hb = QHBoxLayout()
        for text, fn in (("Agregar planta", self._live_add_inv), ("Quitar planta", self._live_del_inv)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            hb.addWidget(b)
        hb.addStretch()
        il.addLayout(hb)
        self.t_live_inv = QTableWidget(0, len(INV_COLS))
        self.t_live_inv.setHorizontalHeaderLabels([c for c, _ in INV_COLS])
        self.t_live_inv.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.t_live_inv.itemChanged.connect(self._live_inv_edited)
        il.addWidget(self.t_live_inv)
        ll.addWidget(gi, 1)
        split.addWidget(left)
        # --- derecha: actividad
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("Actividad en el navegador (lo más reciente arriba)"))
        self.t_live_act = QTableWidget(0, 4)
        self.t_live_act.setHorizontalHeaderLabels(["Hora", "Campo", "Valor", "Estado"])
        h = self.t_live_act.horizontalHeader()
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        rl.addWidget(self.t_live_act)
        split.addWidget(right)
        split.setSizes([560, 640])
        lay.addWidget(split, 1)
        self._live_fill_combo()
        self._live_load_day()
        return w

    # ------------------------------------------------------------ sembrador actual
    def _live_semb(self) -> Sembrador | None:
        return next((s for s in self.sembradores if s.uid == self._live_uid), None)

    def _live_fill_combo(self):
        self.cb_live.blockSignals(True)
        self.cb_live.clear()
        for s in self.sembradores:
            self.cb_live.addItem(s.draft_name or "(nuevo sembrador sin datos)", s.uid)
        if not self.sembradores:
            self._live_uid = None
        elif self._live_uid not in [s.uid for s in self.sembradores]:
            self._live_uid = self.sembradores[0].uid
        idx = self.cb_live.findData(self._live_uid)
        self.cb_live.setCurrentIndex(max(0, idx))
        self.cb_live.blockSignals(False)
        self._live_load_semb()

    def _live_load_semb(self):
        s = self._live_semb()
        self._live_loading = True
        for attr, _, _ in SEMB_FIELDS:
            self.live_edits[attr].setText(_fmt(getattr(s, attr)) if s else "")
            self.live_edits[attr].setEnabled(s is not None)
            self.live_marks[attr].setText("")
        rows = self.inventario.get(s.uid, []) if s else []
        self.t_live_inv.setRowCount(len(rows))
        for r, f in enumerate(rows):
            for c, (_, attr) in enumerate(INV_COLS):
                self.t_live_inv.setItem(r, c, QTableWidgetItem(_fmt(getattr(f, attr))))
        self._live_loading = False

    def _live_load_day(self):
        d = self.builder.dia
        self._live_loading = True
        saved = (d.get("fecha") or "").strip()
        self.live_fecha.setDate(QDate.fromString(saved, "yyyy-MM-dd") if saved == dt.date.today().isoformat()
                                else QDate.currentDate())
        self.live_edits["hora_inicio"].setText(d.get("hora_inicio") or "")
        self.live_edits["hora_termino"].setText(d.get("hora_termino") or "")
        self.live_calidad.setCurrentText(d.get("calidad_entrevista") or "(pendiente)")
        self._live_loading = False

    def _live_new_semb(self):
        s = Sembrador(curp_tecnica=(self.builder.dia.get("curp_tecnico") or "").upper())
        self.sembradores.append(s)
        self.inventario[s.uid] = []
        self.seleccion.add(s.uid)
        self._save_session()
        self._live_switch_to(s.uid)
        self.live_edits["curp"].setFocus()

    def _live_pick(self, idx: int):
        uid = self.cb_live.itemData(idx)
        if uid != self._live_uid:
            self._live_switch_to(uid)

    def _live_switch_to(self, uid: str):
        """Cambiar de sembrador: si el formulario tiene datos pintados, preguntar si se guarda."""
        if self._live_connected() and self.painted:
            prev = self._live_semb()
            box = QMessageBox(self)
            box.setWindowTitle("Cambiar de sembrador")
            box.setText(f"El formulario tiene datos de\n{prev.draft_name if prev else '(sin nombre)'}.\n\n"
                        "¿Guardar su borrador antes de empezar con el siguiente?")
            bs = box.addButton("Guardar borrador", QMessageBox.AcceptRole)
            bd = box.addButton("Descartar y empezar limpio", QMessageBox.DestructiveRole)
            box.addButton("Cancelar", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is bs:
                self._live_uid_after_save = uid
                self._live_save(advance=False)
                return
            if box.clickedButton() is not bd:
                self.cb_live.setCurrentIndex(max(0, self.cb_live.findData(self._live_uid)))
                return
            self._live_uid = uid
            self._live_fill_combo()
            self._live_reset_form()
            return
        self._live_uid = uid
        self._live_fill_combo()
        self._live_changed()

    # ------------------------------------------------------------ ediciones
    def _live_field_edited(self, attr: str):
        if self._live_loading:
            return
        txt = self.live_edits[attr].text().strip()
        if attr in ("hora_inicio", "hora_termino"):
            if txt and not HORA_RE.match(txt):
                self.live_marks[attr].setText("…")
                return
            self.builder.dia[attr] = txt
            self._live_save_day()
        else:
            s = self._live_semb()
            if s is None:
                return
            if attr in ("latitud", "longitud"):
                setattr(s, attr, _num(txt))
            elif attr in ("curp", "curp_tecnica", "nombre", "apellido_p", "apellido_m"):
                setattr(s, attr, txt.upper())
            else:
                setattr(s, attr, txt)
                if attr == "id_predio" and "," in txt and (s.latitud is None or s.longitud is None):
                    a, b = (_num(x) for x in txt.split(",", 1))
                    s.latitud, s.longitud = a, b
                    self._live_loading = True
                    self.live_edits["latitud"].setText(_fmt(a))
                    self.live_edits["longitud"].setText(_fmt(b))
                    self._live_loading = False
            if attr in ("curp", "nombre", "apellido_p", "apellido_m"):
                i = self.cb_live.findData(s.uid)
                self.cb_live.setItemText(i, s.draft_name or "(nuevo sembrador sin datos)")
            self._save_session()
        self.live_marks[attr].setText(ICON["pintando"] if self._live_connected() else "")
        self._live_changed()

    def _live_day_edited(self):
        if self._live_loading:
            return
        self.builder.dia["fecha"] = self.live_fecha.date().toString("yyyy-MM-dd")
        cal = self.live_calidad.currentText()
        self.builder.dia["calidad_entrevista"] = None if cal.startswith("(") else cal
        self._live_save_day()
        self._live_changed()

    def _live_save_day(self):
        save_yaml("dia.yaml", self.builder.dia, "# DATOS DEL DIA - editados desde la app\n")

    def _live_add_inv(self):
        s = self._live_semb()
        if not s:
            return
        self.inventario.setdefault(s.uid, []).append(PlantaFila(
            id_sembrador=s.id_sembrador, nombre_sembrador=s.nombre_completo, cac=s.cac_nombre, poligono=s.poligono,
            ha=None, anio=None, comun="", cientifico="", numero=None, diametro_cm=None, altura_cm=None, fila_excel=0))
        self._live_load_semb()
        self.t_live_inv.editItem(self.t_live_inv.item(self.t_live_inv.rowCount() - 1, 1))

    def _live_del_inv(self):
        s = self._live_semb()
        r = self.t_live_inv.currentRow()
        if s and r >= 0:
            self.inventario[s.uid].pop(r)
            self._live_load_semb()
            self._save_session()
            self._live_changed()

    def _live_inv_edited(self, it):
        if self._live_loading:
            return
        s = self._live_semb()
        if not s:
            return
        f = self.inventario[s.uid][it.row()]
        attr = INV_COLS[it.column()][1]
        txt = it.text().strip()
        if attr in ("comun", "cientifico"):
            setattr(f, attr, txt.upper())
        elif attr == "anio":
            v = _num(txt)
            f.anio = int(v) if v is not None else None
        else:
            setattr(f, attr, _num(txt))
        self._save_session()
        # una planta a medias (sin nombre o sin numero) todavia no se pinta
        if (f.comun or f.cientifico) and f.numero:
            self._live_changed()

    # ------------------------------------------------------------ conexion
    def _live_connected(self) -> bool:
        return bool(self.live and self.live.isRunning() and getattr(self, "_live_ready", False))

    def _live_open(self):
        if self.live and self.live.isRunning():
            return
        if getattr(self, "worker", None) and self.worker.isRunning():
            QMessageBox.information(self, "AutoForm PSV", "Espera a que termine el llenado por lote.")
            return
        if getattr(self, "review", None) and self.review.isRunning():
            QMessageBox.information(self, "AutoForm PSV", "Cierra primero el navegador de revisión.")
            return
        if not self.sembradores:
            self._live_new_semb()
        self._live_ready = False
        self.live = LiveSession()
        self.live.status.connect(self._live_on_status)
        self.live.log.connect(lambda m: self._live_act("", m, "", "info"))
        self.live.field_done.connect(self._live_on_done)
        self.live.browser_change.connect(self._live_on_browser)
        self.live.ask_autosave.connect(self._live_on_autosave)
        self.live.draft_saved.connect(self._live_on_saved)
        self.live.form_ready.connect(self._live_on_ready)
        self.b_live_open.setEnabled(False)
        self.live.start()

    def _live_on_status(self, text: str, connected: bool):
        self.l_live.setText(("● " if connected else "○ ") + text)
        self.l_live.setStyleSheet(f"color:{'#2a8a2a' if connected else '#888'}; font-weight:bold;")
        if text == "Navegador cerrado":
            self._live_ready = False
            self.painted.clear()
            self.b_live_open.setEnabled(True)
            for b in (self.b_live_save, self.b_live_req, self.b_live_repaint):
                b.setEnabled(False)

    def _live_on_ready(self):
        self._live_ready = True
        self.painted.clear()
        for b in (self.b_live_save, self.b_live_req, self.b_live_repaint):
            b.setEnabled(True)
        uid = getattr(self, "_live_uid_after_save", None)
        if uid:
            self._live_uid_after_save = None
            self._live_uid = uid
            self._live_fill_combo()
        self._live_changed()

    def _live_on_autosave(self, text: str):
        box = QMessageBox(self)
        box.setWindowTitle("Registro auto-guardado")
        box.setText("El navegador tiene un formulario sin guardar de antes:\n\n"
                    f"{text[:300]}\n\n¿Qué hago?")
        bc = box.addButton("Cargarlo (seguir con ese)", QMessageBox.AcceptRole)
        bd = box.addButton("Descartarlo", QMessageBox.DestructiveRole)
        box.addButton("Cerrar navegador", QMessageBox.RejectRole)
        box.exec()
        c = box.clickedButton()
        self.live.answer("cargar" if c is bc else "descartar" if c is bd else "detener")

    # ------------------------------------------------------------ sincronizacion
    def _live_changed(self, *_):
        if self._live_connected():
            self._sync_timer.start()

    def _live_plan(self):
        s = self._live_semb()
        if s is None:
            return None
        return self.builder.build(s, self.inventario.get(s.uid, []), self.sembradores.index(s),
                                  self.overrides.get(s.uid))

    def _live_sync(self):
        if not self._live_connected():
            return
        plan = self._live_plan()
        if plan is None:
            return
        for a in plan.actions:
            self.live_labels[key_of(a)] = a.label
        todo = diff_plan(plan.actions, self.painted, self.c_live_tpl.isChecked())
        if not todo:
            return
        for a in todo:
            self.painted[key_of(a)] = a.value if a.op != "clear" else None
        self.live.send("apply", todo)

    def _live_repaint(self):
        self.painted.clear()
        self._live_sync()

    def _live_reset_form(self):
        self._live_ready = False
        self.painted.clear()
        self.live.send("new_form", "descartar")

    def _live_on_done(self, path: str, idx: int, status: str, detail: str, value):
        label = self.live_labels.get((path, idx), path.rsplit("/", 1)[-1])
        if not detail and status == "ok" and label.startswith("Instancias"):
            detail = "listo"
        self._live_act(dt.datetime.now().strftime("%H:%M:%S"), label, _fmt(value) or detail, status, detail)
        rel = self.schema.rel(path)
        for attr, _, p in SEMB_FIELDS + DIA_FIELDS:
            if p == rel or (attr in ("latitud", "longitud") and rel == CENTROIDE):
                self.live_marks[attr].setText(ICON.get(status, "?"))
                self.live_marks[attr].setToolTip(detail)

    def _live_on_browser(self, path: str, idx: int, labels):
        """La persona cambio algo a mano en el navegador: se respeta y se regresa a la app."""
        s = self._live_semb()
        if s is None:
            return
        rel = self.schema.rel(path)
        f = self.schema.by_path.get(path) or {}
        multi = f.get("kind") == "select_multiple"
        value = list(labels) if multi else (labels[0] if labels else None)
        self.painted[(path, idx)] = value
        label = self.live_labels.get((path, idx), rel)
        self._live_act(dt.datetime.now().strftime("%H:%M:%S"), label, _fmt(value), "navegador")
        # datos del sembrador / del dia -> actualizar la captura
        self._live_loading = True
        try:
            if rel == CENTROIDE and value:
                parts = str(value).split()
                if len(parts) >= 2:
                    s.latitud, s.longitud = _num(parts[0]), _num(parts[1])
                    self.live_edits["latitud"].setText(_fmt(s.latitud))
                    self.live_edits["longitud"].setText(_fmt(s.longitud))
                return
            for attr, _, p in SEMB_FIELDS:
                if p == rel:
                    setattr(s, attr, value or "")
                    self.live_edits[attr].setText(_fmt(value))
                    return
            for attr, _, p in DIA_FIELDS:
                if p == rel:
                    self.builder.dia[attr] = (value or "")[:5]
                    self.live_edits[attr].setText((value or "")[:5])
                    self._live_save_day()
                    return
            # cualquier otro campo: queda como edicion manual de este sembrador
            self.overrides.setdefault(s.uid, {})[(path, idx)] = value
        finally:
            self._live_loading = False
            self._save_session()

    def _live_act(self, hora: str, campo: str, valor: str, status: str, detail: str = ""):
        t = self.t_live_act
        t.insertRow(0)
        txt = {"navegador": "✎ cambiado en el navegador", "info": ""}.get(status, f"{ICON.get(status, '')} {status}")
        for c, v in enumerate((hora, campo, valor, txt)):
            it = QTableWidgetItem(v)
            if detail:
                it.setToolTip(detail)
            col = COLOR.get(status) or ("#e9e0fb" if status == "navegador" else None)
            if col:
                it.setBackground(QColor(col))
            t.setItem(0, c, it)
        if t.rowCount() > 600:
            t.setRowCount(600)

    # ------------------------------------------------------------ borrador
    def _live_save(self, advance: bool = True):
        s = self._live_semb()
        if not s or not self._live_connected():
            return
        if not s.curp and QMessageBox.question(self, "Guardar borrador",
                                               "Este sembrador no tiene CURP. ¿Guardar de todos modos?") != QMessageBox.Yes:
            return
        name = s.draft_name or f"Sembrador {self.sembradores.index(s) + 1}"
        if advance:
            i = self.sembradores.index(s)
            nxt = self.sembradores[i + 1] if i + 1 < len(self.sembradores) else None
            if nxt is None:   # era el ultimo: se prepara uno nuevo vacio
                nxt = Sembrador(curp_tecnica=s.curp_tecnica or (self.builder.dia.get("curp_tecnico") or "").upper())
                self.sembradores.append(nxt)
                self.inventario[nxt.uid] = []
                self.seleccion.add(nxt.uid)
                self._save_session()
            self._live_uid_after_save = nxt.uid
        self._live_ready = False
        self.live.send("save_draft", name)

    def _live_on_saved(self, name: str):
        s = next((x for x in self.sembradores if x.draft_name == name), self._live_semb())
        if s is not None:
            self.estados[s.uid] = "borrador_guardado (en vivo)"
        self._live_act(dt.datetime.now().strftime("%H:%M:%S"), f"Borrador guardado: {name}", "", "ok")
        self.statusBar().showMessage(f"Borrador guardado: {name}", 6000)

    def _live_stop(self):
        if self.live and self.live.isRunning():
            self.live.running = False
            self.live.send("stop")
            self.live.answer("detener")
            self.live.wait(8000)
