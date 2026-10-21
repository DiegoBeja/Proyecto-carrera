# Guía completa: de los datos crudos al modelo de CO₂

Esta guía explica **todo el flujo** del proyecto: qué archivo es cada cosa, en qué orden se corren los
scripts, qué hace cada uno por dentro, cómo leer sus resultados y cómo planear las sesiones de medición.
Está escrita para poder trabajar sin tener que volver a preguntar.

> **Rama `main`:** `compensar.py`, el modelo `17_mlp_chico` y la opción `--sin-temp-hum` de `entrenar.py`
> por ahora solo existen en la rama `dev`. Las secciones que los mencionan describen esa versión.

---

## 1. Idea general

- **Dispositivo barato:** ESP32-S3 + **BME688** (temperatura, humedad, presión y resistencia de gas MOX)
  + **PMS5003** (partículas). **Ninguno de los dos mide CO₂.**
- **Referencia:** **Aeroqual AQM65**, calibrado. Da CO₂, CO, VOC, PM y temperatura.
- **Objetivo:** medir con los dos al mismo tiempo y entrenar un modelo que estime el CO₂ del AQM65 usando
  **solo** lo que mide el dispositivo barato.
- **Problema principal:** la resistencia de gas del BME688 depende mucho de la **temperatura y la humedad**
  y casi nada del CO₂. Hay que quitar ese efecto (compensar) antes de concluir algo.

---

## 2. Archivos del repositorio

| Archivo | Qué es |
|---|---|
| `esp32s3_logger.ino` | Firmware del ESP32. Mide siempre y guarda una fila promedio cada `interval` segundos durante una sesión. |
| `guardar_csv.py` | **Copia el CSV del ESP32 a la PC por el puerto serie.** |
| `merge.py` | **Une** el CSV del ESP32 con el export del AQM65, minuto a minuto. |
| `compensar.py` | **Quita el efecto de temperatura y humedad** a BME688 y PMS5003. Opcional pero recomendado. (Rama `dev`.) |
| `entrenar.py` | **Compara modelos** para estimar CO₂ y guarda resultados (16 en `main`, 17 con el MLP en `dev`). |
| `S01.csv`, `S02.csv`, `S03.csv` | Datos **crudos** del ESP32 por sesión (60 filas, 1 por minuto). |
| `aqm65_01_cuarto.csv` | **Export** del AQM65 de S01 (16-oct-2026, 12:48 a 15:15). |
| `aqm65_02_03_cuarto.csv` | **Export** del AQM65 de S02 y S03 (19-oct-2026). |
| `entrenamiento/` | CSV **ya unidos** por `merge.py` (ej. `S01_train.csv`). Es lo que entra a los modelos. |
| `resultados/` | Salida de `entrenar.py` (errores, predicciones, importancias, gráfica). |
| `CLAUDE.md` | Contexto y reglas del proyecto (qué entra al modelo, validación, cuidados del hardware). |

---

## 3. Flujo completo

```
ESP32 (sesión)  ──guardar_csv.py──►  S02.csv  (crudo ESP)
                                           │
AQM65 (Aeroqual Connect, export 1 min) ──► aqm65_02.csv
                                           │
                         merge.py  ◄───────┘
                             │
                             ▼
           entrenamiento/S02_train.csv   (unido, 1 fila por minuto)
                             │
                 compensar.py (todas las sesiones juntas)
                             │
                             ▼
                compensado/S02_train.csv + coeficientes_compensacion.json
                             │
                        entrenar.py
                             │
                             ▼
               resultados/  (tabla de errores, predicciones, gráfica)
```

**Regla importante:** los modelos **nunca** reciben los archivos crudos. El ESP32 y el AQM65 tienen
formatos distintos (encabezados, nombres de columna, relojes). `merge.py` los alinea, y `entrenar.py`
se niega a correr si le pasas un archivo que no salió de `merge.py`.

### Comandos (PowerShell, en la carpeta del proyecto)

