import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "0.0.0.0",
    port: 4002,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        // changeOrigin 会把 Host 改写成 localhost:8000，后端拿不到用户实际访问的主机名
        // （如局域网 IP）。透传原始 Host 到 X-Forwarded-Host，后端按它解析接入指南地址。
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq, req) => {
            const host = req.headers.host;
            if (host) proxyReq.setHeader("x-forwarded-host", host);
          });
        },
      },
    },
  },
});
