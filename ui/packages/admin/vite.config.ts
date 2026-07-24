import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  base: "/admin/",
  server: {
    host: "0.0.0.0",
    port: 4001,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // 平台内置图标只在 web/public/icons/v1（生产由 nginx 从 web dist 统一 serve）。
      // admin dev 独立运行无该静态资源，代理到 web dev server 对齐生产行为。
      "/icons": {
        target: "http://localhost:4002",
        changeOrigin: true,
      },
    },
  },
});