```powershell
# 0. Una sola vez
pip install pandas numpy scikit-learn matplotlib pyserial tzdata

# 1. Bajar el CSV del ESP32 (con la sesión ya terminada y el Serial Monitor cerrado)
python guardar_csv.py COM5 S02.csv

# 2. Unir cada sesión con el AQM65 (sin --out guarda en entrenamiento\S02_train.csv)
python merge.py --esp S02.csv --aqm aqm65_02_03_cuarto.csv

# 3. Compensar temperatura/humedad (pasar TODAS las sesiones juntas; rama dev)
python compensar.py entrenamiento\*.csv --out-dir compensado

# 4. Entrenar y comparar modelos
python entrenar.py                                     # usa todos los CSV de entrenamiento\
python entrenar.py compensado\*.csv
python entrenar.py compensado\*.csv --sin-temp-hum     # sin T ni humedad como entradas (ver sección 8)
```

---

## 4. Formatos de los archivos

### 4.1 CSV crudo del ESP32 (`S01.csv`)

Una fila por ventana de `interval` segundos (en S01 fue de 60 s, o sea 1 fila por minuto). La hora de cada fila es la del
**final** de la ventana.

| Columna | Significado |
|---|---|
| `session_id` | Nombre de la sesión (`set id ...` en el firmware). |
| `epoch_utc`, `timestamp_local` | Hora (UTC en segundos y hora local). Vacía si el ESP no tenía hora. |
| `elapsed_s` | Segundos desde el `start`. |
| `pms_n`, `bme_n` | Cuántas lecturas se promediaron en esa fila. |
| `pm*_cf1`, `pm*_atm` | Masa de PM del PMS5003 (µg/m³, enteros; en aire limpio salen 0). |
| `n0_3` … `n10` | **Conteos** de partículas > 0.3, 0.5, 1, 2.5, 5 y 10 µm por 0.1 L. Son más sensibles que la masa. |
| `temp_c`, `rh_pct`, `pressure_hpa` | Temperatura, humedad relativa y presión del BME688. |
| `gas_ohm` | Resistencia del sensor de gas MOX (Ω). **Baja** cuando hay gases reductores/VOC y con humedad. |
| `log10_gas`, `abs_hum_gm3` | log₁₀ de la resistencia y humedad absoluta (g/m³). |
| `heater_c`, `heater_ms` | Perfil del calentador del BME688 (**no cambiarlo entre sesiones**). |
| `event` | Texto que anotaron con `e <texto>` durante la sesión. |

### 4.2 Export del AQM65 (`aqm65_01_cuarto.csv`)

- 6 líneas de encabezado (nombre del equipo, fechas, zona horaria, "Averaging period: 1 minute").
- Luego `Time,CO (ppm),CO2 (ppm),...,TEMP (°C),Inlet`.
- La hora es **local** (`AAAA/MM/DD HH:MM:SS`) y marca el **inicio** del minuto.
- `Inlet = Sample` significa medición normal; las demás filas (calibración, cero) se descartan.
- **Ojo:** `AIR T` y `AIR RH` vienen vacías. El AQM65 **no está dando humedad de referencia**.

### 4.3 Archivo unido (`entrenamiento/S01_train.csv`) — el que entra a los modelos

Una fila **por minuto** con todas las columnas del ESP32 (promediadas a 1 min) más:

| Columna | Origen | ¿Entra al modelo? |
|---|---|---|
| `co2_ref_ppm` | CO₂ del AQM65 | **Es lo que se predice** (objetivo) |
| `pm1_est`, `pm2_5_est` | Masa estimada desde los conteos del PMS (con decimales) | Sí |
| `aqm_pm2_5`, `aqm_pm10`, `aqm_voc`, `aqm_co`, `aqm_temp_c` | AQM65 | **Nunca** (solo análisis; el dispositivo final no los tendrá) |
| `esp_rows` | Cuántas filas del ESP cayeron en ese minuto | No |

---

## 5. `merge.py` — unir ESP32 y AQM65

