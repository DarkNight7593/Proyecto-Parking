"""
ParkingPro - Panel de Reportes Financieros

Vistas de períodos:
  • Hoy     — ingresos por hora del día seleccionado.
  • Semana  — ingresos de los 7 días de la semana seleccionada.
  • Mes     — ingresos del mes/año seleccionado.
  • Año     — ingresos por mes del año seleccionado.

Características:
  • Navegación ◀ / ▶ para TODOS los períodos (incluyendo Hoy y Semana).
  • Clic en la etiqueta de fecha/período abre un selector visual:
      – Hoy/Semana → calendario de días con flechas de mes.
      – Mes        → cuadrícula de meses con navegación por año.
      – Año        → cuadrícula de años disponibles.
  • 4 KPIs: Ingresos, Vehículos cobrados, Canceladas, Tiempo promedio.
  • Gráfico de barras matplotlib (fondo oscuro, profesional).
  • Breakdown por tipo de vehículo (period-aware).
  • Historial COMPLETO del período, paginado de 10 en 10:
      – Todos los períodos muestran TODAS las transacciones del rango.
      – Controles Anterior / Siguiente con "Página X de Y · Z en total".
  • Exportación a Excel (.xlsx) con 5 hojas y gráficos.
  • Carga en hilo daemon para no congelar la UI.

Correcciones mantenidas:
  • Bug badge color: bg oscuro + borde del color del tipo (no hex 8 dígitos).
"""
import calendar
import threading
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import customtkinter as ctk

from ui.theme import C, fuente, TIPOS_VEHICULO, color_tipo, emoji_tipo

# ─── Matplotlib con backend TkAgg ────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib.ticker as mticker
    MPL_OK = True
except Exception:
    MPL_OK = False

# ─── Constantes de localización ──────────────────────────────────────────────
MESES_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]
MESES_CORTO = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
               "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
DIAS_CORTO = ["L", "M", "M", "J", "V", "S", "D"]
DIAS_ES    = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]

_AÑO_ACTUAL      = date.today().year
AÑOS_DISPONIBLES = list(range(_AÑO_ACTUAL - 4, _AÑO_ACTUAL + 1))


# ─── Helpers de rango de fechas ───────────────────────────────────────────────

def _rango_semana(fecha_base: date) -> tuple:
    """Lunes–domingo de la semana que contiene fecha_base."""
    lunes   = fecha_base - timedelta(days=fecha_base.weekday())
    domingo = lunes + timedelta(days=6)
    return lunes.isoformat(), domingo.isoformat()


def _rango_mes(año: int, mes: int) -> tuple:
    """Primer y último día del mes dado."""
    _, ultimo = calendar.monthrange(año, mes)
    return f"{año:04d}-{mes:02d}-01", f"{año:04d}-{mes:02d}-{ultimo:02d}"


def _rango_año(año: int) -> tuple:
    """Primer y último día del año dado."""
    return f"{año:04d}-01-01", f"{año:04d}-12-31"


# ─── Popup: calendario de días ───────────────────────────────────────────────

class _CalendarioPicker(ctk.CTkToplevel):
    """
    Popup calendario para elegir un día específico.
    Deshabilita fechas futuras. Resalta hoy en verde y el día
    seleccionado en azul.
    """

    def __init__(self, parent, initial_date: date, callback,
                 max_date: date = None):
        super().__init__(parent)
        self.title("Seleccionar fecha")
        self.resizable(False, False)
        self.grab_set()
        self.focus_set()
        self.lift()

        self._callback  = callback
        self._max_date  = max_date or date.today()
        self._view_year = initial_date.year
        self._view_month= initial_date.month
        self._selected  = initial_date

        self._build()
        self._render()

        # Centrar sobre el padre
        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0,px)}+{max(0,py)}")

    def _build(self):
        # Navegación de mes
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.pack(fill="x", padx=10, pady=(10, 4))

        self._btn_prev = ctk.CTkButton(
            nav, text="◀", width=32, height=28,
            fg_color=C["bg_medium"], hover_color=C["bg_light"],
            text_color=C["text_2"], font=fuente(11),
            command=self._mes_ant,
        )
        self._btn_prev.pack(side="left")

        self._lbl_mes = ctk.CTkButton(
            nav, text="", width=174, height=28,
            fg_color="transparent", hover_color=C["bg_light"],
            text_color=C["text_1"], font=fuente(13, bold=True),
            anchor="center", corner_radius=6,
            command=lambda: None,   # solo estético
        )
        self._lbl_mes.pack(side="left", expand=True, fill="x", padx=4)

        self._btn_next = ctk.CTkButton(
            nav, text="▶", width=32, height=28,
            fg_color=C["bg_medium"], hover_color=C["bg_light"],
            text_color=C["text_2"], font=fuente(11),
            command=self._mes_sig,
        )
        self._btn_next.pack(side="right")

        # Cabeceras de días
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(padx=10, pady=(2, 0))
        for d in DIAS_CORTO:
            ctk.CTkLabel(
                hdr, text=d, width=36, height=22,
                font=fuente(10, bold=True), text_color=C["text_3"], anchor="center",
            ).pack(side="left", padx=1)

        # Cuadrícula de días
        self._grid = ctk.CTkFrame(self, fg_color="transparent")
        self._grid.pack(padx=10, pady=(2, 12))

    def _render(self):
        for w in self._grid.winfo_children():
            w.destroy()

        self._lbl_mes.configure(
            text=f"{MESES_ES[self._view_month - 1]}  {self._view_year}")

        at_max = (
            self._view_year > self._max_date.year or
            (self._view_year == self._max_date.year and
             self._view_month >= self._max_date.month)
        )
        self._btn_next.configure(state="disabled" if at_max else "normal")

        hoy = date.today()
        for r, semana in enumerate(calendar.monthcalendar(self._view_year, self._view_month)):
            for c, dia in enumerate(semana):
                if dia == 0:
                    ctk.CTkFrame(
                        self._grid, fg_color="transparent", width=36, height=32,
                    ).grid(row=r, column=c, padx=1, pady=1)
                    continue

                fecha  = date(self._view_year, self._view_month, dia)
                future = fecha > self._max_date

                if future:
                    fg, tc, state = C["bg_light"], C["text_3"], "disabled"
                elif fecha == self._selected:
                    fg, tc, state = C["blue"],    "white",       "normal"
                elif fecha == hoy:
                    fg, tc, state = C["bg_light"], C["green"],   "normal"
                else:
                    fg, tc, state = C["bg_medium"], C["text_1"], "normal"

                ctk.CTkButton(
                    self._grid,
                    text=str(dia), width=36, height=32,
                    fg_color=fg, text_color=tc,
                    hover_color=C["blue_h"] if not future else fg,
                    font=fuente(11), state=state, corner_radius=6,
                    command=lambda f=fecha: self._pick(f),
                ).grid(row=r, column=c, padx=1, pady=1)

    def _mes_ant(self):
        if self._view_month == 1:
            self._view_month, self._view_year = 12, self._view_year - 1
        else:
            self._view_month -= 1
        self._render()

    def _mes_sig(self):
        if self._view_month == 12:
            self._view_month, self._view_year = 1, self._view_year + 1
        else:
            self._view_month += 1
        self._render()

    def _pick(self, fecha: date):
        self._callback(fecha)
        self.destroy()


