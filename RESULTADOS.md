# Resultados: estimación de CO₂ con sensores de bajo costo (PMS5003 + BME688)

Documento con **todos los resultados, tablas y comentarios** del proyecto hasta el 26 de octubre de 2026.
Incluye tres experimentos de entrenamiento, el análisis de correlación entre la resistencia de gas del
BME688 y el CO₂, la implementación de la red en el ESP32-S3 y las conclusiones.

---

## 1. Resumen

- **Objetivo:** estimar el CO₂ (ppm) en interiores con un ESP32-S3 y dos sensores baratos que **no miden
  CO₂**: un PMS5003 (partículas) y un BME688 (temperatura, humedad, presión y resistencia de gas MOX).
  La referencia es un monitor profesional **Aeroqual AQM65**.
- **Modelo:** perceptrón multicapa (MLP) pequeño, elegido entre 24 configuraciones con validación cruzada por sesión.
- **Resultados principales:**
  - **Experimento 1** (3 sesiones): en la prueba con S02 la red explicó el **18 % de la variación** del
    CO₂ (R² = 0.18, MAE 95 ppm), apenas 6 % mejor que predecir el promedio. Al rotar la sesión de prueba,
    el resultado no se sostuvo (R² promedio −12).
  - **Experimento 2** (9 sesiones, con humedad): en la validación la red le ganó al promedio por 6 %
    (R² 0.17). En la prueba final detectó los eventos de CO₂ en S06 (+27.5 % contra el promedio), pero
    falló en S04 (−81 %), donde predijo al revés.
  - **Experimento 3** (9 sesiones, sin humedad): la validación mejoró (+15.8 %, R² 0.27), pero la prueba
    no: S04 siguió al revés y S06 empeoró.
- **Hallazgo central:** **no hay una correlación real entre la resistencia de gas del BME688 y el CO₂.**
  La resistencia depende casi por completo de la **humedad** (r = −0.95). Quitar la humedad como entrada
  no la elimina del modelo, porque sigue entrando a través de la resistencia de gas.
- **Implementación:** la red corre dentro del ESP32-S3 (mismo resultado que en Python, diferencia
  máxima de 0.4 ppm) y se muestra en un dashboard web local en tiempo real.

---

## 2. Hardware y adquisición de datos

| Componente | Función |
|---|---|
| ESP32-S3 | Microcontrolador. Registra las lecturas y, en la versión final, corre la red |
| PMS5003 | Partículas: masa (PM1, PM2.5, PM10) y conteos por tamaño (> 0.3, 0.5, 1, 2.5, 5 y 10 µm) |
| BME688 | Temperatura, humedad relativa, presión y resistencia de gas (sensor MOX, calentador a 320 °C por 150 ms, cada 3 s) |
| Aeroqual AQM65 | Referencia: CO₂ (NDIR), CO, VOC, PM y temperatura. Exporta promedios de 1 minuto |

- **Pines:** BME688 SDA = GPIO 15, SCL = GPIO 16; PMS5003 TX → GPIO 18 (el firmware usa 18; `CLAUDE.md` y
  el README dicen 17, falta verificar el cable).
- **Registro:** el firmware `esp32s3_logger` promedia las lecturas y guarda una fila por minuto en la
  memoria del ESP32. `guardar_csv.py` la copia a la PC.
- **Unión:** `merge.py` alinea por minuto el CSV del ESP32 con el export del AQM65 (zona horaria
  `America/Tijuana`). En todas las sesiones S02–S10 se unieron 60 de 60 minutos; en S01, 59 de 60.

---

## 3. Sesiones de medición

Cada sesión dura ~60 minutos con una muestra por minuto.

