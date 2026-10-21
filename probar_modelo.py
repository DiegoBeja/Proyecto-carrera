#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probar_modelo.py - Prueba en una sesion nueva el MLP que guardo entrenar.py --buscar-mlp.

Uso:
  python probar_modelo.py                                   # modelo_mlp/ en entrenamiento/S02_train.csv
  python probar_modelo.py --csv entrenamiento/S04_train.csv
  python probar_modelo.py --modelo otra_carpeta/modelo_mlp.joblib

Salida (en la carpeta del modelo):
  prueba_<sesion>.csv   CO2 real y predicho minuto a minuto
  prueba_<sesion>.png   grafica real vs predicho
La sesion de prueba NO debe haberse usado para entrenar ni para elegir la red.
"""
import argparse
import sys
from pathlib import Path

import joblib
import numpy as np

from entrenar import TARGET, cargar, crear_features, metricas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modelo", default="modelo_mlp/modelo_mlp.joblib")
    ap.add_argument("--csv", default="entrenamiento/S02_train.csv", help="CSV de merge.py de la sesion a probar")
    a = ap.parse_args()

    if not Path(a.modelo).is_file():
        sys.exit(f"No existe {a.modelo}. Primero: python entrenar.py --test S02 --buscar-mlp --salida modelo_mlp")
    guardado = joblib.load(a.modelo)
    modelo, meta = guardado["modelo"], guardado["meta"]

    df = cargar([a.csv], meta["saltar_min"])
    df, cols = crear_features(df, meta["ventana"], meta["sin_presion"])
    if cols != meta["cols"]:
        sys.exit("Las variables de este CSV no coinciden con las del modelo.")
    usadas = set(meta["sesiones_entrenamiento"]) & set(df["session_id"])
    if usadas:
        sys.exit(f"{sorted(usadas)} se uso para entrenar este modelo; no sirve como prueba.")

    y = df[TARGET].values
    p = modelo.predict(df[cols])
    base = np.full(len(y), meta["co2_media_entrenamiento"])
    m, mb = metricas(y, p), metricas(y, base)
    sesion = "_".join(sorted(df["session_id"].unique()))

    print(f"\nModelo: {meta['nombre']}  (entrenado con {meta['sesiones_entrenamiento']})")
    print(f"Prueba: {sesion} | {len(df)} minutos | CO2 real {y.min():.0f}-{y.max():.0f} ppm\n")
    print(f"{'':22s}{'MAE':>8s}{'RMSE':>8s}{'R2':>8s}")
    print(f"{'MLP':22s}{m['MAE']:8.1f}{m['RMSE']:8.1f}{m['R2']:8.2f}")
    print(f"{'Promedio (referencia)':22s}{mb['MAE']:8.1f}{mb['RMSE']:8.1f}{mb['R2']:8.2f}")
    print(f"\nMejora vs promedio: {100 * (1 - m['MAE'] / mb['MAE']):+.1f} %  "
          f"(en la validacion fue MAE {meta['validacion']['MAE']:.1f} vs {meta['validacion']['MAE_media']:.1f})")

    out = Path(a.modelo).parent
    res = df[["session_id", "timestamp_local", TARGET]].copy()
    res["co2_pred_ppm"] = p.round(1)
    res.to_csv(out / f"prueba_{sesion}.csv", index=False)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("(matplotlib no esta instalado: se omite la grafica)")
    else:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(df["t"], y, "k", lw=2, label="AQM65 (real)")
        ax.plot(df["t"], p, lw=1.5, label=f"MLP ({meta['nombre']})")
        ax.axhline(meta["co2_media_entrenamiento"], ls="--", lw=1, color="gray", label="promedio de entrenamiento")
        ax.set_title(f"{sesion}: MAE {m['MAE']:.0f} ppm")
        ax.set_ylabel("CO2 (ppm)")
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(out / f"prueba_{sesion}.png", dpi=120)
        plt.close(fig)
    print(f"Guardado en {out}/prueba_{sesion}.csv y .png")


if __name__ == "__main__":
    main()
