import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Serves `/config.js` from the environment during development.
 *
 * In a container the entrypoint writes that file; here the dev server
 * generates the same shape, so there is one source of truth for the SPA's
 * runtime configuration instead of a committed file with local values in it.
 */
function runtimeConfig(): Plugin {
  return {
    name: "runtime-config",
    configureServer(server) {
      server.middlewares.use("/config.js", (_request, response) => {
        const body = JSON.stringify({
          apiBaseUrl: process.env.WEB_API_BASE_URL ?? "",
        });
        response.setHeader("content-type", "application/javascript");
        response.setHeader("cache-control", "no-store");
        response.end(`window.__APP_CONFIG__ = ${body};`);
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), runtimeConfig()],
  server: { port: 5173, host: true },
  test: {
    globals: true,
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