### Qué hace
1. Lee el AQM65: se salta el encabezado, quita las unidades de los nombres de columna, descarta filas con
   `Inlet` distinto de `Sample` y convierte la hora local a UTC (zona `America/Tijuana` por defecto).
2. Lee el ESP32: a cada fila le asigna el minuto donde cae el **centro** de su ventana.
3. Promedia el ESP32 por minuto (ponderando por `pms_n` / `bme_n`).
4. Une **solo los minutos que existen en los dos** (unión interna).
5. Recalcula `log10_gas`, `abs_hum_gm3` y calcula `pm1_est`, `pm2_5_est`.

### Opciones útiles

| Opción | Para qué |
|---|---|
| `--esp A.csv B.csv` | Varias sesiones a la vez (cada una conserva su `session_id`). |
| `--esp-offset-sec N` | Segundos que se suman al reloj del ESP si no coincide con el AQM. |
| `--start "S02=2026-10-20 10:00:00"` | Hora de inicio si la sesión se grabó sin hora (`epoch_utc` vacío). |
| `--exclude "2026-10-20 10:30" "2026-10-20 10:35"` | Descartar minutos del AQM (ej. calibración). |
| `--tz America/Tijuana` | Zona horaria del export del AQM. |
| `--aqm-stamp end` | Si la hora del AQM marcara el **fin** del minuto. |

### Cómo revisar que salió bien
En la salida:
```
Minutos del ESP32: 60 (2026-10-16 14:17 a 2026-10-16 15:16)
Minutos del AQM65: 148 (2026-10-16 12:48 a 2026-10-16 15:15)
Minutos unidos:    59
```
- **Minutos unidos ≈ minutos del ESP32** → bien. (Aquí falta 1 porque el AQM se exportó hasta las 15:15.)
- **0 o muy pocos** → reloj del ESP mal, zona horaria equivocada o el export del AQM no cubre esas horas.
- Comprobado: regenerar `S01_train.csv` desde `S01.csv` + `aqm65_01_cuarto.csv` da los mismos datos (comprobado antes del cambio de nombre de `S01_3` a `S01`).

---

## 6. `compensar.py` — quitar el efecto de temperatura y humedad

### Es una corrección **lineal + fórmulas físicas**, no una red neuronal
Solo se ajustan unos 6 números con mínimos cuadrados. Caben en `coeficientes_compensacion.json` y el
ESP32 los puede aplicar con unas cuantas multiplicaciones.

### Qué corrige

| Paso | Fórmula | Qué se ajusta |
|---|---|---|
| **Temperatura BME** | `temp_comp = a + b·temp_c` (contra `aqm_temp_c`) | a, b |
| **Humedad relativa** | `rh_comp = rh · es(temp_c) / es(temp_comp)` (Magnus). Misma agua, temperatura corregida | Nada (física) |
| **Gas MOX** | `log10_gas = base_sesión + b·(T−25) + c·(AH−10)` ajustado **solo en minutos limpios** | b, c |
| | `log10_gas_comp = log10_gas − b·(T−25) − c·(AH−10)` | |
| | `gas_dev_pct` = % de cambio vs. la línea base de la sesión | |
| **PMS (crecimiento por humedad)** | `pm_comp = pm_est / (1 + (κ/1.65)/(1/aw − 1))`, `aw = rh_comp/100` | κ fija (0.4) |
| **PMS (calibración)** | `pm2_5_cal = a + b·pm2_5_comp` (contra `aqm_pm2_5`) | a, b |

- **Minuto limpio:** pasó el calentamiento del sensor, no hay pico de CO₂ (más de `--umbral-co2` ppm sobre la
  mediana de la sesión) ni evento anotado, y no está a `--margen` minutos de uno.
- **`base_sesión`:** absorbe la deriva del sensor entre días. Los coeficientes b y c son comunes a todas las sesiones.
- **`gas_dev_pct`:** usa como línea base la mediana de los primeros `--base-min` minutos después del
  calentamiento. El dispositivo final lo puede calcular solo, sin el AQM65.

### Opciones