| Sesión | Fecha | Descripción | CO₂ (ppm) | Desv. CO₂ | Temp. (°C) | HR (%) | Hum. abs. (g/m³) | Resistencia gas (kΩ) | Uso |
|---|---|---|---|---|---|---|---|---|---|
| S01 | 16-oct | Laboratorio, vinagre + bicarbonato en cantidades no controladas | 809–1546 | 125 | 24.3–26.1 | 44–47 | 10.0–10.9 | 62–71 | Exp. 1; **descartada** en exp. 2 y 3 |
| S02 | 19-oct | Cuarto (sin descripción registrada; CO₂ variando con humedad normal) | 777–1285 | 129 | 23.8–25.6 | 47–52 | 10.9–11.7 | 58–62 | Exp. 1 prueba; exp. 2–3 entrenamiento |
| S03 | 19-oct | Cuarto (sin descripción registrada; humedad subiendo, poco CO₂) | 865–1011 | 39 | 24.2–26.0 | 46–67 | 10.9–15.1 | 44–64 | Entrenamiento |
| S04 | 22-oct | CO₂ arriba 20 min | 830–1388 | 176 | 24.1–25.7 | 52–72 | 12.5–16.0 | 44–58 | **Prueba** exp. 2–3 |
| S05 | 22-oct | Mucha humedad, sin subir CO₂ | 833–1109 | 53 | 24.0–24.8 | 67–82 | 14.8–18.3 | 44–52 | Entrenamiento |
| S06 | 23-oct | CO₂ bajo; 2 subidas de 10 min; 1 persona | 527–1305 | 187 | 24.3–25.3 | 47–51 | 10.7–11.7 | 56–68 | **Prueba** exp. 2–3 |
| S07 | 23-oct | Humedad + 2 subidas de CO₂ de 10 min | 578–1415 | 250 | 23.5–24.6 | 67–84 | 14.8–17.9 | 39–52 | Entrenamiento |
| S08 | 23-oct | Solo humedad, > 80 % | 655–891 | 65 | 23.5–23.6 | 85–86 | 17.9–18.2 | 45–47 | Entrenamiento |
| S09 | 23-oct | Humedad → subir CO₂ → quitar humedad → subir CO₂ | 753–1506 | 216 | 23.7–25.8 | 46–85 | 11.2–18.4 | 46–69 | Entrenamiento |
| S10 | 23-oct | Humedad en escalones cada ~10 min; últimos 10 min > 80 % | 740–1020 | 49 | 24.4–25.9 | 46–85 | 11.0–19.0 | 42–69 | Entrenamiento |

**Comentarios sobre los datos:**
- **S01 se descartó** en los experimentos 2 y 3. El vinagre libera ácido acético (un VOC) y vapor de agua,
  que alteran al BME688; además los primeros ~15 minutos fueron de calentamiento del sensor.
- **S04 tiene una subida de humedad (52 % → 72 %) al final que no está en su descripción.** Ocurre después
  del evento de CO₂ y justo antes de S05 (que empezó 4 minutos después), así que probablemente se estaba
  preparando el humidificador para S05.
- **S06 es la única sesión con CO₂ base tan bajo (~530 ppm).**
- Las sesiones **no tienen eventos anotados** con el comando `e` del firmware; las descripciones vienen de
  notas aparte.

---

## 4. Metodología

### 4.1 Variables de entrada
Solo variables que tendrá el dispositivo final (las columnas del AQM65 nunca entran al modelo):

| Grupo | Variables |
|---|---|
| Partículas (8) | log(1 + conteo) de > 0.3, 0.5, 1, 2.5, 5 y 10 µm; log(1 + PM1 estimado); log(1 + PM2.5 estimado) |
| BME688 (4) | Temperatura, HR, humedad absoluta, log₁₀ de la resistencia de gas |
| Dinámicas (8) | Promedio móvil y tendencia de 5 min de: log₁₀ gas, humedad absoluta, temperatura, log conteo > 0.3 µm |
| Presión (1) | Se probó con y sin ella |

### 4.2 Validación
- **Por sesión, nunca por filas al azar:** minutos consecutivos son casi idénticos, y mezclarlos haría que
  el modelo se aprendiera los datos de memoria.
- **Validación cruzada dejando una sesión fuera:** se entrena con todas las sesiones de entrenamiento menos
  una y se prueba en esa, rotando.
- **Sesiones de prueba final:** se apartan antes de entrenar, no se usan para elegir nada y se evalúan una
  sola vez.

### 4.3 Búsqueda de la red (24 configuraciones)

| Parámetro | Valores probados |
|---|---|
| Capas ocultas | (4), (8), (16), (8, 4) neuronas |
| Regularización `alpha` | 0.1, 1, 10 |
| Activación | `tanh`, `relu` |
| Entrenamiento | `lbfgs`, entradas y CO₂ escalados (`StandardScaler`) |
| Estabilidad | Cada configuración es el promedio de **5 redes con semillas distintas** |

**Regla de elección:** menor MAE de validación; si otra red queda a menos de 5 ppm, gana la más chica.

### 4.4 Métricas

| Métrica | Qué mide |
|---|---|
| **MAE** | Error absoluto medio en ppm. "En promedio, se equivoca X ppm" |
| **RMSE** | Raíz del error cuadrático medio, en ppm. Castiga más los errores grandes |
| **R²** | Fracción de la variación del CO₂ que explica el modelo. 1 = perfecto, 0 = igual que predecir el promedio, negativo = peor que el promedio. **No es un porcentaje de aciertos** |
| **Mejora vs. promedio** | Cuánto menor es el MAE del modelo que el de predecir siempre el promedio de entrenamiento |

En las pruebas, la referencia "Promedio" usa el promedio del CO₂ **de entrenamiento**; por eso su R² puede
salir negativo (la sesión de prueba tiene otro nivel promedio).

---

## 5. Experimento 1: primeras tres sesiones (S01, S02, S03)

