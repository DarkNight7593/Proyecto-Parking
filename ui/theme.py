"""
ParkingPro - Tema visual global
Paleta de colores, fuentes y constantes compartidas por todos los paneles.
"""
import customtkinter as ctk

# ─── Paleta de colores (Dark Professional) ───────────────────────────────────
C = {
    # Fondos
    "bg_root":   "#080d14",
    "bg_dark":   "#0f172a",
    "bg_medium": "#1e293b",
    "bg_light":  "#263244",
    "sidebar":   "#0b1120",

    # Bordes
    "border":    "#2d3f55",
    "border_l":  "#374151",

    # Texto
    "text_1":    "#f1f5f9",
    "text_2":    "#94a3b8",
    "text_3":    "#64748b",

    # Accents
    "blue":      "#3b82f6",
    "blue_h":    "#2563eb",
    "blue_d":    "#1d4ed8",
    "green":     "#10b981",
    "green_h":   "#059669",
    "yellow":    "#f59e0b",
    "yellow_h":  "#d97706",
    "red":       "#ef4444",
    "red_h":     "#dc2626",
    "purple":    "#8b5cf6",
    "purple_h":  "#7c3aed",
    "orange":    "#f97316",
    "orange_h":  "#ea6c05",

    # KPI
    "kpi_bg":    "#131e31",
    "kpi_line":  "#3b82f6",
}

# ─── Tipos de vehículo ────────────────────────────────────────────────────────
TIPOS_VEHICULO = [
    {"nombre": "Auto",      "emoji": "🚗", "key": "auto",      "color": C["blue"],   "hover": C["blue_h"]},
    {"nombre": "Moto",      "emoji": "🏍️", "key": "moto",      "color": C["purple"], "hover": C["purple_h"]},
    {"nombre": "Camioneta", "emoji": "🚙", "key": "camioneta", "color": C["yellow"], "hover": C["yellow_h"]},
    {"nombre": "Bus",       "emoji": "🚌", "key": "bus",       "color": C["red"],    "hover": C["red_h"]},
    {"nombre": "Camión",    "emoji": "🚚", "key": "camion",    "color": C["orange"], "hover": C["orange_h"]},
    {"nombre": "Bicicleta", "emoji": "🚲", "key": "bicicleta", "color": C["green"],  "hover": C["green_h"]},
]

TIPO_POR_NOMBRE = {t["nombre"]: t for t in TIPOS_VEHICULO}
TIPO_POR_CLAVE  = {t["key"]:    t for t in TIPOS_VEHICULO}
NOMBRES_TIPOS   = [t["nombre"] for t in TIPOS_VEHICULO]


# ─── Fuentes ──────────────────────────────────────────────────────────────────

def fuente(size: int = 13, bold: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(family="Helvetica", size=size, weight="bold" if bold else "normal")


def fuente_mono(size: int = 13) -> ctk.CTkFont:
    return ctk.CTkFont(family="Courier", size=size)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def color_tipo(tipo_nombre: str) -> str:
    tipo = TIPO_POR_NOMBRE.get(tipo_nombre) or TIPO_POR_CLAVE.get(tipo_nombre.lower())
    return tipo["color"] if tipo else C["blue"]


def hover_tipo(tipo_nombre: str) -> str:
    tipo = TIPO_POR_NOMBRE.get(tipo_nombre) or TIPO_POR_CLAVE.get(tipo_nombre.lower())
    return tipo["hover"] if tipo else C["blue_h"]


def emoji_tipo(tipo_nombre: str) -> str:
    tipo = TIPO_POR_NOMBRE.get(tipo_nombre) or TIPO_POR_CLAVE.get(tipo_nombre.lower())
    return tipo["emoji"] if tipo else "🚘"