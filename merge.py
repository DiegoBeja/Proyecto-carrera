#!/usr/bin/env python3
"""Une los CSV del ESP32 (PMS5003 + BME688) con el export de 1 minuto del AQM65.

Genera un CSV con UNA FILA POR MINUTO: variables de los sensores de bajo costo
(promediadas a 1 min) + co2_ref_ppm (CO2 del AQM65), listo para entrenar.

Requisitos:  pip install pandas tzdata

Uso basico (PowerShell):
  python tools\\merge.py --esp data\\S01.csv --aqm data\\AQM65_Export.csv --out data\\S01_train.csv

Varias sesiones a la vez (quedan en un solo archivo; session_id sirve para validar por sesion):
  python tools\\merge_aqm65.py --esp data\\C1.csv data\\C2.csv --aqm data\\AQM65_Export.csv --out data\\train.csv

Opciones utiles:
  --esp-offset-sec N      segundos que se SUMAN al reloj del ESP32 para igualarlo al del AQM65
                          (positivo = el AQM65 va adelantado). Se mide con la exhalacion de sincronizacion.
  --aqm-stamp start|end   si la hora de cada fila del AQM65 marca el inicio (por defecto) o el fin del minuto.
  --exclude INICIO FIN    descarta minutos del AQM65 en ese rango (hora local, 'AAAA-MM-DD HH:MM',
                          FIN no incluido). Se puede repetir.
  --start "NOMBRE=AAAA-MM-DD HH:MM:SS"
                          hora local de inicio de una sesion grabada SIN hora (NOMBRE = archivo sin .csv).
  --tz America/Tijuana    zona horaria en la que exporta el AQM65 (hora local con horario de verano).
  --min-rows-frac 0.66    fraccion minima de filas del ESP32 que debe tener un minuto para conservarlo.
  --pm-density 1.65       densidad (g/cm3) que se supone para estimar pm1_est y pm2_5_est.

Notas:
  * Cada fila del ESP32 es el promedio de una ventana y su hora es la del FINAL de la ventana. Aqui se
    asigna cada fila al minuto donde cae el CENTRO de su ventana.
  * Los minutos del ESP32 se promedian ponderando por pms_n / bme_n (cuantas lecturas tuvo cada fila).
  * log10_gas y abs_hum_gm3 se recalculan despues de promediar.
  * pm1_est y pm2_5_est (ug/m3, con decimales) se calculan aqui a partir de los conteos por tamano ya
    promediados a 1 min. El PMS5003 solo entrega PM como enteros (en aire limpio, 0), pero los conteos si
    cambian. Es una estimacion (supone una densidad, --pm-density, y no cuenta particulas < 0.3 um): sirve
    para ver cambios. No se estima PM10 porque los conteos de 5 y 10 um son poco fiables.
  * Las columnas aqm_* (PM, VOC, CO, TEMP del AQM65) son SOLO de referencia para analisis: el dispositivo
    final no las tendra, asi que NO deben usarse como entradas del modelo. Tampoco esp_rows.
"""
import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PMS_COLS = ["pm1_0_cf1", "pm2_5_cf1", "pm10_cf1", "pm1_0_atm", "pm2_5_atm", "pm10_atm",
            "n0_3", "n0_5", "n1_0", "n2_5", "n5_0", "n10"]
BME_COLS = ["temp_c", "rh_pct", "pressure_hpa", "gas_ohm"]
AQM_REF = {"PM2.5": "aqm_pm2_5", "PM10": "aqm_pm10", "VOC": "aqm_voc", "CO": "aqm_co", "TEMP": "aqm_temp_c"}
EPOCH0 = pd.Timestamp("1970-01-01", tz="UTC")


def die(msg):
    sys.exit("ERROR: " + msg)


def series_to_epoch(ts_utc):
    return (ts_utc - EPOCH0).dt.total_seconds().astype("int64")


