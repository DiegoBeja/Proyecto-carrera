#!/usr/bin/env python3
"""Guarda en la PC el CSV que el ESP32 imprime por serial.

Requisito:  pip install pyserial
Cierren antes el Serial Monitor de Arduino (solo un programa puede usar el puerto).

Uso:
  python guardar_csv.py COM5 S01_cuarto.csv    # pide ese archivo al ESP32 y lo guarda
  python guardar_csv.py COM5                   # espera el volcado automatico al terminar una sesion
  (en Linux/Mac el puerto es algo como /dev/ttyACM0 o /dev/cu.usbmodem1101)

Aviso: en algunas placas, abrir el puerto reinicia el ESP32. Los archivos guardados en su
memoria no se pierden, pero una sesion en curso si se interrumpiria. Para no arriesgarse,
corran este script cuando la sesion ya termino (opcion 1).
"""
import os
import sys
import time

import serial


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    port = sys.argv[1]
    wanted = sys.argv[2] if len(sys.argv) > 2 else None

    ser = serial.Serial()
    ser.port = port
    ser.baudrate = 115200
    ser.timeout = 1
    ser.dtr = False   # intenta evitar el reinicio de la placa al abrir el puerto
    ser.rts = False
    ser.open()
    time.sleep(1.0)

    if wanted:
        ser.reset_input_buffer()
        ser.write(f"dump {wanted}\n".encode())

    lines, capturing, out_name = [], False, None
    print("Esperando datos del ESP32...")
    while True:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line.startswith("#BEGIN_CSV,"):
            capturing = True
            out_name = os.path.basename(line.split(",", 1)[1].strip())
            lines = []
            print(f"Recibiendo {out_name} ...")
        elif line.startswith("#END_CSV"):
            break
        elif capturing:
            lines.append(line)
        else:
            print(line)
            if line.startswith("No existe"):
                sys.exit(1)

    ser.close()
    with open(out_name, "w", newline="", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Guardado: {os.path.abspath(out_name)}  ({max(len(lines) - 1, 0)} filas de datos)")


if __name__ == "__main__":
    main()