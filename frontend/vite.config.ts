import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs on :8000; in Azure, Front Door routes /api/* to the Container App,
// so the UI always calls a same-origin relative path and needs no CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.UI_PORT ?? 5173),
    proxy: { "/api": process.env.API_PROXY_TARGET ?? "http://localhost:8000" },
  },
  build: { sourcemap: false, outDir: "dist" },
});