- **Entrenamiento:** S01 + S03. **Prueba:** S02 (elegida antes de ver resultados por tener el rango de CO₂
  más amplio).
- **Validación:** entrenar con S01 y probar en S03, y al revés.

### 5.1 Línea base: 17 modelos clásicos (con presión)

| Modelo | MAE | RMSE | R² | Mejora vs. promedio |
|---|---|---|---|---|
| Promedio | 72.2 | 102.7 | −0.18 | — |
| **Huber** | **61.1** | 98.2 | −0.08 | **+15.4 %** |
| Extra Trees | 67.2 | 97.9 | −0.07 | +6.9 % |
| SVR | 69.7 | 100.3 | −0.13 | +3.5 % |
| Kernel Ridge | 71.7 | 102.8 | −0.18 | +0.7 % |
| Proceso gaussiano | 71.8 | 102.9 | −0.18 | +0.6 % |
| Random Forest | 90.6 | 114.9 | −0.48 | −25.4 % |
| GBM chico | 109.9 | 137.4 | −1.11 | −52.2 % |
| PLS | 109.6 | 157.6 | −1.77 | −51.8 % |
| kNN | 112.8 | 133.6 | −0.99 | −56.2 % |
| Árbol chico | 145.4 | 178.2 | −2.55 | −101.3 % |
| Ridge fuerte | 169.5 | 210.7 | −3.96 | −134.8 % |
| Bayesian Ridge | 188.5 | 255.0 | −6.27 | −161.0 % |
| MLP fijo (8 neuronas, tanh) | 211.3 | 269.6 | −7.12 | −192.6 % |
| Elastic Net | 304.0 | 420.4 | −18.74 | −321.0 % |
| Ridge | 388.5 | 538.0 | −31.34 | −437.9 % |
| Lineal (solo T y HR) | 487.0 | 696.8 | −53.24 | −574.3 % |

**Comentarios:** ningún modelo le ganó con claridad al promedio. Los lineales fallaron mucho en S03 porque
su humedad (hasta 67 %) quedó fuera del rango de S01.

### 5.2 Búsqueda de la red

| Variante | Red elegida | MAE val. | RMSE val. | R² val. | Mejora vs. promedio |
|---|---|---|---|---|---|
| Con presión | 8×4, α = 10, tanh | 135.5 | — | — | −87.7 % |
| **Sin presión** | **16, α = 0.1, tanh** | **64.3** | 99.8 | −0.11 | **+11.0 %** |

Por sesión (red elegida sin presión): S01 65.1 ppm (promedio 98.2) y S03 63.4 ppm (promedio 46.6).

**Comentarios:**
- **La presión engañaba al modelo:** cambia con el clima de cada día, no con el CO₂. Quitarla bajó el error
  a la mitad.
- **`relu` falló fuertemente** en esta etapa (errores de miles de ppm): al salir del rango de
  entrenamiento sus predicciones crecen sin límite. `tanh` limita la salida.

### 5.3 Prueba final en S02

| | MAE | RMSE | R² |
|---|---|---|---|
| **MLP (16, α = 0.1, tanh, sin presión)** | **94.7** | 115.7 | **0.18** |
| Promedio | 100.5 | 128.4 | 0.00 |

- Mejora vs. promedio: **+5.8 %**. Correlación real vs. predicho: **0.52**.
- Sigue a medias la subida grande de 13:04–13:14 (predice ~1000–1100 ppm, el real llega a 1285).
- **Predice una subida falsa entre 12:52 y 13:03** (hasta 1160 ppm con el real en ~845): en esos minutos
  solo subió la temperatura.
- No detecta los picos cortos de 2–3 min.

### 5.4 Rotación de la sesión de prueba (validación cruzada anidada)
En cada ronda se aparta una sesión y la red se busca de nuevo, con y sin presión, solo con las otras dos.

| Prueba | Entrenamiento | Red elegida | MAE val. (promedio) | MAE prueba | RMSE prueba | R² prueba | MAE promedio | Mejora |
|---|---|---|---|---|---|---|---|---|
| S01 | S02 + S03 | 8×4, α = 0.1, tanh | 104.1 (73.3) | 179.9 | 225.9 | −2.31 | 91.9 | −95.7 % |
| S02 | S01 + S03 | 16, α = 0.1, tanh | 64.3 (72.2) | 94.7 | 115.7 | 0.18 | 100.5 | +5.8 % |
| S03 | S01 + S02 | 8×4, α = 1, tanh | 118.0 (89.1) | 185.0 | 232.4 | −34.33 | 39.4 | −369.1 % |
| **Promedio** | | | | **153.2** | | **−12.15** | **77.3** | |

