"""
ParkingPro - Exportador de reportes a Excel (.xlsx)

Genera un libro con 5 hojas:
  1. Resumen     — KPIs globales, del año y del mes actual.
  2. Sesiones    — Detalle de todas las sesiones finalizadas.
  3. Por Día     — Ingresos diarios (últimos 30 días) + gráfico.
  4. Por Mes     — Ingresos mensuales del año actual + gráfico.
  5. Por Tipo    — Desglose por tipo de vehículo + gráfico.
"""
import calendar
from datetime import date, datetime
from typing import List, Dict

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.marker import DataPoint
from openpyxl.chart.label import DataLabelList
from openpyxl.utils import get_column_letter


# ── Paleta de colores (modo oscuro adaptado a Excel) ──────────────────────────
_C = {
    "hdr_bg":   "1E293B",   # cabecera principal
    "hdr_txt":  "F1F5F9",
    "sub_bg":   "263244",   # sub-cabecera
    "sub_txt":  "94A3B8",
    "title_bg": "0B1120",   # título de hoja
    "title_txt":"3B82F6",   # azul ParkingPro
    "alt":      "131E31",   # fila alternada
    "ok_bg":    "0A1F12",   # sesión cobrada
    "ok_txt":   "10B981",
    "err_bg":   "1F0707",   # sesión cancelada
    "err_txt":  "EF4444",
    "total_bg": "0F172A",   # fila totales
    "total_txt":"3B82F6",
    "border":   "2D3F55",
    "white":    "FFFFFF",
    "green":    "10B981",
    "blue":     "3B82F6",
    "yellow":   "F59E0B",
    "red":      "EF4444",
    "gray":     "64748B",
}

MESES_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


# ── Helpers de estilo ─────────────────────────────────────────────────────────

def _fill(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color)


def _font(color: str = "FFFFFF", size: int = 10, bold: bool = False,
          italic: bool = False) -> Font:
    return Font(name="Arial", size=size, bold=bold, italic=italic, color=color)


def _center(wrap: bool = False) -> Alignment:
    return Alignment(horizontal="center", vertical="center", wrap_text=wrap)


def _left() -> Alignment:
    return Alignment(horizontal="left", vertical="center")


def _right() -> Alignment:
    return Alignment(horizontal="right", vertical="center")


def _thin_border(sides: str = "bottom") -> Border:
    """sides: combinación de 'top', 'bottom', 'left', 'right'."""
    thin = Side(style="thin", color=_C["border"])
    return Border(
        top=thin    if "top"    in sides else None,
        bottom=thin if "bottom" in sides else None,
        left=thin   if "left"   in sides else None,
        right=thin  if "right"  in sides else None,
    )


def _apply_row(ws, row: int, cols: int,
               bg: str = None, fg: str = "FFFFFF",
               bold: bool = False, font_size: int = 10,
               align: str = "left", border: bool = True):
    """Aplica bg/fg/font/align a toda una fila de 'cols' columnas."""
    aln = _center() if align == "center" else (_right() if align == "right" else _left())
    for c in range(1, cols + 1):
        cell = ws.cell(row=row, column=c)
        if bg:
            cell.fill = _fill(bg)
        cell.font  = _font(fg, font_size, bold)
        cell.alignment = aln
        if border:
            cell.border = _thin_border("bottom")


def _header_row(ws, row: int, labels: List[str],
                bg: str = None, fg: str = "FFFFFF",
                bold: bool = True, font_size: int = 10,
                heights: List[int] = None):
    """Escribe una fila de cabecera con etiquetas y estilo."""
    bg = bg or _C["hdr_bg"]
    for c, label in enumerate(labels, 1):
        cell = ws.cell(row=row, column=c, value=label)
        cell.fill = _fill(bg)
        cell.font = _font(fg, font_size, bold)
        cell.alignment = _center()
        cell.border = _thin_border("bottom")
    ws.row_dimensions[row].height = heights[0] if heights else 22


def _set_widths(ws, widths: Dict[int, float]):
    """Define anchos de columna. widths = {col_index: width}."""
    for idx, w in widths.items():
        ws.column_dimensions[get_column_letter(idx)].width = w


def _merge_title(ws, row: int, max_col: int, text: str,
                 bg: str = None, fg: str = None,
                 font_size: int = 16, height: int = 36):
    """Fila de título fusionada A..max_col."""
    bg = bg or _C["title_bg"]
    fg = fg or _C["title_txt"]
    ws.merge_cells(start_row=row, start_column=1,
                   end_row=row, end_column=max_col)
    cell = ws.cell(row=row, column=1, value=text)
    cell.fill = _fill(bg)
    cell.font = _font(fg, font_size, bold=True)
    cell.alignment = _center()
    ws.row_dimensions[row].height = height


