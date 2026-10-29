import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the interface runs on :5173 and forwards /api to the local backend on :8765.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": { target: "http://127.0.0.1:8765", changeOrigin: false } } },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