**Comentarios:**
- Solo la ronda de S02 funcionó. S02 es la sesión que más se parece a las otras dos.
- En las rondas de S01 y S03 ninguna red le ganó al promedio ni siquiera en la validación.
- En S01 la red predijo una subida larga cuando el CO₂ estaba plano (coincidía con el aire acondicionado y
  el calentamiento del sensor). En S03 osciló entre 850 y 1420 ppm con el real casi fijo, porque la humedad
  (hasta 61 %) estaba fuera de lo visto al entrenar.
- En cada ronda ganó una arquitectura distinta; lo constante fue: **sin presión, `tanh` y redes chicas**.

---

## 6. Experimento 2: nueve sesiones, con humedad

- **S01 descartada.** **Entrenamiento (7):** S02, S03, S05, S07, S08, S09, S10 (420 minutos).
  **Prueba (2):** S04 y S06.
- **Razones del split:** mucha variación de CO₂ en las dos de prueba (desv. 176 y 187), una con humedad
  estable (S06, parecida a una demostración con personas) y otra con humedad cambiando (S04), de días
  distintos, y sin sesiones de entrenamiento grabadas inmediatamente antes y después de ellas.
- Rango del entrenamiento: CO₂ 578–1506 ppm, humedad absoluta 10.9–19.0 g/m³.

### 6.1 Línea base: 17 modelos (sin presión)

| Modelo | MAE | RMSE | R² | Mejora vs. promedio |
|---|---|---|---|---|
| Promedio | 112.2 | 161.8 | −0.08 | — |
| **Kernel Ridge** | **108.8** | 149.1 | 0.09 | **+3.0 %** |
| Proceso gaussiano | 109.3 | 149.2 | 0.09 | +2.6 % |
| Extra Trees | 118.5 | 154.3 | 0.02 | −5.7 % |
| SVR | 119.1 | 159.7 | −0.05 | −6.1 % |
| Lineal (solo T y HR) | 120.0 | 162.9 | −0.09 | −6.9 % |
| GBM chico | 122.0 | 156.2 | 0.00 | −8.8 % |
| kNN | 129.9 | 169.8 | −0.19 | −15.8 % |
| Random Forest | 137.5 | 168.0 | −0.16 | −22.5 % |
| Ridge fuerte | 141.7 | 187.5 | −0.44 | −26.3 % |
| Elastic Net | 141.8 | 187.7 | −0.45 | −26.4 % |
| Ridge | 146.4 | 191.9 | −0.51 | −30.5 % |
| Bayesian Ridge | 149.1 | 195.3 | −0.57 | −32.9 % |
| PLS | 149.2 | 198.7 | −0.62 | −33.0 % |
| Árbol chico | 152.5 | 185.2 | −0.41 | −36.0 % |
| Huber | 153.2 | 199.4 | −0.63 | −36.5 % |
| MLP fijo (8 neuronas, tanh) | 160.0 | 206.7 | −0.76 | −42.7 % |

MAE por sesión de algunos modelos (validación):

| Sesión | Promedio | Extra Trees | Kernel Ridge | Proc. gaussiano | MLP fijo |
|---|---|---|---|---|---|
| S02 | 86.7 | 118.8 | 78.9 | 80.1 | 203.4 |
| S03 | 84.1 | 69.8 | 77.6 | 131.8 | 279.1 |
| S05 | 20.5 | 120.4 | 65.6 | 80.5 | 130.5 |
| S07 | 240.2 | 208.8 | 191.7 | 178.6 | 167.3 |
| S08 | 117.1 | 88.3 | 132.3 | 77.7 | 87.6 |
| S09 | 151.1 | 131.2 | 130.7 | 126.8 | 123.2 |
| S10 | 85.6 | 92.6 | 84.5 | 89.2 | 129.2 |

### 6.2 Búsqueda de la red

| Variante | Red | MAE val. | RMSE val. | R² val. | Mejora | Parámetros |
|---|---|---|---|---|---|---|
| Sin presión | 8×4, α = 10, relu | 104.4 | 137.3 | 0.23 | +6.9 % | 209 |
| **Sin presión (elegida)** | **8, α = 10, relu** | **105.1** | 142.0 | **0.17** | **+6.3 %** | 177 |
| Sin presión | 16, α = 10, relu | 106.2 | 144.0 | 0.15 | +5.3 % | 353 |
| Con presión | 8, α = 10, relu | 105.6 | 149.3 | 0.08 | +5.8 % | 185 |
| Promedio | — | 112.2 | 161.8 | −0.08 | — | — |

La de 8 neuronas se eligió sobre la de 8×4 por la regla de empate (menos de 5 ppm de diferencia, gana la
más chica).

MAE por sesión de la red elegida (validación):

| Sesión | S02 | S03 | S05 | S07 | S08 | S09 | S10 |
|---|---|---|---|---|---|---|---|
| Red (8, relu) | 106.5 | 88.3 | 48.9 | 167.3 | 102.6 | 105.3 | 117.2 |
| Promedio | 86.7 | 84.1 | 20.5 | 240.2 | 117.1 | 151.1 | 85.6 |

