"""
ParkingPro - Panel de Configuración
Tabs: Negocio | Tarifas | Impresora
"""
import threading
import customtkinter as ctk
from tkinter import messagebox
from typing import Dict, List, Optional

from ui.theme import C, fuente, TIPOS_VEHICULO
from installer import PrinterInstaller


class PanelConfiguracion(ctk.CTkFrame):
    """
    Panel de configuración con tres pestañas:
      • Negocio   — datos del negocio y moneda
      • Tarifas   — precio/hora por tipo + tiempo libre
      • Impresora — selección de ticketera desde lista instalada
    """

    def __init__(self, parent, config, db, printer, on_guardado=None, **kwargs):
        super().__init__(parent, fg_color=C["bg_dark"], corner_radius=0, **kwargs)
        self.config      = config
        self.db          = db
        self.printer     = printer
        self.on_guardado = on_guardado
        self._build_ui()

    def set_printer(self, printer):
        self.printer = printer

    # ─── Layout ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        hdr = ctk.CTkFrame(self, fg_color=C["sidebar"], height=56, corner_radius=0)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="⚙️  Configuración del Sistema",
                     font=fuente(17, bold=True), text_color=C["text_1"]).pack(side="left", padx=24)

        self._tabs = ctk.CTkTabview(
            self,
            fg_color=C["bg_medium"],
            segmented_button_fg_color=C["bg_dark"],
            segmented_button_selected_color=C["blue"],
            segmented_button_selected_hover_color=C["blue_h"],
            segmented_button_unselected_color=C["bg_dark"],
            segmented_button_unselected_hover_color=C["bg_light"],
            text_color=C["text_1"],
            corner_radius=14,
        )
        self._tabs.pack(fill="both", expand=True, padx=20, pady=12)

        for tab in ("🏢  Negocio", "💰  Tarifas", "🖨️  Impresora"):
            self._tabs.add(tab)

        self._build_tab_negocio(self._tabs.tab("🏢  Negocio"))
        self._build_tab_tarifas(self._tabs.tab("💰  Tarifas"))
        self._build_tab_impresora(self._tabs.tab("🖨️  Impresora"))

    # ─── Tab: Negocio ─────────────────────────────────────────────────────────

    def _build_tab_negocio(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent",
                                         scrollbar_fg_color=C["bg_light"])
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        self._entries_negocio: Dict[str, ctk.CTkEntry] = {}

        self._seccion(scroll, "Datos del Negocio")
        datos = self.config.get_datos_negocio()
        for label, key, valor in [
            ("Nombre del estacionamiento", "nombre",    datos["nombre"]),
            ("Dirección",                  "direccion", datos["direccion"]),
            ("Teléfono",                   "telefono",  datos["telefono"]),
            ("RUC / N° Documento",         "ruc",       datos["ruc"]),
        ]:
            self._entries_negocio[key] = self._campo_entrada(scroll, label, valor)

        self._seccion(scroll, "Sistema")
        self._entry_moneda = self._campo_entrada(
            scroll, "Símbolo de moneda (ej: S/, $, €)", self.config.get_moneda())
        self._entry_tl = self._campo_entrada(
            scroll, "Tiempo libre / tolerancia (minutos)",
            str(self.config.get_tiempo_libre()))

        ctk.CTkButton(
            scroll, text="💾  Guardar Datos del Negocio",
            fg_color=C["blue"], hover_color=C["blue_h"],
            text_color="white", font=fuente(13, bold=True),
            height=42, command=self._guardar_negocio,
        ).pack(pady=(20, 6))

    def _guardar_negocio(self):
        e = self._entries_negocio
        self.config.set_datos_negocio(
            e["nombre"].get().strip() or "Mi Estacionamiento",
            e["direccion"].get().strip(),
            e["telefono"].get().strip(),
            e["ruc"].get().strip(),
        )
        moneda = self._entry_moneda.get().strip()
        if moneda:
            self.config.set("sistema", "moneda", moneda)

        error_tl = False
        try:
            val_tl = max(0, int(self._entry_tl.get().strip()))
            self.config.set("sistema", "tiempo_libre_min", str(val_tl))
            self._entry_tl.configure(border_color=C["border"])
            if hasattr(self, "_entry_tl_tarifas"):
                try:
                    self._entry_tl_tarifas.delete(0, "end")
                    self._entry_tl_tarifas.insert(0, str(val_tl))
                    self._entry_tl_tarifas.configure(border_color=C["border"])
                except Exception:
                    pass
        except ValueError:
            self._entry_tl.configure(border_color=C["red"])
            error_tl = True

        if error_tl:
            messagebox.showwarning(
                "Advertencia",
                "El tiempo libre ingresado no es válido.\nLos demás datos se guardaron.")
        else:
            messagebox.showinfo("✅ Guardado", "Datos del negocio guardados correctamente.")

        if self.on_guardado:
            self.on_guardado()

    # ─── Tab: Tarifas ─────────────────────────────────────────────────────────

    def _build_tab_tarifas(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent",
                                         scrollbar_fg_color=C["bg_light"])
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        self._seccion(scroll, "Precio por Hora — por Tipo de Vehículo")
        ctk.CTkLabel(scroll,
                     text="Tarifa que se cobra por cada hora de estacionamiento.",
                     font=fuente(11), text_color=C["text_3"],
                     ).pack(anchor="w", padx=10, pady=(0, 12))

        self._entries_tarifas: Dict[str, ctk.CTkEntry] = {}
        tarifas = self.config.get_all_tarifas()

        grid = ctk.CTkFrame(scroll, fg_color="transparent")
        grid.pack(fill="x", padx=4)
        for i, tipo in enumerate(TIPOS_VEHICULO):
            fila, col = divmod(i, 2)
            card = self._tarifa_card(grid, tipo, tarifas.get(tipo["key"], 2.0))
            card.grid(row=fila, column=col, padx=8, pady=6, sticky="ew")
            grid.grid_columnconfigure(col, weight=1)

        self._seccion(scroll, "Tolerancia / Tiempo Libre")
        fila_tl = ctk.CTkFrame(scroll, fg_color=C["bg_dark"], corner_radius=10)
        fila_tl.pack(fill="x", padx=4, pady=4)
        ctk.CTkLabel(fila_tl, text="Minutos de gracia antes de empezar a cobrar:",
                     font=fuente(12), text_color=C["text_2"]).pack(side="left", padx=16, pady=14)
        self._entry_tl_tarifas = ctk.CTkEntry(
            fila_tl, fg_color=C["bg_medium"], border_color=C["border"],
            text_color=C["text_1"], height=36, width=80, justify="center",
        )
        self._entry_tl_tarifas.insert(0, str(self.config.get_tiempo_libre()))
        self._entry_tl_tarifas.pack(side="right", padx=16, pady=14)

        ctk.CTkButton(
            scroll, text="💾  Guardar Tarifas",
            fg_color=C["green"], hover_color=C["green_h"],
            text_color="white", font=fuente(13, bold=True),
            height=42, command=self._guardar_tarifas,
        ).pack(pady=(20, 6))

    def _tarifa_card(self, parent, tipo: Dict, tarifa_actual: float) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=C["bg_dark"], corner_radius=14)
        ctk.CTkFrame(card, fg_color=tipo["color"], height=4, corner_radius=0).pack(fill="x")
        cuerpo = ctk.CTkFrame(card, fg_color="transparent")
        cuerpo.pack(fill="x", padx=14, pady=10)
        ctk.CTkLabel(cuerpo, text=f"{tipo['emoji']}  {tipo['nombre']}",
                     font=fuente(14, bold=True), text_color=tipo["color"],
                     anchor="w").pack(fill="x")
        fila_precio = ctk.CTkFrame(cuerpo, fg_color="transparent")
        fila_precio.pack(fill="x", pady=(6, 0))
        ctk.CTkLabel(fila_precio, text=self.config.get_moneda(),
                     font=fuente(13), text_color=C["text_2"]).pack(side="left")
        entry = ctk.CTkEntry(
            fila_precio,
            fg_color=C["bg_medium"], border_color=tipo["color"], border_width=1,
            text_color=tipo["color"], font=fuente(16, bold=True),
            height=36, width=90, justify="center",
        )
        entry.insert(0, f"{tarifa_actual:.2f}")
        entry.pack(side="left", padx=4)
        ctk.CTkLabel(fila_precio, text="/ hr",
                     font=fuente(11), text_color=C["text_3"]).pack(side="left")
        self._entries_tarifas[tipo["key"]] = entry
        return card

    def _guardar_tarifas(self):
        errores = []
        for key, entry in self._entries_tarifas.items():
            tipo = next((t for t in TIPOS_VEHICULO if t["key"] == key), None)
            color_orig = tipo["color"] if tipo else C["border"]
            try:
                val = float(entry.get().strip().replace(",", "."))
                if val < 0:
                    raise ValueError
                self.config.set_tarifa(key, val)
                entry.configure(border_color=color_orig)
            except ValueError:
                errores.append(key)
                entry.configure(border_color=C["red"])

        try:
            val_tl = max(0, int(self._entry_tl_tarifas.get().strip()))
            self.config.set("sistema", "tiempo_libre_min", str(val_tl))
            self._entry_tl_tarifas.configure(border_color=C["border"])
            if hasattr(self, "_entry_tl"):
                try:
                    self._entry_tl.delete(0, "end")
                    self._entry_tl.insert(0, str(val_tl))
                    self._entry_tl.configure(border_color=C["border"])
                except Exception:
                    pass
        except ValueError:
            errores.append("Tiempo libre")
            self._entry_tl_tarifas.configure(border_color=C["red"])

        if errores:
            messagebox.showwarning("Advertencia",
                                   f"Valores inválidos en: {', '.join(errores)}\n"
                                   "Los demás se guardaron correctamente.")
        else:
            messagebox.showinfo("✅ Guardado", "Tarifas guardadas correctamente.")

        if self.on_guardado:
            self.on_guardado()

    # ─── Tab: Impresora ───────────────────────────────────────────────────────

    def _build_tab_impresora(self, parent):
        self._imp_seleccionada: str = self.config.get_nombre_impresora()

        # ── Botones de acción fijos en la parte inferior ──────────────────
        # Se empaquetan ANTES que el scroll para que siempre estén visibles
        btns_frame = ctk.CTkFrame(parent, fg_color=C["bg_dark"], corner_radius=0)
        btns_frame.pack(side="bottom", fill="x", padx=4, pady=(4, 6))

        btns_inner = ctk.CTkFrame(btns_frame, fg_color="transparent")
        btns_inner.pack(pady=6)

        ctk.CTkButton(
            btns_inner, text="🔄  Actualizar Lista",
            fg_color=C["bg_light"], hover_color=C["border"],
            text_color=C["text_1"], font=fuente(12), height=40, width=180,
            command=self._escanear,
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btns_inner, text="🧪  Página de Prueba",
            fg_color=C["bg_dark"], hover_color=C["bg_light"],
            text_color=C["text_2"], font=fuente(12), height=40, width=160,
            border_color=C["border"], border_width=1,
            command=self._test_impresora,
        ).pack(side="left", padx=5)

        # ── Contenido scrollable ──────────────────────────────────────────
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent",
                                         scrollbar_fg_color=C["bg_light"])
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        # ── Ticketera activa ──────────────────────────────────────────────
        self._seccion(scroll, "Ticketera Activa")

        self._card_activa = ctk.CTkFrame(scroll, fg_color=C["bg_dark"], corner_radius=12,
                                          border_color=C["green"], border_width=2)
        self._card_activa.pack(fill="x", padx=4, pady=(0, 4))

        fila_act = ctk.CTkFrame(self._card_activa, fg_color="transparent")
        fila_act.pack(fill="x", padx=16, pady=12)

        self._lbl_imp_activa = ctk.CTkLabel(
            fila_act,
            text=f"🖨️  {self._imp_seleccionada}",
            font=fuente(14, bold=True), text_color=C["green"], anchor="w",
        )
        self._lbl_imp_activa.pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            fila_act, text="🧪 Prueba",
            fg_color=C["bg_medium"], hover_color=C["bg_light"],
            text_color=C["text_2"], font=fuente(11), height=34, width=100,
            command=self._test_impresora,
        ).pack(side="right")

        self._lbl_estado_imp = ctk.CTkLabel(
            self._card_activa, text="Verificando estado real...",
            font=fuente(11), text_color=C["text_3"],
        )
        self._lbl_estado_imp.pack(anchor="w", padx=16, pady=(0, 10))

        # ── Lista de impresoras instaladas (scroll propio) ─────────────────
        self._seccion(scroll, "Impresoras Instaladas en Windows")

        ctk.CTkLabel(
            scroll,
            text="Selecciona la impresora que usarás como ticketera.\n"
                 "⭐ = driver Generic/Text Only (ideal ESC/POS)  •  "
                 "🔄 = cambiar driver a Generic (requiere Admin)",
            font=fuente(11), text_color=C["text_3"], justify="left",
        ).pack(anchor="w", padx=10, pady=(0, 6))

        # Frame con borde que contiene el scroll de la lista
        lista_border = ctk.CTkFrame(scroll, fg_color=C["bg_dark"],
                                     corner_radius=12, border_color=C["border"],
                                     border_width=1)
        lista_border.pack(fill="x", padx=4, pady=(0, 8))

        self._frame_lista = ctk.CTkScrollableFrame(
            lista_border, fg_color="transparent", corner_radius=10,
            height=200,
        )
        self._frame_lista.pack(fill="x", padx=2, pady=2)

        ctk.CTkLabel(self._frame_lista, text="🔄  Cargando impresoras...",
                     font=fuente(12), text_color=C["text_3"]).pack(pady=20)

        # ── Hardware sin driver (scroll propio) ───────────────────────────
        self._seccion(scroll, "Hardware USB Detectado sin Driver")

        ctk.CTkLabel(
            scroll,
            text="Si tu ticketera aparece aquí, instala el driver para poder seleccionarla.",
            font=fuente(11), text_color=C["text_3"],
        ).pack(anchor="w", padx=10, pady=(0, 6))

        hw_border = ctk.CTkFrame(scroll, fg_color=C["bg_dark"],
                                  corner_radius=12, border_color=C["border"],
                                  border_width=1)
        hw_border.pack(fill="x", padx=4, pady=(0, 8))

        self._frame_hw = ctk.CTkScrollableFrame(
            hw_border, fg_color="transparent", corner_radius=10,
            height=110,
        )
        self._frame_hw.pack(fill="x", padx=2, pady=2)

        ctk.CTkLabel(self._frame_hw, text="Presiona 🔄 Actualizar para detectar hardware",
                     font=fuente(11), text_color=C["text_3"]).pack(pady=14)

        # ── Log ───────────────────────────────────────────────────────────
        self._seccion(scroll, "Registro de Actividad")

        self._txt_log = ctk.CTkTextbox(
            scroll, fg_color=C["bg_dark"], text_color=C["text_2"],
            height=60, font=ctk.CTkFont("Courier", 10),
        )
        self._txt_log.pack(fill="x", padx=4, pady=(0, 4))

        self._log("Sistema listo. Presiona 🔄 Actualizar para ver las impresoras.")

        # Auto-escanear y verificar estado real
        self.after(300, self._escanear)
        self.after(400, self._actualizar_estado_badge)
        # Loop de verificación periódica del estado real de la impresora
        self.after(15_000, self._loop_estado_imp)

    # ─── Verificación de estado en tiempo real ────────────────────────────────

    def _actualizar_estado_badge(self):
        """
        Actualiza el badge de la ticketera activa con estado REAL de Windows.
        No usa el config guardado — consulta directamente al sistema.
        """
        try:
            estado = self.printer.get_estado_detallado()
            nivel  = estado["nivel"]
            msg    = estado["mensaje"]

            if nivel == "ok":
                color_borde = C["green"]
                color_txt   = C["green"]
                color_titulo = C["green"]
            elif nivel == "warning":
                color_borde = C["yellow"]
                color_txt   = C["yellow"]
                color_titulo = C["text_1"]
            elif nivel == "error":
                color_borde = C["red"]
                color_txt   = C["red"]
                color_titulo = C["text_1"]
                self._log(f"⚠ Error detectado: {msg}")
            else:  # offline
                color_borde = C["red"]
                color_txt   = C["red"]
                color_titulo = C["text_3"]

            self._lbl_estado_imp.configure(text=msg, text_color=color_txt)
            self._card_activa.configure(border_color=color_borde)
            self._lbl_imp_activa.configure(
                text=f"🖨️  {self._imp_seleccionada}",
                text_color=color_titulo,
            )
        except Exception:
            pass

    def _loop_estado_imp(self):
        """Loop periódico de verificación del estado de la impresora (cada 15 s)."""
        if not self.winfo_exists():
            return
        self._actualizar_estado_badge()
        self.after(15_000, self._loop_estado_imp)

    # ─── Selección de impresora ───────────────────────────────────────────────

    def _seleccionar_impresora(self, nombre: str):
        """Guarda la impresora seleccionada y actualiza la UI."""
        self._imp_seleccionada = nombre
        self.config.set("impresora", "nombre", nombre)
        # Actualizar la instancia de printer en el panel
        from printer import Printer
        self.printer = Printer(nombre)
        self._log(f"✅ Impresora seleccionada: {nombre}")
        self._lbl_imp_activa.configure(text=f"🖨️  {nombre}")
        self._actualizar_estado_badge()
        if self.on_guardado:
            self.on_guardado()
        self._escanear()

    # ─── Escaneo en background ────────────────────────────────────────────────

    def _escanear(self):
        """Lanza el escaneo de impresoras en un hilo daemon."""
        for w in self._frame_lista.winfo_children():
            w.destroy()
        ctk.CTkLabel(self._frame_lista, text="🔄  Escaneando...",
                     font=fuente(12), text_color=C["yellow"]).pack(pady=20)

        for w in self._frame_hw.winfo_children():
            w.destroy()
        ctk.CTkLabel(self._frame_hw, text="🔄  Escaneando hardware...",
                     font=fuente(11), text_color=C["yellow"]).pack(pady=14)

        self._log("Buscando impresoras instaladas y hardware USB...")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        inst       = PrinterInstaller(self._imp_seleccionada)
        impresoras = inst.listar_impresoras_detalle()
        hardware   = inst.listar_hardware_sin_driver()
        self.after(0, lambda: self._mostrar_resultados(impresoras, hardware))

    def _mostrar_resultados(self, impresoras: List[Dict], hardware: List[Dict]):
        if not self.winfo_exists():
            return

        # ── Lista de impresoras ───────────────────────────────────────────
        for w in self._frame_lista.winfo_children():
            w.destroy()

        if not impresoras:
            ctk.CTkLabel(
                self._frame_lista,
                text="❌  No se encontraron impresoras instaladas en Windows.\n"
                     "Instala una impresora con driver Generic/Text Only primero.",
                font=fuente(11), text_color=C["red"],
            ).pack(pady=20)
        else:
            for imp in impresoras:
                self._render_imp_card(imp)

        self._log(f"Encontradas: {len(impresoras)} impresoras, "
                  f"{len(hardware)} dispositivo(s) sin driver.")

        # ── Hardware sin driver ───────────────────────────────────────────
        for w in self._frame_hw.winfo_children():
            w.destroy()

        if not hardware:
            ctk.CTkLabel(self._frame_hw,
                         text="✓  No hay hardware sin driver pendiente",
                         font=fuente(11), text_color=C["text_3"]).pack(pady=14)
        else:
            for dev in hardware:
                self._render_hw_card(dev)

        self._actualizar_estado_badge()

    def _render_imp_card(self, imp: Dict):
        """Tarjeta para cada impresora instalada."""
        nombre    = imp["nombre"]
        driver    = imp["driver"]
        puerto    = imp["puerto"]
        es_compat = imp["es_compatible_termica"]
        es_ticket = imp["es_ticketera"]
        es_activa = (nombre == self._imp_seleccionada)

        border_color = C["green"] if es_activa else (C["blue"] if es_compat else C["border"])
        border_w     = 2 if (es_activa or es_compat) else 1
        bg_card      = C["bg_medium"] if es_compat else C["bg_dark"]

        card = ctk.CTkFrame(self._frame_lista, fg_color=bg_card, corner_radius=10,
                             border_color=border_color, border_width=border_w)
        card.pack(fill="x", padx=8, pady=4)

        # Izquierda: info
        left = ctk.CTkFrame(card, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True, padx=14, pady=10)

        top_row = ctk.CTkFrame(left, fg_color="transparent")
        top_row.pack(fill="x")

        name_color = C["green"] if es_activa else C["text_1"]
        ctk.CTkLabel(top_row, text=f"🖨️  {nombre}",
                     font=fuente(13, bold=True), text_color=name_color,
                     anchor="w").pack(side="left")

        if es_compat:
            ctk.CTkLabel(top_row, text="⭐ Recomendada",
                          font=fuente(9, bold=True),
                          fg_color=C["blue"], text_color="white",
                          corner_radius=8, width=100, height=20,
                          ).pack(side="left", padx=(10, 0))
        elif es_ticket:
            # Ticketera con driver no-Generic: indicar que puede no funcionar bien
            ctk.CTkLabel(top_row, text="⚠ Driver propio",
                          font=fuente(9, bold=True),
                          fg_color=C["yellow_h"], text_color="white",
                          corner_radius=8, width=100, height=20,
                          ).pack(side="left", padx=(10, 0))

        ctk.CTkLabel(left,
                     text=f"Driver: {driver}   •   Puerto: {puerto}",
                     font=fuente(10), text_color=C["text_3"],
                     anchor="w").pack(fill="x", pady=(2, 0))

        # Derecha: botones
        right = ctk.CTkFrame(card, fg_color="transparent")
        right.pack(side="right", padx=14, pady=10)

        if es_activa:
            ctk.CTkLabel(right, text="✓ Seleccionada",
                         font=fuente(11, bold=True), text_color=C["green"]).pack()
        elif es_compat:
            # Generic/Text Only → puede seleccionarse directamente
            ctk.CTkButton(
                right, text="Seleccionar",
                fg_color=C["blue"], hover_color=C["blue_h"],
                text_color="white", font=fuente(11, bold=True),
                width=130, height=32, corner_radius=8,
                command=lambda n=nombre: self._seleccionar_impresora(n),
            ).pack()
        else:
            # Driver no compatible — ofrecer cambio a Generic en lugar de Seleccionar
            ctk.CTkButton(
                right, text="🔧 Cambiar Driver\n(Admin)",
                fg_color="#7c2d12", hover_color="#9a3412",
                text_color="white", font=fuente(10, bold=True),
                width=130, height=42, corner_radius=8,
                command=lambda n=nombre: self._cambiar_driver_generico(n),
            ).pack()

    def _render_hw_card(self, dev: Dict):
        """Tarjeta para hardware USB detectado sin driver."""
        nombre = dev.get("nombre", "Desconocido")

        card = ctk.CTkFrame(self._frame_hw, fg_color=C["bg_medium"], corner_radius=8,
                             border_color=C["yellow"], border_width=1)
        card.pack(fill="x", padx=8, pady=4)

        left = ctk.CTkFrame(card, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True, padx=14, pady=10)

        ctk.CTkLabel(left, text=f"🖨️  {nombre}",
                     font=fuente(12, bold=True), text_color=C["yellow"],
                     anchor="w").pack(fill="x")
        ctk.CTkLabel(left, text="Sin driver — necesita instalación",
                     font=fuente(10), text_color=C["text_3"],
                     anchor="w").pack(fill="x")

        ctk.CTkButton(
            card, text="🛡️ Instalar\n(Admin)",
            fg_color="#ea580c", hover_color="#c2410c",
            text_color="white", font=fuente(10, bold=True),
            width=110, height=42, corner_radius=8,
            command=lambda n=nombre: self._instalar_driver_admin(n),
        ).pack(side="right", padx=14, pady=10)

    # ─── Cambiar driver a Generic ─────────────────────────────────────────────

    def _cambiar_driver_generico(self, nombre_impresora: str):
        """
        Cambia el driver de una impresora ticketera a Generic/Text Only.
        Necesario para que ESC/POS funcione con impresoras que tienen driver propio.
        """
        if not messagebox.askyesno(
            "Cambiar Driver a Generic/Text Only",
            f"Se cambiará el driver de:\n\n  {nombre_impresora}\n\n"
            "al driver  Generic / Text Only  (ideal para ESC/POS térmico).\n\n"
            "Windows pedirá permisos de Administrador.\n"
            "⚠ Si el driver propio tiene funciones especiales, se perderán.\n\n"
            "¿Continuar?",
        ):
            return

        self._log(f"Iniciando cambio de driver para: {nombre_impresora}...")

        def _run():
            inst  = PrinterInstaller(nombre_impresora)
            exito = inst.cambiar_driver_generico(
                nombre_impresora,
                log=lambda m: self.after(0, self._log, m),
            )

            def _ui():
                if not self.winfo_exists():
                    return
                if exito:
                    self._log(f"✅ Driver cambiado. '{nombre_impresora}' ahora usa Generic/Text Only.")
                    messagebox.showinfo(
                        "Driver Actualizado",
                        f"'{nombre_impresora}' ahora usa Generic / Text Only.\n"
                        "Puedes seleccionarla para usarla como ticketera.",
                    )
                    self._escanear()
                else:
                    messagebox.showerror(
                        "Error",
                        "No se pudo cambiar el driver.\n\n"
                        "Posibles causas:\n"
                        "• Rechazaste el permiso de Administrador\n"
                        "• La impresora está en uso\n"
                        "• Windows bloqueó el cambio\n\n"
                        "Intenta de nuevo o hazlo manualmente en:\n"
                        "Dispositivos e Impresoras → Propiedades → Avanzadas → Driver",
                    )
            self.after(0, _ui)

        threading.Thread(target=_run, daemon=True).start()

    # ─── Instalación de driver ────────────────────────────────────────────────

    def _instalar_driver_admin(self, nombre_modelo: str):
        if not messagebox.askyesno(
            "Permisos de Administrador",
            f"Windows pedirá permisos de Administrador para instalar:\n\n{nombre_modelo}\n\n"
            "¿Deseas continuar?",
        ):
            return

        self._log(f"Iniciando instalación como Admin para: {nombre_modelo}...")

        def _run():
            inst  = PrinterInstaller(nombre_modelo)
            exito = inst.instalar_como_admin(nombre_modelo, log=lambda m: self.after(0, self._log, m))

            def _ui():
                if not self.winfo_exists():
                    return
                if exito:
                    self._log(f"✅ '{nombre_modelo}' instalada correctamente.")
                    self.config.set("impresora", "nombre", nombre_modelo)
                    self._imp_seleccionada = nombre_modelo
                    self._lbl_imp_activa.configure(text=f"🖨️  {nombre_modelo}")
                    messagebox.showinfo(
                        "Éxito",
                        f"¡'{nombre_modelo}' instalada y seleccionada como ticketera!")
                    self._escanear()
                    if self.on_guardado:
                        self.on_guardado()
                else:
                    self._log(f"❌ No se pudo instalar '{nombre_modelo}'.")
                    messagebox.showerror(
                        "Error",
                        "No se pudo instalar el driver.\n\n"
                        "Posibles causas:\n"
                        "• Rechazaste el permiso de Administrador\n"
                        "• La ticketera no estaba conectada\n"
                        "• Windows bloqueó la instalación")
            self.after(0, _ui)

        threading.Thread(target=_run, daemon=True).start()

    # ─── Test de impresión ────────────────────────────────────────────────────

    def _test_impresora(self):
        inst = PrinterInstaller(self._imp_seleccionada)
        threading.Thread(
            target=lambda: self.after(0, self._mostrar_resultado_test,
                                      *inst.imprimir_pagina_prueba()),
            daemon=True,
        ).start()

    def _mostrar_resultado_test(self, ok: bool, msg: str):
        self._log(f"{'✅' if ok else '❌'} {msg}")
        if ok:
            messagebox.showinfo("Prueba de Impresión", msg)
        else:
            messagebox.showwarning("Prueba de Impresión", msg)

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _seccion(self, parent, titulo: str):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=4, pady=(16, 4))
        ctk.CTkLabel(f, text=titulo, font=fuente(13, bold=True),
                     text_color=C["text_2"], anchor="w").pack(side="left")
        ctk.CTkFrame(f, fg_color=C["border"], height=1).pack(
            side="left", fill="x", expand=True, padx=(10, 0), pady=6)

    def _campo_entrada(self, parent, label: str, valor: str = "") -> ctk.CTkEntry:
        fila = ctk.CTkFrame(parent, fg_color="transparent")
        fila.pack(fill="x", padx=4, pady=4)
        ctk.CTkLabel(fila, text=label, font=fuente(12), text_color=C["text_2"],
                     width=280, anchor="w").pack(side="left")
        entry = ctk.CTkEntry(fila, fg_color=C["bg_dark"], border_color=C["border"],
                              text_color=C["text_1"], height=36, width=280)
        entry.insert(0, valor)
        entry.pack(side="right")
        return entry

    def _log(self, texto: str):
        try:
            self._txt_log.configure(state="normal")
            self._txt_log.insert("end", texto + "\n")
            self._txt_log.see("end")
            self._txt_log.configure(state="disabled")
        except Exception:
            pass