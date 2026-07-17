import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

// Multi-page: buyer (/t/{slug}), group (/g/{gid}), seller PWA.
// Built assets served by FastAPI under /webapp/ (agents/tiemquen_agent/server.py).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  base: "/webapp/",
  build: {
    rollupOptions: {
      input: {
        buyer: path.resolve(__dirname, "buyer.html"),
        group: path.resolve(__dirname, "group.html"),
        seller: path.resolve(__dirname, "seller.html"),
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8787",
      "/orders": "http://127.0.0.1:8787",
      "/group-orders": "http://127.0.0.1:8787",
      "/media": "http://127.0.0.1:8787",
    },
  },
});
