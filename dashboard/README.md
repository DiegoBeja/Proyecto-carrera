# Dashboard de CO₂ en vivo

Página local (React + TypeScript) que se conecta **directo al ESP32 por USB** con Web Serial y muestra
la predicción de la red neuronal en tiempo real. No necesita servidor ni internet.

## Requisitos

- **Chrome o Edge** en la PC (Firefox y Safari no tienen Web Serial).
- Node.js 18 o más nuevo (`node --version`).
- En el ESP32-S3: el firmware **`esp32s3_co2/esp32s3_co2.ino`** (no el logger).

## Uso

```powershell
cd dashboard
npm install        # solo la primera vez
npm run dev        # abre http://localhost:5173 en el navegador
```

1. **Cierren el Monitor Serie de Arduino**: solo un programa puede usar el puerto.
2. **Conectar ESP32** → elijan el puerto del ESP32 en la ventana del navegador.
3. Esperen la bandera verde **ESP32 conectado** (el ESP32 respondió `#HOLA`).
4. **▶ Iniciar**. La primera predicción llega cuando el ESP32 lleva 1 minuto midiendo, y luego una cada 5 s.
5. **■ Parar** detiene el envío (el ESP32 sigue midiendo para no perder el historial).

Para probar la página sin el ESP32: `http://localhost:5173/?demo` (datos simulados, con aviso amarillo).

## Banderas y alertas

| Mensaje | Qué significa |
|---|---|
| ESP32 desconectado / conectado | Si el puerto está abierto y el firmware respondió |
| Midiendo / Detenido | Si el ESP32 está enviando predicciones |
| El dispositivo no responde | El puerto abrió pero no llegó `#HOLA`: revisen que esté subido `esp32s3_co2.ino` o presionen RESET |
| No llegan datos desde hace X s | Se esperaba una predicción y no llegó |
| Calentando | Primeros 6 min: la red todavía no tiene tendencias de 5 min |
| N de 20 entradas fuera de rango | La red ve condiciones que no vio al entrenar; la estimación es menos confiable |
| ESP32: … | Avisos del firmware (por ejemplo, un sensor sin datos) |

## Protocolo serie (115200 baudios)

```
ESP32 → PC   #HOLA,CO2-MLP,<red>,<paso_s>
             #ESTADO,<0|1>
             #PRED,<s_desde_arranque>,<co2_ppm>,<fuera_de_rango>,<calentando 0|1>
             #AVISO,<texto>
PC → ESP32   start | stop | ping | mlp test
```

## Archivos

| Archivo | Qué hace |
|---|---|
| `src/esp32.ts` | Abre el puerto (Web Serial), lee líneas, interpreta el protocolo, modo demo |
| `src/App.tsx` | Pantalla: banderas, botones, alertas, número grande |
| `src/Grafica.tsx` | Gráfica en tiempo real (Recharts) con ventana de 5/15/30 min |
| `src/niveles.ts` | Niveles orientativos de CO₂ (< 800, 800–1200, > 1200 ppm) |
| `src/estilos.css` | Estilos con modo claro y oscuro |
