"""
ParkingPro - Exportador de reportes a Excel (.xlsx)

Una sola hoja "Sesiones":
  • Sesiones agrupadas por Día con una fila de encabezado grande.
  • Fila "Total Ganancias" al final de cada día, mostrando monto y CANTIDAD de vehículos cobrados.
  • Gráfico único a la derecha: ingresos por mes del año actual (Multicolor + Leyenda).
"""
import calendar
from collections import OrderedDict
from datetime import date, datetime
from typing import List, Dict

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.chart import BarChart, Reference, Series
from openpyxl.utils import get_column_letter

# ── Paleta de colores ──────────────────────────────────────────────────────────
_C = {
    "hdr_bg":    "1E293B",
    "hdr_txt":   "F8FAFC",
    "sub_bg":    "1E293B",
    "sub_txt":   "CBD5E1",
    "title_bg":  "0B1120",
    "title_txt": "3B82F6",
    "alt":       "0F172A",
    "ok_bg":     "022C22",
    "ok_txt":    "10B981",
    "err_bg":    "3F1115",
    "err_txt":   "F43F5E",
    "total_bg":  "0F172A",
    "total_txt": "3B82F6",
    "border":    "334155",
    "white":     "FFFFFF",
    "green":     "10B981",
    "blue":      "3B82F6",
    "gray":      "64748B",
    "day_bg":    "1E293B",
    "day_txt":   "F8FAFC",
    "chart_bg":  "0F172A",
}

MESES_ES = [
    "Enero","Febrero","Marzo","Abril","Mayo","Junio",
    "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre",
]

# 12 colores, uno por mes para el gráfico
MES_COLORS = [
    "3B82F6","6366F1","8B5CF6","A855F7",
    "EC4899","F43F5E","EF4444","F97316",
    "F59E0B","EAB308","84CC16","10B981",
]

# ── Helpers de estilo ─────────────────────────────────────────────────────────

def _fill(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color)

def _font(color: str = "FFFFFF", size: int = 10, bold: bool = False, italic: bool = False) -> Font:
    return Font(name="Arial", size=size, bold=bold, italic=italic, color=color)

def _center(wrap: bool = False) -> Alignment:
    return Alignment(horizontal="center", vertical="center", wrap_text=wrap)

def _left() -> Alignment:
    return Alignment(horizontal="left", vertical="center")

def _right() -> Alignment:
    return Alignment(horizontal="right", vertical="center")

def _thin_border(sides: str = "bottom") -> Border:
    thin = Side(style="thin", color=_C["border"])
    return Border(
        top=    thin if "top"    in sides else None,
        bottom= thin if "bottom" in sides else None,
        left=   thin if "left"   in sides else None,
        right=  thin if "right"  in sides else None,
    )

def _set_widths(ws, widths: Dict[int, float]):
    for idx, w in widths.items():
        ws.column_dimensions[get_column_letter(idx)].width = w

def _merge_title(ws, row: int, max_col: int, text: str, font_size: int = 16, height: int = 36):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max_col)
    cell = ws.cell(row=row, column=1, value=text)
    cell.fill      = _fill(_C["title_bg"])
    cell.font      = _font(_C["title_txt"], font_size, bold=True)
    cell.alignment = _center()
    ws.row_dimensions[row].height = height


# ── Clase principal ────────────────────────────────────────────────────────────

