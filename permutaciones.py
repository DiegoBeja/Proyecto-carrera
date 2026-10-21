#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
permutaciones.py - Repite la busqueda del MLP apartando cada sesion como prueba.

Para cada sesion S de entrenamiento/:
  1. entrenar.py --test S --buscar-mlp, con y sin presion (la red se elige SIN ver S).
  2. Se queda con la variante (con/sin presion) de menor MAE de validacion.
  3. probar_modelo.py prueba esa red UNA vez en S.

Uso:
  python permutaciones.py                  # todas las sesiones de entrenamiento/
  python permutaciones.py --semillas 3     # mas rapido

Salida:
  permutaciones/prueba_<S>/sin_presion/   busqueda, modelo y (si se eligio) prueba_<S>.csv/.png
  permutaciones/prueba_<S>/con_presion/
  permutaciones/resumen.csv               una fila por sesion de prueba
  permutaciones/resumen.png               las graficas real vs predicho juntas
"""
import argparse
import glob
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from entrenar import CARPETA, TARGET, metricas

VARIANTES = {"sin_presion": ["--sin-presion"], "con_presion": []}


def correr(args):
    r = subprocess.run([sys.executable, *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"Fallo: {' '.join(args)}\n{r.stdout}\n{r.stderr}")
    return r.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--semillas", type=int, default=5)
    ap.add_argument("--salida", default="permutaciones")
    a = ap.parse_args()

    archivos = {}
    for f in sorted(glob.glob(str(Path(CARPETA) / "*.csv"))):
        for sid in pd.read_csv(f, usecols=["session_id"])["session_id"].unique():
            archivos[sid] = f
    if len(archivos) < 3:
        sys.exit("Se necesitan al menos 3 sesiones (2 para elegir la red y 1 de prueba).")

    raiz = Path(a.salida)
    filas, graficas = [], []
    for s, csv in archivos.items():
        print(f"\n===== Prueba {s} | entrenamiento {[x for x in archivos if x != s]} =====")
        val = {}
        for var, flags in VARIANTES.items():
            out = raiz / f"prueba_{s}" / var
            correr(["entrenar.py", "--test", s, "--buscar-mlp", "--semillas", str(a.semillas),
                    "--salida", str(out), *flags])
            meta = json.loads((out / "modelo_mlp.json").read_text(encoding="utf-8"))
            val[var] = meta
            print(f"  {var:12s} red {meta['nombre']:18s} MAE validacion {meta['validacion']['MAE']:.1f} "
                  f"(promedio {meta['validacion']['MAE_media']:.1f})")
        elegida = min(val, key=lambda v: val[v]["validacion"]["MAE"])
        meta = val[elegida]
        out = raiz / f"prueba_{s}" / elegida
        print(f"  -> se prueba {elegida} / {meta['nombre']}")
        correr(["probar_modelo.py", "--modelo", str(out / "modelo_mlp.joblib"), "--csv", csv])

        pr = pd.read_csv(out / f"prueba_{s}.csv")
        y, p = pr[TARGET].values, pr["co2_pred_ppm"].values
        m = metricas(y, p)
        mb = metricas(y, np.full(len(y), meta["co2_media_entrenamiento"]))
        filas.append(dict(prueba=s, entrenamiento="+".join(meta["sesiones_entrenamiento"]),
                          variante=elegida, red=meta["nombre"], parametros=meta["parametros"],
                          MAE_validacion=meta["validacion"]["MAE"], MAE_val_promedio=meta["validacion"]["MAE_media"],
                          MAE_prueba=m["MAE"], RMSE_prueba=m["RMSE"], R2_prueba=m["R2"],
                          MAE_prueba_promedio=mb["MAE"], mejora_vs_promedio_pct=100 * (1 - m["MAE"] / mb["MAE"])))
        graficas.append((s, meta, pr))
        print(f"  prueba {s}: MAE {m['MAE']:.1f} (promedio {mb['MAE']:.1f}) | R2 {m['R2']:.2f}")

    res = pd.DataFrame(filas).set_index("prueba")
    res.round(3).to_csv(raiz / "resumen.csv")
    pd.set_option("display.width", 200)
    print("\n== Resumen ==")
    print(res.round(2).to_string())
    print(f"\nPromedio de las {len(res)} pruebas: MAE {res['MAE_prueba'].mean():.1f} ppm "
          f"(promedio {res['MAE_prueba_promedio'].mean():.1f}) | R2 {res['R2_prueba'].mean():.2f}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    fig, axs = plt.subplots(len(graficas), 1, figsize=(10, 3.2 * len(graficas)), squeeze=False)
    for ax, (s, meta, pr) in zip(axs[:, 0], graficas):
        t = pd.to_datetime(pr["timestamp_local"])
        f = res.loc[s]
        ax.plot(t, pr[TARGET], "k", lw=2, label="AQM65 (real)")
        ax.plot(t, pr["co2_pred_ppm"], lw=1.5, label=f"MLP {meta['nombre']} ({f['variante']})")
        ax.axhline(meta["co2_media_entrenamiento"], ls="--", lw=1, color="gray", label="promedio de entrenamiento")
        ax.set_title(f"Prueba {s} (entrenada con {f['entrenamiento']}): MAE {f['MAE_prueba']:.0f} ppm, "
                     f"R2 {f['R2_prueba']:.2f}")
        ax.set_ylabel("CO2 (ppm)")
        ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(raiz / "resumen.png", dpi=120)
    plt.close(fig)
    print(f"Graficas: {raiz / 'resumen.png'} y una por carpeta")


if __name__ == "__main__":
    main()