def local_to_epoch(text, tz):
    try:
        t = pd.Timestamp(text).tz_localize(tz)
    except Exception:
        die(f"hora local invalida, ambigua o inexistente (cambio de horario): {text!r}")
    return int((t - EPOCH0).total_seconds())


def wmean(values, weights):
    mask = ~np.isnan(values) & (weights > 0)
    if not mask.any():
        return np.nan
    return float(np.average(values[mask], weights=weights[mask]))


def abs_humidity(t_c, rh):
    return 6.112 * np.exp(17.67 * t_c / (t_c + 243.5)) * rh * 2.1674 / (273.15 + t_c)


def add_pm_estimates(df, rho):
    """Masa estimada (ug/m3) desde conteos acumulados por 0.1 L (n0_3 = particulas > 0.3 um, etc.)."""
    def coef(d):   # ug/m3 por cada particula por 0.1 L, para un diametro representativo d (um)
        return math.pi / 6 * d ** 3 * rho * 1e-2
    pm1 = (df["n0_3"] - df["n0_5"]) * coef(0.3873) + (df["n0_5"] - df["n1_0"]) * coef(0.7071)
    df["pm1_est"] = pm1
    df["pm2_5_est"] = pm1 + (df["n1_0"] - df["n2_5"]) * coef(1.5811)


