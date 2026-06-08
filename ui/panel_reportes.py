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
  • Historial de las últimas transacciones del período.
  • Estado vacío amigable cuando no hay datos.
  • Carga en hilo daemon para no congelar la UI.

Correcciones sobre la versión anterior:
  • Breakdown y historial ahora son period-aware (usaban siempre "Hoy").
  • Eliminada llamada a get_por_tipo_hoy() y métodos obsoletos.
  • El gráfico de Mes ahora usa el mes/año seleccionado, no el mes actual.
  • "Total hoy" cambiado a "Total del período".
  • cargar_datos() ya no bloquea el hilo principal (threading).
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

# Años disponibles en el selector (5 años hacia atrás + actual)
_AÑO_ACTUAL = date.today().year
AÑOS_DISPONIBLES = list(range(_AÑO_ACTUAL - 4, _AÑO_ACTUAL + 1))


# ─── Helpers de rango de fechas ───────────────────────────────────────────────

def _rango_semana() -> tuple:
    """Últimos 7 días (incluyendo hoy)."""
    hoy = date.today()
    return (hoy - timedelta(days=6)).isoformat(), hoy.isoformat()


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

        # Estado del período seleccionado
        self._periodo  = "Hoy"
        self._sel_mes  = date.today().month   # mes para la vista "Mes"
        self._sel_año  = date.today().year    # año para las vistas "Mes" y "Año"

        # Referencia al canvas de matplotlib (para destruir antes de redibujar)
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

        # Botón de actualización manual
        ctk.CTkButton(
            hdr, text="🔄 Actualizar",
            fg_color=C["bg_medium"], hover_color=C["bg_light"],
            text_color=C["text_2"], font=fuente(11), height=32, width=110,
            command=self.cargar_datos,
        ).pack(side="right", padx=14)

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
        # Se muestra/oculta dinámicamente con pack_forget / pack(before=...)
        self._frame_nav = ctk.CTkFrame(
            self, fg_color=C["bg_medium"], height=44, corner_radius=0)
        self._frame_nav.pack_propagate(False)
        # Se oculta inicialmente (se mostrará para Mes/Año)

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

        # Guardamos referencias para actualizar los valores sin recrear los widgets
        self._kpi_refs: Dict[str, ctk.CTkLabel] = {}
        _kpis_def = [
            ("ingresos",  "Ingresos del período", f"{self.config.get_moneda()} 0.00", C["green"]),
            ("vehiculos", "Vehículos atendidos",  "0",                                C["blue"]),
            ("activos",   "Activos ahora",         "0",                                C["yellow"]),
            ("promedio",  "Tiempo promedio",       "—",                                C["purple"]),
        ]
        for key, titulo, val_init, color in _kpis_def:
            card = ctk.CTkFrame(
                self._frame_kpis, fg_color=C["bg_medium"],
                corner_radius=14, border_color=color, border_width=1,
            )
            card.pack(side="left", expand=True, fill="both", padx=5)
            # Línea superior de color (acento visual)
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

        # -- Columna izquierda: gráfico de barras --
        self._frame_chart = ctk.CTkFrame(
            centro, fg_color=C["bg_medium"], corner_radius=14)
        self._frame_chart.pack(side="left", fill="both", expand=True, padx=(0, 8))

        self._lbl_chart_titulo = ctk.CTkLabel(
            self._frame_chart, text="📈  Ingresos",
            font=fuente(13, bold=True), text_color=C["text_1"],
        )
        self._lbl_chart_titulo.pack(anchor="w", padx=16, pady=(12, 0))

        # Contenedor interno del canvas matplotlib
        self._frame_chart_inner = ctk.CTkFrame(
            self._frame_chart, fg_color="transparent")
        self._frame_chart_inner.pack(fill="both", expand=True, padx=8, pady=8)

        # -- Columna derecha: breakdown por tipo --
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

        # ── Historial de transacciones ─────────────────────────────────────
        hist_card = ctk.CTkFrame(self, fg_color=C["bg_medium"], corner_radius=14)
        hist_card.pack(fill="x", padx=20, pady=(0, 14))
        hist_card.configure(height=195)
        hist_card.pack_propagate(False)

        # Título del historial
        ctk.CTkLabel(
            hist_card, text="🕐  Últimas transacciones del período",
            font=fuente(13, bold=True), text_color=C["text_1"],
        ).pack(anchor="w", padx=16, pady=(10, 0))

        # Cabecera de columnas del historial
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

        # Área scrollable de filas del historial
        self._scroll_hist = ctk.CTkScrollableFrame(
            hist_card, fg_color="transparent",
            scrollbar_fg_color=C["bg_light"], corner_radius=0,
        )
        self._scroll_hist.pack(fill="both", expand=True, padx=10)

    # ─── Control de período ───────────────────────────────────────────────────

    def _on_periodo(self, valor: str):
        """
        Callback del selector de período.
        Muestra/oculta la barra de navegación de fecha y recarga los datos.
        """
        self._periodo = valor

        if valor in ("Mes", "Año"):
            # Mostrar la barra de navegación antes de los KPIs
            if not self._frame_nav.winfo_ismapped():
                self._frame_nav.pack(fill="x", before=self._frame_kpis)
            self._actualizar_nav()
        else:
            # Ocultar la barra de navegación para Hoy/Semana
            self._frame_nav.pack_forget()

        self.cargar_datos()

    def _actualizar_nav(self):
        """
        Actualiza el label de navegación y deshabilita el botón '▶'
        cuando ya estamos en el período actual.
        """
        hoy = date.today()
        if self._periodo == "Mes":
            self._lbl_nav.configure(
                text=f"{MESES_ES[self._sel_mes - 1]}  {self._sel_año}")
            # Deshabilitar "siguiente" si ya estamos en el mes actual o futuro
            en_limite = (self._sel_año > hoy.year or
                         (self._sel_año == hoy.year and self._sel_mes >= hoy.month))
        else:  # Año
            self._lbl_nav.configure(text=str(self._sel_año))
            en_limite = (self._sel_año >= hoy.year)

        self._btn_sig.configure(state="disabled" if en_limite else "normal")

    def _navegar_anterior(self):
        """Retrocede un mes o un año según el período activo."""
        if self._periodo == "Mes":
            if self._sel_mes == 1:
                self._sel_mes = 12
                self._sel_año -= 1
            else:
                self._sel_mes -= 1
        else:  # Año
            self._sel_año -= 1
        self._actualizar_nav()
        self.cargar_datos()

    def _navegar_siguiente(self):
        """Avanza un mes o un año según el período activo."""
        if self._periodo == "Mes":
            if self._sel_mes == 12:
                self._sel_mes = 1
                self._sel_año += 1
            else:
                self._sel_mes += 1
        else:  # Año
            self._sel_año += 1
        self._actualizar_nav()
        self.cargar_datos()

    # ─── Rango de fechas ──────────────────────────────────────────────────────

    def _get_rango(self) -> tuple:
        """
        Calcula (fecha_inicio, fecha_fin) en formato 'YYYY-MM-DD'
        según el período activo y los selectores de mes/año.
        """
        hoy = date.today().isoformat()
        if self._periodo == "Hoy":
            return hoy, hoy
        elif self._periodo == "Semana":
            return _rango_semana()
        elif self._periodo == "Mes":
            return _rango_mes(self._sel_año, self._sel_mes)
        else:  # Año
            return _rango_año(self._sel_año)

    # ─── Carga de datos ───────────────────────────────────────────────────────

    def cargar_datos(self):
        """
        Punto de entrada para actualizar todo el panel.
        Lanza un hilo daemon que consulta la BD; cuando termina,
        programa la actualización de la UI en el hilo principal.
        """
        fi, ff    = self._get_rango()
        periodo   = self._periodo
        moneda    = self.config.get_moneda()
        sel_año   = self._sel_año

        def _worker():
            """Hilo daemon: consulta la BD y envía resultados al hilo principal."""
            try:
                # Resumen KPI del período
                resumen   = self.db.get_resumen_rango(fi, ff)
                activos   = self.db.contar_activos()

                # Breakdown por tipo de vehículo (siempre del período activo)
                tipos     = self.db.get_por_tipo_rango(fi, ff)

                # Últimas transacciones del período
                historial = self.db.get_historial_rango(fi, ff, limit=30)

                # Datos del gráfico (dependen del período)
                if periodo == "Hoy":
                    chart_data = self.db.get_ingresos_por_hora(fi)
                    chart_tipo = "hora"
                elif periodo in ("Semana", "Mes"):
                    chart_data = self.db.get_ingresos_por_dia(fi, ff)
                    chart_tipo = "dia"
                else:  # Año
                    chart_data = self.db.get_ingresos_por_mes_en_año(sel_año)
                    chart_tipo = "mes"

                # Actualizar UI en el hilo principal
                self.after(0, lambda: self._actualizar_ui(
                    resumen, activos, tipos, historial,
                    chart_data, chart_tipo, moneda, fi, ff,
                ))
            except Exception as e:
                # Mostrar el error en el KPI de ingresos (visible al usuario)
                self.after(0, lambda: self._kpi_refs["ingresos"].configure(
                    text=f"⚠ Error: {e}"
                ))

        threading.Thread(target=_worker, daemon=True).start()

    def _actualizar_ui(self, resumen: Dict, activos: int, tipos: List[Dict],
                        historial: List[Dict], chart_data: List[Dict],
                        chart_tipo: str, moneda: str,
                        fi: str, ff: str):
        """
        Actualiza todos los componentes del panel con los datos cargados.
        Siempre se ejecuta en el hilo principal (llamado vía after(0, ...)).
        """
        if not self.winfo_exists():
            return

        # ── KPIs ──────────────────────────────────────────────────────────
        ing    = float(resumen.get("ingresos",        0))
        veh    = int(resumen.get("total_vehiculos",    0))
        prom   = int(resumen.get("prom_minutos",       0))

        self._kpi_refs["ingresos"].configure(text=f"{moneda} {ing:.2f}")
        self._kpi_refs["vehiculos"].configure(text=str(veh))
        self._kpi_refs["activos"].configure(text=str(activos))

        # Formatear tiempo promedio como Xh XXm si supera la hora
        if prom >= 60:
            prom_txt = f"{prom // 60}h {prom % 60:02d}m"
        elif prom > 0:
            prom_txt = f"{prom} min"
        else:
            prom_txt = "—"
        self._kpi_refs["promedio"].configure(text=prom_txt)

        # ── Título del gráfico ────────────────────────────────────────────
        self._lbl_chart_titulo.configure(text=self._titulo_grafico())

        # ── Componentes principales ───────────────────────────────────────
        self._renderizar_grafico(chart_data, chart_tipo, moneda, fi, ff)
        self._renderizar_breakdown(tipos, moneda)
        self._renderizar_historial(historial, moneda)

    def _titulo_grafico(self) -> str:
        """Genera el título del gráfico según el período activo."""
        if self._periodo == "Hoy":
            return f"📈  Ingresos por hora — {date.today().strftime('%d/%m/%Y')}"
        elif self._periodo == "Semana":
            return "📈  Ingresos — últimos 7 días"
        elif self._periodo == "Mes":
            return f"📈  Ingresos — {MESES_ES[self._sel_mes - 1]} {self._sel_año}"
        else:  # Año
            return f"📈  Ingresos mensuales — {self._sel_año}"

    # ─── Gráfico de barras ────────────────────────────────────────────────────

    def _renderizar_grafico(self, datos: List[Dict], chart_tipo: str,
                             moneda: str, fi: str, ff: str):
        """
        Dibuja el gráfico de barras con matplotlib.
        Soporta 3 tipos:
          'hora' → 24 barras (una por hora del día).
          'dia'  → una barra por día del rango.
          'mes'  → 12 barras (una por mes del año).
        Muestra estado vacío si no hay datos.
        """
        # Limpiar canvas anterior
        for w in self._frame_chart_inner.winfo_children():
            w.destroy()
        self._canvas_mpl = None

        if not MPL_OK:
            # matplotlib no instalado
            ctk.CTkLabel(
                self._frame_chart_inner,
                text="⚠  matplotlib no disponible\npip install matplotlib",
                font=fuente(12), text_color=C["yellow"],
            ).pack(expand=True)
            return

        # Preparar etiquetas y valores según el tipo de gráfico
        etiquetas, valores = self._preparar_datos_grafico(
            datos, chart_tipo, fi, ff)

        # Estado vacío: no hay datos en el período
        if not datos or sum(valores) == 0:
            self._mostrar_grafico_vacio()
            return

        # ── Dibujar con matplotlib ─────────────────────────────────────────
        fig = Figure(figsize=(5, 2.7), dpi=92)
        fig.patch.set_facecolor("#1e293b")   # fondo del canvas

        ax = fig.add_subplot(111)
        ax.set_facecolor("#0f172a")          # fondo del área del gráfico

        n = len(etiquetas)
        x = list(range(n))

        # Ancho de barra dinámico: menos barras → más anchas
        ancho_barra = max(0.35, min(0.65, 8 / n)) if n > 0 else 0.6

        bars = ax.bar(
            x, valores,
            color="#3b82f6", width=ancho_barra,
            edgecolor="#1d4ed8", linewidth=0.4, zorder=3,
        )

        # Etiqueta de valor sobre cada barra con ingreso > 0
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

        # Ejes
        ax.set_xticks(x)
        rotacion = 45 if n > 14 else 0
        ax.set_xticklabels(
            etiquetas, fontsize=7, color="#94a3b8", rotation=rotacion,
            ha="right" if rotacion else "center",
        )
        ax.tick_params(axis="y", colors="#64748b", labelsize=7)

        # Formatear el eje Y con símbolo de moneda
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda v, _: f"{moneda}{v:.0f}")
        )

        # Ocultar bordes superiores y derechos (estilo moderno)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["bottom"].set_color("#2d3f55")
        ax.spines["left"].set_color("#2d3f55")

        # Grilla horizontal suave
        ax.yaxis.grid(True, color="#1e3a5f", linestyle="--", linewidth=0.5, zorder=0)
        ax.set_axisbelow(True)

        fig.tight_layout(pad=1.2)

        # Incrustar el canvas en el frame de customtkinter
        canvas = FigureCanvasTkAgg(fig, master=self._frame_chart_inner)
        canvas.draw()
        widget = canvas.get_tk_widget()
        widget.configure(bg="#1e293b", highlightthickness=0)
        widget.pack(fill="both", expand=True)
        self._canvas_mpl = canvas

    def _preparar_datos_grafico(self, datos: List[Dict], chart_tipo: str,
                                  fi: str, ff: str):
        """
        Transforma los datos de la BD en listas paralelas (etiquetas, valores)
        listas para graficar. Rellena con 0 los períodos sin datos.
        """
        if chart_tipo == "hora":
            # 24 barras (00h–23h), con 0 para horas sin ingreso
            hora_map  = {d["hora"]: float(d["ingresos"]) for d in datos}
            etiquetas = [f"{h:02d}" for h in range(24)]
            valores   = [hora_map.get(f"{h:02d}", 0.0) for h in range(24)]

        elif chart_tipo == "dia":
            # Una barra por cada día del rango, con 0 para días sin ingreso
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

        else:  # chart_tipo == "mes"
            # 12 barras (Ene–Dic), con 0 para meses sin ingreso
            mes_map   = {d["mes"]: float(d["ingresos"]) for d in datos}
            etiquetas = MESES_CORTO
            valores   = [mes_map.get(f"{m:02d}", 0.0) for m in range(1, 13)]

        return etiquetas, valores

    def _mostrar_grafico_vacio(self):
        """Muestra un estado vacío amigable en el área del gráfico."""
        ctk.CTkLabel(
            self._frame_chart_inner,
            text="📭\n\nSin ingresos registrados\npara este período",
            font=fuente(13), text_color=C["text_3"],
            justify="center",
        ).pack(expand=True)

    # ─── Breakdown por tipo de vehículo ───────────────────────────────────────

    def _renderizar_breakdown(self, tipos: List[Dict], moneda: str):
        """
        Muestra la distribución de vehículos e ingresos por tipo
        para el período activo (no siempre "hoy" como en la versión anterior).
        Incluye una barra de proporción y el porcentaje de ingreso.
        """
        # Limpiar contenido anterior
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
            # Porcentaje respecto al total de ingresos del período
            pct_ing  = (ingresos / total_ing * 100) if total_ing > 0 else 0
            # Ancho de la barra de proporción (respecto a vehículos)
            pct_veh  = (cantidad / total_veh) if total_veh > 0 else 0

            card = ctk.CTkFrame(
                self._frame_tipo_rows, fg_color=C["bg_dark"], corner_radius=10)
            card.pack(fill="x", pady=4)

            # Fila superior: emoji + nombre + conteo
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

            # Barra de proporción de vehículos
            track = ctk.CTkFrame(card, fg_color=C["bg_medium"], height=5, corner_radius=3)
            track.pack(fill="x", padx=12, pady=(2, 4))
            track.pack_propagate(False)
            # La barra activa con ancho relativo
            ctk.CTkFrame(
                track, fg_color=color, height=5,
                width=max(4, int(pct_veh * 220)),
                corner_radius=3,
            ).place(x=0, y=0)

            # Monto e ingresos
            ctk.CTkLabel(
                card, text=f"{moneda} {ingresos:.2f}   ({pct_ing:.0f}%)",
                font=fuente(11, bold=True), text_color=C["text_2"], anchor="w",
            ).pack(padx=12, pady=(0, 8))

        # Totales del período
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
        Muestra las últimas transacciones del período activo.
        Sesiones cobradas aparecen en verde; canceladas en rojo.
        """
        # Limpiar filas anteriores
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
            # Alternar fondo de fila
            bg    = C["bg_medium"] if idx % 2 == 0 else C["bg_dark"]
            estado = ses.get("estado", "cobrado")

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

            # Tipo — badge coloreado
            tipo  = ses.get("tipo_vehiculo", "?")
            cv    = color_tipo(tipo)
            badge = ctk.CTkFrame(
                fila, fg_color=cv + "33", corner_radius=4,
                width=anchs[1] - 8, height=20)
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
            min_t   = ses.get("minutos_total", 0) or 0
            t_str   = (f"{min_t // 60}h {min_t % 60:02d}m" if min_t else "—")
            ctk.CTkLabel(
                fila, text=t_str,
                font=fuente(10), text_color=C["text_3"],
                width=anchs[5],
            ).pack(side="left", padx=2)

            # Monto — verde si cobrado, rojo si cancelado
            monto = ses.get("monto")
            if estado == "cancelado":
                m_txt, m_color = "Cancelado", C["red"]
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

    # ─── Cambio de período (callback externo del segmented button) ────────────

    def _cambiar_periodo(self, valor: str):
        """Alias de _on_periodo para compatibilidad con código externo."""
        self._on_periodo(valor)