**Comentarios:**
- **Ahora gana `relu`** (con regularización fuerte, α = 10): con más rango de humedad y CO₂ ya no se dispara.
- **Sin presión sigue siendo mejor**, aunque por poco.
- La red le gana claramente al promedio donde el CO₂ se mueve mucho (S07, S09) y pierde donde casi no se
  mueve (S05).

### 6.3 Prueba final en S04 y S06

| Prueba | Modelo | MAE | RMSE | R² | Mejora vs. promedio |
|---|---|---|---|---|---|
| S04 | **MLP** | 246.3 | 302.8 | −2.02 | **−81.1 %** |
| S04 | Promedio | 136.0 | 216.6 | −0.55 | — |
| S06 | **MLP** | 176.1 | 202.4 | −0.19 | **+27.5 %** |
| S06 | Promedio | 243.0 | 262.1 | −1.00 | — |
| Media de las dos | MLP / Promedio | 211.2 / 189.5 | | | |

**Comentarios:**
- **S06:** la red **detecta los dos eventos de CO₂** (09:45 y 10:03), sube y baja con ellos, pero **se queda
  200–300 ppm arriba en los tramos bajos** (real ~540, predicho 700–880). S06 baja a 527 ppm, menos que
  cualquier sesión de entrenamiento (mínimo 578).
- **S04: la red predice al revés.** Con el CO₂ alto (14:10–14:33) predice ~750 ppm; cuando el CO₂ cae
  (14:34) sube a ~950 ppm. En S04 la humedad subió justo cuando el CO₂ bajó (correlación −0.54), y la red
  interpretó la humedad como CO₂.
- **Problema del split:** S06 no tenía una sesión "gemela" en el entrenamiento (nivel base tan bajo), y la
  subida de humedad al final de S04 no estaba planeada. Con las descripciones de las sesiones el split
  habría sido distinto, pero no se cambió después de ver los resultados para no sesgar la prueba.

---

## 7. Experimento 3: nueve sesiones, sin humedad

Mismo split del experimento 2 y sin presión. Se quitaron **HR, humedad absoluta y sus promedios y
tendencias de 5 min** (16 entradas en lugar de 20). La temperatura y la resistencia de gas se mantienen.

### 7.1 Línea base: 17 modelos (16 sin el modelo lineal de T y HR)

| Modelo | MAE con humedad | MAE sin humedad | Mejora con | Mejora sin |
|---|---|---|---|---|
| Promedio | 112.2 | 112.2 | — | — |
| **Kernel Ridge** | 108.8 | **104.1** | +3.0 % | **+7.2 %** |
| Proceso gaussiano | 109.3 | 108.5 | +2.6 % | +3.2 % |
| SVR | 119.1 | 114.7 | −6.1 % | −2.3 % |
| Extra Trees | 118.5 | 123.8 | −5.7 % | −10.3 % |
| kNN | 129.9 | 128.0 | −15.8 % | −14.1 % |
| GBM chico | 122.0 | 134.8 | −8.8 % | −20.2 % |
| Ridge fuerte | 141.7 | 141.9 | −26.3 % | −26.5 % |
| Elastic Net | 141.8 | 141.9 | −26.4 % | −26.5 % |
| Ridge | 146.4 | 145.7 | −30.5 % | −29.9 % |
| Random Forest | 137.5 | 146.3 | −22.5 % | −30.4 % |
| Bayesian Ridge | 149.1 | 147.6 | −32.9 % | −31.5 % |
| PLS | 149.2 | 148.8 | −33.0 % | −32.7 % |
| Huber | 153.2 | 152.0 | −36.5 % | −35.5 % |
| MLP fijo | 160.0 | 154.5 | −42.7 % | −37.7 % |
| Árbol chico | 152.5 | 175.5 | −36.0 % | −56.5 % |
| Lineal (solo T y HR) | 120.0 | (no aplica) | −6.9 % | — |

### 7.2 Búsqueda de la red

| Variante | Red elegida | MAE val. | RMSE val. | R² val. | Mejora | Parámetros |
|---|---|---|---|---|---|---|
| Con humedad (exp. 2) | 8, α = 10, relu | 105.1 | 142.0 | 0.17 | +6.3 % | 177 |
| **Sin humedad** | **8, α = 10, relu** | **94.5** | **132.9** | **0.27** | **+15.8 %** | 145 |

MAE por sesión (validación):

| Sesión | S02 | S03 | S05 | S07 | S08 | S09 | S10 |
|---|---|---|---|---|---|---|---|
| Con humedad | 106.5 | 88.3 | 48.9 | 167.3 | 102.6 | 105.3 | 117.2 |
| **Sin humedad** | **88.1** | **54.8** | **45.6** | **161.4** | 111.9 | 114.4 | **85.2** |
| Promedio | 86.7 | 84.1 | 20.5 | 240.2 | 117.1 | 151.1 | 85.6 |

