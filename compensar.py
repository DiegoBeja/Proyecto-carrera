#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compensar.py - Quita el efecto de temperatura y humedad a BME688 y PMS5003.

Entrada : los CSV que genera merge.py (una sesion por archivo, o varias).
Salida  : los mismos CSV con columnas compensadas + coeficientes_compensacion.json.

Requisitos:  pip install pandas numpy

Uso:
  python compensar.py S01_train.csv S02_train.csv S03_train.csv --out-dir compensado
  python entrenar.py compensado/*.csv          # entrenar.py usa las columnas nuevas solo

Que hace:
  1. Temperatura: el BME688 se autocalienta. Ajusta aqm_temp_c = a + b*temp_c  ->  temp_comp.
  2. Humedad relativa: con la misma agua (humedad absoluta) pero a la temperatura corregida,
     rh_comp = rh * es(temp_c) / es(temp_comp). El AQM65 no exporta HR, por eso no se calibra
     contra el; solo se quita el error que causa el autocalentamiento.
  3. Gas (MOX): ajusta  log10_gas = a_sesion + b*temp_comp + c*abs_hum  SOLO con minutos
     "limpios" (sin calentamiento, sin evento de CO2 y sin los minutos de alrededor). a_sesion
     absorbe la deriva entre sesiones; b y c son comunes. Luego:
        log10_gas_comp = log10_gas - b*(T - 25) - c*(AH - 10)
        gas_dev_pct    = cambio (%) de la resistencia compensada respecto a la linea base de la
                         sesion (mediana de los primeros --base-min minutos despues del calentamiento).
     El dispositivo final puede calcular gas_dev_pct solo: no usa el AQM65, solo b y c.
  4. PMS5003: los aerosoles absorben agua y crecen con la HR (kappa-Kohler):
        pm_comp = pm_est / (1 + (kappa/1.65) / (1/aw - 1)),   aw = rh_comp/100
     y despues una recta contra aqm_pm2_5  ->  pm2_5_cal.

Validacion (necesita 2 o mas sesiones): para cada sesion se ajustan b y c con las DEMAS y se mide
en la sesion apartada cuanto ruido queda en los minutos limpios (antes y despues de compensar) y
cuanto baja la resistencia en los eventos de CO2 comparado con ese ruido.

Nota: para que b y c salgan bien, T y humedad deben VARIAR entre los minutos limpios, y no juntas
(si suben siempre juntas no se pueden separar). El script avisa si no es asi.
"""
import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

T_REF = 25.0     # C
AH_REF = 10.0    # g/m3


def es_hpa(t):
    """Presion de vapor de saturacion (Magnus), hPa."""
    return 6.112 * np.exp(17.67 * t / (t + 243.5))


def abs_humidity(t_c, rh):
    return es_hpa(t_c) * rh * 2.1674 / (273.15 + t_c)


# --------------------------------------------------------------------------
# 1. Carga y minutos limpios
# --------------------------------------------------------------------------
def cargar(rutas):
    archivos = []
    for r in rutas:
        archivos += sorted(glob.glob(r)) or [r]
    partes = []
    for a in archivos:
        if not Path(a).is_file():
            sys.exit(f"No existe el archivo: {a}")
        d = pd.read_csv(a)
        faltan = [c for c in ["session_id", "timestamp_local", "temp_c", "rh_pct", "gas_ohm", "co2_ref_ppm"]
                  if c not in d.columns]
        if faltan:
            sys.exit(f"{a} no parece salida de merge.py (faltan columnas: {faltan})")
        d["archivo"] = Path(a).name
        partes.append(d)
    df = pd.concat(partes, ignore_index=True)
    df["t"] = pd.to_datetime(df["timestamp_local"])
    return df.sort_values(["session_id", "t"]).reset_index(drop=True)


def marcar_limpios(df, calentamiento, umbral_co2, margen):
    """Limpio = paso el calentamiento, no hay pico de CO2 ni evento anotado (+- margen minutos)."""
    g = df.groupby("session_id", sort=False)
    df["minuto"] = g.cumcount()
    co2_base = g["co2_ref_ppm"].transform("median")
    evento = (df["co2_ref_ppm"] > co2_base + umbral_co2)
    if "event" in df.columns:
        evento |= df["event"].fillna("").astype(str).str.strip() != ""
    # extiende el evento a los minutos de alrededor (el MOX tarda en responder y en recuperarse)
    ancho = 2 * margen + 1
    df["evento"] = evento.groupby(df["session_id"]).transform(
        lambda s: s.astype(int).rolling(ancho, center=True, min_periods=1).max().astype(bool))
    df["minuto_limpio"] = (df["minuto"] >= calentamiento) & ~df["evento"]
    return df


# --------------------------------------------------------------------------
# 2. Temperatura y humedad del BME688
# --------------------------------------------------------------------------
def ajustar_temp(df):
    if "aqm_temp_c" not in df.columns or df["aqm_temp_c"].notna().sum() < 10:
        print("AVISO: no hay aqm_temp_c; temp_comp = temp_c.")
        return {"a": 0.0, "b": 1.0}
    d = df.dropna(subset=["temp_c", "aqm_temp_c"])
    if d["temp_c"].std() < 0.3:
        # rango muy chico: solo se puede estimar el offset
        return {"a": float((d["aqm_temp_c"] - d["temp_c"]).mean()), "b": 1.0}
    b, a = np.polyfit(d["temp_c"], d["aqm_temp_c"], 1)
    return {"a": float(a), "b": float(b)}


def aplicar_temp_hr(df, ct):
    df["temp_comp"] = ct["a"] + ct["b"] * df["temp_c"]
    df["rh_comp"] = (df["rh_pct"] * es_hpa(df["temp_c"]) / es_hpa(df["temp_comp"])).clip(0, 100)
    df["abs_hum_gm3"] = abs_humidity(df["temp_c"], df["rh_pct"])   # el agua no cambia con la correccion
    return df


# --------------------------------------------------------------------------
# 3. Gas (MOX)
# --------------------------------------------------------------------------
def ajustar_gas(d):
    """log10_gas = a_sesion + b*(T-25) + c*(AH-10). Devuelve b, c."""
    ses = pd.get_dummies(d["session_id"]).astype(float)
    X = np.column_stack([ses.values, d["temp_comp"] - T_REF, d["abs_hum_gm3"] - AH_REF])
    coef, *_ = np.linalg.lstsq(X, d["log10_gas"].values, rcond=None)
    return float(coef[-2]), float(coef[-1])


def gas_compensado(df, b, c, calentamiento, base_min):
    comp = df["log10_gas"] - b * (df["temp_comp"] - T_REF) - c * (df["abs_hum_gm3"] - AH_REF)
    en_base = (df["minuto"] >= calentamiento) & (df["minuto"] < calentamiento + base_min)
    base = comp.where(en_base).groupby(df["session_id"]).transform("median")
    return comp, 100 * (10 ** (comp - base) - 1)


def validar_gas(df, calentamiento, base_min):
    sesiones = df["session_id"].unique()
    filas = []
    for s in sesiones:
        entr = df[(df["session_id"] != s) & df["minuto_limpio"]]
        b, c = ajustar_gas(entr)
        prueba = df["session_id"] == s
        _, dev = gas_compensado(df[prueba], b, c, calentamiento, base_min)
        _, crudo = gas_compensado(df[prueba], 0.0, 0.0, calentamiento, base_min)
        limpio = df.loc[prueba, "minuto_limpio"]
        evento = df.loc[prueba, "evento"]
        ruido_c, ruido_s = crudo[limpio].std(), dev[limpio].std()
        pico = dev[evento].min() if evento.any() else np.nan
        filas.append(dict(sesion=s, b=b, c=c,
                          ruido_sin_comp_pct=ruido_c, ruido_comp_pct=ruido_s,
                          reduccion_ruido_pct=100 * (1 - ruido_s / ruido_c),
                          baja_en_evento_pct=pico,
                          senal_ruido=abs(pico) / ruido_s if evento.any() else np.nan))
    return pd.DataFrame(filas).set_index("sesion")


# --------------------------------------------------------------------------
# 4. PMS5003
# --------------------------------------------------------------------------
def aplicar_pms(df, kappa):
    if "pm2_5_est" not in df.columns:
        print("AVISO: no hay pm2_5_est (vuelve a correr merge.py); se omite la correccion del PMS.")
        return df, None
    aw = (df["rh_comp"] / 100).clip(0.01, 0.95)
    crecimiento = 1 + (kappa / 1.65) / (1 / aw - 1)
    df["pm1_comp"] = df["pm1_est"] / crecimiento
    df["pm2_5_comp"] = df["pm2_5_est"] / crecimiento
    if "aqm_pm2_5" not in df.columns or df["aqm_pm2_5"].notna().sum() < 10:
        return df, None
    d = df.dropna(subset=["pm2_5_comp", "aqm_pm2_5"])
    b, a = np.polyfit(d["pm2_5_comp"], d["aqm_pm2_5"], 1)
    df["pm2_5_cal"] = a + b * df["pm2_5_comp"]
    info = {"a": float(a), "b": float(b), "kappa": kappa,
            "r_sin_comp": float(d["pm2_5_est"].corr(d["aqm_pm2_5"])),
            "r_comp": float(d["pm2_5_comp"].corr(d["aqm_pm2_5"]))}
    return df, info


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Compensa T/HR en BME688 y PMS5003.")
    ap.add_argument("csv", nargs="+", help="CSV de merge.py (acepta comodines)")
    ap.add_argument("--out-dir", default="compensado")
    ap.add_argument("--calentamiento", type=int, default=10,
                    help="minutos iniciales de cada sesion que no se usan para ajustar (MOX estabilizando)")
    ap.add_argument("--base-min", type=int, default=5,
                    help="minutos despues del calentamiento para la linea base de gas de cada sesion")
    ap.add_argument("--umbral-co2", type=float, default=60,
                    help="ppm sobre la mediana de la sesion para marcar un minuto como evento")
    ap.add_argument("--margen", type=int, default=3, help="minutos alrededor de un evento que tampoco se usan")
    ap.add_argument("--kappa", type=float, default=0.4, help="higroscopicidad del aerosol (0.2-0.6 tipico)")
    args = ap.parse_args()

    df = cargar(args.csv)
    df = marcar_limpios(df, args.calentamiento, args.umbral_co2, args.margen)
    df["log10_gas"] = np.log10(df["gas_ohm"].where(df["gas_ohm"] > 0))

    ct = ajustar_temp(df)
    df = aplicar_temp_hr(df, ct)
    print(f"Temperatura: aqm = {ct['a']:.3f} + {ct['b']:.3f} * bme   "
          f"(offset medio {(df['temp_comp'] - df['temp_c']).mean():+.2f} C)")
    print(f"HR: el BME marca en promedio {(df['rh_pct'] - df['rh_comp']).mean():+.2f} puntos vs la HR corregida")

    limpio = df[df["minuto_limpio"]]
    n_ses = df["session_id"].nunique()
    print(f"\nSesiones: {n_ses} | minutos: {len(df)} | limpios: {len(limpio)} | en evento: {int(df['evento'].sum())}")
    if len(limpio) < 15:
        sys.exit("Muy pocos minutos limpios para ajustar el gas. Baja --calentamiento o --margen.")
    rango_t, rango_ah = np.ptp(limpio["temp_comp"]), np.ptp(limpio["abs_hum_gm3"])
    r_t_ah = limpio["temp_comp"].corr(limpio["abs_hum_gm3"])
    print(f"Rango en minutos limpios: T {rango_t:.1f} C, humedad abs {rango_ah:.2f} g/m3, r(T, AH) = {r_t_ah:+.2f}")
    if rango_t < 3 or rango_ah < 2:
        print("AVISO: T o humedad varian poco; b y c seran poco confiables. Hagan una sesion que las mueva.")
    if abs(r_t_ah) > 0.8:
        print("AVISO: T y humedad se movieron juntas; no se puede separar bien su efecto.")

    b, c = ajustar_gas(limpio)
    df["log10_gas_comp"], df["gas_dev_pct"] = gas_compensado(df, b, c, args.calentamiento, args.base_min)
    print(f"\nGas: log10(R) cambia {b:+.4f} por C y {c:+.4f} por g/m3  "
          f"(= {100 * (10 ** b - 1):+.1f} %/C, {100 * (10 ** c - 1):+.1f} %/(g/m3))")

    if n_ses >= 2:
        v = validar_gas(df, args.calentamiento, args.base_min)
        pd.set_option("display.width", 160)
        print("\nValidacion dejando una sesion fuera (gas):")
        print(v.round(3).to_string())
        print("  senal_ruido > 3: la baja en el evento se distingue del ruido; < 2: no se distingue.")
    else:
        print("\nAVISO: con 1 sesion no hay validacion; los coeficientes estan ajustados con los mismos datos.")

    df, cp = aplicar_pms(df, args.kappa)
    if cp:
        print(f"\nPMS: aqm_pm2_5 = {cp['a']:.3f} + {cp['b']:.3f} * pm2_5_comp   "
              f"(r sin corregir {cp['r_sin_comp']:.2f}, corregido {cp['r_comp']:.2f})")
        if np.ptp(df["rh_comp"]) < 15 or df["rh_comp"].max() < 60:
            print("AVISO: la HR vario poco o no paso de 60 %; la correccion por crecimiento casi no se puede comprobar.")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    nuevas = ["temp_comp", "rh_comp", "log10_gas_comp", "gas_dev_pct", "pm1_comp", "pm2_5_comp", "pm2_5_cal",
              "minuto_limpio", "evento"]
    for archivo, d in df.groupby("archivo"):
        cols = [c_ for c_ in d.columns if c_ not in ("archivo", "t", "minuto")]
        redondeo = {k: 4 for k in nuevas + ["log10_gas"] if k in d.columns and d[k].dtype.kind == "f"}
        redondeo["abs_hum_gm3"] = 3
        d[cols].round(redondeo).to_csv(
            out / archivo, index=False)
    coef = {"temp": ct, "gas": {"b_por_C": b, "c_por_gm3": c, "T_ref": T_REF, "AH_ref": AH_REF,
                                "calentamiento_min": args.calentamiento, "base_min": args.base_min},
            "pms": cp}
    (out / "coeficientes_compensacion.json").write_text(json.dumps(coef, indent=2), encoding="utf-8")
    print(f"\nGuardado en {out.resolve()}")


if __name__ == "__main__":
    main()