def _kpi_block(ws, start_row: int, titulo: str, items: List[tuple],
               col_label: int = 1, col_val: int = 2, max_col: int = 5):
    """
    Escribe un bloque KPI: título fusionado + filas (label, valor).
    Todos los fondos son oscuros para que el texto blanco sea visible.
    items: [(label, valor), ...]
    """
    # ── Cabecera de sección ──────────────────────────────────────────────────
    ws.merge_cells(start_row=start_row, start_column=col_label,
                   end_row=start_row, end_column=max_col)
    cell = ws.cell(row=start_row, column=col_label, value=titulo)
    cell.fill = _fill(_C["sub_bg"])
    cell.font = _font(_C["title_txt"], 10, bold=True)   # azul visible
    cell.alignment = _left()
    ws.row_dimensions[start_row].height = 22

    # ── Filas de datos ───────────────────────────────────────────────────────
    for i, (label, val) in enumerate(items, 1):
        r = start_row + i
        # Label — fondo oscuro + texto gris claro
        lc = ws.cell(row=r, column=col_label, value=label)
        lc.fill  = _fill(_C["hdr_bg"])       # FIX: fondo oscuro (antes era blanco → texto invisible)
        lc.font  = _font(_C["sub_txt"], 10)
        lc.alignment = _left()
        # Valor — fondo oscuro + texto blanco bold
        vc = ws.cell(row=r, column=col_val, value=val)
        vc.fill  = _fill(_C["hdr_bg"])       # FIX: fondo oscuro (antes era blanco → texto invisible)
        vc.font  = _font(_C["white"], 11, bold=True)
        vc.alignment = _right()
        vc.border = _thin_border("bottom")
        # Rellenar columnas restantes con el mismo fondo oscuro
        for c in range(col_val + 1, max_col + 1):
            extra = ws.cell(row=r, column=c)
            extra.fill = _fill(_C["hdr_bg"])
        ws.row_dimensions[r].height = 20

    return start_row + len(items) + 2   # próxima fila disponible


def _bar_chart(ws, data_ref, cats_ref, title: str, y_label: str,
               anchor: str, width: int = 18, height: int = 12,
               bar_color: str = "3B82F6",
               colors_per_bar: List[str] = None):
    """
    Crea y coloca un gráfico de barras verticales con etiquetas de valor.

    colors_per_bar: lista de colores hex; cada barra recibe el suyo.
    """
    chart = BarChart()
    chart.type       = "col"
    chart.grouping   = "clustered"
    chart.title      = title
    chart.y_axis.title  = y_label
    chart.y_axis.numFmt = '#,##0.00'
    chart.y_axis.delete = False        # asegura que el eje Y sea visible
    chart.style      = 10
    chart.width      = width
    chart.height     = height
    chart.gapWidth   = 80
    chart.add_data(data_ref, titles_from_data=True)
    chart.set_categories(cats_ref)

    # Etiquetas de valor sobre cada barra (equivalente al texto encima de barras en UI)
    chart.dataLabels = DataLabelList()
    chart.dataLabels.showVal        = True
    chart.dataLabels.showCatName    = False
    chart.dataLabels.showSerName    = False
    chart.dataLabels.showLegendKey  = False

    if chart.series:
        s = chart.series[0]
        s.graphicalProperties.solidFill          = bar_color
        s.graphicalProperties.line.solidFill     = bar_color

        # Colores individuales por barra (solo solidFill; line se hereda de la serie)
        if colors_per_bar:
            for i, color in enumerate(colors_per_bar):
                pt = DataPoint(idx=i)
                pt.graphicalProperties.solidFill = color
                s.dPt.append(pt)

    ws.add_chart(chart, anchor)
    return chart


# ── Clase principal ───────────────────────────────────────────────────────────

