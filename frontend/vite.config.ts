import { defineConfig } from "vitest/config";
import { resolve } from "node:path";

export default defineConfig({
  server: {
    fs: {
      allow: [resolve(__dirname), resolve(__dirname, "..", "core")]
    },
    host: "0.0.0.0",
    port: 3000
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    restoreMocks: true,
    unstubGlobals: true,
    env: {
      VITE_DEMO_MODE: "true"
    }
  }
});
