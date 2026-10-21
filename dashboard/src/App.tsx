import { useEffect, useState } from "react";
import { useEsp32, type Estado } from "./esp32";
import { Grafica } from "./Grafica";
import { nivel } from "./niveles";

const DEMO = new URLSearchParams(location.search).has("demo");
const VENTANAS = [5, 15, 30];

type Alerta = { tipo: "critico" | "aviso" | "info"; texto: string };

function alertas(e: Estado, ahora: number, conectadoDesde: number | null): Alerta[] {
  const a: Alerta[] = [];
  if (e.conexion === "sin-soporte")
    a.push({ tipo: "critico", texto: "Este navegador no tiene Web Serial. Abran la página en Chrome o Edge." });
  if (e.error) a.push({ tipo: "critico", texto: e.error });
  if (e.conexion === "conectado" && !e.espListo && conectadoDesde && ahora - conectadoDesde > 4000)
    a.push({ tipo: "aviso", texto: "El dispositivo no responde. ¿Tiene subido esp32s3_co2.ino? Prueben presionar RESET." });
  const ultimo = e.puntos.at(-1);
  if (e.enviando && e.conexion === "conectado") {
    const espera = ultimo ? (ahora - ultimo.t) / 1000 : null;
    if (!ultimo && conectadoDesde && ahora - conectadoDesde > 70_000)
      a.push({ tipo: "aviso", texto: "Iniciado, pero no llegan predicciones. Revisen los sensores." });
    else if (espera !== null && espera > e.pasoS * 3 + 3)
      a.push({ tipo: "aviso", texto: `No llegan datos desde hace ${Math.round(espera)} s.` });
    else if (!ultimo) a.push({ tipo: "info", texto: "Esperando la primera predicción (el ESP32 necesita 1 minuto de lecturas)." });
  }
  for (const av of e.avisos) a.push({ tipo: "aviso", texto: `ESP32: ${av}` });
  if (ultimo?.calentando)
    a.push({ tipo: "info", texto: "Calentando: los primeros 6 minutos la red todavía no tiene tendencias de 5 min." });
  if (ultimo && ultimo.fuera >= 10)
    a.push({
      tipo: "info",
      texto: `${ultimo.fuera} de 20 entradas están fuera de lo que la red vio al entrenar: tomen la estimación con cautela.`,
    });
  return a;
}

function Bandera({ ok, si, no }: { ok: boolean | null; si: string; no: string }) {
  const clase = ok === null ? "neutral" : ok ? "bueno" : "critico";
  return (
    <span className={`bandera ${clase}`}>
      <span className="punto" aria-hidden />
      {ok ? si : no}
    </span>
  );
}

export default function App() {
  const { estado: e, conectar, desconectar, iniciar, parar } = useEsp32(DEMO);
  const [ahora, setAhora] = useState(Date.now());
  const [ventana, setVentana] = useState(15);
  const [conectadoDesde, setConectadoDesde] = useState<number | null>(null);

  useEffect(() => {
    const id = setInterval(() => setAhora(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  useEffect(() => setConectadoDesde(e.conexion === "conectado" ? Date.now() : null), [e.conexion]);

  const ultimo = e.puntos.at(-1);
  const fresco = ultimo && ahora - ultimo.t < (e.pasoS * 3 + 3) * 1000;
  const n = ultimo ? nivel(ultimo.co2) : null;
  const conectado = e.conexion === "conectado";
  const lista = alertas(e, ahora, conectadoDesde);

  return (
    <div className="pagina">
      {DEMO && <div className="demo">MODO DEMO: datos simulados, no vienen del ESP32</div>}

      <header className="encabezado">
        <div>
          <h1>CO₂ estimado en vivo</h1>
          <p className="subtitulo">
            ESP32-S3 · PMS5003 + BME688 · red neuronal {e.red ?? "—"}
          </p>
        </div>
        <div className="banderas">
          <Bandera
            ok={e.conexion === "sin-soporte" ? false : conectado ? e.espListo : e.conexion === "conectando" ? null : false}
            si="ESP32 conectado"
            no={e.conexion === "conectando" ? "Conectando…" : conectado ? "Esperando respuesta…" : "ESP32 desconectado"}
          />
          <Bandera ok={conectado && e.espListo ? e.enviando : null} si="Midiendo" no="Detenido" />
        </div>
      </header>

      <div className="controles">
        {conectado ? (
          <button className="boton secundario" onClick={() => void desconectar()}>Desconectar</button>
        ) : (
          <button className="boton" onClick={() => void conectar()} disabled={e.conexion !== "desconectado"}>
            Conectar ESP32
          </button>
        )}
        <button className="boton iniciar" onClick={() => void iniciar()} disabled={!conectado || !e.espListo || e.enviando}>
          ▶ Iniciar
        </button>
        <button className="boton parar" onClick={() => void parar()} disabled={!conectado || !e.enviando}>
          ■ Parar
        </button>
      </div>

      {lista.length > 0 && (
        <ul className="alertas">
          {lista.map((a, i) => (
            <li key={i} className={`alerta ${a.tipo}`}>
              <span className="alerta-icono" aria-hidden>{a.tipo === "critico" ? "✕" : a.tipo === "aviso" ? "!" : "i"}</span>
              {a.texto}
            </li>
          ))}
        </ul>
      )}

      <main className="contenido">
        <section className="tarjeta lectura" aria-live="polite">
          <h2>Predicción actual</h2>
          {ultimo ? (
            <div className={`numero ${fresco ? "" : "viejo"}`}>
              {Math.round(ultimo.co2)}
              <span className="unidad">ppm</span>
            </div>
          ) : (
            <div className="numero vacio">Sin datos</div>
          )}
          {n && (
            <div className={`nivel ${n.clase}`}>
              <span aria-hidden>{n.icono}</span> {n.texto}
            </div>
          )}
          <dl className="detalles">
            <div><dt>Actualiza cada</dt><dd>{e.pasoS} s</dd></div>
            <div><dt>Fuera de rango</dt><dd>{ultimo ? `${ultimo.fuera}/20` : "—"}</dd></div>
            <div><dt>Última lectura</dt><dd>{ultimo ? new Date(ultimo.t).toLocaleTimeString("es-MX") : "—"}</dd></div>
          </dl>
        </section>

        <section className="tarjeta grafica">
          <div className="grafica-cabecera">
            <h2>CO₂ estimado (ppm), últimos {ventana} min</h2>
            <div className="segmentos" role="group" aria-label="Ventana de tiempo">
              {VENTANAS.map((v) => (
                <button key={v} className={v === ventana ? "activo" : ""} onClick={() => setVentana(v)}>
                  {v} min
                </button>
              ))}
            </div>
          </div>
          <div className="grafica-cuerpo">
            <Grafica puntos={e.puntos} ventanaMin={ventana} ahora={ahora} />
          </div>
        </section>
      </main>

      <footer className="pie">
        Estimación de una red neuronal entrenada con 2 sesiones (R² = 0.18 en la sesión de prueba). Es un prototipo:
        no sustituye a un medidor de CO₂.
      </footer>
    </div>
  );
}
