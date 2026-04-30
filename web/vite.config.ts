import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite dev server runs on :5173. The FastAPI backend runs on :8000.
// We proxy `/api/*` requests through to the backend so the frontend can
// always talk to a same-origin path; in prod (`signal-trck serve`) the
// FastAPI app serves the SPA assets and there's no proxy.
//
// Decision 11 (Phase B plan): support both dev and prod modes.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    target: "es2022",
  },
});