| Opción | Default | Significado |
|---|---|---|
| `--calentamiento` | 10 | Minutos iniciales que no se usan para ajustar. Con precalentamiento usar 2. |
| `--base-min` | 5 | Minutos para la línea base de gas de cada sesión. |
| `--umbral-co2` | 60 | ppm sobre la mediana para marcar evento. |
| `--margen` | 3 | Minutos alrededor de un evento que tampoco se usan. |
| `--kappa` | 0.4 | Higroscopicidad del aerosol (0.2–0.6 típico). |
| `--out-dir` | `compensado` | Carpeta de salida. |

### Columnas nuevas en la salida
`temp_comp`, `rh_comp`, `log10_gas_comp`, `gas_dev_pct`, `pm1_comp`, `pm2_5_comp`, `pm2_5_cal`,
`minuto_limpio`, `evento`.

### Cómo leer la validación (necesita 2 o más sesiones)
Para cada sesión ajusta b y c con las **demás** y mide en la apartada:

| Columna | Significado | Qué buscar |
|---|---|---|
| `ruido_sin_comp_pct` | Variación de la resistencia en minutos limpios, sin compensar | — |
| `ruido_comp_pct` | Lo mismo, ya compensado | Menor que el anterior |
| `reduccion_ruido_pct` | Cuánto bajó el ruido | Positivo y consistente en todas las sesiones |
| `baja_en_evento_pct` | Cuánto bajó la resistencia compensada en los eventos de CO₂ | — |
| `senal_ruido` | `|baja en evento| / ruido` | **> 3:** el evento se distingue. **< 2:** no se distingue |

### Avisos que puede dar
- **"T o humedad varían poco"**: el rango es < 3 °C o < 2 g/m³. Los coeficientes no son confiables.
- **"T y humedad se movieron juntas"**: `|r| > 0.8`. No se puede separar el efecto de cada una.
- **"la HR varió poco o no pasó de 60 %"**: la corrección del PMS no se puede comprobar.

---

## 7. `entrenar.py` — comparar modelos

### Entradas (features)
Solo variables que tendrá el dispositivo final:

| Grupo | Columnas |
|---|---|
| Partículas | `log_n0_3` … `log_n10`, `log_pm1_est`, `log_pm2_5_est` (log(1+x)) |
| BME688 | `temp_c`, `rh_pct`, `abs_hum_gm3`, `log10_gas` |
| Dinámicas (ventana 5 min) | Promedio móvil `_m5` y tendencia `_d5` de `log10_gas`, `abs_hum_gm3`, `temp_c`, `log_n0_3` |
| Compensadas (si el CSV viene de `compensar.py`) | `temp_comp`, `rh_comp`, `gas_dev_pct`, `log_pm2_5_comp` |
| Presión | `pressure_hpa` (quitar con `--sin-presion`) |

**Nunca entran:** `aqm_*`, `esp_rows`, `co2_ref_ppm`.

### Modelos (17)

| # | Modelo | Tipo |
|---|---|---|
| 01 | Media | Referencia: predice siempre el promedio. **Cualquier modelo útil debe ganarle.** |
| 02 | Lineal T + HR | Solo temperatura y humedad (para ver cuánto explican solas) |
| 03, 07 | Ridge (α 10 y 100) | Lineal regularizado |
| 08 | Elastic Net | Lineal regularizado |
| 09 | Bayesian Ridge | Lineal bayesiano |
| 10 | Huber | Lineal robusto a valores atípicos |
| 11 | PLS (3 componentes) | Lineal por componentes |
| 06 | SVR | Kernel |
| 12 | Kernel Ridge | Kernel |
| 14 | Proceso gaussiano | Kernel bayesiano |
| 13 | kNN (k=7) | Vecinos |
| 04, 05 | Extra Trees, Random Forest | Árboles |
| 15 | Árbol chico (profundidad 3) | Árbol |
| 16 | GBM chico | Árboles en serie |
| **17** | **MLP chico** | **Red neuronal:** 1 capa oculta de 8 neuronas `tanh`, `lbfgs`, α=1.0 (~220 parámetros) |

