# Caracterización de CO₂ con PMS5003 y BME688

Registro de datos con un **ESP32-S3**, un **PMS5003** (partículas) y un **BME688** (temperatura, humedad, presión y gas), pensado para entrenar un modelo que estime CO₂ con sensores de bajo costo. Como ninguno de los dos sensores mide CO₂, se toman muestras al mismo tiempo que un **Aeroqual AQM65** (referencia) y después se une el CO₂ del AQM65 a los datos del ESP32.

El ESP32 guarda un archivo `.csv` en su propia memoria, y un script de Python lo copia a la computadora.

## Contenido del repositorio

```
├── esp32s3_logger/        Firmware: esp32s3_logger.ino + co2_mlp.h + modelo_co2.h (red de CO2)
├── guardar_csv.py         Copia el CSV del ESP32 a la PC
├── merge.py               Une el CSV del ESP32 con el export de 1 minuto del AQM65
├── entrenar.py            Compara modelos y escribe los resultados en resultados/
├── S01.csv, S02.csv, ...  CSV crudos del ESP32, uno por sesión
├── aqm65_*.csv            Exports crudos del AQM65
├── entrenamiento/         CSV unidos (una fila por minuto), listos para entrenar
├── resultados/            Salidas de entrenar.py (errores, predicciones, gráfica)
├── CLAUDE.md              Contexto del proyecto para Claude Code
└── README.md
```

## Hardware y conexiones

| Sensor | Pin del sensor | Pin del ESP32-S3 |
| --- | --- | --- |
| BME688 | SDA | GPIO 15 |
| BME688 | SCL | GPIO 16 |
| BME688 | VCC / GND | 3V3 / GND |
| PMS5003 | TX | GPIO 17 (es el RX del ESP32) |
| PMS5003 | VCC | **5V** (no 3V3) |
| PMS5003 | GND | GND |
| PMS5003 | SET | 3V3 (o sin conectar) |
| PMS5003 | RX, RESET | Sin conectar |

- El BME688 usa la dirección I2C 0x77 o 0x76; el firmware prueba las dos.
- Todos los GND deben estar unidos.
- El pin 5V de muchas placas ESP32-S3 solo tiene voltaje cuando están conectadas por USB.

## Requisitos de software

- **Arduino IDE 2.x** con el soporte de placas **esp32** (de Espressif) instalado.
- Librerías (Administrador de bibliotecas): **Adafruit BME680 Library** y **Adafruit Unified Sensor**.
- **Python 3** con pyserial: `pip install pyserial`

En Arduino IDE elige la placa **ESP32S3 Dev Module**. Si conectas el ESP32 por su puerto USB nativo, activa **USB CDC On Boot**.

## Parámetros que debes cambiar

Todos están al inicio de `esp32s3_logger/esp32s3_logger.ino`.

| Parámetro | Valor por defecto | Qué hace y cuándo cambiarlo |
| --- | --- | --- |
| `WIFI_SSID` | `""` (vacío) | Nombre de tu red WiFi, entre comillas. Solo sirve para fijar la hora por internet al encender. Con valor vacío no se usa WiFi. |
| `WIFI_PASS` | `""` (vacío) | Contraseña de esa red. |
| `TZ_INFO` | `"PST8PDT,M3.2.0,M11.1.0"` | Zona horaria (Tijuana/Mexicali). Cámbiala si estás en otra zona. |
| `PIN_SDA`, `PIN_SCL` | 15, 16 | Pines I2C del BME688. Cámbialos solo si conectas distinto. |
| `PIN_PMS_RX` | 17 | Pin del ESP32 donde llega el TX del PMS5003. |
| `logIntervalS` | 10 | Cada cuántos segundos se guarda una fila (2 a 3600). Cada fila es el promedio de las lecturas de ese intervalo. |
| `durationMin` | 120 | Duración de la sesión en minutos (1 a 1440). |
| `sessionId` | `"S01"` | Nombre de la sesión y del archivo (`S01.csv`). |
| `HEATER_TEMP_C`, `HEATER_MS` | 320, 150 | Perfil del calentador del sensor de gas del BME688. |
| `BME_PERIOD_MS` | 3000 | Cada cuánto mide el BME688. |
| `SERIAL_BAUD` | 115200 | Velocidad del puerto serie. Debe coincidir con el Monitor Serie y con `guardar_csv.py`. |

