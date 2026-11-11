/** Test của phần portal (tests/*.test.ts) — cùng bí danh / lớp phủ như bản build (vite.config.ts). */
import { defineConfig, mergeConfig } from "vitest/config"
import viteConfig from "./vite.config"

export default defineConfig((env) =>
  mergeConfig(typeof viteConfig === "function" ? viteConfig(env) : viteConfig, {
    test: {
      environment: "jsdom",
      include: ["tests/**/*.test.ts"],
    },
  })
)
