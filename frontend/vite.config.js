import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs separately (uvicorn on 8000) and Vite forwards /api to it.
// In production FastAPI serves the built files from dist/, so there is one process and one link.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: false } },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