Ejemplo para usar WiFi:

```cpp
const char* WIFI_SSID = "NombreDeMiRed";
const char* WIFI_PASS = "miContraseña";
```

Notas importantes:
- **No subas tu contraseña de WiFi al repositorio.** Déjala vacía antes de hacer `git add`, o ponla solo en tu copia local.
- El ESP32-S3 solo se conecta a redes de **2.4 GHz**. El hotspot de un celular sirve.
- `logIntervalS`, `durationMin` y `sessionId` son solo los valores iniciales; los puedes cambiar por comandos sin volver a subir el código.
- **No cambies `HEATER_TEMP_C`, `HEATER_MS` ni `BME_PERIOD_MS` entre sesiones.** La resistencia de gas depende de ellos, y el firmware final debe usar los mismos valores con los que tomaste los datos de entrenamiento.

## Subir el firmware al ESP32

1. Abre `esp32s3_logger/esp32s3_logger.ino` con Arduino IDE (la carpeta ya tiene el nombre que pide el IDE y los `.h` de la red).
2. Edita los parámetros de la sección anterior.
3. Elige la placa y el puerto (Herramientas → Placa / Puerto).
4. Presiona **Subir**. No hay que repetirlo después; el programa queda grabado.

## Correr una sesión de muestreo

1. Abre el **Monitor Serie** (115200 baudios, terminador "Nueva línea" / Newline).
2. Escribe `status` y comprueba que los dos sensores den datos.
3. Configura la sesión, un comando a la vez:
   ```
   set id C1_ocupacion
   set interval 10
   set duration 120
   settime 2026-10-14 05:00:00
   ```
   (`settime` solo hace falta si no usas WiFi. La hora va en formato local.)
4. Escribe `start`. Durante la sesión puedes anotar eventos: `e entra persona 3`.
5. Al terminar el tiempo, el ESP32 cierra el archivo. Para parar antes, escribe `stop`.

### Comandos del Monitor Serie

| Comando | Qué hace |
| --- | --- |
| `help` | Muestra la lista de comandos |
| `status` | Estado de la sesión, hora, diagnóstico del PMS5003 y lecturas del BME688 |
| `set interval <s>` | Segundos entre filas (2 a 3600) |
| `set duration <min>` | Duración de la sesión (1 a 1440) |
| `set id <nombre>` | Nombre de la sesión (letras, números, `_` y `-`) |
| `settime AAAA-MM-DD HH:MM:SS` | Fija la hora local |
| `start` / `stop` | Inicia / detiene la sesión |
| `e <texto>` | Anota un evento en la siguiente fila |
| `ls` | Lista los archivos del ESP32 y el espacio libre |
| `dump <archivo>` | Imprime un archivo por serial |
| `del <archivo>` | Borra un archivo |

Si el archivo ya existe, la nueva sesión se guarda como `S01_2.csv`, `S01_3.csv`, etc.

## Guardar el CSV en tu computadora

El archivo se crea en la memoria del ESP32, no en la PC. Para copiarlo:

1. **Cierra el Monitor Serie** (el puerto no puede estar abierto en dos programas).
2. Averigua el nombre del archivo con `ls` en el Monitor Serie (antes de cerrarlo).
3. En PowerShell, desde la carpeta donde quieras que quede el CSV:
   ```
   python guardar_csv.py COM11 C1_ocupacion.csv
   ```

Qué cambiar en ese comando:
- **`guardar_csv.py`**: la ruta donde esté el script. Si estás en otra carpeta, usa la ruta completa, por ejemplo `python C:\Users\bombo\OneDrive\Desktop\8vo\ProyectoCarrera\esp32s3_logger\guardar_csv.py COM11 S01.csv`.
- **`COM11`**: el puerto de tu ESP32 (Arduino IDE → Herramientas → Puerto). En Linux es algo como `/dev/ttyACM0` y en Mac `/dev/cu.usbmodem1101`.
- **`C1_ocupacion.csv`**: el nombre del archivo en el ESP32 (el id de la sesión más `.csv`).

El CSV queda en la carpeta donde estás parado (la carpeta actual de PowerShell), no donde está el script.