# ─── Popup: selector de mes/año ──────────────────────────────────────────────

class _MesPicker(ctk.CTkToplevel):
    """Popup para elegir mes y año (cuadrícula 4×3 de meses con nav de año)."""

    def __init__(self, parent, initial_year: int, initial_month: int, callback):
        super().__init__(parent)
        self.title("Seleccionar mes")
        self.resizable(False, False)
        self.grab_set()
        self.focus_set()
        self.lift()

        self._callback   = callback
        self._view_year  = initial_year
        self._sel_year   = initial_year
        self._sel_month  = initial_month
        self._max_year   = date.today().year
        self._max_month  = date.today().month

        self._build()

        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0,px)}+{max(0,py)}")

    def _build(self):
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.pack(fill="x", padx=14, pady=(12, 8))

        ctk.CTkButton(
            nav, text="◀", width=32, height=28,
            fg_color=C["bg_medium"], hover_color=C["bg_light"],
            text_color=C["text_2"], command=self._año_ant,
        ).pack(side="left")

        self._lbl_año = ctk.CTkLabel(
            nav, text=str(self._view_year),
            font=fuente(14, bold=True), text_color=C["text_1"],
            width=120, anchor="center",
        )
        self._lbl_año.pack(side="left", expand=True)

        self._btn_año_sig = ctk.CTkButton(
            nav, text="▶", width=32, height=28,
            fg_color=C["bg_medium"], hover_color=C["bg_light"],
            text_color=C["text_2"], command=self._año_sig,
        )
        self._btn_año_sig.pack(side="right")

        self._grid = ctk.CTkFrame(self, fg_color="transparent")
        self._grid.pack(padx=14, pady=(0, 14))

        self._mes_btns: List[ctk.CTkButton] = []
        for i, mes in enumerate(MESES_CORTO):
            btn = ctk.CTkButton(self._grid, text=mes, width=74, height=38, font=fuente(12))
            btn.grid(row=i // 3, column=i % 3, padx=3, pady=3)
            self._mes_btns.append(btn)

        self._actualizar()

    def _actualizar(self):
        self._lbl_año.configure(text=str(self._view_year))
        self._btn_año_sig.configure(
            state="disabled" if self._view_year >= self._max_year else "normal")

        for i, btn in enumerate(self._mes_btns):
            mes    = i + 1
            future = (
                self._view_year > self._max_year or
                (self._view_year == self._max_year and mes > self._max_month)
            )
            sel = (self._view_year == self._sel_year and mes == self._sel_month)

            if future:
                fg, tc, state = C["bg_light"], C["text_3"], "disabled"
            elif sel:
                fg, tc, state = C["blue"],     "white",     "normal"
            else:
                fg, tc, state = C["bg_medium"], C["text_1"], "normal"

            btn.configure(
                fg_color=fg, text_color=tc, state=state,
                hover_color=C["blue_h"] if not future else fg,
                command=lambda m=mes: self._pick(m),
            )

    def _año_ant(self):
        if self._view_year > _AÑO_ACTUAL - 4:
            self._view_year -= 1
            self._actualizar()

    def _año_sig(self):
        if self._view_year < self._max_year:
            self._view_year += 1
            self._actualizar()

    def _pick(self, mes: int):
        self._callback(self._view_year, mes)
        self.destroy()


# ─── Popup: selector de año ──────────────────────────────────────────────────

class _AñoPicker(ctk.CTkToplevel):
    """Popup para elegir año (cuadrícula de años disponibles)."""

    def __init__(self, parent, initial_year: int, callback):
        super().__init__(parent)
        self.title("Seleccionar año")
        self.resizable(False, False)
        self.grab_set()
        self.focus_set()
        self.lift()

        self._callback = callback
        self._sel_year = initial_year

        self._build()

        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0,px)}+{max(0,py)}")

    def _build(self):
        ctk.CTkLabel(
            self, text="Seleccionar año",
            font=fuente(13, bold=True), text_color=C["text_1"],
        ).pack(pady=(14, 8), padx=20)

        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(padx=16, pady=(0, 16))

        for i, año in enumerate(AÑOS_DISPONIBLES):
            sel = (año == self._sel_year)
            ctk.CTkButton(
                grid,
                text=str(año), width=84, height=42,
                fg_color=C["blue"]     if sel else C["bg_medium"],
                text_color="white"     if sel else C["text_1"],
                hover_color=C["blue_h"], font=fuente(13, bold=sel),
                command=lambda y=año: self._pick(y),
            ).grid(row=i // 3, column=i % 3, padx=4, pady=4)

    def _pick(self, año: int):
        self._callback(año)
        self.destroy()


# ─── Panel principal ──────────────────────────────────────────────────────────

class PanelReportes(ctk.CTkFrame):
    """
    Panel de reportes financieros con 4 vistas de período.
    Ahora con:
      • Navegación diaria en la vista 'Hoy'.
      • Selector de fecha/mes/año al clicar la etiqueta central.
      • Historial paginado (10 por página) para todos los períodos.
    """

    _ANCHS_HIST      = [115, 100, 85, 95, 95, 75, 90]
    _HIST_POR_PAGINA = 10

    def __init__(self, parent, config, db, printer, **kwargs):
        super().__init__(parent, fg_color=C["bg_dark"], corner_radius=0, **kwargs)
        self.config  = config
        self.db      = db
        self.printer = printer

        self._request_id = 0
        self._periodo  = "Hoy"
        self._sel_fecha_dia    = date.today()
        self._sel_mes  = date.today().month
        self._sel_año  = date.today().year
        self._sel_fecha_semana = date.today()

        self._hist_pagina = 0
        self._hist_total  = 0

        self._canvas_mpl: Optional[object] = None

        self._build_ui()
        self._actualizar_nav()   # texto inicial de la barra de navegación
        self.cargar_datos()

    # ─── Construcción de la UI ────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header principal ───────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=C["sidebar"], height=56, corner_radius=0)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(
            hdr, text="📊  Reportes Financieros",
            font=fuente(17, bold=True), text_color=C["text_1"],
        ).pack(side="left", padx=24)

        self._btn_excel = ctk.CTkButton(
            hdr, text="📊 Exportar Excel",
            fg_color=C["green"], hover_color=C["green_h"],
            text_color="white", font=fuente(11, bold=True), height=32, width=150,
            command=self._exportar_excel,
        )
        self._btn_excel.pack(side="right", padx=(0, 4))

        self._seg = ctk.CTkSegmentedButton(
            hdr,
            values=["Hoy", "Semana", "Mes", "Año"],
            command=self._on_periodo,
            fg_color=C["bg_dark"],
            selected_color=C["blue"],
            selected_hover_color=C["blue_h"],
            unselected_color=C["bg_medium"],
            unselected_hover_color=C["bg_light"],
            text_color=C["text_1"],
            font=fuente(12), width=300, height=34,
        )
        self._seg.set("Hoy")
        self._seg.pack(side="right", padx=(0, 8))

        # ── Barra de navegación (siempre visible en todos los períodos) ────
        self._frame_nav = ctk.CTkFrame(
            self, fg_color=C["bg_medium"], height=46, corner_radius=0)
        self._frame_nav.pack(fill="x")
        self._frame_nav.pack_propagate(False)

        nav_inner = ctk.CTkFrame(self._frame_nav, fg_color="transparent")
        nav_inner.pack(expand=True)

        self._btn_ant = ctk.CTkButton(
            nav_inner, text="◀", width=34, height=30,
            fg_color=C["bg_dark"], hover_color=C["bg_light"],
            text_color=C["text_2"], font=fuente(12),
            command=self._navegar_anterior,
        )
        self._btn_ant.pack(side="left", padx=4)

        # Botón-etiqueta clicable que abre el selector de fecha/período
        self._lbl_nav = ctk.CTkButton(
            nav_inner, text="",
            width=240, height=30,
            fg_color="transparent", hover_color=C["bg_light"],
            text_color=C["text_1"], font=fuente(14, bold=True),
            anchor="center", corner_radius=8,
            command=self._abrir_selector_fecha,
        )
        self._lbl_nav.pack(side="left", padx=4)

        self._btn_sig = ctk.CTkButton(
            nav_inner, text="▶", width=34, height=30,
            fg_color=C["bg_dark"], hover_color=C["bg_light"],
            text_color=C["text_2"], font=fuente(12),
            command=self._navegar_siguiente,
        )
        self._btn_sig.pack(side="left", padx=4)

        # Icono de ayuda — indica que la fecha es clicable
        ctk.CTkLabel(
            nav_inner, text="📅",
            font=fuente(13), text_color=C["text_3"],
        ).pack(side="left", padx=(2, 0))

        # ── KPI cards ─────────────────────────────────────────────────────
        self._frame_kpis = ctk.CTkFrame(self, fg_color="transparent")
        self._frame_kpis.pack(fill="x", padx=20, pady=(12, 0))

        self._kpi_refs: Dict[str, ctk.CTkLabel] = {}
        _kpis_def = [
            ("ingresos",   "Ingresos del período",  f"{self.config.get_moneda()} 0.00", C["green"]),
            ("vehiculos",  "Vehículos cobrados",     "0",                                C["blue"]),
            ("cancelados", "Canceladas período",     "0",                                C["red"]),
            ("promedio",   "Tiempo promedio",        "—",                                C["purple"]),
        ]
        for key, titulo, val_init, color in _kpis_def:
            card = ctk.CTkFrame(
                self._frame_kpis, fg_color=C["bg_medium"],
                corner_radius=14, border_color=color, border_width=1,
            )
            card.pack(side="left", expand=True, fill="both", padx=5)
            ctk.CTkFrame(card, fg_color=color, height=3, corner_radius=0).pack(fill="x")
            ctk.CTkLabel(card, text=titulo,
                         font=fuente(10), text_color=C["text_3"]).pack(pady=(8, 1))
            lbl = ctk.CTkLabel(card, text=val_init,
                               font=fuente(22, bold=True), text_color=color)
            lbl.pack(pady=(0, 10))
            self._kpi_refs[key] = lbl

        # ── Área central: gráfico (izquierda) + breakdown (derecha) ───────
        centro = ctk.CTkFrame(self, fg_color="transparent")
        centro.pack(fill="both", expand=True, padx=20, pady=10)

        self._frame_chart = ctk.CTkFrame(
            centro, fg_color=C["bg_medium"], corner_radius=14)
        self._frame_chart.pack(side="left", fill="both", expand=True, padx=(0, 8))

        self._lbl_chart_titulo = ctk.CTkLabel(
            self._frame_chart, text="📈  Ingresos",
            font=fuente(13, bold=True), text_color=C["text_1"],
        )
        self._lbl_chart_titulo.pack(anchor="w", padx=16, pady=(12, 0))

        self._frame_chart_inner = ctk.CTkFrame(
            self._frame_chart, fg_color="transparent")
        self._frame_chart_inner.pack(fill="both", expand=True, padx=8, pady=8)

        self._frame_tipo = ctk.CTkFrame(
            centro, fg_color=C["bg_medium"], corner_radius=14, width=270)
        self._frame_tipo.pack(side="right", fill="y")
        self._frame_tipo.pack_propagate(False)

        ctk.CTkLabel(
            self._frame_tipo, text="🚗  Por tipo de vehículo",
            font=fuente(13, bold=True), text_color=C["text_1"],
        ).pack(anchor="w", padx=16, pady=(12, 6))

        self._frame_tipo_rows = ctk.CTkScrollableFrame(
            self._frame_tipo, fg_color="transparent",
            scrollbar_fg_color=C["bg_light"],
        )
        self._frame_tipo_rows.pack(fill="both", expand=True, padx=6, pady=(0, 8))

        # ── Historial paginado ─────────────────────────────────────────────
        hist_card = ctk.CTkFrame(self, fg_color=C["bg_medium"], corner_radius=14)
        hist_card.pack(fill="x", padx=20, pady=(0, 14))
        hist_card.configure(height=252)
        hist_card.pack_propagate(False)

        # Cabecera del historial
        hdr_hist_row = ctk.CTkFrame(hist_card, fg_color="transparent")
        hdr_hist_row.pack(fill="x", padx=16, pady=(10, 0))

        self._lbl_hist_titulo = ctk.CTkLabel(
            hdr_hist_row, text="🕐  Transacciones del período",
            font=fuente(13, bold=True), text_color=C["text_1"],
        )
        self._lbl_hist_titulo.pack(side="left")

        leyenda = ctk.CTkFrame(hdr_hist_row, fg_color="transparent")
        leyenda.pack(side="right")
        for txt, color in [("● Cobrado", C["green"]), ("● Cancelado", C["red"])]:
            ctk.CTkLabel(
                leyenda, text=txt, font=fuente(10), text_color=color,
            ).pack(side="left", padx=6)

        # Columnas de la cabecera
        cols_hist = ["Ticket", "Tipo", "Placa", "Entrada", "Salida", "Tiempo", "Monto"]
        hdr_hist = ctk.CTkFrame(
            hist_card, fg_color=C["bg_dark"], height=28, corner_radius=0)
        hdr_hist.pack(fill="x", padx=10, pady=(6, 0))
        hdr_hist.pack_propagate(False)
        for i, (col, w) in enumerate(zip(cols_hist, self._ANCHS_HIST)):
            ctk.CTkLabel(
                hdr_hist, text=col,
                font=fuente(10, bold=True), text_color=C["text_3"],
                width=w, anchor="w",
            ).pack(side="left", padx=(10 if i == 0 else 2, 2))

        # Área scrollable de filas
        self._scroll_hist = ctk.CTkScrollableFrame(
            hist_card, fg_color="transparent",
            scrollbar_fg_color=C["bg_light"], corner_radius=0,
        )
        self._scroll_hist.pack(fill="both", expand=True, padx=10)

        # ── Controles de paginación ────────────────────────────────────────
        pag_bar = ctk.CTkFrame(hist_card, fg_color="transparent", height=34)
        pag_bar.pack(fill="x", padx=10, pady=(2, 4))
        pag_bar.pack_propagate(False)

        self._btn_hist_prev = ctk.CTkButton(
            pag_bar, text="◀ Anterior", width=95, height=26,
            fg_color=C["bg_dark"], hover_color=C["bg_light"],
            text_color=C["text_2"], font=fuente(10),
            command=lambda: self._cambiar_pagina_hist(-1),
        )
        self._btn_hist_prev.pack(side="left", padx=(0, 6))

        self._lbl_hist_pag = ctk.CTkLabel(
            pag_bar, text="",
            font=fuente(10), text_color=C["text_3"], anchor="center",
        )
        self._lbl_hist_pag.pack(side="left", expand=True)

        self._btn_hist_next = ctk.CTkButton(
            pag_bar, text="Siguiente ▶", width=95, height=26,
            fg_color=C["bg_dark"], hover_color=C["bg_light"],
            text_color=C["text_2"], font=fuente(10),
            command=lambda: self._cambiar_pagina_hist(1),
        )
        self._btn_hist_next.pack(side="right", padx=(6, 0))

    # ─── Control de período ───────────────────────────────────────────────────

    def _on_periodo(self, valor: str):
        self._periodo = valor
        self._hist_pagina = 0
        self._actualizar_nav()
        self.cargar_datos()

    def _actualizar_nav(self):
        hoy = date.today()

        if self._periodo == "Hoy":
            d       = self._sel_fecha_dia
            dia_txt = DIAS_ES[d.weekday()]
            self._lbl_nav.configure(
                text=f"{dia_txt}  {d.day:02d} {MESES_CORTO[d.month - 1]}  {d.year}"
            )
            en_limite = (d >= hoy)

        elif self._periodo == "Semana":
            lunes   = self._sel_fecha_semana - timedelta(days=self._sel_fecha_semana.weekday())
            domingo = lunes + timedelta(days=6)
            self._lbl_nav.configure(
                text=f"{lunes.strftime('%d/%m')} — {domingo.strftime('%d/%m/%Y')}"
            )
            lunes_actual = hoy - timedelta(days=hoy.weekday())
            en_limite = (lunes >= lunes_actual)

        elif self._periodo == "Mes":
            self._lbl_nav.configure(
                text=f"{MESES_ES[self._sel_mes - 1]}  {self._sel_año}")
            en_limite = (
                self._sel_año > hoy.year or
                (self._sel_año == hoy.year and self._sel_mes >= hoy.month)
            )

        else:  # Año
            self._lbl_nav.configure(text=str(self._sel_año))
            en_limite = (self._sel_año >= hoy.year)

        self._btn_sig.configure(state="disabled" if en_limite else "normal")

    def _navegar_anterior(self):
        if self._periodo == "Hoy":
            self._sel_fecha_dia -= timedelta(days=1)
        elif self._periodo == "Semana":
            self._sel_fecha_semana -= timedelta(days=7)
        elif self._periodo == "Mes":
            if self._sel_mes == 1:
                self._sel_mes, self._sel_año = 12, self._sel_año - 1
            else:
                self._sel_mes -= 1
        else:
            self._sel_año -= 1
        self._hist_pagina = 0
        self._actualizar_nav()
        self.cargar_datos()

    def _navegar_siguiente(self):
        if self._periodo == "Hoy":
            self._sel_fecha_dia += timedelta(days=1)
        elif self._periodo == "Semana":
            self._sel_fecha_semana += timedelta(days=7)
        elif self._periodo == "Mes":
            if self._sel_mes == 12:
                self._sel_mes, self._sel_año = 1, self._sel_año + 1
            else:
                self._sel_mes += 1
        else:
            self._sel_año += 1
        self._hist_pagina = 0
        self._actualizar_nav()
        self.cargar_datos()

    # ─── Selectores de fecha (popups) ─────────────────────────────────────────

    def _abrir_selector_fecha(self):
        """Abre el popup adecuado según el período activo."""
        if self._periodo == "Hoy":
            _CalendarioPicker(
                self, self._sel_fecha_dia,
                callback=self._on_fecha_dia,
                max_date=date.today(),
            )
        elif self._periodo == "Semana":
            _CalendarioPicker(
                self, self._sel_fecha_semana,
                callback=self._on_fecha_semana,
                max_date=date.today(),
            )
        elif self._periodo == "Mes":
            _MesPicker(
                self, self._sel_año, self._sel_mes,
                callback=self._on_mes,
            )
        else:
            _AñoPicker(
                self, self._sel_año,
                callback=self._on_año,
            )

    def _on_fecha_dia(self, fecha: date):
        self._sel_fecha_dia = fecha
        self._hist_pagina = 0
        self._actualizar_nav()
        self.cargar_datos()

    def _on_fecha_semana(self, fecha: date):
        self._sel_fecha_semana = fecha
        self._hist_pagina = 0
        self._actualizar_nav()
        self.cargar_datos()

    def _on_mes(self, año: int, mes: int):
        self._sel_año, self._sel_mes = año, mes
        self._hist_pagina = 0
        self._actualizar_nav()
        self.cargar_datos()

    def _on_año(self, año: int):
        self._sel_año = año
        self._hist_pagina = 0
        self._actualizar_nav()
        self.cargar_datos()

    # ─── Rango de fechas ──────────────────────────────────────────────────────

    def _get_rango(self) -> tuple:
        if self._periodo == "Hoy":
            f = self._sel_fecha_dia.isoformat()
            return f, f
        elif self._periodo == "Semana":
            return _rango_semana(self._sel_fecha_semana)
        elif self._periodo == "Mes":
            return _rango_mes(self._sel_año, self._sel_mes)
        else:
            return _rango_año(self._sel_año)

    # ─── Carga de datos ───────────────────────────────────────────────────────

    def cargar_datos(self):
        """
        Recarga todo el panel.
        Corre en hilo daemon; actualiza la UI en el hilo principal.
        """
        self._request_id += 1
        rid = self._request_id

        fi, ff  = self._get_rango()
        periodo = self._periodo
        moneda  = self.config.get_moneda()
        sel_año = self._sel_año
        ppag    = self._HIST_POR_PAGINA
        pagina  = self._hist_pagina

        def _worker():
            try:
                resumen    = self.db.get_resumen_rango(fi, ff)
                tipos      = self.db.get_por_tipo_rango(fi, ff)
                hist_total = self.db.get_historial_rango_count(fi, ff)
                historial  = self.db.get_historial_rango(
                    fi, ff, limit=ppag, offset=pagina * ppag)

                if periodo == "Hoy":
                    chart_data = self.db.get_ingresos_por_hora(fi)
                    chart_tipo = "hora"
                elif periodo in ("Semana", "Mes"):
                    chart_data = self.db.get_ingresos_por_dia(fi, ff)
                    chart_tipo = "dia"
                else:
                    chart_data = self.db.get_ingresos_por_mes_en_año(sel_año)
                    chart_tipo = "mes"

                def _update():
                    if rid != self._request_id:
                        return
                    self._actualizar_ui(
                        resumen, tipos, historial, hist_total,
                        chart_data, chart_tipo, moneda, fi, ff,
                    )

                self.after(0, _update)
            except Exception as e:
                self.after(0, lambda: self._kpi_refs["ingresos"].configure(
                    text=f"⚠ Error: {e}"
                ))

        threading.Thread(target=_worker, daemon=True).start()

    def _actualizar_ui(self, resumen: Dict, tipos: List[Dict],
                        historial: List[Dict], hist_total: int,
                        chart_data: List[Dict], chart_tipo: str,
                        moneda: str, fi: str, ff: str):
        if not self.winfo_exists():
            return

        # ── KPIs ──────────────────────────────────────────────────────────
        ing        = float(resumen.get("ingresos",    0))
        cobrados   = int(resumen.get("cobrados",      0))
        cancelados = int(resumen.get("cancelados",    0))
        prom       = int(resumen.get("prom_minutos",  0))

        self._kpi_refs["ingresos"].configure(text=f"{moneda} {ing:.2f}")
        self._kpi_refs["vehiculos"].configure(text=str(cobrados))
        self._kpi_refs["cancelados"].configure(text=str(cancelados))

        if prom >= 60:
            prom_txt = f"{prom // 60}h {prom % 60:02d}m"
        elif prom > 0:
            prom_txt = f"{prom} min"
        else:
            prom_txt = "—"
        self._kpi_refs["promedio"].configure(text=prom_txt)

        # ── Título historial (dinámico según período) ──────────────────────
        _titulos_hist = {
            "Hoy":    f"🕐  Transacciones del día — "
                      f"{self._sel_fecha_dia.strftime('%d/%m/%Y')}",
            "Semana": "🕐  Transacciones de la semana",
            "Mes":    f"🕐  Transacciones del mes — "
                      f"{MESES_ES[self._sel_mes - 1]} {self._sel_año}",
            "Año":    f"🕐  Transacciones del año {self._sel_año}",
        }
        self._lbl_hist_titulo.configure(
            text=_titulos_hist.get(self._periodo, "🕐  Transacciones del período"))

        # ── Gráfico, breakdown, historial y paginación ────────────────────
        self._hist_total = hist_total
        self._lbl_chart_titulo.configure(text=self._titulo_grafico())
        self._renderizar_grafico(chart_data, chart_tipo, moneda, fi, ff)
        self._renderizar_breakdown(tipos, moneda)
        self._renderizar_historial(historial, moneda)
        self._actualizar_paginacion_hist()

    def _titulo_grafico(self) -> str:
        if self._periodo == "Hoy":
            return f"📈  Ingresos por hora — {self._sel_fecha_dia.strftime('%d/%m/%Y')}"
        elif self._periodo == "Semana":
            lunes   = self._sel_fecha_semana - timedelta(days=self._sel_fecha_semana.weekday())
            domingo = lunes + timedelta(days=6)
            return f"📈  Ingresos — semana ({lunes.strftime('%d/%m')} al {domingo.strftime('%d/%m')})"
        elif self._periodo == "Mes":
            return f"📈  Ingresos — {MESES_ES[self._sel_mes - 1]} {self._sel_año}"
        else:
            return f"📈  Ingresos mensuales — {self._sel_año}"

    # ─── Paginación del historial ─────────────────────────────────────────────

    def _actualizar_paginacion_hist(self):
        ppag       = self._HIST_POR_PAGINA
        total_pags = max(1, (self._hist_total + ppag - 1) // ppag)
        pag_actual = self._hist_pagina + 1

        self._lbl_hist_pag.configure(
            text=f"Página {pag_actual} de {total_pags}  ·  {self._hist_total} transacciones"
        )
        self._btn_hist_prev.configure(
            state="disabled" if self._hist_pagina == 0 else "normal")
        self._btn_hist_next.configure(
            state="disabled" if pag_actual >= total_pags else "normal")

    def _cambiar_pagina_hist(self, delta: int):
        ppag       = self._HIST_POR_PAGINA
        total_pags = max(1, (self._hist_total + ppag - 1) // ppag)
        nueva      = self._hist_pagina + delta
        if 0 <= nueva < total_pags:
            self._hist_pagina = nueva
            self._cargar_pagina_historial()

    def _cargar_pagina_historial(self):
        """Carga solo la página del historial sin recargar todo el panel."""
        self._request_id += 1
        rid    = self._request_id
        fi, ff = self._get_rango()
        moneda = self.config.get_moneda()
        ppag   = self._HIST_POR_PAGINA
        offset = self._hist_pagina * ppag

        def _worker():
            try:
                historial = self.db.get_historial_rango(fi, ff, limit=ppag, offset=offset)

                def _update():
                    if rid != self._request_id:
                        return
                    self._renderizar_historial(historial, moneda)
                    self._actualizar_paginacion_hist()

                self.after(0, _update)
            except Exception:
                pass   # fallo silencioso en paginación

        threading.Thread(target=_worker, daemon=True).start()

    # ─── Gráfico de barras ────────────────────────────────────────────────────

    def _renderizar_grafico(self, datos: List[Dict], chart_tipo: str,
                             moneda: str, fi: str, ff: str):
        for w in self._frame_chart_inner.winfo_children():
            w.destroy()
        self._canvas_mpl = None

        if not MPL_OK:
            ctk.CTkLabel(
                self._frame_chart_inner,
                text="⚠  matplotlib no disponible\npip install matplotlib",
                font=fuente(12), text_color=C["yellow"],
            ).pack(expand=True)
            return

        etiquetas, valores = self._preparar_datos_grafico(datos, chart_tipo, fi, ff)

        if not datos or sum(valores) == 0:
            self._mostrar_grafico_vacio()
            return

        fig = Figure(figsize=(5, 2.7), dpi=92)
        fig.patch.set_facecolor("#1e293b")

        ax = fig.add_subplot(111)
        ax.set_facecolor("#0f172a")

        n = len(etiquetas)
        x = list(range(n))
        ancho_barra = max(0.35, min(0.65, 8 / n)) if n > 0 else 0.6

        bars = ax.bar(
            x, valores,
            color="#3b82f6", width=ancho_barra,
            edgecolor="#1d4ed8", linewidth=0.4, zorder=3,
        )

        max_val = max(valores) if valores else 1
        for bar, val in zip(bars, valores):
            if val > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max_val * 0.025,
                    f"{moneda}{val:.0f}",
                    ha="center", va="bottom",
                    color="#e2e8f0", fontsize=7, fontweight="bold",
                )

        ax.set_xticks(x)
        rotacion = 45 if n > 14 else 0
        ax.set_xticklabels(
            etiquetas, fontsize=7, color="#94a3b8", rotation=rotacion,
            ha="right" if rotacion else "center",
        )
        ax.tick_params(axis="y", colors="#64748b", labelsize=7)
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda v, _: f"{moneda}{v:.0f}")
        )
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["bottom"].set_color("#2d3f55")
        ax.spines["left"].set_color("#2d3f55")
        ax.yaxis.grid(True, color="#1e3a5f", linestyle="--",
                      linewidth=0.5, zorder=0)
        ax.set_axisbelow(True)
        fig.tight_layout(pad=1.2)

        canvas = FigureCanvasTkAgg(fig, master=self._frame_chart_inner)
        canvas.draw()
        widget = canvas.get_tk_widget()
        widget.configure(bg="#1e293b", highlightthickness=0)
        widget.pack(fill="both", expand=True)
        self._canvas_mpl = canvas

    def _preparar_datos_grafico(self, datos: List[Dict], chart_tipo: str,
                                  fi: str, ff: str):
        if chart_tipo == "hora":
            hora_map  = {d["hora"]: float(d["ingresos"]) for d in datos}
            etiquetas = [f"{h:02d}" for h in range(24)]
            valores   = [hora_map.get(f"{h:02d}", 0.0) for h in range(24)]

        elif chart_tipo == "dia":
            fecha_map = {d["fecha"]: float(d["ingresos"]) for d in datos}
            fi_d  = date.fromisoformat(fi)
            ff_d  = date.fromisoformat(ff)
            dias  = []
            cur   = fi_d
            while cur <= ff_d:
                dias.append(cur)
                cur += timedelta(days=1)
            etiquetas = [d.strftime("%d/%m") for d in dias]
            valores   = [fecha_map.get(d.isoformat(), 0.0) for d in dias]

        else:  # mes
            mes_map   = {d["mes"]: float(d["ingresos"]) for d in datos}
            etiquetas = MESES_CORTO
            valores   = [mes_map.get(f"{m:02d}", 0.0) for m in range(1, 13)]

        return etiquetas, valores

    def _mostrar_grafico_vacio(self):
        ctk.CTkLabel(
            self._frame_chart_inner,
            text="📭\n\nSin ingresos registrados\npara este período",
            font=fuente(13), text_color=C["text_3"],
            justify="center",
        ).pack(expand=True)

    # ─── Breakdown por tipo de vehículo ───────────────────────────────────────

    def _renderizar_breakdown(self, tipos: List[Dict], moneda: str):
        for w in self._frame_tipo_rows.winfo_children():
            w.destroy()

        if not tipos:
            ctk.CTkLabel(
                self._frame_tipo_rows,
                text="📭\n\nSin datos\npara el período",
                font=fuente(12), text_color=C["text_3"],
                justify="center",
            ).pack(expand=True, pady=30)
            return

        total_ing = sum(float(t.get("ingresos", 0)) for t in tipos)
        total_veh = sum(int(t.get("cantidad",   0)) for t in tipos)

        for row in tipos:
            nombre   = row.get("tipo_vehiculo", "?")
            cantidad = int(row.get("cantidad",   0))
            ingresos = float(row.get("ingresos", 0))
            color    = color_tipo(nombre)
            emj      = emoji_tipo(nombre)
            pct_ing  = (ingresos / total_ing * 100) if total_ing > 0 else 0
            pct_veh  = (cantidad / total_veh)        if total_veh > 0 else 0

            card = ctk.CTkFrame(
                self._frame_tipo_rows, fg_color=C["bg_dark"], corner_radius=10)
            card.pack(fill="x", pady=4)

            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(8, 2))
            ctk.CTkLabel(
                top, text=f"{emj}  {nombre}",
                font=fuente(12, bold=True), text_color=color, anchor="w",
            ).pack(side="left")
            ctk.CTkLabel(
                top, text=f"{cantidad} veh.",
                font=fuente(10), text_color=C["text_3"],
            ).pack(side="right")

            track = ctk.CTkFrame(card, fg_color=C["bg_medium"],
                                 height=5, corner_radius=3)
            track.pack(fill="x", padx=12, pady=(2, 4))
            track.pack_propagate(False)
            ctk.CTkFrame(
                track, fg_color=color, height=5,
                width=max(4, int(pct_veh * 220)),
                corner_radius=3,
            ).place(x=0, y=0)

            ctk.CTkLabel(
                card, text=f"{moneda} {ingresos:.2f}   ({pct_ing:.0f}%)",
                font=fuente(11, bold=True), text_color=C["text_2"], anchor="w",
            ).pack(padx=12, pady=(0, 8))

        ctk.CTkFrame(self._frame_tipo_rows, fg_color=C["border"], height=1).pack(
            fill="x", pady=4)
        total_row = ctk.CTkFrame(self._frame_tipo_rows, fg_color="transparent")
        total_row.pack(fill="x", padx=8)
        ctk.CTkLabel(
            total_row, text="Total período:",
            font=fuente(11), text_color=C["text_3"], anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            total_row, text=f"{moneda} {total_ing:.2f}",
            font=fuente(12, bold=True), text_color=C["green"], anchor="e",
        ).pack(side="right")

    # ─── Historial paginado ───────────────────────────────────────────────────

    def _renderizar_historial(self, historial: List[Dict], moneda: str):
        """
        Renderiza las transacciones de la página actual.
        Verde = cobrado / fondo rojizo + texto rojo = cancelado.
        """
        for w in self._scroll_hist.winfo_children():
            w.destroy()

        if not historial:
            ctk.CTkLabel(
                self._scroll_hist,
                text="Sin transacciones en este período",
                font=fuente(12), text_color=C["text_3"],
            ).pack(pady=10)
            return

        anchs = self._ANCHS_HIST

        for idx, ses in enumerate(historial):
            estado    = ses.get("estado", "cobrado")
            cancelado = (estado == "cancelado")

            bg = "#1f0a0a" if cancelado else (C["bg_medium"] if idx % 2 == 0 else C["bg_dark"])

            fila = ctk.CTkFrame(
                self._scroll_hist, fg_color=bg, height=32, corner_radius=6)
            fila.pack(fill="x", pady=1)
            fila.pack_propagate(False)

            # Ticket
            ctk.CTkLabel(
                fila, text=ses.get("ticket_numero", ""),
                font=fuente(10), text_color=C["text_3"],
                width=anchs[0], anchor="w",
            ).pack(side="left", padx=(8, 2))

            # Tipo — badge con borde del color del tipo
            tipo  = ses.get("tipo_vehiculo", "?")
            cv    = color_tipo(tipo)
            badge = ctk.CTkFrame(
                fila, fg_color=C["bg_dark"],
                corner_radius=4, border_color=cv, border_width=1,
                width=anchs[1] - 8, height=20,
            )
            badge.pack(side="left", padx=2)
            badge.pack_propagate(False)
            ctk.CTkLabel(
                badge, text=tipo[:8],
                font=fuente(9, bold=True), text_color=cv,
            ).place(relx=0.5, rely=0.5, anchor="center")

            # Placa
            ctk.CTkLabel(
                fila, text=ses.get("placa", ""),
                font=fuente(10, bold=True), text_color=C["text_1"],
                width=anchs[2],
            ).pack(side="left", padx=2)

            # Hora de entrada
            try:
                ent_str = datetime.strptime(
                    ses["hora_entrada"], "%Y-%m-%d %H:%M:%S").strftime("%H:%M")
            except Exception:
                ent_str = "?"
            ctk.CTkLabel(
                fila, text=ent_str,
                font=fuente(10), text_color=C["text_2"],
                width=anchs[3],
            ).pack(side="left", padx=2)

            # Hora de salida
            sal_str = "—"
            if ses.get("hora_salida"):
                try:
                    sal_str = datetime.strptime(
                        ses["hora_salida"], "%Y-%m-%d %H:%M:%S").strftime("%H:%M")
                except Exception:
                    sal_str = "?"
            ctk.CTkLabel(
                fila, text=sal_str,
                font=fuente(10), text_color=C["text_2"],
                width=anchs[4],
            ).pack(side="left", padx=2)

            # Tiempo total
            min_t = ses.get("minutos_total", 0) or 0
            t_str = (f"{min_t // 60}h {min_t % 60:02d}m" if min_t else "—")
            ctk.CTkLabel(
                fila, text=t_str,
                font=fuente(10), text_color=C["text_3"],
                width=anchs[5],
            ).pack(side="left", padx=2)

            # Monto
            monto = ses.get("monto")
            if cancelado:
                m_txt, m_color = "✕ Cancelado", C["red"]
            elif monto is not None:
                m_txt   = f"{moneda} {float(monto):.2f}"
                m_color = C["green"]
            else:
                m_txt, m_color = "—", C["text_3"]

            ctk.CTkLabel(
                fila, text=m_txt,
                font=fuente(10, bold=True), text_color=m_color,
                width=anchs[6],
            ).pack(side="left", padx=2)

    # ─── Exportación a Excel ──────────────────────────────────────────────────

    def _exportar_excel(self):
        from tkinter import filedialog, messagebox
        from excel_exporter import ExcelExporter

        nombre_sugerido = (
            f"ParkingPro_Reporte_{date.today().strftime('%Y%m%d')}.xlsx"
        )
        ruta = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx"), ("Todos", "*.*")],
            title="Exportar reporte a Excel",
            initialfile=nombre_sugerido,
        )
        if not ruta:
            return

        self._btn_excel.configure(state="disabled", text="⏳ Exportando...")

        def _worker():
            try:
                ExcelExporter(self.db, self.config).exportar(ruta)
                self.after(0, _on_ok)
            except Exception as e:
                self.after(0, lambda: _on_err(str(e)))

        def _on_ok():
            if self.winfo_exists():
                self._btn_excel.configure(state="normal", text="📊 Exportar Excel")
                messagebox.showinfo(
                    "✅ Exportado",
                    f"Reporte guardado correctamente en:\n\n{ruta}",
                )

        def _on_err(msg: str):
            if self.winfo_exists():
                self._btn_excel.configure(state="normal", text="📊 Exportar Excel")
                messagebox.showerror(
                    "Error al exportar",
                    f"No se pudo generar el archivo:\n\n{msg}",
                )

        threading.Thread(target=_worker, daemon=True).start()

    # ─── Alias externo ────────────────────────────────────────────────────────

    def _cambiar_periodo(self, valor: str):
        """Alias de _on_periodo para compatibilidad con código externo."""
        self._on_periodo(valor)