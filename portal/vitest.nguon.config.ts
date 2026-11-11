/**
 * Chạy bộ test của nppsale (nguon/tests) trên nền portal: cùng lớp phủ / bí danh như bản build — bắt chỗ lớp thay `next/*`,
 * `@supabase/*`, `src/thay` làm lệch logic của nppsale. Chạy từ thư mục nguon/ (test đọc tệp theo đường dẫn tương đối):
 *   cd nguon && npx vitest run --config ../vitest.nguon.config.ts
 */
import path from "node:path"
import { fileURLToPath } from "node:url"
import { defineConfig, mergeConfig } from "vitest/config"
import viteConfig from "./vite.config"

const goc = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig((env) =>
  mergeConfig(typeof viteConfig === "function" ? viteConfig(env) : viteConfig, {
    root: path.join(goc, "nguon"),
    esbuild: { jsx: "automatic" },
    test: {
      environment: "node",
      include: ["tests/**/*.test.ts"],
    },
  })
)
