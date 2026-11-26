import { defineConfig } from "vite";

export default defineConfig({
  base: "/",
  publicDir: "public",
  server: {
    host: "127.0.0.1",
    port: 8765,
    strictPort: true,
    hmr: {
      host: "127.0.0.1",
      port: 8765,
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 8765,
    strictPort: true,
  },
  build: {
    outDir: "../dashboard",
    emptyOutDir: true,
    sourcemap: false,
  },
});