### 7.3 Prueba en S04 y S06

| Prueba | Modelo | MAE | RMSE | R² | Mejora vs. promedio |
|---|---|---|---|---|---|
| S04 | MLP con humedad (exp. 2) | 246.3 | 302.8 | −2.02 | −81.1 % |
| S04 | **MLP sin humedad** | 234.8 | 289.0 | −1.75 | −72.7 % |
| S04 | Promedio | 136.0 | 216.6 | −0.55 | — |
| S06 | MLP con humedad (exp. 2) | 176.1 | 202.4 | −0.19 | +27.5 % |
| S06 | **MLP sin humedad** | 235.9 | 267.9 | −1.09 | +2.9 % |
| S06 | Promedio | 243.0 | 262.1 | −1.00 | — |
| Media | Con / sin humedad / promedio | 211.2 / 235.4 / 189.5 | | | |

**Comentarios:**
- **La validación mejora** (+15.8 % contra +6.3 %, R² 0.27 contra 0.17), en 5 de 7 sesiones.
- **La prueba no mejora:** S04 sigue al revés (casi igual que con humedad) y S06 empeora (en los tramos
  bajos predice ~900 ppm con el real en ~540, aunque sigue detectando los dos eventos).
- **Por qué no se arregló S04:** la información de humedad sigue entrando a través de la resistencia de gas
  (ver sección 8). Quitar la HR no basta.
- S04 y S06 ya se habían usado en el experimento 2, así que esta prueba sirve para **comparar** las dos
  versiones, no como prueba final independiente.

---

## 8. Correlación entre la resistencia de gas del BME688 y el CO₂

### 8.1 Por sesión
r = coeficiente de correlación con el log₁₀ de la resistencia de gas.

| Sesión | r simple CO₂–gas | r parcial (descontando T y humedad) | r de los cambios minuto a minuto | r gas–humedad |
|---|---|---|---|---|
| S01 (descartada) | −0.28 | +0.07 | −0.22 | −0.82 |
| S02 | −0.29 | +0.26 | −0.06 | −0.31 |
| S03 | −0.13 | +0.56 | −0.17 | −0.89 |
| S04 | +0.64 | +0.50 | +0.23 | −0.81 |
| S05 | +0.63 | −0.05 | −0.10 | −0.76 |
| S06 | −0.34 | +0.32 | **−0.68** | −0.38 |
| S07 | +0.51 | −0.05 | +0.20 | −0.63 |
| S08 | +0.75 | +0.68 | +0.20 | −0.05 |
| S09 | +0.05 | +0.07 | +0.09 | **−1.00** |
| S10 | −0.20 | +0.34 | −0.31 | **−0.99** |

### 8.2 Juntando las 9 sesiones (sin S01, restando el promedio de cada sesión)

| Relación | r |
|---|---|
| Resistencia – humedad | **−0.95** |
| Resistencia – CO₂ | +0.09 |
| Resistencia – CO₂, descontando temperatura y humedad | +0.15 |

Regresión que separa los efectos:
- **+1 g/m³ de humedad → la resistencia baja 5.7 %.**
- **+100 ppm de CO₂ → la resistencia cambia +0.3 %**: menos que el ruido normal del sensor (~1.4 %) y en
  dirección contraria a la de un gas que el sensor detecta (la resistencia bajaría, no subiría).

### 8.3 Análisis inicial de S01
- r(CO₂, resistencia) = −0.28, sin mejora con desfases de 1 a 4 minutos.
- La resistencia dependía de la humedad absoluta (r = −0.82) y de la temperatura (r = −0.72).
- Las partículas se correlacionaban con el CO₂ (r ≈ +0.6) solo porque la reacción también las generaba.
- Al compensar temperatura y humedad, el primer evento de CO₂ desaparecía por completo (lo explicaba la
  humedad); en el segundo quedaba una baja de −3.4 % que llegaba 2 minutos tarde y no se recuperaba con el
  CO₂, más parecida a la curva del CO del AQM65 (probablemente ácido acético del vinagre).
- El BME688 marcaba +0.37 °C más que el AQM65 (autocalentamiento) y ~1 punto menos de HR por la misma razón.

### 8.4 Conclusiones de la correlación
1. **No hay una correlación real entre la resistencia de gas y el CO₂.** Tiene sentido físicamente: el sensor
   MOX del BME688 responde a gases reductores y VOC, y el CO₂ es químicamente inerte para él.
2. **La resistencia depende casi por completo de la humedad** (r = −0.95; −1.00 en S09 y −0.99 en S10).
3. **La correlación con el CO₂ cambia de signo entre sesiones**, incluso después de descontar temperatura y
   humedad: son efectos propios de cada sesión, no una respuesta del sensor.
