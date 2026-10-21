#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
entrenar.py - Compara modelos para estimar CO2 con PMS5003 + BME688.

Entrada : los CSV que genera merge_aqm65.py (uno por sesion o varios).
Salida  : tabla de errores en pantalla + carpeta resultados/ con predicciones,
          importancias y una grafica.

Requisitos:  pip install pandas scikit-learn matplotlib

Uso basico:
  python entrenar.py                       # usa todos los CSV de entrenamiento/
  python entrenar.py entrenamiento/*.csv
  python entrenar.py S01_unido.csv S02_unido.csv S03_unido.csv --saltar-min 10

Con sesiones de prueba final (NO se usan para elegir nada):
  python entrenar.py entrenamiento/*.csv --test S08 S09 S10          # las aparta y no las toca
  python entrenar.py entrenamiento/*.csv --test S08 S09 S10 --final  # evalua UNA vez al terminar

Busqueda del MLP (prueba varias redes, elige la mejor y la guarda entrenada):
  python entrenar.py --test S02 --buscar-mlp --salida modelo_mlp
  python probar_modelo.py                          # prueba ese modelo en S02

Validacion:
  - 2 o mas sesiones : leave-one-session-out (entrena con todas menos una, prueba en esa).
  - 1 sesion         : bloques contiguos en el tiempo. SOLO sirve para probar que el codigo
                       corre; no dice nada de si el modelo generaliza a otra sesion.

Solo se usan como entradas variables que tendra el dispositivo final (PMS5003 y BME688).
Las columnas aqm_* NUNCA entran como entrada (serian fuga de informacion).
"""
import argparse
import glob
import itertools
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor, RandomForestRegressor, VotingRegressor
from sklearn.cross_decomposition import PLSRegression
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel
from sklearn.kernel_ridge import KernelRidge
from sklearn.linear_model import BayesianRidge, ElasticNet, HuberRegressor, LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.neighbors import KNeighborsRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR
from sklearn.tree import DecisionTreeRegressor

TARGET = "co2_ref_ppm"

# --------------------------------------------------------------------------
# 1. Carga y features
# --------------------------------------------------------------------------
CONTEOS = ["n0_3", "n0_5", "n1_0", "n2_5", "n5_0", "n10"]
ESTIMADOS = ["pm1_est", "pm2_5_est"]
BME = ["temp_c", "rh_pct", "abs_hum_gm3", "log10_gas"]
# columnas sobre las que se calculan promedio movil y tendencia
DINAMICAS = ["log10_gas", "abs_hum_gm3", "temp_c", "log_n0_3"]


CARPETA = "entrenamiento"


def cargar(rutas, saltar_min):
    archivos = []
    for r in rutas:
        archivos += sorted(glob.glob(r)) or [r]
    if not archivos or not any(Path(a).is_file() for a in archivos):
        sys.exit(f"No hay CSV de entrenamiento en: {', '.join(rutas)}")
    partes = []
    for a in archivos:
        if not Path(a).is_file():
            sys.exit(f"No existe el archivo: {a}")
        d = pd.read_csv(a)
        faltan = [c for c in [TARGET, "session_id", "timestamp_local", "temp_c", "n0_3"] if c not in d.columns]
        if faltan:
            sys.exit(f"{a} no parece salida de merge_aqm65.py (faltan columnas: {faltan})")
        d["archivo"] = Path(a).name
        partes.append(d)
    sesiones = {}
    for d in partes:
        for sid in d["session_id"].unique():
            if sid in sesiones and sesiones[sid] != d["archivo"].iloc[0]:
                sys.exit(f"session_id '{sid}' esta en {sesiones[sid]} y en {d['archivo'].iloc[0]}; deben ser distintos.")
            sesiones[sid] = d["archivo"].iloc[0]
    df = pd.concat(partes, ignore_index=True)
    df["t"] = pd.to_datetime(df["timestamp_local"])
    df = df.sort_values(["session_id", "t"]).reset_index(drop=True)
    df = df.dropna(subset=[TARGET])
    if saltar_min > 0:
        df = df[df.groupby("session_id").cumcount() >= saltar_min].reset_index(drop=True)
    return df


def crear_features(df, ventana, sin_presion):
    df = df.copy()
    for c in CONTEOS + ESTIMADOS:
        df["log_" + c] = np.log1p(df[c])
    g = df.groupby("session_id", sort=False)
    for c in DINAMICAS:
        df[c + f"_m{ventana}"] = g[c].transform(lambda s: s.rolling(ventana, min_periods=1).mean())
        df[c + f"_d{ventana}"] = g[c].transform(lambda s: s - s.shift(ventana)).fillna(0.0)
    cols = (
        ["log_" + c for c in CONTEOS + ESTIMADOS]
        + BME
        + [c + f"_m{ventana}" for c in DINAMICAS]
        + [c + f"_d{ventana}" for c in DINAMICAS]
    )
    if not sin_presion:
        cols.append("pressure_hpa")
    return df, cols


# --------------------------------------------------------------------------
# 2. Modelos (cada uno con su preprocesado; se reentrenan en cada pliegue)
# --------------------------------------------------------------------------
def escalado_y(regresor):
    """Escala tambien el CO2 (modelos de kernel/GP lo necesitan)."""
    return TransformedTargetRegressor(regressor=regresor, transformer=StandardScaler())


def modelos(cols):
    """Modelos pensados para pocos datos: lineales regularizados, kernel, vecinos y arboles chicos."""
    solo_lineal = ColumnTransformer([("c", "passthrough", ["temp_c", "rh_pct"])])
    kernel_gp = ConstantKernel(1.0) * RBF(length_scale=3.0) + WhiteKernel(noise_level=0.5)
    return {
        "01_media": DummyRegressor(strategy="mean"),
        "02_lineal_T_HR": make_pipeline(solo_lineal, LinearRegression()),
        "03_ridge": make_pipeline(StandardScaler(), Ridge(alpha=10.0)),
        "04_extra_trees": ExtraTreesRegressor(
            n_estimators=300, min_samples_leaf=5, max_features=0.7, random_state=0, n_jobs=-1
        ),
        "05_random_forest": RandomForestRegressor(
            n_estimators=300, min_samples_leaf=5, max_features=0.5, random_state=0, n_jobs=-1
        ),
        "06_svr": escalado_y(make_pipeline(StandardScaler(), SVR(C=3.0, epsilon=0.1, gamma="scale"))),
        "07_ridge_fuerte": make_pipeline(StandardScaler(), Ridge(alpha=100.0)),
        "08_elastic_net": make_pipeline(StandardScaler(), ElasticNet(alpha=0.5, l1_ratio=0.5, max_iter=10000)),
        "09_bayesian_ridge": make_pipeline(StandardScaler(), BayesianRidge()),
        "10_huber": make_pipeline(StandardScaler(), HuberRegressor(alpha=1.0, max_iter=1000)),
        "11_pls_3comp": escalado_y(make_pipeline(StandardScaler(), PLSRegression(n_components=3))),
        "12_kernel_ridge": escalado_y(make_pipeline(StandardScaler(), KernelRidge(alpha=1.0, kernel="rbf", gamma=0.02))),
        "13_knn": make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=7, weights="distance")),
        "14_gauss_process": escalado_y(
            make_pipeline(
                StandardScaler(), GaussianProcessRegressor(kernel=kernel_gp, normalize_y=False, random_state=0)
            )
        ),
        "15_arbol_chico": DecisionTreeRegressor(max_depth=3, min_samples_leaf=5, random_state=0),
        "16_gbm_chico": GradientBoostingRegressor(
            n_estimators=100, learning_rate=0.05, max_depth=2, min_samples_leaf=5, subsample=0.8, random_state=0
        ),
        # red chica (1 capa oculta de 8) con regularizacion fuerte; lbfgs converge mejor que adam con pocos datos
        "17_mlp_chico": escalado_y(
            make_pipeline(
                StandardScaler(),
                MLPRegressor(hidden_layer_sizes=(8,), activation="tanh", solver="lbfgs", alpha=1.0,
                             max_iter=5000, random_state=0),
            )
        ),
    }


# --------------------------------------------------------------------------
# 3. Validacion
# --------------------------------------------------------------------------
def generar_pliegues(df, purga):
    """Devuelve (modo, lista de (idx_train, idx_test))."""
    grupos = df["session_id"].values
    if len(np.unique(grupos)) >= 2:
        return "leave-one-session-out", list(LeaveOneGroupOut().split(df, groups=grupos))
    n = len(df)
    k = 5
    lim = np.linspace(0, n, k + 1).astype(int)
    pliegues = []
    for i in range(k):
        a, b = lim[i], lim[i + 1]
        test = np.arange(a, b)
        train = np.array([j for j in range(n) if j < a - purga or j >= b + purga])
        pliegues.append((train, test))
    return "bloques en el tiempo (1 sola sesion: solo prueba de codigo)", pliegues


def metricas(y, p):
    return dict(
        MAE=mean_absolute_error(y, p),
        RMSE=np.sqrt(mean_squared_error(y, p)),
        R2=r2_score(y, p) if len(y) > 1 else np.nan,
    )


def evaluar(df, cols, mods, purga):
    modo, pliegues = generar_pliegues(df, purga)
    X, y = df[cols], df[TARGET].values
    oof = {n: np.full(len(df), np.nan) for n in mods}
    for tr, te in pliegues:
        for n, mod in mods.items():
            ajustado = clone(mod).fit(X.iloc[tr], y[tr])
            oof[n][te] = ajustado.predict(X.iloc[te])
    return modo, oof


def tabla_global(y, oof):
    filas = []
    for n, p in oof.items():
        ok = ~np.isnan(p)
        filas.append(dict(modelo=n, **metricas(y[ok], p[ok])))
    t = pd.DataFrame(filas).set_index("modelo")
    base = t.loc["01_media", "MAE"]
    t["mejora_vs_media_%"] = 100 * (1 - t["MAE"] / base)
    return t


def tabla_por_sesion(df, oof):
    filas = []
    for s, idx in df.groupby("session_id").groups.items():
        y = df.loc[idx, TARGET].values
        for n, p in oof.items():
            pp = p[idx]
            filas.append(dict(sesion=s, modelo=n, MAE=mean_absolute_error(y, pp), sesgo=float(np.mean(pp - y))))
    return pd.DataFrame(filas).pivot(index="sesion", columns="modelo", values="MAE")


# --------------------------------------------------------------------------
# 4. Salidas
# --------------------------------------------------------------------------
def grafica(df, oof, ruta):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("(matplotlib no esta instalado: se omite la grafica)")
        return
    ses = list(df["session_id"].unique())
    fig, axs = plt.subplots(len(ses), 1, figsize=(10, 3 * len(ses)), squeeze=False)
    for ax, s in zip(axs[:, 0], ses):
        d = df[df["session_id"] == s]
        ax.plot(d["t"], d[TARGET], "k", lw=2, label="AQM65 (real)")
        for n in oof:
            if n in ("01_media", "02_lineal_T_HR"):
                continue
            ax.plot(d["t"], oof[n][d.index], lw=1, label=n)
        ax.set_title(s)
        ax.set_ylabel("CO2 (ppm)")
        ax.legend(fontsize=7, ncol=3)
    fig.tight_layout()
    fig.savefig(ruta, dpi=120)
    plt.close(fig)


# --------------------------------------------------------------------------
# 5. Busqueda del MLP
# --------------------------------------------------------------------------
MLP_CAPAS = [(4,), (8,), (16,), (8, 4)]
MLP_ALPHAS = [0.1, 1.0, 10.0]
MLP_ACTIVACIONES = ["tanh", "relu"]
EMPATE_PPM = 5.0   # diferencias menores a esto se consideran empate; gana la red mas chica


def mlp_promedio(capas, alpha, activacion, semillas):
    """Promedia la prediccion de varias semillas: con pocos datos una sola red es muy inestable."""
    redes = [
        (f"s{s}", MLPRegressor(hidden_layer_sizes=capas, activation=activacion, solver="lbfgs",
                               alpha=alpha, max_iter=5000, random_state=s))
        for s in range(semillas)
    ]
    return escalado_y(make_pipeline(StandardScaler(), VotingRegressor(redes)))


def n_parametros(n_entradas, capas):
    tam = [n_entradas, *capas, 1]
    return sum(a * b + b for a, b in zip(tam[:-1], tam[1:]))


def buscar_mlp(df, cols, purga, semillas, out, info):
    variantes = {}
    for capas, alpha, act in itertools.product(MLP_CAPAS, MLP_ALPHAS, MLP_ACTIVACIONES):
        nombre = f"mlp_{'x'.join(map(str, capas))}_a{alpha:g}_{act}"
        variantes[nombre] = dict(capas=list(capas), alpha=alpha, activacion=act,
                                 parametros=n_parametros(len(cols), capas))
    mods = {"01_media": DummyRegressor(strategy="mean")}
    mods.update({n: mlp_promedio(tuple(v["capas"]), v["alpha"], v["activacion"], semillas)
                 for n, v in variantes.items()})
    print(f"\nProbando {len(variantes)} redes x {semillas} semillas ...")
    modo, oof = evaluar(df, cols, mods, purga)
    y = df[TARGET].values

    tg = tabla_global(y, oof)
    ps = tabla_por_sesion(df, oof)
    tg["MAE_peor_sesion"] = ps.max()
    tg["parametros"] = [variantes[n]["parametros"] if n in variantes else 0 for n in tg.index]
    tg = tg.sort_values("MAE")
    print(f"\nValidacion: {modo}")
    print("\n== Redes ordenadas por MAE (ppm) ==")
    print(tg.round(2).to_string())
    print("\n== MAE por sesion (ppm), 8 mejores redes ==")
    print(ps[[n for n in tg.index if n != "01_media"][:8] + ["01_media"]].round(1).to_string())
    tg.round(3).to_csv(out / "busqueda_mlp.csv")

    # la de menor MAE; si otra esta a menos de EMPATE_PPM, gana la mas chica
    redes = tg.drop(index="01_media")
    empatadas = redes[redes["MAE"] <= redes["MAE"].min() + EMPATE_PPM]
    elegida = empatadas.sort_values(["parametros", "MAE"]).index[0]
    cfg = variantes[elegida]
    fila = tg.loc[elegida]
    print(f"\nRed elegida: {elegida}  (MAE {fila['MAE']:.1f} ppm vs media {tg.loc['01_media', 'MAE']:.1f}; "
          f"{fila['mejora_vs_media_%']:+.1f} %; {cfg['parametros']} parametros)")
    if fila["mejora_vs_media_%"] <= 0:
        print("AVISO: ninguna red le gana a predecir el promedio en la validacion.")

    # se entrena con TODAS las sesiones de entrenamiento y se guarda
    modelo = mlp_promedio(tuple(cfg["capas"]), cfg["alpha"], cfg["activacion"], semillas).fit(df[cols], y)
    meta = dict(info, nombre=elegida, **cfg, semillas=semillas, cols=cols,
                sesiones_entrenamiento=sorted(df["session_id"].unique()),
                co2_media_entrenamiento=float(y.mean()),
                validacion=dict(MAE=float(fila["MAE"]), RMSE=float(fila["RMSE"]),
                                MAE_media=float(tg.loc["01_media", "MAE"])))
    joblib.dump(dict(modelo=modelo, meta=meta), out / "modelo_mlp.joblib")
    (out / "modelo_mlp.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Modelo entrenado con {meta['sesiones_entrenamiento']} y guardado en {out / 'modelo_mlp.joblib'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="*", help="CSV(s) generados por merge.py (admite comodines); "
                    f"si no se da ninguno, usa todos los de la carpeta {CARPETA}/")
    ap.add_argument("--saltar-min", type=int, default=0, help="descartar los primeros N min de cada sesion (calentamiento)")
    ap.add_argument("--ventana", type=int, default=5, help="minutos para promedio movil y tendencia (5)")
    ap.add_argument("--sin-presion", action="store_true", help="no usar pressure_hpa (puede delatar el dia, no el CO2)")
    ap.add_argument("--test", nargs="*", default=[], help="session_id de las sesiones de prueba final (se apartan)")
    ap.add_argument("--final", action="store_true", help="entrenar con todo lo demas y evaluar en --test (hacerlo UNA vez)")
    ap.add_argument("--salida", default="resultados", help="carpeta de resultados")
    ap.add_argument("--buscar-mlp", action="store_true",
                    help="probar varias redes MLP, elegir la mejor y guardarla entrenada (en vez de los 17 modelos)")
    ap.add_argument("--semillas", type=int, default=5, help="semillas promediadas por red en --buscar-mlp (5)")
    a = ap.parse_args()

    rutas = a.csv or [str(Path(CARPETA) / "*.csv")]
    df = cargar(rutas, a.saltar_min)
    df, cols = crear_features(df, a.ventana, a.sin_presion)
    out = Path(a.salida)
    out.mkdir(parents=True, exist_ok=True)

    test = df[df["session_id"].isin(a.test)].reset_index(drop=True) if a.test else df.iloc[0:0]
    df = df[~df["session_id"].isin(a.test)].reset_index(drop=True)
    if df.empty:
        sys.exit("No quedaron datos de entrenamiento.")

    print(f"\nSesiones de entrenamiento: {df['session_id'].nunique()} | filas: {len(df)} | features: {len(cols)}")
    print(f"CO2 de entrenamiento: min {df[TARGET].min():.0f}  mediana {df[TARGET].median():.0f}  max {df[TARGET].max():.0f} ppm")
    if a.test:
        print(f"Sesiones apartadas para la prueba final: {sorted(test['session_id'].unique())} (no se tocan sin --final)")

    if a.buscar_mlp:
        info = dict(ventana=a.ventana, sin_presion=a.sin_presion, saltar_min=a.saltar_min)
        buscar_mlp(df, cols, a.ventana, a.semillas, out, info)
        return

    mods = modelos(cols)
    purga = a.ventana
    modo, oof = evaluar(df, cols, mods, purga)
    y = df[TARGET].values

    print(f"\nValidacion: {modo}")
    tg = tabla_global(y, oof)
    print("\n== Error global (ppm) ==")
    print(tg.round(2).to_string())
    if df["session_id"].nunique() >= 2:
        print("\n== MAE por sesion (ppm): cada columna es un modelo ==")
        print(tabla_por_sesion(df, oof).round(1).to_string())
    else:
        print("\n(Con una sola sesion estos numeros NO miden generalizacion.)")

    pred = df[["session_id", "timestamp_local", TARGET]].copy()
    for n, p in oof.items():
        pred[n] = p.round(1)
    pred.to_csv(out / "predicciones_cv.csv", index=False)
    tg.round(3).to_csv(out / "errores_globales.csv")
    grafica(df, oof, out / "real_vs_predicho.png")

    # importancia de variables (solo informativa, entrenada con todo)
    et = mods["04_extra_trees"].fit(df[cols], y)
    imp = pd.Series(et.feature_importances_, index=cols).sort_values(ascending=False)
    imp.round(4).to_csv(out / "importancias_extra_trees.csv", header=["importancia"])
    print("\n== 8 variables mas usadas por Extra Trees ==")
    print(imp.head(8).round(3).to_string())

    if a.final:
        if test.empty:
            sys.exit("--final necesita --test con session_id existentes.")
        print("\n== PRUEBA FINAL (una sola vez) ==")
        filas = []
        for n, mod in modelos(cols).items():
            mod.fit(df[cols], y)
            p = mod.predict(test[cols])
            filas.append(dict(modelo=n, **metricas(test[TARGET].values, p)))
        tf = pd.DataFrame(filas).set_index("modelo")
        print(tf.round(2).to_string())
        tf.round(3).to_csv(out / "prueba_final.csv")
    print(f"\nResultados guardados en {out}/")


if __name__ == "__main__":
    main()