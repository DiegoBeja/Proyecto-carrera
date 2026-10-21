import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import type { Punto } from "./esp32";
import { nivel } from "./niveles";

const hora = (t: number) => new Date(t).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const horaCorta = (t: number) => new Date(t).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" });

// marcas del eje X en minutos redondos: cada 1, 3 o 5 min segun la ventana
function marcas(desde: number, hasta: number, ventanaMin: number) {
  const paso = (ventanaMin <= 5 ? 1 : ventanaMin <= 15 ? 3 : 5) * 60_000;
  const lista: number[] = [];
  for (let t = Math.ceil(desde / paso) * paso; t <= hasta; t += paso) lista.push(t);
  return lista;
}

function Etiqueta({ active, payload }: TooltipProps<number, string>) {
  const p = payload?.[0]?.payload as Punto | undefined;
  if (!active || !p) return null;
  return (
    <div className="tooltip">
      <div className="tooltip-hora">{hora(p.t)}</div>
      <div className="tooltip-valor">{Math.round(p.co2)} ppm</div>
      <div className="tooltip-extra">
        {nivel(p.co2).texto} · fuera de rango {p.fuera}/20{p.calentando ? " · calentando" : ""}
      </div>
    </div>
  );
}

export function Grafica({ puntos, ventanaMin, ahora }: { puntos: Punto[]; ventanaMin: number; ahora: number }) {
  const desde = ahora - ventanaMin * 60_000;
  const visibles = puntos.filter((p) => p.t >= desde);
  const valores = visibles.map((p) => p.co2);
  const min = Math.floor((Math.min(...valores, 800) - 50) / 50) * 50;
  const max = Math.ceil((Math.max(...valores, 900) + 50) / 50) * 50;

  if (!visibles.length) {
    return <div className="grafica-vacia">Sin datos todavía. Conecten el ESP32 y presionen Iniciar.</div>;
  }
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={visibles} margin={{ top: 12, right: 24, bottom: 4, left: 4 }}>
        <CartesianGrid vertical={false} stroke="var(--grid)" />
        <XAxis
          dataKey="t"
          type="number"
          scale="time"
          domain={[desde, ahora]}
          ticks={marcas(desde, ahora, ventanaMin)}
          tickFormatter={horaCorta}
          tick={{ fill: "var(--muted)", fontSize: 12 }}
          stroke="var(--baseline)"
          tickLine={false}
        />
        <YAxis
          domain={[min, max]}
          tick={{ fill: "var(--muted)", fontSize: 12 }}
          axisLine={false}
          tickLine={false}
          width={48}
          unit=""
        />
        <ReferenceLine y={800} stroke="var(--baseline)" strokeDasharray="4 4"
          label={{ value: "800 ppm", position: "insideTopRight", fill: "var(--muted)", fontSize: 11 }} />
        <ReferenceLine y={1200} stroke="var(--baseline)" strokeDasharray="4 4"
          label={{ value: "1200 ppm", position: "insideTopRight", fill: "var(--muted)", fontSize: 11 }} />
        <Tooltip content={<Etiqueta />} cursor={{ stroke: "var(--muted)", strokeWidth: 1 }} isAnimationActive={false} />
        <Line
          type="monotone"
          dataKey="co2"
          stroke="var(--serie)"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 5, stroke: "var(--superficie)", strokeWidth: 2 }}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
