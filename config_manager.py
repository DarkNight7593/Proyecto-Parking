"""
ParkingPro - Gestor de configuración
Lee y escribe config.ini con todos los parámetros del negocio.
"""
import configparser
import os
import sys


class ConfigManager:
    """Maneja toda la configuración persistente de la aplicación."""

    DEFAULT_CONFIG = {
        "negocio": {
            "nombre":    "Mi Estacionamiento",
            "direccion": "",
            "telefono":  "",
            "ruc":       "",
        },
        "impresora": {
            "nombre":    "TicketeraEstacionamiento",
            "activa":    "true",
            "papel_mm":  "80",
        },
        "sistema": {
            "version":          "1.0.0",
            "db_path":          "parkingpro.db",
            "moneda":           "S/",
            "tiempo_libre_min": "0",
        },
        "tarifas": {
            "auto":       "2.0",
            "moto":       "1.5",
            "camioneta":  "3.0",
            "bus":        "5.0",
            "camion":     "5.0",
            "bicicleta":  "1.0",
        },
    }

    TIPOS_CLAVE = ["auto", "moto", "camioneta", "bus", "camion", "bicicleta"]

    def __init__(self, config_path: str = None):
        if config_path is None:
            base = (
                os.path.dirname(sys.executable)
                if getattr(sys, "frozen", False)
                else os.path.dirname(os.path.abspath(__file__))
            )
            config_path = os.path.join(base, "config.ini")

        self.config_path = config_path
        self.config = configparser.ConfigParser()
        self._cargar()

    def _cargar(self):
        if not os.path.exists(self.config_path):
            self._crear_default()
        else:
            self.config.read(self.config_path, encoding="utf-8")
            # Asegura que todas las secciones y claves del default existan
            for seccion, valores in self.DEFAULT_CONFIG.items():
                if not self.config.has_section(seccion):
                    self.config.add_section(seccion)
                for clave, valor in valores.items():
                    if not self.config.has_option(seccion, clave):
                        self.config.set(seccion, clave, valor)
            self._guardar()

    def _crear_default(self):
        for seccion, valores in self.DEFAULT_CONFIG.items():
            self.config[seccion] = valores
        self._guardar()

    def _guardar(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            self.config.write(f)

    # ─── Acceso genérico ──────────────────────────────────────────────────────

    def get(self, seccion: str, clave: str, fallback=None) -> str:
        return self.config.get(seccion, clave, fallback=fallback)

    def set(self, seccion: str, clave: str, valor: str):
        if not self.config.has_section(seccion):
            self.config.add_section(seccion)
        self.config.set(seccion, clave, str(valor))
        self._guardar()

    def getbool(self, seccion: str, clave: str, fallback: bool = False) -> bool:
        return self.config.getboolean(seccion, clave, fallback=fallback)

    def getfloat(self, seccion: str, clave: str, fallback: float = 0.0) -> float:
        try:
            return float(self.config.get(seccion, clave, fallback=str(fallback)))
        except (ValueError, TypeError):
            return fallback

    def getint(self, seccion: str, clave: str, fallback: int = 0) -> int:
        try:
            return int(self.config.get(seccion, clave, fallback=str(fallback)))
        except (ValueError, TypeError):
            return fallback

    # ─── Acceso tipado ────────────────────────────────────────────────────────

    def get_nombre_negocio(self) -> str:
        return self.get("negocio", "nombre", fallback="Mi Estacionamiento")

    def get_nombre_impresora(self) -> str:
        return self.get("impresora", "nombre", fallback="TicketeraEstacionamiento")

    def get_moneda(self) -> str:
        return self.get("sistema", "moneda", fallback="S/")

    def get_tiempo_libre(self) -> int:
        return self.getint("sistema", "tiempo_libre_min", fallback=0)

    def get_tarifa(self, tipo_vehiculo: str) -> float:
        clave = (
            tipo_vehiculo.lower()
            .replace(" ", "_")
            .replace("o\u0301", "o")
            .replace("a\u0301", "a")
            .replace("\u00f3", "o")
            .replace("\u00e1", "a")
        )
        return self.getfloat("tarifas", clave, fallback=2.0)

    def set_tarifa(self, tipo_vehiculo: str, precio: float):
        clave = (
            tipo_vehiculo.lower()
            .replace(" ", "_")
            .replace("\u00f3", "o")
            .replace("\u00e1", "a")
        )
        self.set("tarifas", clave, f"{precio:.2f}")

    def get_all_tarifas(self) -> dict:
        return {tipo: self.getfloat("tarifas", tipo, fallback=2.0) for tipo in self.TIPOS_CLAVE}

    def get_db_path(self) -> str:
        db_path = self.get("sistema", "db_path", fallback="parkingpro.db")
        if not os.path.isabs(db_path):
            base = (
                os.path.dirname(sys.executable)
                if getattr(sys, "frozen", False)
                else os.path.dirname(os.path.abspath(__file__))
            )
            db_path = os.path.join(base, db_path)
        return db_path

    def get_datos_negocio(self) -> dict:
        return {
            "nombre":    self.get("negocio", "nombre",    fallback=""),
            "direccion": self.get("negocio", "direccion", fallback=""),
            "telefono":  self.get("negocio", "telefono",  fallback=""),
            "ruc":       self.get("negocio", "ruc",       fallback=""),
        }

    def set_datos_negocio(self, nombre: str, direccion: str, telefono: str, ruc: str):
        self.set("negocio", "nombre",    nombre)
        self.set("negocio", "direccion", direccion)
        self.set("negocio", "telefono",  telefono)
        self.set("negocio", "ruc",       ruc)