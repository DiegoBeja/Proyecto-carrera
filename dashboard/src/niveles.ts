// Niveles orientativos de CO2 en interiores (ppm)
export type Nivel = { clase: "bueno" | "regular" | "alto"; icono: string; texto: string };

export function nivel(co2: number): Nivel {
  if (co2 < 800) return { clase: "bueno", icono: "✓", texto: "Aire fresco" };
  if (co2 < 1200) return { clase: "regular", icono: "!", texto: "Conviene ventilar" };
  return { clase: "alto", icono: "▲", texto: "Ventilar ya" };
}
