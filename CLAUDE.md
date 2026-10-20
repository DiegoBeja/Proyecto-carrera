# CLAUDE.md

## Objetivo del proyecto

Estimar la concentración de CO2 (ppm) en interiores con sensores de bajo costo que **no miden CO2**. Un modelo predice el CO2 a partir de:

- **PMS5003**: sensor de partículas (masa y conteos por tamaño).
- **BME688**: temperatura, humedad, presión y resistencia de gas.

Ambos van conectados a un **ESP32-S3** que registra las lecturas en un CSV con intervalo configurable (p. ej. cada 10 s). La referencia de CO2 real es un monitor **Aeroqual AQM65**, que exporta datos con promedio de 1 minuto.

## Flujo de trabajo

1. **Registro**: `esp32s3_logger.ino` (firmware del ESP32-S3) guarda el CSV en la memoria del ESP32.
2. **Descarga a la PC**: `guardar_csv.py` copia por serial el CSV del ESP32 a la PC (`python guardar_csv.py COM5 S01.csv`). Requiere `pyserial` y cerrar antes el Monitor Serie.
3. **Unión con el AQM65**: `merge.py` une el CSV del ESP32 con el export de 1 minuto del AQM65 y genera **una fila por minuto** lista para entrenar (salida en `entrenamiento/`, p. ej. `S01_train.csv`).
4. **Entrenamiento y comparación**: `entrenar.py` compara modelos y escribe en `resultados/` (`errores_globales.csv`, `predicciones_cv.csv`, `importancias_extra_trees.csv`, `real_vs_predicho.png`).

Dependencias de Python: `pandas`, `tzdata`, `scikit-learn`, `matplotlib`, `pyserial`.

```
python merge.py --esp S01.csv --aqm <export_aqm65>.csv --out entrenamiento/S01_train.csv
python entrenar.py                                   # usa todos los CSV de entrenamiento/
python entrenar.py entrenamiento/*.csv --test S08 S09 S10          # aparta sesiones de prueba final
python entrenar.py entrenamiento/*.csv --test S08 S09 S10 --final  # evalúa UNA sola vez al terminar
```

Opciones útiles de `merge.py`: `--esp-offset-sec`, `--aqm-stamp start|end`, `--exclude INICIO FIN`, `--start "NOMBRE=AAAA-MM-DD HH:MM:SS"`, `--tz America/Tijuana`. Ver el docstring del script.

## Estructura del repositorio

- `esp32s3_logger.ino`: firmware de registro (PMS5003 + BME688).
- `merge.py`, `entrenar.py`, `guardar_csv.py`: scripts descritos arriba.
- `S01.csv`, `S02.csv`, `S03.csv`: CSV crudos del ESP32 por sesión.
- `aqm65_*.csv`: exports crudos del AQM65 (el archivo tiene un encabezado de varias líneas antes de los datos).
- `entrenamiento/`: CSV ya unidos (una fila por minuto) que usa `entrenar.py`.
- `resultados/`: salidas de `entrenar.py`.

## Datos y sesiones

- Sesiones de ~60 minutos: una al aire libre y varias en un cuarto.
- En el cuarto se varían las condiciones para cubrir un rango amplio de CO2: humedad alta, personas respirando y reacción de bicarbonato de sodio con vinagre o ácido cítrico (CO2 controlado).
- `session_id` identifica cada sesión y es la base de la validación.
- Hora local de Tijuana/Mexicali (`America/Tijuana`, con horario de verano).

## Modelado: reglas que no se rompen

- **Solo se usan como entradas las variables del dispositivo final**: partículas (PMS5003) y BME688. Las columnas `aqm_*` (PM, VOC, CO, TEMP del AQM65) y `esp_rows` son solo de referencia/análisis y **nunca** entran como entradas (fuga de información). `co2_ref_ppm` es el objetivo.
- **Validación por sesión**: leave-one-session-out (se deja una sesión completa fuera en cada ronda). Nunca separar por filas al azar. Con una sola sesión se usan bloques contiguos, y eso solo sirve para probar que el código corre.
- **Sesiones de prueba final** (`--test`): se apartan al inicio, no se usan para elegir nada y se evalúan **una sola vez** (`--final`). No ajustar el modelo mirándolas.
- Modelos a comparar: línea base (promedio), lineal, Ridge, Extra Trees, Random Forest y un perceptrón multicapa pequeño. `entrenar.py` hoy incluye además otros (PLS, KNN, SVR, GP, etc.); la lista final del proyecto es la anterior.
- En aire limpio el PM del PMS5003 es casi siempre 0; los conteos por tamaño (`n0_3`...`n10`) son más informativos.

## Cuidados con el hardware y los datos

- No cambiar `HEATER_TEMP_C` (320), `HEATER_MS` (150) ni `BME_PERIOD_MS` (3000) entre sesiones: la resistencia de gas depende de ellos y el firmware final debe usar los mismos valores que los datos de entrenamiento.
- No subir el WiFi (`WIFI_SSID`/`WIFI_PASS`) al repositorio; dejarlos vacíos antes de `git add`.
- Pines: BME688 SDA=15, SCL=16; PMS5003 TX→GPIO 17; PMS5003 va a 5 V.
- El AQM65 exporta hora local; hay que alinearla con el reloj del ESP32 (ver `--esp-offset-sec`).

## Notas

- El README ya está alineado con los archivos reales. Ante contradicciones, mandan los scripts.
- Idioma del proyecto: español (código, comentarios, documentación y commits).