class ExcelExporter:
    """Genera el reporte Excel de ParkingPro (hoja única)."""

    def __init__(self, db, config):
        self.db      = db
        self.config  = config
        self.moneda  = config.get_moneda()
        self.negocio = config.get_nombre_negocio()

    def exportar(self, ruta: str):
        hoy     = date.today()
        año_act = hoy.year

        sesiones    = self.db.get_historial(limit=50_000)
        mensual_act = self.db.get_ingresos_por_mes_en_año(año_act)

        wb = Workbook()
        wb.remove(wb.active)

        self._hoja_sesiones(wb, sesiones, mensual_act, año_act)
        wb.save(ruta)

    def _hoja_sesiones(self, wb: Workbook, sesiones: List[dict], mensual_act: List[dict], año_act: int):
        ws = wb.create_sheet("Sesiones")
        ws.sheet_properties.tabColor = "3B82F6"
        ws.sheet_view.showGridLines = False  # Modo oscuro limpio, sin fondo forzado
        ws.freeze_panes = "A4"               # Congelar cabeceras

        M       = self.moneda
        N_COLS  = 8   # Fin de la tabla principal
        C_TKT = 1
        C_PLA = 2
        C_TIP = 3
        C_ENT = 4
        C_SAL = 5
        C_MIN = 6
        C_MNT = 7
        C_EST = 8

        # ── Fila 1 y 2: Títulos ──────────────────────────────────────────────
        _merge_title(ws, 1, N_COLS, f"ParkingPro — Registro de Sesiones  |  {self.negocio}", 14, 38)
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=N_COLS)
        sub = ws.cell(row=2, column=1, value=f"Exportado: {datetime.now().strftime('%d/%m/%Y  %H:%M')}   |   Moneda: {M}")
        sub.fill      = _fill(_C["title_bg"])
        sub.font      = _font(_C["gray"], 9, italic=True)
        sub.alignment = _center()
        ws.row_dimensions[2].height = 16

        # ── Fila 3: Cabeceras de Columnas (Tabla Principal) ──────────────────
        CABECERAS = ["Ticket", "Placa", "Tipo", "H. Entrada", "H. Salida", "Minutos", f"Monto ({M})", "Estado"]
        for c, label in enumerate(CABECERAS, 1):
            cell = ws.cell(row=3, column=c, value=label)
            cell.fill      = _fill(_C["hdr_bg"])
            cell.font      = _font(_C["hdr_txt"], 10, bold=True)
            cell.alignment = _center()
            cell.border    = _thin_border("bottom")
        ws.row_dimensions[3].height = 22

        # ── Agrupación de datos ──────────────────────────────────────────────
        year_data = OrderedDict()
        for ses in sesiones:
            try:
                ent = datetime.strptime(ses["hora_entrada"], "%Y-%m-%d %H:%M:%S")
                y, m, d = ent.year, ent.month, ent.day
            except Exception:
                continue

            if y not in year_data: year_data[y] = OrderedDict()
            if m not in year_data[y]: year_data[y][m] = OrderedDict()
            if d not in year_data[y][m]: year_data[y][m][d] = []
            year_data[y][m][d].append(ses)

        # ── Renderizado de la tabla ──────────────────────────────────────────
        current_row = 4

        if not year_data:
            ws.merge_cells(start_row=4, start_column=1, end_row=4, end_column=N_COLS)
            empty = ws.cell(row=4, column=1, value="Sin sesiones finalizadas registradas")
            empty.fill = _fill(_C["hdr_bg"]); empty.font = _font(_C["gray"], 11, italic=True)
            empty.alignment = _center()
            current_row = 5
        else:
            for year in year_data:
                for month in year_data[year]:
                    for day in year_data[year][month]:
                        sesiones_dia = year_data[year][month][day]
                        
                        # 1. ENCABEZADO GIGANTE DEL DÍA
                        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=N_COLS)
                        fecha_str = f"{day} de {MESES_ES[month-1]} del {year}"
                        c_dia = ws.cell(row=current_row, column=1, value=f"  📅 {fecha_str}")
                        c_dia.fill = _fill(_C["day_bg"])
                        c_dia.font = _font(_C["day_txt"], 12, bold=True)
                        c_dia.alignment = _left()
                        ws.row_dimensions[current_row].height = 26
                        current_row += 1

                        total_dia = 0.0
                        veh_cobrados = 0  # <--- NUEVO CONTADOR

                        # 2. FILAS DE SESIONES
                        for idx, ses in enumerate(sesiones_dia):
                            try:
                                h_ent = datetime.strptime(ses["hora_entrada"], "%Y-%m-%d %H:%M:%S").strftime("%I:%M %p")
                            except: h_ent = "—"
                            
                            h_sal = "—"
                            if ses.get("hora_salida"):
                                try: h_sal = datetime.strptime(ses["hora_salida"], "%Y-%m-%d %H:%M:%S").strftime("%I:%M %p")
                                except: pass

                            monto = ses.get("monto")
                            monto_v = round(float(monto), 2) if monto is not None else "—"
                            estado = (ses.get("estado") or "").capitalize()
                            
                            if estado == "Cobrado":
                                total_dia += (float(monto) if monto else 0.0)
                                veh_cobrados += 1  # <--- INCREMENTAMOS CONTADOR
                                row_bg, row_fg = _C["ok_bg"], _C["ok_txt"]
                            elif estado == "Cancelado":
                                row_bg, row_fg = _C["err_bg"], _C["err_txt"]
                            else:
                                row_bg, row_fg = (_C["sub_bg"] if idx % 2 == 0 else _C["alt"]), _C["white"]

                            datos = [
                                (C_TKT, ses.get("ticket_numero", ""), "left"),
                                (C_PLA, ses.get("placa", ""), "left"),
                                (C_TIP, ses.get("tipo_vehiculo", ""), "left"),
                                (C_ENT, h_ent, "center"),
                                (C_SAL, h_sal, "center"),
                                (C_MIN, ses.get("minutos_total") or "—", "center"),
                                (C_MNT, monto_v, "right"),
                                (C_EST, estado, "center"),
                            ]

                            for col, val, aln in datos:
                                cell = ws.cell(row=current_row, column=col, value=val)
                                cell.fill = _fill(row_bg)
                                cell.font = _font(row_fg, 10, bold=(col == C_PLA or col == C_MNT))
                                cell.alignment = (_left() if aln == "left" else _right() if aln == "right" else _center())
                                if col == C_MNT and isinstance(val, float): cell.number_format = "#,##0.00"
                            
                            ws.row_dimensions[current_row].height = 18
                            current_row += 1
                        
                        # 3. TOTAL DEL DÍA (Ahora incluye cantidad de vehículos cobrados)
                        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=C_MNT - 1)
                        
                        texto_total = f"Total Ingresos del Día ({veh_cobrados} vehículos cobrados):"
                        c_tot = ws.cell(row=current_row, column=1, value=texto_total)
                        c_tot.fill = _fill(_C["hdr_bg"])
                        c_tot.font = _font(_C["gray"], 10, bold=True)
                        c_tot.alignment = _right()

                        c_monto = ws.cell(row=current_row, column=C_MNT, value=total_dia)
                        c_monto.fill = _fill(_C["hdr_bg"])
                        c_monto.font = _font(_C["green"], 11, bold=True)
                        c_monto.alignment = _right()
                        c_monto.number_format = '"S/" #,##0.00'

                        ws.cell(row=current_row, column=C_EST, value="").fill = _fill(_C["hdr_bg"])
                        ws.row_dimensions[current_row].height = 22
                        current_row += 2 # Salto de línea limpio entre días

        # ── Anchos de columnas ───────────────────────────────────────────────
        _set_widths(ws, {
            1: 15, 2: 12, 3: 13, 4: 12, 5: 12, 6: 10, 7: 14, 8: 12,
            9: 4, 10: 4,   # Columnas 9 y 10 vacías para separar la tabla
            11: 12, 12: 14 # Columnas K y L para los datos del gráfico
        })

        # ── Gráfico Mensual y su Tabla Independiente ─────────────────────────
        COL_DATA = 11  # Columna K
        fila_grafico = 4

        mes_map = {int(d["mes"]): float(d.get("ingresos", 0)) for d in mensual_act}

        # Encabezado para la tablita de datos del gráfico
        c_h1 = ws.cell(row=3, column=COL_DATA, value="Mes")
        c_h1.fill = _fill(_C["hdr_bg"]); c_h1.font = _font(_C["hdr_txt"], 10, bold=True); c_h1.alignment = _center()
        
        c_h2 = ws.cell(row=3, column=COL_DATA + 1, value=f"Total ({M})")
        c_h2.fill = _fill(_C["hdr_bg"]); c_h2.font = _font(_C["hdr_txt"], 10, bold=True); c_h2.alignment = _center()

        chart = BarChart()
        chart.type = "col"
        chart.grouping = "clustered"
        chart.style = 13
        chart.title = f"Ingresos Mensuales ({año_act})"
        chart.y_axis.title = f"Monto ({M})"
        chart.width = 18
        chart.height = 12

        # Rellenar la tabla de datos y añadir al gráfico
        for i, mes_name in enumerate(MESES_ES):
            r = fila_grafico + i
            ingreso = mes_map.get(i + 1, 0.0)
            
            c_mes = ws.cell(row=r, column=COL_DATA, value=mes_name)
            c_val = ws.cell(row=r, column=COL_DATA + 1, value=ingreso)
            
            # Estilo de la tablita (intercalado igual que la tabla principal)
            row_bg = _C["sub_bg"] if i % 2 == 0 else _C["alt"]
            c_mes.fill = _fill(row_bg); c_mes.font = _font(_C["white"], 10); c_mes.alignment = _left()
            c_val.fill = _fill(row_bg); c_val.font = _font(_C["white"], 10); c_val.alignment = _right()
            c_val.number_format = '#,##0.00'

            # Referenciar esta fila como serie para el gráfico
            data_ref = Reference(ws, min_col=COL_DATA+1, min_row=r, max_row=r)
            serie = Series(data_ref, title=mes_name)
            
            color_hex = MES_COLORS[i]
            serie.graphicalProperties.solidFill = color_hex
            serie.graphicalProperties.line.solidFill = color_hex
            chart.series.append(serie)
        
        # Colocar el gráfico separado de la tabla (Columna N)
        ws.add_chart(chart, "N4")