# ----------------------------------------------------------------- AQM65
def read_aqm(path, tz, stamp, excludes):
    lines = Path(path).read_text(encoding="utf-8-sig", errors="replace").splitlines()
    hdr = next((i for i, line in enumerate(lines) if line.startswith("Time,")), None)
    if hdr is None:
        die("no encontre la fila de encabezado 'Time,...' en el archivo del AQM65.")
    df = pd.read_csv(path, skiprows=hdr, encoding="utf-8-sig").reset_index(drop=True)
    names = {c.split(" (")[0].strip(): c for c in df.columns}
    for need in ("Time", "CO2"):
        if need not in names:
            die(f"el archivo del AQM65 no trae la columna {need}.")

    raw = df[names["Time"]].astype(str).str.strip()
    try:
        t_local = pd.to_datetime(raw, format="%Y/%m/%d %H:%M:%S")
    except ValueError:
        print("AVISO: formato de hora distinto al esperado (AAAA/MM/DD HH:MM:SS); intento detectarlo.")
        t_local = pd.to_datetime(raw)

    keep = pd.Series(True, index=df.index)
    if "Inlet" in names:
        keep &= df[names["Inlet"]].astype(str).str.strip().str.lower() == "sample"
        print(f"AQM65: {int((~keep).sum())} filas descartadas por Inlet distinto de 'Sample'.")
    for a, b in excludes:
        inside = (t_local >= pd.Timestamp(a)) & (t_local < pd.Timestamp(b))
        print(f"AQM65: {int((inside & keep).sum())} filas descartadas por --exclude {a} a {b}.")
        keep &= ~inside

    out = pd.DataFrame({"t_local": t_local})
    out["co2_ref_ppm"] = pd.to_numeric(df[names["CO2"]], errors="coerce")
    for name, new in AQM_REF.items():
        if name in names:
            col = pd.to_numeric(df[names[name]], errors="coerce")
            if col.notna().any():
                out[new] = col
    out = out[keep & out["co2_ref_ppm"].notna()].copy()

    t_loc = out["t_local"].dt.tz_localize(tz, ambiguous="NaT", nonexistent="NaT")
    bad = t_loc.isna()
    if bad.any():
        print(f"AVISO: {int(bad.sum())} filas del AQM65 caen en el cambio de horario y se descartan.")
    out = out[~bad].copy()
    epoch = series_to_epoch(t_loc[~bad].dt.tz_convert("UTC"))
    if stamp == "end":
        epoch = epoch - 60
    out["minute"] = (epoch // 60) * 60
    dup = out["minute"].duplicated(keep="first")
    if dup.any():
        print(f"AVISO: {int(dup.sum())} minutos repetidos en el AQM65; me quedo con el primero.")
        out = out[~dup]
    return out.drop(columns="t_local").reset_index(drop=True)


# ------------------------------------------------------------------ ESP32
def read_esp(path, starts, offset, min_frac):
    df = pd.read_csv(path)
    need_cols = ["session_id", "elapsed_s", "pms_n", "bme_n"] + PMS_COLS + BME_COLS
    missing = [c for c in need_cols if c not in df.columns]
    if missing:
        die(f"{path}: faltan columnas {missing}. Es un CSV del firmware esp32s3_logger?")
    stem = Path(path).stem
    if "epoch_utc" not in df.columns or df["epoch_utc"].isna().all():
        if stem not in starts:
            die(f'{path} no tiene hora (epoch_utc vacio). Pasa la hora local de inicio con '
                f'--start "{stem}=AAAA-MM-DD HH:MM:SS".')
        df["epoch_utc"] = starts[stem] + df["elapsed_s"]
    df = df[df["epoch_utc"].notna()].copy()
    if len(df) == 0:
        die(f"{path}: sin filas con hora.")

    steps = df["elapsed_s"].diff().dropna()
    interval = float(steps.median()) if len(steps) else float(df["elapsed_s"].iloc[0])
    if interval <= 0:
        die(f"{path}: intervalo invalido ({interval}).")
    expected = max(1, round(60 / interval))
    df["mid"] = df["epoch_utc"].astype(float) - interval / 2 + offset
    df["minute"] = (np.floor(df["mid"] / 60) * 60).astype("int64")
    df["need"] = max(1, math.ceil(min_frac * expected))
    print(f"ESP32 {Path(path).name}: {len(df)} filas, intervalo {interval:g} s, "
          f"{expected} filas por minuto, minimo {int(df['need'].iloc[0])} para conservar un minuto.")
    return df


def aggregate_minutes(esp):
    rows, dropped = [], 0
    for (sid, minute), g in esp.groupby(["session_id", "minute"], sort=True):
        if len(g) < g["need"].iloc[0]:
            dropped += 1
            continue
        wp = g["pms_n"].fillna(0).to_numpy(float)
        wb = g["bme_n"].fillna(0).to_numpy(float)
        r = {"session_id": sid, "minute": int(minute), "esp_rows": len(g),
             "pms_n": int(wp.sum()), "bme_n": int(wb.sum())}
        for c in PMS_COLS:
            r[c] = wmean(g[c].to_numpy(float), wp)
        for c in BME_COLS:
            r[c] = wmean(g[c].to_numpy(float), wb)
        for c in ("heater_c", "heater_ms"):
            r[c] = g[c].iloc[0] if c in g else np.nan
        events = [str(e).strip() for e in g["event"].dropna()] if "event" in g else []
        r["event"] = " | ".join(dict.fromkeys(e for e in events if e))
        rows.append(r)
    return pd.DataFrame(rows), dropped


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Une CSV del ESP32 con el export de 1 minuto del AQM65.")
    ap.add_argument("--esp", nargs="+", required=True, help="uno o mas CSV del ESP32")
    ap.add_argument("--aqm", required=True, help="CSV exportado del AQM65 (promedio de 1 minuto)")
    ap.add_argument("--out", required=True, help="CSV de salida")
    ap.add_argument("--tz", default="America/Tijuana")
    ap.add_argument("--esp-offset-sec", type=float, default=0.0)
    ap.add_argument("--aqm-stamp", choices=["start", "end"], default="start")
    ap.add_argument("--exclude", nargs=2, action="append", default=[], metavar=("INICIO", "FIN"))
    ap.add_argument("--start", action="append", default=[], metavar="NOMBRE=HORA")
    ap.add_argument("--min-rows-frac", type=float, default=0.66)
    ap.add_argument("--pm-density", type=float, default=1.65)
    args = ap.parse_args()

    try:
        pd.Timestamp("2026-01-01").tz_localize(args.tz)
    except Exception:
        die(f"zona horaria desconocida: {args.tz}. En Windows prueba: pip install tzdata")

    starts = {}
    for item in args.start:
        if "=" not in item:
            die(f'--start debe ser "NOMBRE=AAAA-MM-DD HH:MM:SS" (recibi {item!r})')
        k, v = item.split("=", 1)
        starts[k.strip()] = local_to_epoch(v.strip(), args.tz)

    aqm = read_aqm(args.aqm, args.tz, args.aqm_stamp, args.exclude)
    esp = pd.concat([read_esp(p, starts, args.esp_offset_sec, args.min_rows_frac) for p in args.esp],
                    ignore_index=True)

    if esp[["heater_c", "heater_ms"]].drop_duplicates().shape[0] > 1:
        print("AVISO: hay mas de un perfil de calentador del BME688 en los archivos. "
              "Los datos de entrenamiento deberian usar uno solo.")

    mins, dropped = aggregate_minutes(esp)
    if dropped:
        print(f"ESP32: {dropped} minutos descartados por tener pocas filas (inicio/fin de sesion o huecos).")
    if mins.empty:
        die("ningun minuto del ESP32 tiene filas suficientes.")

    merged = mins.merge(aqm, on="minute", how="inner")

    def local_str(sec):
        return pd.to_datetime(sec, unit="s", utc=True).tz_convert(args.tz).strftime("%Y-%m-%d %H:%M")

    print(f"\nMinutos del ESP32: {len(mins)} ({local_str(mins['minute'].min())} a {local_str(mins['minute'].max())})")
    print(f"Minutos del AQM65: {len(aqm)} ({local_str(aqm['minute'].min())} a {local_str(aqm['minute'].max())})")
    print(f"Minutos unidos:    {len(merged)}")
    if merged.empty:
        print("\nNo hay ningun minuto en comun. Revisa: que el AQM65 sea del mismo dia, la zona horaria (--tz) "
              "y el desfase entre relojes (--esp-offset-sec).")
        sys.exit(1)
    if len(merged) < 0.5 * len(mins):
        print("AVISO: menos de la mitad de los minutos del ESP32 tienen pareja en el AQM65. "
              "Revisa el desfase de relojes o si descartaste demasiado con --exclude.")

    merged["log10_gas"] = np.where(merged["gas_ohm"] > 0, np.log10(merged["gas_ohm"].where(merged["gas_ohm"] > 0)), np.nan)
    merged["abs_hum_gm3"] = abs_humidity(merged["temp_c"], merged["rh_pct"])
    add_pm_estimates(merged, args.pm_density)
    merged["epoch_utc"] = merged["minute"]
    merged["timestamp_local"] = merged["minute"].map(local_str)

    rounding = {c: 2 for c in PMS_COLS + ["temp_c", "rh_pct", "pressure_hpa"]}
    rounding.update({"gas_ohm": 0, "log10_gas": 4, "abs_hum_gm3": 3, "co2_ref_ppm": 1,
                     "pm1_est": 3, "pm2_5_est": 3})
    merged = merged.round(rounding)

    ref_cols = [c for c in AQM_REF.values() if c in merged.columns]
    order = (["session_id", "timestamp_local", "epoch_utc", "esp_rows", "pms_n"] + PMS_COLS +
             ["pm1_est", "pm2_5_est", "bme_n"] + BME_COLS + ["log10_gas", "abs_hum_gm3", "heater_c", "heater_ms", "event",
                                       "co2_ref_ppm"] + ref_cols)
    merged = merged.sort_values(["session_id", "epoch_utc"])[order]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.out, index=False)

    print("\nPor sesion:")
    for sid, g in merged.groupby("session_id"):
        c = g["co2_ref_ppm"]
        print(f"  {sid}: {len(g)} minutos | CO2 {c.min():.0f}-{c.max():.0f} ppm (desv. {c.std():.0f})")
    print(f"\nGuardado: {Path(args.out).resolve()}")


if __name__ == "__main__":
    main()