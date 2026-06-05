"""
ParkingPro - Panel de Reportes Financieros
KPIs + gráfico de barras (7 días) + breakdown por tipo + historial.
"""
import customtkinter as ctk
from datetime import datetime, date, timedelta
from typing import List, Dict

from ui.theme import C, fuente, TIPOS_VEHICULO, color_tipo

# Matplotlib integrado con fondo oscuro
try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.ticker import FuncFormatter
    MPL_OK = True
except Exception:
    MPL_OK = False

# Colores tipo → hex  (para matplotlib)
_COLOR_HEX = {
    t["nombre"]: t["color"]
    for t in TIPOS_VEHICULO
}


class PanelReportes(ctk.CTkFrame):
    """
    Panel de reportes con tres vistas:
      Hoy · Semana · Mes
    Muestra KPIs, gráfico de ingresos, breakdown por tipo y últimas transacciones.
    """

    def __init__(self, parent, config, db, printer, **kwargs):
        super().__init__(parent, fg_color=C["bg_dark"], corner_radius=0, **kwargs)
        self.config    = config
        self.db        = db
        self.printer   = printer
        self._periodo  = "Hoy"      # "Hoy" | "Semana" | "Mes"
        self._canvas_fig = None     # referencia al canvas matplotlib

        self._build_ui()
        self.cargar_datos()

    # ─── UI base ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=C["sidebar"], height=56, corner_radius=0)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(
            hdr, text="📊  Reportes Financieros",
            font=fuente(17, bold=True), text_color=C["text_1"],
        ).pack(side="left", padx=24)

        # Selector de período
        self._seg = ctk.CTkSegmentedButton(
            hdr,
            values=["Hoy", "Semana", "Mes"],
            command=self._cambiar_periodo,
            fg_color=C["bg_dark"],
            selected_color=C["blue"],
            selected_hover_color=C["blue_h"],
            unselected_color=C["bg_medium"],
            unselected_hover_color=C["bg_light"],
            text_color=C["text_1"],
            font=fuente(12),
            width=230, height=34,
        )
        self._seg.set("Hoy")
        self._seg.pack(side="right", padx=(0, 80))

        ctk.CTkButton(
            hdr, text="🔄  Actualizar",
            fg_color=C["bg_medium"], hover_color=C["bg_light"],
            text_color=C["text_2"], font=fuente(11), height=32, width=110,
            command=self.cargar_datos,
        ).pack(side="right", padx=6)

        # ── KPI cards ─────────────────────────────────────────────────────
        self._frame_kpis = ctk.CTkFrame(self, fg_color="transparent")
        self._frame_kpis.pack(fill="x", padx=20, pady=(14, 0))

        self._kpi_refs: Dict = {}   # guardamos labels para actualizar

        kpis = [
            ("kpi_ingresos",  "Ingresos del período", f"{self.config.get_moneda()} 0.00", C["green"]),
            ("kpi_vehiculos", "Vehículos atendidos",  "0",                                C["blue"]),
            ("kpi_activos",   "Activos ahora",        "0",                                C["yellow"]),
            ("kpi_promedio",  "Tiempo promedio",      "0 min",                            C["purple"]),
        ]
        for key, titulo, valor_init, color in kpis:
            card = ctk.CTkFrame(
                self._frame_kpis, fg_color=C["bg_medium"], corner_radius=14,
                border_color=color, border_width=1,
            )
            card.pack(side="left", expand=True, fill="both", padx=6)

            # Línea superior de color
            ctk.CTkFrame(card, fg_color=color, height=3, corner_radius=0).pack(fill="x")

            ctk.CTkLabel(card, text=titulo, font=fuente(11),
                         text_color=C["text_3"]).pack(pady=(10, 2))

            lbl_val = ctk.CTkLabel(card, text=valor_init,
                                   font=fuente(24, bold=True), text_color=color)
            lbl_val.pack(pady=(0, 12))
            self._kpi_refs[key] = lbl_val

        # ── Área principal (gráfico + breakdown) ──────────────────────────
        self._frame_centro = ctk.CTkFrame(self, fg_color="transparent")
        self._frame_centro.pack(fill="both", expand=True, padx=20, pady=10)

        # Columna izquierda: gráfico de barras
        self._frame_chart = ctk.CTkFrame(
            self._frame_centro, fg_color=C["bg_medium"], corner_radius=14,
        )
        self._frame_chart.pack(side="left", fill="both", expand=True, padx=(0, 8))

        self._lbl_chart_titulo = ctk.CTkLabel(
            self._frame_chart,
            text="📈  Ingresos — últimos 7 días",
            font=fuente(13, bold=True), text_color=C["text_1"],
        )
        self._lbl_chart_titulo.pack(anchor="w", padx=16, pady=(14, 0))

        self._frame_chart_inner = ctk.CTkFrame(
            self._frame_chart, fg_color="transparent"
        )
        self._frame_chart_inner.pack(fill="both", expand=True, padx=8, pady=8)

        # Columna derecha: tabla por tipo
        self._frame_tipo = ctk.CTkFrame(
            self._frame_centro, fg_color=C["bg_medium"], corner_radius=14, width=280,
        )
        self._frame_tipo.pack(side="right", fill="y", padx=(0, 0))
        self._frame_tipo.pack_propagate(False)

        ctk.CTkLabel(
            self._frame_tipo, text="🚗  Por tipo de vehículo",
            font=fuente(13, bold=True), text_color=C["text_1"],
        ).pack(anchor="w", padx=16, pady=(14, 8))

        self._frame_tipo_rows = ctk.CTkScrollableFrame(
            self._frame_tipo, fg_color="transparent",
            scrollbar_fg_color=C["bg_light"],
        )
        self._frame_tipo_rows.pack(fill="both", expand=True, padx=6, pady=(0, 8))

        # ── Historial reciente ────────────────────────────────────────────
        hist_wrap = ctk.CTkFrame(self, fg_color=C["bg_medium"], corner_radius=14)
        hist_wrap.pack(fill="x", padx=20, pady=(0, 12))
        hist_wrap.pack_propagate(False)
        hist_wrap.configure(height=200)

        ctk.CTkLabel(
            hist_wrap, text="🕐  Últimas transacciones",
            font=fuente(13, bold=True), text_color=C["text_1"],
        ).pack(anchor="w", padx=16, pady=(12, 6))

        # Cabecera tabla
        cols  = ["Ticket",   "Tipo",     "Placa",  "Entrada",  "Salida",  "Tiempo", "Monto"]
        anchs = [120,        110,        90,        100,        100,       80,       90]
        hdr_t = ctk.CTkFrame(hist_wrap, fg_color=C["bg_dark"], height=30, corner_radius=0)
        hdr_t.pack(fill="x", padx=10)
        hdr_t.pack_propagate(False)
        for c, w in zip(cols, anchs):
            ctk.CTkLabel(hdr_t, text=c, font=fuente(10, bold=True),
                         text_color=C["text_3"], width=w, anchor="w").pack(
                side="left", padx=(8 if c == "Ticket" else 2, 2), pady=4)

        self._scroll_hist = ctk.CTkScrollableFrame(
            hist_wrap, fg_color="transparent",
            scrollbar_fg_color=C["bg_light"],
            corner_radius=0,
        )
        self._scroll_hist.pack(fill="both", expand=True, padx=10)

    # ─── Carga de datos ───────────────────────────────────────────────────────

    def cargar_datos(self):
        self._periodo = self._seg.get()
        moneda = self.config.get_moneda()

        try:
            resumen = self.db.get_resumen_hoy()
            activos = self.db.contar_activos()

            # ── KPIs ──────────────────────────────────────────────────────
            if self._periodo == "Hoy":
                ingresos   = resumen.get("ingresos", 0)
                vehiculos  = resumen.get("total_vehiculos", 0)
                prom_min   = int(resumen.get("prom_minutos", 0))
            elif self._periodo == "Semana":
                semana = self.db.get_ingresos_semana()
                ingresos   = sum(d["ingresos"] for d in semana)
                vehiculos  = sum(d["vehiculos"] for d in semana)
                prom_min   = 0
            else:  # Mes
                kpi_mes  = self.db.get_kpi_mes()
                ingresos  = kpi_mes.get("ingresos", 0)
                vehiculos = kpi_mes.get("total_vehiculos", 0)
                prom_min  = int(kpi_mes.get("prom_minutos", 0))

            self._kpi_refs["kpi_ingresos"].configure(
                text=f"{moneda} {ingresos:.2f}")
            self._kpi_refs["kpi_vehiculos"].configure(text=str(vehiculos))
            self._kpi_refs["kpi_activos"].configure(text=str(activos))
            self._kpi_refs["kpi_promedio"].configure(
                text=f"{prom_min} min" if prom_min else "—")

            # ── Gráfico ───────────────────────────────────────────────────
            if self._periodo == "Mes":
                datos_chart = self.db.get_ingresos_mes_actual()
                titulo_chart = f"📈  Ingresos — {date.today().strftime('%B %Y').title()}"
            else:
                datos_chart = self.db.get_ingresos_semana()
                titulo_chart = "📈  Ingresos — últimos 7 días"

            self._lbl_chart_titulo.configure(text=titulo_chart)
            self._renderizar_grafico(datos_chart, moneda)

            # ── Breakdown por tipo ────────────────────────────────────────
            tipos_data = self.db.get_por_tipo_hoy()
            self._renderizar_breakdown(tipos_data, moneda)

            # ── Historial ─────────────────────────────────────────────────
            historial = self.db.get_historial(limit=25)
            self._renderizar_historial(historial, moneda)

        except Exception as e:
            self._kpi_refs["kpi_ingresos"].configure(text=f"Error: {e}")

    def _cambiar_periodo(self, valor: str):
        self._periodo = valor
        self.cargar_datos()

    # ─── Gráfico de barras ────────────────────────────────────────────────────

    def _renderizar_grafico(self, datos: List[Dict], moneda: str):
        """Dibuja (o actualiza) el gráfico de barras en el panel izquierdo."""
        for w in self._frame_chart_inner.winfo_children():
            w.destroy()
        self._canvas_fig = None

        if not MPL_OK:
            ctk.CTkLabel(
                self._frame_chart_inner,
                text="⚠ matplotlib no disponible\npip install matplotlib",
                font=fuente(12), text_color=C["yellow"],
            ).pack(expand=True)
            return

        if not datos:
            ctk.CTkLabel(
                self._frame_chart_inner,
                text="Sin datos para el período seleccionado",
                font=fuente(13), text_color=C["text_3"],
            ).pack(expand=True)
            return

        fechas   = [d["fecha"][-5:] for d in datos]  # MM-DD
        ingresos = [float(d["ingresos"]) for d in datos]
        vehiculos= [int(d.get("vehiculos", 0)) for d in datos]

        # Completar días faltantes con 0
        if len(fechas) < 2:
            fechas   += [""] * (2 - len(fechas))
            ingresos += [0.0] * (2 - len(ingresos))

        fig = Figure(figsize=(5, 2.8), dpi=88)
        fig.patch.set_facecolor("#1e293b")
        ax = fig.add_subplot(111)
        ax.set_facecolor("#0f172a")

        x = range(len(fechas))
        bars = ax.bar(x, ingresos, color="#3b82f6", width=0.55,
                      edgecolor="#1d4ed8", linewidth=0.5, zorder=3)

        # Etiquetas de valor sobre cada barra
        for bar, val in zip(bars, ingresos):
            if val > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max(ingresos) * 0.02,
                    f"{moneda}{val:.1f}",
                    ha="center", va="bottom",
                    color="#f1f5f9", fontsize=7.5, fontweight="bold",
                )

        ax.set_xticks(list(x))
        ax.set_xticklabels(fechas, fontsize=8, color="#94a3b8")
        ax.tick_params(axis="y", colors="#64748b", labelsize=8)
        ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(lambda v, _: f"{moneda}{v:.0f}")
        )
        ax.spines["bottom"].set_color("#2d3f55")
        ax.spines["left"].set_color("#2d3f55")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.set_ylabel(f"Ingresos ({moneda})", color="#64748b", fontsize=8)
        ax.yaxis.grid(True, color="#2d3f55", linestyle="--", linewidth=0.5, zorder=0)
        ax.set_axisbelow(True)
        fig.tight_layout(pad=1.4)

        canvas = FigureCanvasTkAgg(fig, master=self._frame_chart_inner)
        canvas.draw()
        canvas.get_tk_widget().configure(bg="#1e293b", highlightthickness=0)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._canvas_fig = canvas

    # ─── Breakdown por tipo ───────────────────────────────────────────────────

    def _renderizar_breakdown(self, tipos: List[Dict], moneda: str):
        for w in self._frame_tipo_rows.winfo_children():
            w.destroy()

        if not tipos:
            ctk.CTkLabel(
                self._frame_tipo_rows,
                text="Sin datos hoy",
                font=fuente(12), text_color=C["text_3"],
            ).pack(pady=20)
            return

        total_ing = sum(float(t.get("ingresos", 0)) for t in tipos)
        total_veh = sum(int(t.get("cantidad", 0)) for t in tipos)

        for row in tipos:
            nombre   = row.get("tipo_vehiculo", "?")
            cantidad = int(row.get("cantidad", 0))
            ingresos = float(row.get("ingresos", 0))
            color    = color_tipo(nombre)
            pct      = (ingresos / total_ing * 100) if total_ing > 0 else 0

            card = ctk.CTkFrame(
                self._frame_tipo_rows, fg_color=C["bg_dark"], corner_radius=10,
            )
            card.pack(fill="x", pady=4)

            # Fila superior: emoji + nombre + cantidad
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(8, 2))
            ctk.CTkLabel(top, text=nombre, font=fuente(12, bold=True),
                         text_color=color, anchor="w").pack(side="left")
            ctk.CTkLabel(top, text=f"{cantidad} veh.",
                         font=fuente(10), text_color=C["text_3"]).pack(side="right")

            # Barra de progreso
            if total_veh > 0:
                bar_w = max(4, int((cantidad / total_veh) * 220))
                bar_track = ctk.CTkFrame(card, fg_color=C["bg_medium"], height=5,
                                          corner_radius=3)
                bar_track.pack(fill="x", padx=12, pady=(2, 4))
                ctk.CTkFrame(bar_track, fg_color=color, height=5,
                              width=bar_w, corner_radius=3).place(x=0, y=0)

            # Monto
            ctk.CTkLabel(card, text=f"{moneda} {ingresos:.2f}   ({pct:.0f}%)",
                         font=fuente(11, bold=True), text_color=C["text_2"],
                         anchor="w").pack(padx=12, pady=(0, 8))

        # Total
        sep = ctk.CTkFrame(self._frame_tipo_rows, fg_color=C["border"], height=1)
        sep.pack(fill="x", pady=4)
        total_card = ctk.CTkFrame(self._frame_tipo_rows, fg_color="transparent")
        total_card.pack(fill="x", padx=8)
        ctk.CTkLabel(total_card, text="Total hoy:", font=fuente(11),
                     text_color=C["text_3"], anchor="w").pack(side="left")
        ctk.CTkLabel(total_card,
                     text=f"{moneda} {total_ing:.2f}",
                     font=fuente(12, bold=True), text_color=C["green"],
                     anchor="e").pack(side="right")

    # ─── Historial reciente ───────────────────────────────────────────────────

    def _renderizar_historial(self, historial: List[Dict], moneda: str):
        for w in self._scroll_hist.winfo_children():
            w.destroy()

        if not historial:
            ctk.CTkLabel(
                self._scroll_hist,
                text="Sin transacciones registradas aún",
                font=fuente(12), text_color=C["text_3"],
            ).pack(pady=10)
            return

        anchs = [120, 110, 90, 100, 100, 80, 90]

        for idx, ses in enumerate(historial):
            bg = C["bg_medium"] if idx % 2 == 0 else C["bg_dark"]
            fila = ctk.CTkFrame(self._scroll_hist, fg_color=bg, height=32, corner_radius=6)
            fila.pack(fill="x", pady=1)
            fila.pack_propagate(False)

            # Ticket
            ctk.CTkLabel(fila, text=ses.get("ticket_numero", ""), font=fuente(10),
                         text_color=C["text_3"], width=anchs[0], anchor="w").pack(
                side="left", padx=(8, 2))

            # Tipo — badge de color
            tipo   = ses.get("tipo_vehiculo", "?")
            cv     = color_tipo(tipo)
            badge  = ctk.CTkFrame(fila, fg_color=cv + "33", corner_radius=4,
                                   width=anchs[1] - 8, height=20)
            badge.pack(side="left", padx=2)
            badge.pack_propagate(False)
            ctk.CTkLabel(badge, text=tipo[:8], font=fuente(9, bold=True),
                         text_color=cv).place(relx=0.5, rely=0.5, anchor="center")

            # Placa
            ctk.CTkLabel(fila, text=ses.get("placa", ""), font=fuente(10, bold=True),
                         text_color=C["text_1"], width=anchs[2]).pack(side="left", padx=2)

            # Entrada
            try:
                ent = datetime.strptime(ses["hora_entrada"], "%Y-%m-%d %H:%M:%S")
                ent_str = ent.strftime("%H:%M")
            except Exception:
                ent_str = "?"
            ctk.CTkLabel(fila, text=ent_str, font=fuente(10),
                         text_color=C["text_2"], width=anchs[3]).pack(side="left", padx=2)

            # Salida
            sal_str = "—"
            if ses.get("hora_salida"):
                try:
                    sal = datetime.strptime(ses["hora_salida"], "%Y-%m-%d %H:%M:%S")
                    sal_str = sal.strftime("%H:%M")
                except Exception:
                    sal_str = "?"
            ctk.CTkLabel(fila, text=sal_str, font=fuente(10),
                         text_color=C["text_2"], width=anchs[4]).pack(side="left", padx=2)

            # Tiempo
            min_total = ses.get("minutos_total", 0) or 0
            if min_total:
                t_str = f"{min_total // 60}h {min_total % 60:02d}m"
            else:
                t_str = "—"
            ctk.CTkLabel(fila, text=t_str, font=fuente(10),
                         text_color=C["text_3"], width=anchs[5]).pack(side="left", padx=2)

            # Monto
            monto = ses.get("monto")
            if monto is not None:
                m_txt   = f"{moneda} {float(monto):.2f}"
                m_color = C["green"]
            else:
                m_txt   = "—"
                m_color = C["text_3"]
            ctk.CTkLabel(fila, text=m_txt, font=fuente(10, bold=True),
                         text_color=m_color, width=anchs[6]).pack(side="left", padx=2)