Alternativa manual: al terminar la sesión, el Monitor Serie muestra el CSV entre las líneas `#BEGIN_CSV` y `#END_CSV`. Copia ese texto (sin esas dos líneas), pégalo en el Bloc de notas y guárdalo con extensión `.csv`.

## Formato del CSV

Cada fila es el promedio de las lecturas de un intervalo.

| Columna | Qué es |
| --- | --- |
| `session_id` | Nombre de la sesión |
| `epoch_utc`, `timestamp_local` | Hora (vacías si no hay hora) |
| `elapsed_s` | Segundos desde `start` |
| `pms_n` | Cuántas lecturas del PMS5003 se promediaron |
| `pm1_0_cf1`, `pm2_5_cf1`, `pm10_cf1` | Masa de partículas en µg/m³ (calibración de fábrica CF=1) |
| `pm1_0_atm`, `pm2_5_atm`, `pm10_atm` | Masa de partículas en µg/m³ (condiciones ambientales) |
| `n0_3`, `n0_5`, `n1_0`, `n2_5`, `n5_0`, `n10` | Partículas mayores a ese tamaño (µm) por cada 0.1 L de aire |
| `bme_n` | Cuántas lecturas del BME688 se promediaron |
| `temp_c`, `rh_pct`, `pressure_hpa` | Temperatura (°C), humedad relativa (%), presión (hPa) |
| `gas_ohm`, `log10_gas` | Resistencia de gas (Ω) y su logaritmo |
| `abs_hum_gm3` | Humedad absoluta (g/m³), calculada |
| `heater_c`, `heater_ms` | Perfil del calentador usado |
| `event` | Evento anotado con el comando `e` |
| `co2_ref_ppm` | **Vacía.** Se llena con el CO₂ del AQM65 al unir los datos |

## Solución de problemas

| Problema | Qué revisar |
| --- | --- |
| `PMS5003: sin datos` justo al arrancar | Es normal; espera unos segundos y escribe `status` otra vez |
| Todo en 0 pero los conteos (`n0_3`, ...) cambian | El sensor funciona; el aire es muy limpio y la masa se redondea a 0. Usa los conteos como variables |
| Todo en 0, incluso los conteos | Revisa que el VCC del PMS5003 esté en 5 V y que el ventilador gire |
| `bytes=0` | No llega nada por el pin 17: revisa TX del sensor, GND común y alimentación |
| `DETENIDAS` en `status` | El sensor dejó de enviar: cable o conector flojo, pin SET, alimentación |
| `BME688: NO detectado` | Revisa SDA (15), SCL (16), 3V3 y GND |
| `Hora: sin hora` | Pon el WiFi en el código o usa `settime` antes de `start` |
| `can't open file '...guardar_csv.py'` | Estás en otra carpeta; usa la ruta completa del script |
| `No module named serial` | Corre `pip install pyserial` |
| No abre el puerto (`COM`) | Cierra el Monitor Serie y revisa el número de puerto |
| `No existe: ...` | El nombre del archivo es distinto; revisa con `ls` |

## Notas del proyecto

- El AQM65 se exporta con **promedio de 1 minuto**. `merge.py` promedia el CSV del ESP32 a 1 minuto, lo alinea con la hora del AQM65 y une el CO₂ en `co2_ref_ppm`, dejando una fila por minuto en `entrenamiento/`.
- Para unir: `python merge.py --esp S01.csv --aqm <export_aqm65>.csv --out entrenamiento/S01_train.csv`. Si los relojes no coinciden, usa `--esp-offset-sec`.
- Para entrenar: `python entrenar.py` (usa todos los CSV de `entrenamiento/`). Requiere `pip install pandas tzdata scikit-learn matplotlib`.
- Al evaluar el modelo, separa los datos **por sesión**, nunca por filas al azar (leave-one-session-out). Algunas sesiones se apartan con `--test` y se evalúan una sola vez al final con `--final`.
- Solo se usan como entradas las variables del dispositivo final (PMS5003 y BME688); las columnas `aqm_*` son solo referencia.
- En aire limpio el PM del PMS5003 es casi siempre 0; los conteos por tamaño son más informativos.
- Antes de usar los sensores en campo, deja el BME688 encendido de 24 a 48 horas de forma continua para que se estabilice, y conserva el mismo perfil de calentador entre sesiones.
