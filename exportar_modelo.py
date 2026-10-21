#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
exportar_modelo.py - Pasa el MLP guardado por entrenar.py --buscar-mlp a un .h para el ESP32.

Uso:
  python exportar_modelo.py                                  # modelo_mlp/modelo_mlp.joblib -> esp32s3_co2/modelo_co2.h
  python exportar_modelo.py --modelo otra/modelo_mlp.joblib --prueba entrenamiento/S02_train.csv

Genera modelo_co2.h con:
  - medias y escalas de las entradas (StandardScaler) y del CO2,
  - pesos de las N redes que se promedian (una por semilla),
  - rangos min/max de cada entrada en el entrenamiento (para avisar si se sale),
  - 3 vectores de prueba con la prediccion de Python (comando "mlp test" en el ESP32).
Despues abran esp32s3_co2/esp32s3_co2.ino en Arduino IDE y suban el firmware.
"""
import argparse
import sys
from pathlib import Path

import joblib
import numpy as np

from entrenar import cargar, crear_features

# orden de entradas que calcula co2_mlp.h; si el modelo usa otro, hay que cambiar co2_mlp.h
ENTRADAS_ESP = [
    "log_n0_3", "log_n0_5", "log_n1_0", "log_n2_5", "log_n5_0", "log_n10", "log_pm1_est", "log_pm2_5_est",
    "temp_c", "rh_pct", "abs_hum_gm3", "log10_gas",
    "log10_gas_m5", "abs_hum_gm3_m5", "temp_c_m5", "log_n0_3_m5",
    "log10_gas_d5", "abs_hum_gm3_d5", "temp_c_d5", "log_n0_3_d5",
]


def flotante(x):
    s = f"{x:.9g}"
    return s + ("f" if any(c in s for c in ".e") else ".0f")   # "0f" no es valido en C


def arreglo(nombre, valores):
    v = np.asarray(valores, dtype=float).ravel()
    cuerpo = ",\n  ".join(", ".join(flotante(x) for x in v[i:i + 6]) for i in range(0, len(v), 6))
    return f"static const float {nombre}[{len(v)}] = {{\n  {cuerpo}\n}};\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modelo", default="modelo_mlp/modelo_mlp.joblib")
    ap.add_argument("--prueba", default="entrenamiento/S02_train.csv", help="CSV para los vectores de prueba")
    ap.add_argument("--out", default="esp32s3_co2/modelo_co2.h")
    a = ap.parse_args()

    g = joblib.load(a.modelo)
    modelo, meta = g["modelo"], g["meta"]
    if meta["cols"] != ENTRADAS_ESP or meta["ventana"] != 5:
        sys.exit("Este modelo usa otras entradas o ventana; co2_mlp.h calcula solo:\n  " + ", ".join(ENTRADAS_ESP))

    escx, votacion = (paso for _, paso in modelo.regressor_.steps)
    escy = modelo.transformer_
    redes = votacion.estimators_
    capas = redes[0].hidden_layer_sizes
    if len(capas) != 1 or any(r.activation != "tanh" for r in redes):
        sys.exit("co2_mlp.h solo implementa 1 capa oculta con tanh.")
    oculta = capas[0]

    # rangos de entrenamiento (por entrada) para avisar cuando el ESP mide algo que la red nunca vio
    rutas = [str(Path("entrenamiento") / f"{s}_train.csv") for s in meta["sesiones_entrenamiento"]]
    ent, cols = crear_features(cargar(rutas, meta["saltar_min"]), meta["ventana"], meta["sin_presion"])
    xmin, xmax = ent[cols].min().values, ent[cols].max().values

    prueba, _ = crear_features(cargar([a.prueba], meta["saltar_min"]), meta["ventana"], meta["sin_presion"])
    filas = np.linspace(10, len(prueba) - 1, 3).astype(int)
    xp = prueba[cols].iloc[filas]
    yp = modelo.predict(xp)

    n = len(cols)
    h = [
        "// Generado por exportar_modelo.py. NO editar a mano.",
        f"// Modelo: {meta['nombre']} | entrenado con {', '.join(meta['sesiones_entrenamiento'])} | "
        f"{len(redes)} redes promediadas",
        "// Entradas (en este orden): " + ", ".join(cols),
        "#pragma once",
        "",
        f"#define MLP_ENTRADAS {n}",
        f"#define MLP_OCULTA {oculta}",
        f"#define MLP_REDES {len(redes)}",
        f"#define MLP_VENTANA {meta['ventana']}",
        f"#define MLP_NOMBRE \"{meta['nombre']}\"",
        "",
        arreglo("MLP_X_MEDIA", escx.mean_),
        arreglo("MLP_X_ESCALA", escx.scale_),
        f"static const float MLP_Y_MEDIA = {flotante(escy.mean_[0])};",
        f"static const float MLP_Y_ESCALA = {flotante(escy.scale_[0])};",
        "",
        "// W1[red][entrada][oculta], B1[red][oculta], W2[red][oculta], B2[red]",
        arreglo("MLP_W1", [r.coefs_[0] for r in redes]),
        arreglo("MLP_B1", [r.intercepts_[0] for r in redes]),
        arreglo("MLP_W2", [r.coefs_[1].ravel() for r in redes]),
        arreglo("MLP_B2", [r.intercepts_[1][0] for r in redes]),
        "// rango de cada entrada en el entrenamiento",
        arreglo("MLP_X_MIN", xmin),
        arreglo("MLP_X_MAX", xmax),
        f"// vectores de prueba ({Path(a.prueba).name}, filas {', '.join(map(str, filas))}) y prediccion de Python",
        "#define MLP_N_PRUEBAS 3",
        arreglo("MLP_PRUEBA_X", xp.values),
        arreglo("MLP_PRUEBA_Y", yp),
    ]
    Path(a.out).write_text("\n".join(h), encoding="utf-8")
    print(f"Guardado {a.out}: {meta['nombre']}, {len(redes)} redes de {n}-{oculta}-1, "
          f"{len(redes) * (n * oculta + 2 * oculta + 1)} pesos")
    print("Prediccion de Python en los vectores de prueba:", ", ".join(f"{v:.1f}" for v in yp))


if __name__ == "__main__":
    main()
