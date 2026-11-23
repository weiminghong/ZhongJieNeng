import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": "http://127.0.0.1:8503" } },
  build: {
    rollupOptions: {
      input: {
        main: "index.html",
        settings: "settings.html",
      },
      output: {
        manualChunks: { charts: ["echarts"], react: ["react", "react-dom"] },
      },
    },
  },
});