### Validación
- **2 o más sesiones:** *leave-one-session-out*. Entrena con todas menos una y prueba en la que dejó fuera.
  Es la única forma honesta de saber si funciona en un día nuevo.
- **1 sesión:** bloques en el tiempo. **Solo sirve para ver que el código corre.**

### Opciones

| Opción | Significado |
|---|---|
| `--saltar-min N` | Descarta los primeros N minutos de cada sesión. |
| `--ventana N` | Minutos del promedio móvil y la tendencia (5). |
| `--sin-presion` | No usa la presión (cambia por clima, no por CO₂). |
| `--sin-temp-hum` | No usa temperatura ni humedad como entradas (ver sección 8). |
| `--test S08 S09` | **Nombres de sesión** (no archivos) que se apartan como prueba final. |
| `--final` | Entrena con todo y evalúa **una sola vez** en `--test`. Hacerlo al final del proyecto. |
| `--salida carpeta` | Dónde guardar resultados (`resultados` por defecto; **sobrescribe**). |

### Salidas

| Archivo | Contenido |
|---|---|
| `errores_globales.csv` | MAE, RMSE, R² y `mejora_vs_media_%` por modelo |
| `predicciones_cv.csv` | Predicción de cada modelo minuto a minuto (validación cruzada) |
| `importancias_extra_trees.csv` | Qué variables usa más Extra Trees |
| `real_vs_predicho.png` | CO₂ real vs. predicho por sesión |
| `prueba_final.csv` | Solo con `--final` |

### Cómo leer la tabla
- **`mejora_vs_media_%` > 0** → el modelo le gana a predecir siempre el promedio.
- **R² cerca de 0 o negativo** → no explica nada.
- Mira también el **MAE por sesión**. Un modelo que es el mejor en una sesión y el peor en otra
  (como el MLP en las pruebas) no es confiable.

---

## 8. Temperatura y humedad como entradas: ¿sí o no?

**Sí se usan por defecto.** `entrenar.py` mete `temp_c`, `rh_pct`, `abs_hum_gm3` y sus promedios y
tendencias. En S01, la variable que más usó Extra Trees fue `abs_hum_gm3`.

**Eso es un problema mientras no hayan variado la humedad a propósito.** En S01 la humedad subió
justo cuando hubo CO₂, porque la reacción también soltó vapor. El modelo aprende "más humedad = más CO₂".
El día que la humedad cambie por otra causa (lluvia, regadera, humidificador), va a predecir picos de
CO₂ falsos.

**Qué hacer:**
1. **Mientras no tengan sesiones de humedad:** corran también con `--sin-temp-hum` y comparen.
   Esa opción quita `temp_c`, `rh_pct`, `abs_hum_gm3`, `temp_comp`, `rh_comp` y sus `_m`/`_d`. El modelo
   02 (que solo usa T y HR) se omite. Quedan partículas, `log10_gas`, `gas_dev_pct` y presión.
2. **Cuidado:** sin T ni humedad, los modelos se apoyan en los **conteos de partículas**. Eso tampoco es
   CO₂: la reacción también soltó partículas. Solo sirve si el escenario real produce CO₂ y partículas
   juntos (por ejemplo, combustión).
3. **`gas_dev_pct` también depende de la compensación.** Si b y c salieron con poco rango de humedad, esa
   columna arrastra el mismo error. Revisen los avisos de `compensar.py`.
4. **Cuando ya tengan sesiones con humedad y temperatura variando** (sección 10), vuelvan a usar
   temperatura y humedad. Ahí el modelo sí puede aprender a separarlas del CO₂.

Prueba con S01 partida en dos (orientativa, son muy pocos datos):

| | Features | Mejor modelo (MAE) | MLP (MAE) | Variable más usada |
|---|---|---|---|---|
| Con T/HR | 25 | kNN 52 ppm (+25 %) | 83 ppm (−19 %) | `abs_hum_gm3` |
| `--sin-temp-hum` | 16 | kNN 56 ppm (+20 %), Huber 57 ppm (+19 %) | 94 ppm (−34 %) | `log_pm1_est` |

