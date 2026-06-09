"""
ParkingPro - Panel de Reportes Financieros

Vistas de períodos:
  • Hoy     — ingresos por hora del día actual.
  • Semana  — ingresos de los últimos 7 días (barras diarias).
  • Mes     — ingresos del mes/año seleccionado (barras diarias).
  • Año     — ingresos por mes del año seleccionado (12 barras).

Características:
  • Navegación ◀ / ▶ para mes y año.
  • 4 KPIs: Ingresos, Vehículos, Activos ahora, Tiempo promedio.
  • Gráfico de barras matplotlib (fondo oscuro, profesional).
  • Breakdown por tipo de vehículo (siempre del período activo).
  • Historial de las últimas 10 transacciones del período (cobradas y canceladas).
  • Exportación a Excel (.xlsx) con 5 hojas y gráficos.
  • Estado vacío amigable cuando no hay datos.
  • Carga en hilo daemon para no congelar la UI.

Correcciones:
  • Bug badge color: cv+"33" generaba hex de 8 dígitos no válido para Tkinter;
    reemplazado por bg oscuro + borde del color del tipo.
  • Historial limitado a 10 items (últimas transacciones del período).
  • Breakdown y historial son period-aware.
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

_AÑO_ACTUAL       = date.today().year
AÑOS_DISPONIBLES  = list(range(_AÑO_ACTUAL - 4, _AÑO_ACTUAL + 1))


# ─── Helpers de rango de fechas ───────────────────────────────────────────────

def _rango_semana(fecha_base: date) -> tuple:
    """
    Devuelve el rango lunes-domingo de la semana
    correspondiente a fecha_base.
    """
    lunes = fecha_base - timedelta(days=fecha_base.weekday())
    domingo = lunes + timedelta(days=6)

    return (
        lunes.isoformat(),
        domingo.isoformat()
    )


def _rango_mes(año: int, mes: int) -> tuple:
    """Primer y último día del mes dado."""
    _, ultimo = calendar.monthrange(año, mes)
    return f"{año:04d}-{mes:02d}-01", f"{año:04d}-{mes:02d}-{ultimo:02d}"


def _rango_año(año: int) -> tuple:
    """Primer y último día del año dado."""
    return f"{año:04d}-01-01", f"{año:04d}-12-31"


class PanelReportes(ctk.CTkFrame):
    """
    Panel de reportes financieros con 4 vistas de período.
    La carga de datos corre en hilo daemon; la UI se actualiza en el hilo principal.
    """

    # Anchos de columna de la tabla de historial
    _ANCHS_HIST = [115, 100, 85, 95, 95, 75, 90]

    def __init__(self, parent, config, db, printer, **kwargs):
        super().__init__(parent, fg_color=C["bg_dark"], corner_radius=0, **kwargs)
        self.config  = config
        self.db      = db
        self.printer = printer

        self._request_id = 0
        self._periodo  = "Hoy"
        self._sel_mes  = date.today().month
        self._sel_año  = date.today().year
        self._sel_fecha_semana = date.today()

        self._canvas_mpl: Optional[object] = None

        self._build_ui()
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

        # Botón de exportación a Excel
        self._btn_excel = ctk.CTkButton(
            hdr, text="📊 Exportar Excel",
            fg_color=C["green"], hover_color=C["green_h"],
            text_color="white", font=fuente(11, bold=True), height=32, width=150,
            command=self._exportar_excel,
        )
        self._btn_excel.pack(side="right", padx=(0, 4))

        # Selector de período (tabs)
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

        # ── Barra de navegación de fecha (Mes / Año) ───────────────────────
        self._frame_nav = ctk.CTkFrame(
            self, fg_color=C["bg_medium"], height=44, corner_radius=0)
        self._frame_nav.pack_propagate(False)

        nav_inner = ctk.CTkFrame(self._frame_nav, fg_color="transparent")
        nav_inner.pack(expand=True)

        self._btn_ant = ctk.CTkButton(
            nav_inner, text="◀", width=34, height=30,
            fg_color=C["bg_dark"], hover_color=C["bg_light"],
            text_color=C["text_2"], command=self._navegar_anterior,
        )
        self._btn_ant.pack(side="left", padx=4)

        self._lbl_nav = ctk.CTkLabel(
            nav_inner, text="",
            font=fuente(14, bold=True), text_color=C["text_1"],
            width=200, anchor="center",
        )
        self._lbl_nav.pack(side="left", padx=8)

        self._btn_sig = ctk.CTkButton(
            nav_inner, text="▶", width=34, height=30,
            fg_color=C["bg_dark"], hover_color=C["bg_light"],
            text_color=C["text_2"], command=self._navegar_siguiente,
        )
        self._btn_sig.pack(side="left", padx=4)

        # ── KPI cards ─────────────────────────────────────────────────────
        self._frame_kpis = ctk.CTkFrame(self, fg_color="transparent")
        self._frame_kpis.pack(fill="x", padx=20, pady=(12, 0))

        self._kpi_refs: Dict[str, ctk.CTkLabel] = {}
        _kpis_def = [
            ("ingresos",    "Ingresos del período",   f"{self.config.get_moneda()} 0.00", C["green"]),
            ("vehiculos",   "Vehículos cobrados",      "0",                                C["blue"]),
            ("cancelados",  "Canceladas período",      "0",                                C["red"]),
            ("promedio",    "Tiempo promedio",          "—",                                C["purple"]),
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

        # ── Historial de transacciones (últimas 10 del período) ────────────
        hist_card = ctk.CTkFrame(self, fg_color=C["bg_medium"], corner_radius=14)
        hist_card.pack(fill="x", padx=20, pady=(0, 14))
        hist_card.configure(height=195)
        hist_card.pack_propagate(False)

        # Cabecera del historial
        hdr_hist_row = ctk.CTkFrame(hist_card, fg_color="transparent")
        hdr_hist_row.pack(fill="x", padx=16, pady=(10, 0))

        ctk.CTkLabel(
            hdr_hist_row, text="🕐  Últimas 10 transacciones del período",
            font=fuente(13, bold=True), text_color=C["text_1"],
        ).pack(side="left")

        # Leyenda de colores: verde = cobrado, rojo = cancelado
        leyenda = ctk.CTkFrame(hdr_hist_row, fg_color="transparent")
        leyenda.pack(side="right")
        for txt, color in [("● Cobrado", C["green"]), ("● Cancelado", C["red"])]:
            ctk.CTkLabel(
                leyenda, text=txt, font=fuente(10),
                text_color=color,
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

    # ─── Control de período ───────────────────────────────────────────────────

    def _on_periodo(self, valor: str):
        self._periodo = valor
        if valor in ("Semana","Mes", "Año"):
            if not self._frame_nav.winfo_ismapped():
                self._frame_nav.pack(fill="x", before=self._frame_kpis)
            self._actualizar_nav()
        else:
            self._frame_nav.pack_forget()
        self.cargar_datos()

    def _actualizar_nav(self):
        hoy = date.today()
        if self._periodo == "Semana":
            # Calcular el lunes y domingo de la semana seleccionada
            lunes = self._sel_fecha_semana - timedelta(days=self._sel_fecha_semana.weekday())
            domingo = lunes + timedelta(days=6)
            
            # Mostrar el rango de la semana (Ej: 08/06 - 14/06) entre las flechas
            self._lbl_nav.configure(text=f"{lunes.strftime('%d/%m')} - {domingo.strftime('%d/%m')}")
            
            # Control de límites: Bloquear flecha derecha si es la semana actual
            lunes_actual = hoy - timedelta(days=hoy.weekday())
            en_limite = (lunes >= lunes_actual)
        elif self._periodo == "Mes":
            self._lbl_nav.configure(
                text=f"{MESES_ES[self._sel_mes - 1]}  {self._sel_año}")
            en_limite = (self._sel_año > hoy.year or
                         (self._sel_año == hoy.year and self._sel_mes >= hoy.month))
        else:
            self._lbl_nav.configure(text=str(self._sel_año))
            en_limite = (self._sel_año >= hoy.year)
        self._btn_sig.configure(state="disabled" if en_limite else "normal")

    def _navegar_anterior(self):
        if self._periodo == "Semana":
            self._sel_fecha_semana -= timedelta(days=7)
        elif self._periodo == "Mes":
            if self._sel_mes == 1:
                self._sel_mes = 12
                self._sel_año -= 1
            else:
                self._sel_mes -= 1
        else:
            self._sel_año -= 1
        self._actualizar_nav()
        self.cargar_datos()

    def _navegar_siguiente(self):
        if self._periodo == "Semana":
            self._sel_fecha_semana += timedelta(days=7)
        elif self._periodo == "Mes":
            if self._sel_mes == 12:
                self._sel_mes = 1
                self._sel_año += 1
            else:
                self._sel_mes += 1
        else:
            self._sel_año += 1
        self._actualizar_nav()
        self.cargar_datos()

    # ─── Rango de fechas ──────────────────────────────────────────────────────

    def _get_rango(self) -> tuple:

        hoy = date.today().isoformat()

        if self._periodo == "Hoy":
            return hoy, hoy

        elif self._periodo == "Semana":
            return _rango_semana(self._sel_fecha_semana)

        elif self._periodo == "Mes":
            return _rango_mes(self._sel_año, self._sel_mes)

        else:
            return _rango_año(self._sel_año)

    # ─── Carga de datos ───────────────────────────────────────────────────────
    
    def cargar_datos(self):
        """
        Punto de entrada para actualizar todo el panel.
        Lanza un hilo daemon que consulta la BD; cuando termina,
        programa la actualización de la UI en el hilo principal.
        """
        self._request_id += 1
        request_id = self._request_id

        fi, ff  = self._get_rango()
        periodo = self._periodo
        moneda  = self.config.get_moneda()
        sel_año = self._sel_año

        def _worker():
            try:
                resumen  = self.db.get_resumen_rango(fi, ff)
                tipos    = self.db.get_por_tipo_rango(fi, ff)
                # Últimas 10 transacciones finalizadas del período
                historial = self.db.get_historial_rango(fi, ff, limit=10)

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
                    if request_id != self._request_id:
                        return

                    self._actualizar_ui(
                        resumen,
                        tipos,
                        historial,
                        chart_data,
                        chart_tipo,
                        moneda,
                        fi,
                        ff,
                    )

                self.after(0, _update)
            except Exception as e:
                self.after(0, lambda: self._kpi_refs["ingresos"].configure(
                    text=f"⚠ Error: {e}"
                ))

        threading.Thread(target=_worker, daemon=True).start()

    def _actualizar_ui(self, resumen: Dict, tipos: List[Dict],
                        historial: List[Dict], chart_data: List[Dict],
                        chart_tipo: str, moneda: str,
                        fi: str, ff: str):
        if not self.winfo_exists():
            return

        # ── KPIs ──────────────────────────────────────────────────────────
        # Usamos "cobrados" (sesiones pagadas) para "Vehículos cobrados"
        # y "cancelados" para el nuevo KPI de cancelaciones.
        # "total_vehiculos" incluye activos + cobrados + cancelados.
        ing        = float(resumen.get("ingresos",        0))
        cobrados   = int(resumen.get("cobrados",          0))   # nuevo campo DB
        cancelados = int(resumen.get("cancelados",        0))   # nuevo campo DB
        prom       = int(resumen.get("prom_minutos",      0))

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

        self._lbl_chart_titulo.configure(text=self._titulo_grafico())
        self._renderizar_grafico(chart_data, chart_tipo, moneda, fi, ff)
        self._renderizar_breakdown(tipos, moneda)
        self._renderizar_historial(historial, moneda)

    def _titulo_grafico(self) -> str:
        if self._periodo == "Hoy":
            return f"📈  Ingresos por hora — {date.today().strftime('%d/%m/%Y')}"
        elif self._periodo == "Semana":
            lunes = self._sel_fecha_semana - timedelta(days=self._sel_fecha_semana.weekday())
            domingo = lunes + timedelta(days=6)
            return f"📈  Ingresos — semana ({lunes.strftime('%d/%m')} al {domingo.strftime('%d/%m')})"
        elif self._periodo == "Mes":
            return f"📈  Ingresos — {MESES_ES[self._sel_mes - 1]} {self._sel_año}"
        else:
            return f"📈  Ingresos mensuales — {self._sel_año}"

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

        etiquetas, valores = self._preparar_datos_grafico(
            datos, chart_tipo, fi, ff)

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
            from datetime import date as _date
            fecha_map = {d["fecha"]: float(d["ingresos"]) for d in datos}
            fi_d  = _date.fromisoformat(fi)
            ff_d  = _date.fromisoformat(ff)
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
            pct_veh  = (cantidad / total_veh) if total_veh > 0 else 0

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

    # ─── Historial de transacciones ───────────────────────────────────────────

    def _renderizar_historial(self, historial: List[Dict], moneda: str):
        """
        Muestra las últimas 10 transacciones del período.

        Visualización diferenciada:
          • Sesiones cobradas  → fondo normal alternado, monto en verde.
          • Sesiones canceladas → fondo con tinte rojo, monto como "✕ Cancelado" en rojo.

        El badge de tipo usa fg_color oscuro + borde del color del vehículo
        para evitar el bug anterior de hex de 8 dígitos en Tkinter.
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
            estado = ses.get("estado", "cobrado")
            cancelado = (estado == "cancelado")

            # Fondo: canceladas tienen tinte rojizo para distinguirse
            if cancelado:
                bg = "#1f0a0a"   # tinte rojo muy oscuro
            else:
                bg = C["bg_medium"] if idx % 2 == 0 else C["bg_dark"]

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

            # Tipo — badge con borde del color del tipo de vehículo
            tipo = ses.get("tipo_vehiculo", "?")
            cv   = color_tipo(tipo)
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
                ent = datetime.strptime(ses["hora_entrada"], "%Y-%m-%d %H:%M:%S")
                ent_str = ent.strftime("%H:%M")
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
                    sal = datetime.strptime(ses["hora_salida"], "%Y-%m-%d %H:%M:%S")
                    sal_str = sal.strftime("%H:%M")
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

            # Monto — verde si cobrado, rojo con icono si cancelado
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
        """
        Abre un diálogo para elegir dónde guardar el reporte .xlsx,
        luego genera el archivo en un hilo daemon.
        """
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
            return  # El usuario canceló el diálogo

        self._btn_excel.configure(state="disabled", text="⏳ Exportando...")

        def _worker():
            try:
                ExcelExporter(self.db, self.config).exportar(ruta)
                self.after(0, _on_ok)
            except Exception as e:
                self.after(0, lambda: _on_err(str(e)))

        def _on_ok():
            if self.winfo_exists():
                self._btn_excel.configure(
                    state="normal", text="📊 Exportar Excel")
                messagebox.showinfo(
                    "✅ Exportado",
                    f"Reporte guardado correctamente en:\n\n{ruta}",
                )

        def _on_err(msg: str):
            if self.winfo_exists():
                self._btn_excel.configure(
                    state="normal", text="📊 Exportar Excel")
                messagebox.showerror(
                    "Error al exportar",
                    f"No se pudo generar el archivo:\n\n{msg}",
                )

        threading.Thread(target=_worker, daemon=True).start()

    # ─── Alias externo ────────────────────────────────────────────────────────

    def _cambiar_periodo(self, valor: str):
        """Alias de _on_periodo para compatibilidad con código externo."""
        self._on_periodo(valor)