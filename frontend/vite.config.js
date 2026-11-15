import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API runs separately; proxying keeps the browser on one origin so there
// are no CORS surprises in development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        // 8095 is the port restart_api.ps1 starts the API on; keep the two
        // defaults the same so `npm run dev` with no API_URL just works.
        target: process.env.API_URL || "http://127.0.0.1:8095",
        changeOrigin: true,
      },
    },
  },
});