---

## 9. Lo que se observó en la sesión S01 (16-oct-2026)

### Eventos de CO₂ (AQM65)

| Evento | CO₂ | Resistencia BME | Partículas (n0_3) | HR BME |
|---|---|---|---|---|
| 1 (14:45–14:46) | ~815 → **1365 ppm** | −2.4 %, se recupera en ~2 min | 44 → 197 | 46.0 → 47.4 % |
| 2 (15:07–15:09) | ~835 → **1546 ppm** | −5.6 %, mínimo 2 min después, recuperación lenta | 85 → 186 | 44.4 → 45.2 % |

### Conclusiones
- **El BME688 no "ve" CO₂.** Su sensor MOX responde a VOC, CO, vapor de agua y otros gases reductores. La baja de
  resistencia en las reacciones se explica por **humedad y probablemente VOC/CO** de la reacción.
- Al compensar T y humedad, **el evento 1 desaparece** (lo explicaba la humedad). En el evento 2 queda una baja
  de −3.4 % que llega 2 min tarde y no se recupera con el CO₂. Se parece más a la curva del **CO** del AQM.
- Correlación CO₂ vs. resistencia: **r = −0.28** (con desfase de 1–4 min no mejora).
- La resistencia depende de la **humedad absoluta (r = −0.82)** y de la **temperatura (r = −0.72)**.
- Las **partículas** se correlacionan con el CO₂ (r ≈ +0.6), solo porque la reacción las genera.
- **Temperatura:** BME vs. AQM r = 0.98, el BME marca **+0.37 °C** de más (autocalentamiento). Su HR
  sale **~1 punto baja** por la misma razón.
- Los primeros ~15 min la resistencia sube sola (62k → 70.5k Ω): es el **calentamiento del MOX**.
- El AQM midió desde las 12:48, con picos de CO₂ a las 13:00, 13:21, 13:42 y 14:09 que **no tienen datos del ESP**.
- Rango de T y humedad en minutos limpios: 1.8 °C y 0.7 g/m³. **Insuficiente para compensar.** Al partir la
  sesión, el coeficiente de temperatura cambia de signo entre mitades.

---

## 10. Plan de sesiones (60 min cada una, 1 muestra por minuto)

### Antes de cada sesión
- [ ] Mismo firmware y **mismo perfil de calentador** (320 °C / 150 ms).
- [ ] **Encender el ESP32 30–60 min antes** del `start`. El firmware mide aunque no haya sesión, así que el
      MOX llega estabilizado y no se pierden minutos. Después usar `compensar.py --calentamiento 2`.
- [ ] Hora correcta (WiFi/NTP o `settime`). Comparar contra el reloj del AQM65.
- [ ] `set interval 60`, `set duration 60`, `set id S0X_descripcion` (**id distinto en cada sesión**).
- [ ] ESP32 junto a la entrada de aire del AQM65, en el mismo lugar en todas las sesiones.
- [ ] El AQM65 debe exportar a 1 minuto y cubrir toda la sesión, con margen antes y después.

### Durante
- [ ] Anotar cada evento con `e <texto>` (ej. `e reaccion 1 inicio`, `e humidificador on`).
- [ ] Separar eventos de CO₂ por **al menos 8 minutos** para que el sensor regrese a su línea base.

### Tipos de sesión

| Tipo | Cuántas | Qué hacer | Para qué |
|---|---|---|---|
| **Solo humedad** | 1–2 | Humidificador o tetera **eléctrica**, T estable. **Sin personas, sin flama.** | Ajustar `c` (efecto de la humedad) |
| **Solo temperatura** | 1–2 | Calefactor o aire acondicionado, sin agregar agua | Ajustar `b` (efecto de la temperatura) |
| **CO₂ "limpio"** | 1–2 | Respiración, tanque o hielo seco (poco VOC). T y HR estables | Ver si el MOX responde al CO₂ mismo |
| **Solo VOC** | 1 | Alcohol, sin CO₂ | Ver la respuesta a VOC sin CO₂ |
| **Reacción / escenario real** | 2–3 | Lo que quieren detectar | Entrenar y validar el modelo |
| **Prueba final** | 2 | Igual que las reales, **no se tocan hasta el final** (`--test`) | Medir el resultado honesto |

