// Conexion con el ESP32 por Web Serial (Chrome / Edge) y protocolo de esp32s3_co2.ino:
//   #HOLA,CO2-MLP,<red>,<paso_s>   #ESTADO,<0|1>   #PRED,<s>,<co2>,<fuera>,<calentando>   #AVISO,<texto>
import { useCallback, useEffect, useReducer, useRef } from "react";

export type Punto = { t: number; co2: number; fuera: number; calentando: boolean };
export type Conexion = "sin-soporte" | "desconectado" | "conectando" | "conectado";

export type Estado = {
  conexion: Conexion;
  espListo: boolean; // llego #HOLA: es el firmware correcto
  red: string | null;
  pasoS: number;
  enviando: boolean;
  puntos: Punto[];
  avisos: string[]; // ultimos #AVISO del ESP32
  error: string | null;
};

const MAX_PUNTOS = 2000; // ~2.7 h a 5 s
const BAUDIOS = 115200;

type Accion =
  | { tipo: "conexion"; conexion: Conexion; error?: string | null }
  | { tipo: "linea"; linea: string; ahora: number }
  | { tipo: "error"; error: string };

const inicial = (soporte: boolean): Estado => ({
  conexion: soporte ? "desconectado" : "sin-soporte",
  espListo: false,
  red: null,
  pasoS: 5,
  enviando: false,
  puntos: [],
  avisos: [],
  error: null,
});

function reducir(e: Estado, a: Accion): Estado {
  switch (a.tipo) {
    case "conexion":
      if (a.conexion === "desconectado")
        return { ...e, conexion: a.conexion, espListo: false, enviando: false, error: a.error ?? null };
      return { ...e, conexion: a.conexion, error: a.error ?? null };
    case "error":
      return { ...e, error: a.error };
    case "linea": {
      const [tag, ...c] = a.linea.split(",");
      if (tag === "#HOLA") return { ...e, espListo: true, red: c[1] ?? null, pasoS: Number(c[2]) || 5, error: null };
      if (tag === "#ESTADO") return { ...e, espListo: true, enviando: c[0] === "1" };
      if (tag === "#AVISO") return { ...e, avisos: [...e.avisos.slice(-4), c.join(",")] };
      if (tag === "#PRED" && c.length >= 4) {
        const co2 = Number(c[1]);
        if (!Number.isFinite(co2)) return e;
        const p: Punto = { t: a.ahora, co2, fuera: Number(c[2]), calentando: c[3] === "1" };
        return { ...e, espListo: true, enviando: true, puntos: [...e.puntos.slice(-(MAX_PUNTOS - 1)), p] };
      }
      return e; // lineas sin etiqueta (por ejemplo "mlp test") se ignoran
    }
  }
}

export function useEsp32(demo: boolean) {
  const soporte = demo || "serial" in navigator;
  const [estado, despachar] = useReducer(reducir, soporte, inicial);
  const puerto = useRef<SerialPort | null>(null);
  const lector = useRef<ReadableStreamDefaultReader<string> | null>(null);
  const tuberia = useRef<Promise<void> | null>(null);
  const demoEnviando = useRef(false);

  const linea = useCallback((l: string) => despachar({ tipo: "linea", linea: l, ahora: Date.now() }), []);

  const enviar = useCallback(
    async (cmd: string) => {
      if (demo) {
        demoEnviando.current = cmd === "start" ? true : cmd === "stop" ? false : demoEnviando.current;
        linea(cmd === "ping" ? "#HOLA,CO2-MLP,demo,1" : `#ESTADO,${demoEnviando.current ? 1 : 0}`);
        return;
      }
      const p = puerto.current;
      if (!p?.writable) return;
      const w = p.writable.getWriter();
      try {
        await w.write(new TextEncoder().encode(cmd + "\n"));
      } finally {
        w.releaseLock();
      }
    },
    [demo, linea],
  );

  const cerrar = useCallback(async (error?: string) => {
    const p = puerto.current;
    puerto.current = null;
    try {
      await lector.current?.cancel();
      await tuberia.current;
      await p?.close();
    } catch {
      // el puerto ya estaba cerrado (cable desconectado)
    }
    lector.current = null;
    despachar({ tipo: "conexion", conexion: "desconectado", error });
  }, []);

  const conectar = useCallback(async () => {
    if (demo) {
      despachar({ tipo: "conexion", conexion: "conectado" });
      linea("#HOLA,CO2-MLP,demo,1");
      linea("#ESTADO,0");
      return;
    }
    let p: SerialPort;
    try {
      p = await navigator.serial.requestPort();
    } catch {
      return; // el usuario cerro la ventana sin elegir puerto
    }
    despachar({ tipo: "conexion", conexion: "conectando" });
    try {
      await p.open({ baudRate: BAUDIOS });
    } catch {
      despachar({
        tipo: "conexion",
        conexion: "desconectado",
        error: "No se pudo abrir el puerto. Cierren el Monitor Serie de Arduino y prueben de nuevo.",
      });
      return;
    }
    puerto.current = p;
    despachar({ tipo: "conexion", conexion: "conectado" });

    const decodificador = new TextDecoderStream();
    tuberia.current = p.readable!.pipeTo(decodificador.writable as WritableStream<Uint8Array>).catch(() => {});
    const r = decodificador.readable.getReader();
    lector.current = r;
    setTimeout(() => void enviar("ping"), 400);

    let buf = "";
    try {
      for (;;) {
        const { value, done } = await r.read();
        if (done) break;
        buf += value;
        let i: number;
        while ((i = buf.indexOf("\n")) >= 0) {
          const l = buf.slice(0, i).trim();
          buf = buf.slice(i + 1);
          if (l) linea(l);
        }
        if (buf.length > 1000) buf = ""; // basura sin saltos de linea
      }
    } catch {
      // lectura interrumpida: se maneja abajo
    } finally {
      r.releaseLock();
    }
    if (puerto.current === p) await cerrar("Se perdio la conexion con el ESP32.");
  }, [demo, cerrar, enviar, linea]);

  // cable desconectado
  useEffect(() => {
    if (demo || !("serial" in navigator)) return;
    const alDesconectar = (ev: Event) => {
      if (ev.target === puerto.current) void cerrar("Se desconecto el ESP32 (cable USB).");
    };
    navigator.serial.addEventListener("disconnect", alDesconectar);
    return () => navigator.serial.removeEventListener("disconnect", alDesconectar);
  }, [demo, cerrar]);

  // modo demo: se conecta, inicia y simula datos cada segundo (solo para probar la pagina sin el ESP32)
  useEffect(() => {
    if (!demo) return;
    despachar({ tipo: "conexion", conexion: "conectado" });
    linea("#HOLA,CO2-MLP,demo,1");
    demoEnviando.current = true;
    linea("#ESTADO,1");
    let n = 0;
    const id = setInterval(() => {
      if (!demoEnviando.current) return;
      n++;
      const co2 = 850 + 180 * Math.max(0, Math.sin(n / 40)) + 15 * Math.sin(n / 3) + Math.random() * 10;
      linea(`#PRED,${n},${co2.toFixed(1)},${8 + Math.round(4 * Math.sin(n / 25))},${n < 30 ? 1 : 0}`);
    }, 1000);
    return () => clearInterval(id);
  }, [demo, linea]);

  return {
    estado,
    conectar,
    desconectar: () => (demo ? despachar({ tipo: "conexion", conexion: "desconectado" }) : cerrar()),
    iniciar: () => enviar("start"),
    parar: () => enviar("stop"),
  };
}