4. **La única señal que parece real es S06** (una persona): la resistencia baja justo cuando sube el CO₂
   (r = −0.68 en los cambios). Lo más probable es que el sensor detecte los **VOC de la respiración**, que
   salen junto con el CO₂. Esto podría servir para estimar CO₂ cuando viene de personas, pero no cuando
   viene de una reacción química.
5. **Aunque se quite la humedad como entrada, sigue entrando a través de la resistencia de gas.** Por eso el
   experimento 3 no corrigió el error de S04.

---

## 9. Implementación en el ESP32-S3 y dashboard

- **Exportación:** `exportar_modelo.py` convierte la red de Python a un archivo de C (`modelo_co2.h`) con el
  escalado, los pesos de las 5 redes y los rangos de entrenamiento.
- **Red desplegada:** la del experimento 1 (20 → 16 `tanh` → 1, 5 redes promediadas, 1 765 pesos). Las
  redes de los experimentos 2 y 3 usan `relu` y todavía no son exportables (falta implementar `relu` en
  `co2_mlp.h`).
- **Verificación:** con los datos crudos de S02 minuto a minuto, el ESP32 (C++) y Python dieron el mismo
  resultado, con una diferencia máxima de **0.4 ppm**.
- **Firmware `esp32s3_co2`:** solo sensores y red. Ocupa 28 % del flash y 8 % de la RAM. Publica una
  predicción **cada 5 s** usando siempre el promedio del último minuto (12 estimadores desfasados 5 s, cada
  uno recibe un promedio de 1 min por minuto, igual que en el entrenamiento).
- **Indicador "fuera de rango":** cuántas de las 20 entradas tienen valores que la red no vio al entrenar.
  En la práctica salió entre 12 y 17 de 20, lo que indica que las condiciones de uso estaban lejos de las de
  entrenamiento.
- **Dashboard:** página local en React + TypeScript que lee el ESP32 por USB (Web Serial, Chrome/Edge), con
  gráfica en tiempo real, número grande con nivel de CO₂, banderas de conexión, alertas y botones de
  iniciar/parar. Protocolo serie: `#HOLA`, `#ESTADO`, `#PRED`, `#AVISO`.
- **Prueba en vivo:** al soplar cerca del sensor, la estimación subió poco.

---

## 10. Hallazgos generales

1. **El BME688 no mide CO₂ ni de forma indirecta confiable:** su resistencia de gas sigue a la humedad.
2. **La presión engaña al modelo** (cambia con el clima del día). Quitarla redujo el error de validación a
   la mitad en el experimento 1 y mejoró ligeramente en el experimento 2.
3. **`relu` sin suficiente rango de datos diverge;** con más rango y α = 10 funcionó mejor que `tanh`.
4. **El modelo confunde humedad y temperatura con CO₂** porque en varias sesiones subían juntas o en
   sentido contrario. El caso más claro es S04 (predicción invertida).
5. **Los conteos de partículas se correlacionan con el CO₂ solo cuando la fuente genera ambos** (reacción
   química, personas); no es una medición de CO₂.
6. **Ningún modelo clásico** (lineales, árboles, kernel, kNN, proceso gaussiano) le ganó al promedio por
   más de 7 % en la validación con 7 sesiones.
7. **La validación y la prueba no coinciden:** en el experimento 3 la validación mejoró y la prueba empeoró.
   Con 2 sesiones de prueba los resultados son muy variables.

---

## 11. Por qué no conviene iterar permutaciones entre sesiones

Una tentación natural, al ver resultados malos, es **probar otras combinaciones de entrenamiento y prueba
hasta encontrar una que dé buenos números**. Con 9 sesiones hay 36 formas distintas de apartar 2 como
prueba. No es favorable, por estas razones:

1. **Se convierte la prueba en parte del entrenamiento.** Si la combinación se elige *después* de ver cómo
   le fue al modelo, la sesión de prueba ya influyó en la decisión. El número final deja de medir qué tan
   bien funciona el modelo en una sesión nueva y pasa a medir qué tan bien se escogió la sesión más fácil.
   Por eso las sesiones de prueba se apartan **antes** de entrenar y se evalúan **una sola vez**.
2. **Con tantas combinaciones, alguna sale bien por suerte.** Si se prueban 36 combinaciones y se reporta la
   mejor, el resultado está inflado aunque el modelo no haya mejorado. Es el mismo problema que lanzar un
   dado muchas veces y reportar solo el 6.
3. **La variación entre combinaciones es enorme.** En el experimento 1, el mismo procedimiento dio:

   | Sesión de prueba | MAE | R² |
   |---|---|---|
   | S02 | 94.7 | **0.18** |
   | S01 | 179.9 | −2.31 |
   | S03 | 185.0 | **−34.33** |

   La diferencia no viene del modelo, sino de qué sesión tocó como prueba. Elegir la combinación favorable
   sería reportar 0.18 cuando el comportamiento típico es mucho peor.