**Metas de rango** (sumando todas las sesiones): temperatura **≥ 5 °C**, humedad absoluta **≥ 3 g/m³**.
HR hasta **70–80 %** para comprobar la corrección del PMS. Que temperatura y humedad **no suban siempre
juntas**.

**Referencia de humedad:** el AQM65 no exporta HR (`AIR RH` vacío). Activen su sensor meteorológico si lo
tiene, o usen un higrómetro calibrado. Sin eso, la HR del BME solo se corrige por autocalentamiento.

### Después de cada sesión
1. `python guardar_csv.py COM5 S0X_descripcion.csv`
2. Exportar el AQM65 (1 minuto) que cubra la sesión.
3. `python merge.py --esp ... --aqm ...` (guarda en `entrenamiento/`) y revisar "Minutos unidos".
4. Cuando haya 2 o más sesiones: `compensar.py` con **todas** juntas, luego `entrenar.py`.

---

## 11. ¿Corrección lineal o red neuronal?

- **`compensar.py`:** corrección **lineal** (mínimos cuadrados) más fórmulas físicas. Unos 6 coeficientes.
- **`entrenar.py`:** modelos clásicos de machine learning (lineales, kernel, árboles, kNN) más **un MLP chico**.
- Con 60 puntos por sesión (~300 con 6–8 sesiones), una red grande se aprende los datos de memoria.
  El MLP se dejó pequeño y regularizado para poder compararlo, pero en las pruebas fue **inestable entre sesiones**.
- **Si la corrección lineal no basta** (por ejemplo, falla solo con HR alta): primero agregar términos
  cuadráticos (`T²`, `T·AH`), luego un modelo no lineal chico (proceso gaussiano o árboles). Una red
  neuronal más grande solo con miles de puntos.

---

## 12. Problemas comunes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `Minutos unidos: 0` | Reloj del ESP, zona horaria o el export del AQM no cubre esas horas | `--esp-offset-sec`, `--start`, `--tz`; revisar fechas del export |
| `no tiene hora (epoch_utc vacio)` | El ESP no tenía hora | `--start "NOMBRE=AAAA-MM-DD HH:MM:SS"` |
| `entrenar.py`: "no parece salida de merge" | Le pasaron el CSV crudo | Correr `merge.py` primero |
| `zona horaria desconocida` (Windows) | Falta `tzdata` | `pip install tzdata` |
| `No module named sklearn` | Falta scikit-learn | `pip install scikit-learn` |
| `compensar.py`: "Muy pocos minutos limpios" | Sesión corta o muchos eventos | Bajar `--calentamiento` / `--margen`, precalentar el ESP |
| Resultados viejos desaparecieron | `entrenar.py` sobrescribe `resultados/` | Usar `--salida resultados_S0X` |
| Todo R² ≈ 0 | Pocas sesiones, poco rango o el sensor no ve CO₂ | Más sesiones (sección 10); revisar `senal_ruido` |

---

## 13. Pendientes conocidos

- **Contraseña del WiFi escrita en `esp32s3_logger.ino` y subida a git.** Quitarla del código y cambiarla si el
  repositorio es público.
- El README y `CLAUDE.md` dicen que el TX del PMS5003 va al **GPIO 17**, pero el firmware usa `PIN_PMS_RX = 18`.
  Verificar cuál es el correcto y corregir el otro.
- El firmware trae `logIntervalS = 10` y `durationMin = 2` por defecto. Para sesiones de 1 hora usar
  `set interval 60` y `set duration 60` (o cambiar los valores por defecto).
