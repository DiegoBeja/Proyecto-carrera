import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Web Serial solo funciona en localhost o https; vite sirve en http://localhost:5173
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, host: "localhost" },
});
