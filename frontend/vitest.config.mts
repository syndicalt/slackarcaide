import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    coverage: {
      provider: "istanbul",
      reporter: ["text", "json-summary"],
      include: ["lib/**/*.ts", "components/canvas/view.ts"],
      thresholds: {
        statements: 85,
        branches: 60,
        functions: 85,
        lines: 90,
      },
    },
  },
});