4. **Las sesiones no son intercambiables.** Cada una es un escenario distinto (solo humedad, CO₂ con humedad
   alta, una persona, etc.). Una combinación "buena" solo indica que la sesión de prueba se parece a alguna
   del entrenamiento (por ejemplo, S02 se parece a S01 y S03), no que el modelo generalice.
5. **Cada sesión de prueba vista se "gasta".** Después de ver cómo le fue al modelo en S04 y S06, ya no
   sirven como prueba independiente para un modelo nuevo. Iterar combinaciones va gastando todas las
   sesiones, y al final no queda ninguna para medir honestamente.
6. **Pocas muestras por prueba.** Cada sesión son 60 minutos muy correlacionados entre sí (un minuto se
   parece mucho al siguiente), así que una sola sesión de prueba equivale a pocas observaciones
   independientes. Cualquier diferencia entre combinaciones está dentro del ruido.
7. **Costo de cómputo.** Cada ronda completa (búsqueda de 24 redes × 5 semillas con validación interna, con
   y sin presión) tarda 15–20 minutos con 7 sesiones de entrenamiento; recorrer todas las combinaciones
   tomaría horas sin dar información más confiable.

**Lo que sí es válido:** la **rotación completa** (`permutaciones.py`, validación cruzada anidada). En cada
ronda se aparta una sesión, la red se elige solo con las demás, y al final se **reporta el promedio de todas
las rondas**, sin escoger ninguna. Así cada sesión sirve exactamente una vez de prueba y el resultado no
depende de qué combinación se eligió. La diferencia clave es **promediar todas las combinaciones, nunca
elegir la favorable**. Esta es la forma recomendada de evaluar mientras haya pocas sesiones (ver sección 13).

---

## 12. Limitaciones

- **Pocas sesiones** (9 útiles) y cada una con un escenario distinto: una sesión de prueba casi nunca tiene
  una "gemela" en el entrenamiento.
- **Sesiones consecutivas el mismo día** (S06–S10, S04–S05) comparten condiciones; la preparación de una
  sesión puede contaminar la anterior (caso de S04).
- **Sin eventos anotados** en los CSV.
- **S04 y S06 ya se usaron como prueba**; cualquier modelo nuevo necesita sesiones de prueba nuevas.
- **El AQM65 no exporta humedad de referencia** (columnas `AIR RH` y `AIR T` vacías).
- **La fuente de CO₂** (bicarbonato con vinagre o ácido cítrico) también puede liberar agua, partículas o
  VOC.

---

## 13. Siguientes pasos

1. **Probar sin humedad y sin resistencia de gas** (solo partículas y temperatura) para medir cuánto aporta
   realmente el BME688.
2. **Compensar la resistencia de gas por humedad** (`compensar.py`, rama `dev`) en lugar de quitarla.
3. **Evaluar con validación cruzada anidada sobre las 9 sesiones** (`permutaciones.py`), donde cada sesión
   sirve una vez de prueba y la red se elige sin verla.
4. **Grabar sesiones de prueba nuevas** que sean "gemelas" de escenarios del entrenamiento: una como S06
   (CO₂ con una persona, humedad normal, empezando en ~500 ppm) y una como S09 (CO₂ con humedad alta y
   luego normal).
5. **Anotar eventos con `e`** en el firmware y dejar ~10 minutos de aire tranquilo entre sesiones.
6. **Más sesiones con personas,** que es el escenario donde apareció la única señal real (VOC de la
   respiración).
7. **Implementar `relu` en el ESP32** si se decide desplegar una red de los experimentos 2 o 3.

---

## 14. Archivos de resultados

| Carpeta / archivo | Contenido |
|---|---|
| `resultados_base/` | Exp. 1: 17 modelos (prueba S02 apartada) |
| `modelo_mlp/` | Exp. 1: búsqueda, red elegida y prueba en S02 (`prueba_S02.csv`/`.png`) |
| `permutaciones/` | Exp. 1: rotación de la sesión de prueba (`resumen.csv`, `resumen.png`) |
| `resultados_v2/` | Exp. 2: 17 modelos con humedad |
| `modelo_mlp_v2_sin_presion/` | Exp. 2: red elegida y prueba en S04 y S06 |
| `modelo_mlp_v2_con_presion/` | Exp. 2: búsqueda con presión (no elegida) |
| `resultados_v2_sin_humedad/` | Exp. 3: 16 modelos sin humedad |
| `modelo_mlp_v2_sin_humedad/` | Exp. 3: red sin humedad y prueba en S04 y S06 |
| `entrenamiento/` | CSV unidos por sesión (`descartadas/S01_train.csv`) |
| `esp32s3_co2/`, `dashboard/` | Red en el ESP32 y dashboard en tiempo real |
