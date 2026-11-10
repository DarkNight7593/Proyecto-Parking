# ParkingPro

Aplicación de escritorio para registrar entradas, controlar sesiones activas,
procesar cobros y analizar los ingresos de un estacionamiento. El proyecto está
pensado para una operación local rápida, con persistencia SQLite y soporte para
impresoras de tickets en Windows.

## Qué demuestra este proyecto

- Flujo completo de entrada, permanencia, cobro y cancelación.
- Paneles responsivos construidos con CustomTkinter.
- Reportes por día, semana, mes y año.
- Exportación profesional a Excel con totales y gráfico mensual.
- Acceso concurrente seguro a SQLite mediante conexiones por hilo.
- Reglas de negocio independientes y cubiertas por pruebas.
- Configuración local persistente con escrituras atómicas.

## Arquitectura

```text
Proyecto-Parking/
├── src/parkingpro/
│   ├── domain/                 # Entidades, validaciones y reglas puras
│   ├── application/            # Casos de uso y contratos (ports)
│   ├── infrastructure/
│   │   ├── database.py         # Repositorio SQLite
│   │   ├── settings.py         # Configuración persistente
│   │   ├── printing/           # Impresión e instalación de drivers
│   │   └── reporting/          # Exportación a Excel
│   ├── presentation/
│   │   ├── app.py              # Ventana principal
│   │   ├── theme.py            # Sistema visual
│   │   └── views/              # Paneles y ventanas modales
│   ├── bootstrap.py            # Composición de dependencias
│   └── __main__.py             # Entrada para python -m parkingpro
├── scripts/                    # Herramientas operativas y datos de demostración
├── tests/
│   ├── unit/                   # Dominio y casos de uso aislados
│   └── integration/            # SQLite, configuración y Excel
├── pyproject.toml              # Empaquetado, dependencias y calidad
└── uv.lock                     # Versiones reproducibles
```

La dirección de dependencias es `presentación → aplicación → dominio`. La capa
de infraestructura implementa los contratos definidos por aplicación y se
inyecta en el punto de composición. Por eso las vistas no importan SQLite,
OpenPyXL ni los instaladores de Windows directamente.

Las reglas de placas, tarifas y duración no conocen CustomTkinter ni SQLite, de
modo que pueden probarse sin abrir ventanas. La distribución usa un layout
`src/`, que evita imports accidentales desde el directorio del repositorio y
comprueba que el paquete esté instalado correctamente.

## Requisitos

- Python 3.11 o superior.
- Windows 10/11 para impresión física y generación del ejecutable.
- Una impresora de tickets compatible con el controlador de Windows.

La gestión de vehículos, SQLite, reportes y Excel también se puede probar en
Linux o macOS; la impresión física es específica de Windows.

## Instalación

### Con uv

```powershell
git clone <url-del-repositorio>
cd Proyecto-Parking
uv sync --extra dev
uv run parkingpro
```

### Con pip

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
parkingpro
```

También puede iniciarse con `python -m parkingpro` después de instalar el
paquete. Al iniciar por primera vez crea:

- `config.ini`, con los datos del negocio, tarifas e impresora.
- `parkingpro.db`, con las sesiones del estacionamiento.

Por defecto se guardan en `%LOCALAPPDATA%\ParkingPro` en Windows. La variable
`PARKINGPRO_DATA_DIR` permite elegir otro directorio, algo útil para respaldos,
entornos de prueba o instalaciones portables. Los datos locales están excluidos
de Git. Durante el desarrollo editable se conserva la ubicación en la raíz del
repositorio para mantener compatibilidad con instalaciones anteriores.

## Uso

1. En **Configuración**, registra el negocio, las tarifas y la ticketera.
2. En **Operación**, selecciona el tipo de vehículo e ingresa la placa.
3. Usa **Cobrar** para calcular el tiempo y cerrar la sesión, o **Cancelar** si
   el registro fue creado por error.
4. En **Reportes**, consulta indicadores, navega entre períodos y exporta el
   historial a Excel.

El cobro se calcula por cada hora iniciada después del período de gracia
configurado. El operador puede ajustar el importe antes de confirmar.

## Calidad y pruebas

```powershell
uv run pytest
uv run pytest --cov=parkingpro --cov-report=term-missing
uv run ruff check .
```

Las pruebas incluyen reglas de placas y tarifas, persistencia de configuración,
transiciones de estado, reportes, paginación, exportación a Excel y el intento
concurrente de registrar dos veces la misma placa.

## Integridad de datos

- Una placa solo puede tener una sesión activa, garantizado también por un
  índice único en SQLite.
- Los cobros y cancelaciones son transacciones atómicas.
- Los montos no admiten valores negativos, infinitos ni `NaN`.
- Las consultas usan parámetros SQL; los filtros no concatenan datos del
  usuario.
- SQLite usa WAL, espera configurable ante bloqueos y una conexión por hilo.
- `config.ini` se reemplaza de forma atómica para evitar archivos incompletos.

## Crear un ejecutable

```powershell
uv run --with pyinstaller pyinstaller --name ParkingPro --noconsole --onefile `
  --paths src src/parkingpro/__main__.py
```

El resultado se genera en `dist/`. Esa carpeta no se versiona: los binarios
deben publicarse como artefactos de una versión o *release*.

## Próximos pasos

- Copias de seguridad y restauración desde la interfaz.
- Gestión de usuarios y auditoría de ajustes manuales.
- Soporte configurable para tarifas por fracción o por jornada.
- Pruebas automatizadas de interfaz.

## Licencia

Distribuido bajo la licencia MIT. Consulta [LICENSE](LICENSE).

