import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = { target: "http://localhost:8000", changeOrigin: false };

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Same-origin API in dev keeps the SameSite=Strict refresh cookie working.
    proxy: { "/api": backend, "/widget.js": backend, "/widget/": backend },
  },
  build: { sourcemap: false },
});