class ExcelExporter:
    """Genera el reporte Excel completo de ParkingPro."""

    def __init__(self, db, config):
        self.db     = db
        self.config = config
        self.moneda = config.get_moneda()
        self.negocio = config.get_nombre_negocio()

    # ─── Punto de entrada ─────────────────────────────────────────────────────

    def exportar(self, ruta: str):
        """
        Recopila todos los datos de la BD y genera el archivo .xlsx.

        Hojas:
          1. Resumen    — KPIs con fórmulas dinámicas + cobradas/canceladas
          2. Sesiones   — Detalle completo (verde=cobrada, rojo=cancelada)
          3. Mes Actual — Ingresos día a día del mes en curso
          4. Mensual    — 12 meses del año actual + gráfico multicolor
          5. Por Tipo   — Desglose por tipo de vehículo + gráfico multicolor
        """
        hoy      = date.today()
        año_act  = hoy.year
        mes_act  = hoy.month
        _, ult_d = calendar.monthrange(año_act, mes_act)
        mes_ini  = f"{año_act:04d}-{mes_act:02d}-01"
        mes_fin  = f"{año_act:04d}-{mes_act:02d}-{ult_d:02d}"
        año_ini  = f"{año_act:04d}-01-01"
        año_fin  = f"{año_act:04d}-12-31"
        hoy_str  = hoy.isoformat()

        # ── Consultas a la BD ─────────────────────────────────────────────
        globales    = self.db.get_totales_globales()
        resumen_año = self.db.get_resumen_rango(año_ini, año_fin)
        resumen_mes = self.db.get_resumen_rango(mes_ini, mes_fin)
        sesiones    = self.db.get_historial(limit=50_000)
        # Hoja 3: días del mes actual (no los últimos 30 días)
        diarios     = self.db.get_ingresos_por_dia(mes_ini, mes_fin)
        mensual     = self.db.get_ingresos_por_mes_en_año(año_act)
        por_tipo    = self.db.get_por_tipo_rango("2000-01-01", hoy_str)

        wb = Workbook()
        wb.remove(wb.active)   # eliminar hoja vacía por defecto

        self._hoja_resumen(wb, globales, resumen_año, resumen_mes,
                           hoy, año_act, mes_act)
        self._hoja_sesiones(wb, sesiones)
        self._hoja_diario(wb, diarios, mes_ini, mes_fin, año_act, mes_act)
        self._hoja_mensual(wb, mensual, año_act)
        self._hoja_por_tipo(wb, por_tipo)

        wb.save(ruta)

    # ─── Hoja 1: Resumen ──────────────────────────────────────────────────────

    def _hoja_resumen(self, wb: Workbook, globales: dict, resumen_año: dict,
                      resumen_mes: dict, hoy: date, año: int, mes: int):
        """
        Hoja 1 — Resumen ejecutivo.

        Layout (2 columnas activas):
          A = Indicador (descripción)
          B = Valor  (fórmula Excel o valor Python)

        Sección GLOBAL: fórmulas COUNTIF/SUMIF sobre hoja Sesiones (vivas).
        Sección AÑO:    ingresos/vehículos con fórmulas sobre hoja Mensual.
        Sección MES:    ingresos/vehículos con SUMPRODUCT sobre hoja Mes Actual.
        """
        ws = wb.create_sheet("Resumen")
        ws.sheet_properties.tabColor = "3B82F6"
        MAX = 4   # columnas A-D (sin columna Fuente/Nota)
        M   = self.moneda

        # Nombre exacto de la hoja mensual (creada en _hoja_mensual)
        nom_mensual = f"Mensual {año}"

        # Valores Python para datos que no son fácilmente formulables en Excel
        cancelados_a = int(resumen_año.get("cancelados", 0))
        prom_a       = int(resumen_año.get("prom_minutos", 0))
        prom_a_txt   = (f"{prom_a // 60}h {prom_a % 60:02d}m" if prom_a >= 60
                        else f"{prom_a} min" if prom_a else "—")

        cancelados_m = int(resumen_mes.get("cancelados", 0))
        prom_m       = int(resumen_mes.get("prom_minutos", 0))
        prom_m_txt   = (f"{prom_m // 60}h {prom_m % 60:02d}m" if prom_m >= 60
                        else f"{prom_m} min" if prom_m else "—")

        tick_max  = float(globales.get("ticket_maximo", 0))
        dias_mes  = calendar.monthrange(año, mes)[1]

        # ── Helpers internos ──────────────────────────────────────────────
        def fila(r, label, val, fmt=None, bold_val=True, val_color=None):
            """Escribe label|valor con fondo oscuro. Sin columna de notas."""
            lc = ws.cell(row=r, column=1, value=label)
            lc.fill      = _fill(_C["hdr_bg"])
            lc.font      = _font(_C["sub_txt"], 10)
            lc.alignment = _left()

            vc = ws.cell(row=r, column=2, value=val)
            vc.fill      = _fill(_C["hdr_bg"])
            vc.font      = _font(val_color or _C["white"], 11, bold=bold_val)
            vc.alignment = _right()
            vc.border    = _thin_border("bottom")
            if fmt:
                vc.number_format = fmt

            for c in range(3, MAX + 1):
                ws.cell(row=r, column=c).fill = _fill(_C["hdr_bg"])
            ws.row_dimensions[r].height = 20

        def separador(r):
            for c in range(1, MAX + 1):
                ws.cell(row=r, column=c).fill = _fill(_C["title_bg"])
            ws.row_dimensions[r].height = 8

        def seccion(r, titulo, color_tab="title_txt"):
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=MAX)
            cell = ws.cell(row=r, column=1, value=f"  {titulo}")
            cell.fill      = _fill(_C["sub_bg"])
            cell.font      = _font(_C[color_tab], 11, bold=True)
            cell.alignment = _left()
            ws.row_dimensions[r].height = 24

        def mini_hdr(r, cols):
            for c, txt in enumerate(cols, 1):
                cell = ws.cell(row=r, column=c, value=txt)
                cell.fill      = _fill("1A2C44")
                cell.font      = _font(_C["sub_txt"], 9, bold=True)
                cell.alignment = _center() if c > 1 else _left()
            ws.row_dimensions[r].height = 16

        # ── Anchos de columna ─────────────────────────────────────────────
        _set_widths(ws, {1: 40, 2: 28, 3: 10, 4: 10})

        # ══ TÍTULO ════════════════════════════════════════════════════════
        _merge_title(ws, 1, MAX,
                     f"ParkingPro — Reporte de Ingresos  |  {self.negocio}",
                     font_size=16, height=44)

        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=MAX)
        sub = ws.cell(row=2, column=1,
                      value=f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}  "
                            f"|  Moneda: {M}")
        sub.fill      = _fill(_C["title_bg"])
        sub.font      = _font(_C["gray"], 9, italic=True)
        sub.alignment = _center()
        ws.row_dimensions[2].height = 18

        separador(3)

        # ══ SECCIÓN GLOBAL ════════════════════════════════════════════════
        # Fórmulas vivas: COUNTIF/SUMIF referencian la hoja Sesiones
        seccion(4, "GLOBAL — Todo el historial")
        mini_hdr(5, ["Indicador", f"Valor ({M})", "", ""])

        fila(6,  "Sesiones cobradas (historial total)",
             '=COUNTIF(Sesiones!J:J,"Cobrado")',
             fmt="0", val_color=_C["ok_txt"])

        fila(7,  "Sesiones canceladas (historial total)",
             '=COUNTIF(Sesiones!J:J,"Cancelado")',
             fmt="0", val_color=_C["err_txt"])

        fila(8,  "Ingresos totales cobrados",
             '=SUMIF(Sesiones!J:J,"Cobrado",Sesiones!I:I)',
             fmt="#,##0.00", val_color=_C["green"])

        fila(9,  "Ticket más alto registrado",
             tick_max,
             fmt="#,##0.00")

        fila(10, "Ingreso promedio por sesión",
             "=IFERROR(B8/B6,0)",
             fmt="#,##0.00")

        separador(11)

        # ══ SECCIÓN AÑO ═══════════════════════════════════════════════════
        # Vehículos e ingresos referencian la hoja Mensual (fila 15 = TOTAL)
        seccion(12, f"AÑO {año}")
        mini_hdr(13, ["Indicador", "Valor", "", ""])

        fila(14, "Vehículos atendidos (cobrados)",
             f"='{nom_mensual}'!B15",
             fmt="0", val_color=_C["ok_txt"])

        fila(15, "Sesiones canceladas en el año",
             cancelados_a,
             fmt="0", val_color=_C["err_txt"])

        fila(16, "Ingresos del año",
             f"='{nom_mensual}'!C15",
             fmt="#,##0.00", val_color=_C["green"])

        fila(17, "Ingreso promedio diario",
             "=IFERROR(B16/365,0)",
             fmt="#,##0.00")

        fila(18, "Tiempo promedio de visita",
             prom_a_txt)

        separador(19)

        # ══ SECCIÓN MES ACTUAL ════════════════════════════════════════════
        # Vehículos e ingresos con SUMPRODUCT sobre hoja Mes Actual
        seccion(20, f"MES ACTUAL — {MESES_ES[mes - 1]} {año}")
        mini_hdr(21, ["Indicador", "Valor", "", ""])

        fila(22, "Vehículos atendidos (cobrados)",
             "=SUMPRODUCT(('Mes Actual'!A3:A100<>\"TOTAL\")*('Mes Actual'!C3:C100))",
             fmt="0", val_color=_C["ok_txt"])

        fila(23, "Sesiones canceladas este mes",
             cancelados_m,
             fmt="0", val_color=_C["err_txt"])

        fila(24, "Ingresos del mes",
             "=SUMPRODUCT(('Mes Actual'!A3:A100<>\"TOTAL\")*('Mes Actual'!D3:D100))",
             fmt="#,##0.00", val_color=_C["green"])

        fila(25, "Ingreso promedio diario (mes)",
             f"=IFERROR(B24/{dias_mes},0)",
             fmt="#,##0.00")

        fila(26, "Tiempo promedio de visita",
             prom_m_txt)

        separador(27)

        # ══ NOTA FINAL ════════════════════════════════════════════════════
        ws.merge_cells(start_row=28, start_column=1, end_row=28, end_column=MAX)
        nota = ws.cell(row=28, column=1,
                       value="ℹ  Celdas con '=' se recalculan automáticamente "
                             "desde las hojas Sesiones, Mes Actual y Mensual al abrir el archivo.")
        nota.fill      = _fill(_C["title_bg"])
        nota.font      = _font(_C["gray"], 9, italic=True)
        nota.alignment = _left()
        ws.row_dimensions[28].height = 18

    # ─── Hoja 2: Sesiones ─────────────────────────────────────────────────────

    def _hoja_sesiones(self, wb: Workbook, sesiones: List[dict]):
        ws = wb.create_sheet("Sesiones")
        ws.sheet_properties.tabColor = "10B981"
        ws.freeze_panes = "A3"

        COLS = ["Ticket", "Placa", "Tipo Vehículo",
                "Fecha Entrada", "Hora Entrada",
                "Fecha Salida",  "Hora Salida",
                "Duración (min)", f"Monto ({self.moneda})", "Estado"]
        MAX = len(COLS)

        # Título
        _merge_title(ws, 1, MAX, "Detalle de Sesiones Finalizadas",
                     font_size=13, height=30)

        # Cabecera
        _header_row(ws, 2, COLS, heights=[24])

        # Filas de datos
        for idx, ses in enumerate(sesiones):
            r   = idx + 3
            bg  = _C["ok_bg"]  if ses.get("estado") == "cobrado" else (
                  _C["err_bg"] if ses.get("estado") == "cancelado" else None)
            fg  = _C["ok_txt"] if ses.get("estado") == "cobrado" else (
                  _C["err_txt"] if ses.get("estado") == "cancelado" else _C["white"])

            # Parsear fechas
            ent_str, ent_h, sal_str, sal_h = "—", "—", "—", "—"
            try:
                ent = datetime.strptime(ses["hora_entrada"], "%Y-%m-%d %H:%M:%S")
                ent_str = ent.strftime("%d/%m/%Y")
                ent_h   = ent.strftime("%H:%M:%S")
            except Exception:
                pass
            if ses.get("hora_salida"):
                try:
                    sal = datetime.strptime(ses["hora_salida"], "%Y-%m-%d %H:%M:%S")
                    sal_str = sal.strftime("%d/%m/%Y")
                    sal_h   = sal.strftime("%H:%M:%S")
                except Exception:
                    pass

            minutos = ses.get("minutos_total") or 0
            monto   = ses.get("monto")
            estado  = (ses.get("estado") or "").capitalize()

            row_data = [
                ses.get("ticket_numero", ""),
                ses.get("placa", ""),
                ses.get("tipo_vehiculo", ""),
                ent_str, ent_h,
                sal_str, sal_h,
                minutos if minutos else "—",
                round(float(monto), 2) if monto is not None else "—",
                estado,
            ]

            for c, val in enumerate(row_data, 1):
                cell = ws.cell(row=r, column=c, value=val)
                if bg:
                    cell.fill = _fill(bg)
                cell.font  = _font(fg, 9)
                cell.alignment = _center() if c in (1, 4, 5, 6, 7, 8, 10) else _left()
                # Formato numérico para monto
                if c == 9 and isinstance(val, float):
                    cell.number_format = "#,##0.00"
            ws.row_dimensions[r].height = 18

        # Totales en la última fila
        if sesiones:
            last = len(sesiones) + 3
            ws.merge_cells(start_row=last, start_column=1,
                           end_row=last, end_column=8)
            tc = ws.cell(row=last, column=1, value="TOTALES")
            tc.fill = _fill(_C["total_bg"])
            tc.font = _font(_C["total_txt"], 10, bold=True)
            tc.alignment = _right()

            # Total monto (col 9): suma solo cobradas
            cobradas = [s for s in sesiones if s.get("estado") == "cobrado"
                        and s.get("monto") is not None]
            total_monto = sum(float(s["monto"]) for s in cobradas)
            mc = ws.cell(row=last, column=9,
                         value=round(total_monto, 2))
            mc.fill = _fill(_C["total_bg"])
            mc.font = _font(_C["total_txt"], 10, bold=True)
            mc.alignment = _right()
            mc.number_format = "#,##0.00"
            ws.row_dimensions[last].height = 22

        _set_widths(ws, {
            1: 18,   # Ticket
            2: 12,   # Placa
            3: 14,   # Tipo
            4: 14,   # Fecha entrada
            5: 12,   # Hora entrada
            6: 14,   # Fecha salida
            7: 12,   # Hora salida
            8: 16,   # Duración
            9: 14,   # Monto
            10: 12,  # Estado
        })

    # ─── Hoja 3: Últimos 30 Días ──────────────────────────────────────────────

    def _hoja_diario(self, wb: Workbook, diarios: List[dict],
                     fecha_ini: str, fecha_fin: str,
                     año: int = None, mes: int = None):
        """
        Hoja 3 — Ingresos día a día del mes actual.

        Cambio vs versión anterior: antes mostraba los últimos 30 días desde
        hoy; ahora muestra los días del mes en curso (día 1 al último día del mes).
        Cada semana se colorea diferente para facilitar la lectura visual.
        El gráfico de barras usa colores alternados por semana.
        """
        ws = wb.create_sheet("Mes Actual")
        ws.sheet_properties.tabColor = "F59E0B"
        ws.freeze_panes = "A3"

        mes_nombre = MESES_ES[mes - 1] if mes else "Actual"
        COLS = ["Fecha", "Día", "Vehículos", f"Ingresos ({self.moneda})"]
        MAX  = len(COLS)
        LAST = len(diarios) + 2 if diarios else 3

        # Colores por semana para diferenciar grupos de 7 días
        SEMANA_COLORS = ["1E3A5F", "1A2C44", "0F2137", "1E3A5F"]  # 4 semanas

        _merge_title(ws, 1, 9,
                     f"Ingresos por Día — {mes_nombre} {año or ''}",
                     font_size=12, height=28)
        _header_row(ws, 2, COLS, heights=[22])

        if not diarios:
            c = ws.cell(row=3, column=1, value="Sin ingresos registrados en este mes")
            c.font = _font(_C["gray"], 10, italic=True)
            c.fill = _fill(_C["hdr_bg"])
        else:
            total_veh = 0
            total_ing = 0.0

            # Colores alternados de barras (7 días = 1 semana)
            BARRA_COLORS = ["3B82F6", "10B981", "F59E0B", "8B5CF6",
                            "EF4444", "F97316", "06B6D4"]

            for idx, row in enumerate(diarios):
                r    = idx + 3
                semana_idx = idx // 7   # semana 0, 1, 2, 3
                bg   = SEMANA_COLORS[semana_idx % len(SEMANA_COLORS)]

                fecha_obj = None
                fecha_fmt = row.get("fecha", "")
                dia_semana = ""
                try:
                    from datetime import date as _dt
                    fecha_obj  = _dt.fromisoformat(row["fecha"])
                    fecha_fmt  = fecha_obj.strftime("%d/%m/%Y")
                    DIAS_ES    = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
                    dia_semana = DIAS_ES[fecha_obj.weekday()]
                except Exception:
                    pass

                veh = int(row.get("vehiculos", 0))
                ing = float(row.get("ingresos", 0))
                total_veh += veh
                total_ing += ing

                for c, val in enumerate([fecha_fmt, dia_semana, veh, ing], 1):
                    cell = ws.cell(row=r, column=c, value=val)
                    cell.fill = _fill(bg)
                    cell.font = _font(_C["white"], 9)
                    cell.alignment = _center() if c in (1, 2) else _right()
                    if c == 4:
                        cell.number_format = "#,##0.00"
                ws.row_dimensions[r].height = 18

            # Fila de totales
            r_tot = LAST + 1
            for c, val in enumerate(["TOTAL", "", total_veh,
                                      round(total_ing, 2)], 1):
                cell = ws.cell(row=r_tot, column=c, value=val)
                cell.fill = _fill(_C["total_bg"])
                cell.font = _font(_C["total_txt"], 10, bold=True)
                cell.alignment = _right()
                if c == 4:
                    cell.number_format = "#,##0.00"
            ws.row_dimensions[r_tot].height = 22

            # Gráfico con colores alternados por semana de 7 barras
            if len(diarios) >= 1:
                bar_colors = [
                    BARRA_COLORS[i % len(BARRA_COLORS)]
                    for i in range(len(diarios))
                ]
                data = Reference(ws, min_col=4, max_col=4,
                                 min_row=2, max_row=LAST)
                cats = Reference(ws, min_col=1, max_col=1,
                                 min_row=3, max_row=LAST)
                _bar_chart(ws, data, cats,
                           title=f"Ingresos por Día — {mes_nombre}",
                           y_label=f"Ingresos ({self.moneda})",
                           anchor="F2", width=24, height=16,
                           bar_color="3B82F6",
                           colors_per_bar=bar_colors)

        _set_widths(ws, {1: 14, 2: 8, 3: 14, 4: 18})

    # ─── Hoja 4: Por Mes ──────────────────────────────────────────────────────

    def _hoja_mensual(self, wb: Workbook, mensual: List[dict], año: int):
        """
        Hoja 4 — Ingresos por mes del año.

        Cada mes tiene su propio color (12 colores distintos).
        Total en fila 15 con fórmulas SUM para que Resumen pueda referenciarlas.
        """
        ws = wb.create_sheet(f"Mensual {año}")
        ws.sheet_properties.tabColor = "8B5CF6"
        ws.freeze_panes = "A3"

        COLS      = ["Mes", "Vehículos", f"Ingresos ({self.moneda})"]
        LAST_DATA = 14   # fila 3 = Enero … fila 14 = Diciembre
        ROW_TOT   = 15   # total en fila 15

        # 12 colores distintos, uno por mes
        MES_COLORS = [
            "3B82F6",  # Enero   — azul
            "6366F1",  # Febrero — índigo
            "8B5CF6",  # Marzo   — violeta
            "A855F7",  # Abril   — púrpura
            "EC4899",  # Mayo    — rosa
            "F43F5E",  # Junio   — carmesí
            "EF4444",  # Julio   — rojo
            "F97316",  # Agosto  — naranja
            "F59E0B",  # Septiembre — ámbar
            "EAB308",  # Octubre — amarillo
            "84CC16",  # Noviembre  — lima
            "10B981",  # Diciembre  — esmeralda
        ]
        bar_colors = list(MES_COLORS)

        _merge_title(ws, 1, 9,
                     f"Ingresos por Mes — Año {año}",
                     font_size=12, height=28)
        _header_row(ws, 2, COLS, heights=[22])

        mes_map = {d["mes"]: d for d in mensual}

        for m in range(1, 13):
            r   = m + 2           # filas 3..14
            d   = mes_map.get(f"{m:02d}", {})
            bg  = MES_COLORS[m - 1]
            veh = int(d.get("vehiculos", 0))
            ing = float(d.get("ingresos", 0))

            for c, val in enumerate([MESES_ES[m - 1], veh, ing], 1):
                cell = ws.cell(row=r, column=c, value=val)
                # Versión oscurecida del color del mes
                cell.fill = _fill(f"0{bg[1:]}" if bg else _C["alt"])
                cell.font = _font(_C["white"], 9)
                cell.alignment = _left() if c == 1 else _right()
                if c == 3:
                    cell.number_format = "#,##0.00"
            ws.row_dimensions[r].height = 20

        # Total — fórmulas SUM para que Resumen pueda referenciar B15 y C15
        tot_vals = ["TOTAL", "=SUM(B3:B14)", "=SUM(C3:C14)"]
        for c, val in enumerate(tot_vals, 1):
            cell = ws.cell(row=ROW_TOT, column=c, value=val)
            cell.fill = _fill(_C["total_bg"])
            cell.font = _font(_C["total_txt"], 10, bold=True)
            cell.alignment = _right()
            if c == 3:
                cell.number_format = "#,##0.00"
        ws.row_dimensions[ROW_TOT].height = 22

        # Gráfico con color único por mes
        data = Reference(ws, min_col=3, max_col=3,
                         min_row=2, max_row=LAST_DATA)
        cats = Reference(ws, min_col=1, max_col=1,
                         min_row=3, max_row=LAST_DATA)
        _bar_chart(ws, data, cats,
                   title=f"Ingresos Mensuales — {año}",
                   y_label=f"Ingresos ({self.moneda})",
                   anchor="E2", width=24, height=16,
                   bar_color="8B5CF6",
                   colors_per_bar=bar_colors)

        _set_widths(ws, {1: 16, 2: 14, 3: 18})

    # ─── Hoja 5: Por Tipo ─────────────────────────────────────────────────────

    def _hoja_por_tipo(self, wb: Workbook, por_tipo: List[dict]):
        """
        Hoja 5 — Desglose por tipo de vehículo.

        Cada tipo de vehículo tiene su propio color tanto en las filas de la
        tabla como en el gráfico de barras para diferenciación visual inmediata.
        """
        ws = wb.create_sheet("Por Tipo")
        ws.sheet_properties.tabColor = "10B981"
        ws.freeze_panes = "A3"

        COLS = ["Tipo Vehículo", "Cantidad", "% Vehículos",
                f"Ingresos ({self.moneda})", "% Ingresos"]
        MAX  = len(COLS)

        # Color por tipo de vehículo (mismo que en la UI de ParkingPro)
        TIPO_COLORS = {
            "Auto":      "3B82F6",   # azul
            "Moto":      "8B5CF6",   # morado
            "Camioneta": "F59E0B",   # amarillo
            "Bus":       "EF4444",   # rojo
            "Camión":    "F97316",   # naranja
            "Bicicleta": "10B981",   # verde
        }

        _merge_title(ws, 1, 9,
                     "Desglose por Tipo de Vehículo — Histórico Total",
                     font_size=12, height=28)
        _header_row(ws, 2, COLS, heights=[22])

        if not por_tipo:
            c = ws.cell(row=3, column=1, value="Sin datos registrados")
            c.font = _font(_C["gray"], 10, italic=True)
            c.fill = _fill(_C["hdr_bg"])
            _set_widths(ws, {1: 20, 2: 14, 3: 14, 4: 20, 5: 14})
            return

        total_veh = sum(int(r.get("cantidad",  0)) for r in por_tipo)
        total_ing = sum(float(r.get("ingresos", 0)) for r in por_tipo)
        bar_colors_chart = []   # colores para el gráfico

        for idx, row in enumerate(por_tipo):
            r     = idx + 3
            tipo  = row.get("tipo_vehiculo", "?")
            cant  = int(row.get("cantidad",  0))
            ing   = float(row.get("ingresos", 0))
            pct_v = cant / total_veh * 100 if total_veh else 0
            pct_i = ing  / total_ing * 100 if total_ing else 0
            color = TIPO_COLORS.get(tipo, "64748B")   # gris si no reconocido
            bar_colors_chart.append(color)

            row_vals = [tipo, cant, round(pct_v, 1),
                        round(ing, 2), round(pct_i, 1)]
            for c, val in enumerate(row_vals, 1):
                cell = ws.cell(row=r, column=c, value=val)
                # Fondo oscuro del color del tipo (versión muy oscura)
                cell.fill = _fill(f"0{color[1:]}" if color else _C["alt"])
                cell.font = _font(_C["white"], 9,
                                  bold=(c == 1))   # negrita para el nombre
                cell.alignment = _left() if c == 1 else _right()
                if c == 4:
                    cell.number_format = "#,##0.00"
                if c in (3, 5):
                    cell.number_format = "0.0\"%\""
            ws.row_dimensions[r].height = 22

        # Fila de totales
        r_tot = len(por_tipo) + 3
        for c, val in enumerate(["TOTAL", total_veh, 100.0,
                                  round(total_ing, 2), 100.0], 1):
            cell = ws.cell(row=r_tot, column=c, value=val)
            cell.fill = _fill(_C["total_bg"])
            cell.font = _font(_C["total_txt"], 10, bold=True)
            cell.alignment = _right()
            if c == 4:
                cell.number_format = "#,##0.00"
            if c in (3, 5):
                cell.number_format = "0.0\"%\""
        ws.row_dimensions[r_tot].height = 22

        # Gráfico de ingresos por tipo — cada barra con el color de su tipo
        last_data = len(por_tipo) + 2
        data = Reference(ws, min_col=4, max_col=4,
                         min_row=2, max_row=last_data)
        cats = Reference(ws, min_col=1, max_col=1,
                         min_row=3, max_row=last_data)
        _bar_chart(ws, data, cats,
                   title="Ingresos por Tipo de Vehículo",
                   y_label=f"Ingresos ({self.moneda})",
                   anchor="G2", width=20, height=14,
                   bar_color="10B981",
                   colors_per_bar=bar_colors_chart)

        _set_widths(ws, {1: 18, 2: 14, 3: 14, 4: 20, 5: 14})