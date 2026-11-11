/**
 * Build portal nppsale cho Frappe (cách "tích hợp máy chủ" của Vite: không có index.html; vỏ HTML do
 * nppsale/www/nppsale/index.py dựng và đọc .vite/manifest.json để chèn thẻ script / css).
 * Tệp ra: nppsale/public/portal/app → Frappe phục vụ ở /assets/nppsale/portal/app/.
 *
 * MÃ GIAO DIỆN = mã nppsale (portal/nguon, chép theo nguon.json) + LỚP PHỦ của portal (src/thay, cùng đường dẫn tương đối):
 * `@/x` tìm ở src/thay/x trước, không có thì nguon/src/x. `@goc/x` luôn là bản nppsale (để lớp phủ bọc bản gốc).
 * Lời import `next/*` và `@supabase/*` của nppsale trỏ về lớp thay thế (src/khung/next, src/thay/lib/supabase/cong).
 */
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { defineConfig, type Plugin } from "vite"
import react from "@vitejs/plugin-react"

const goc = path.dirname(fileURLToPath(import.meta.url))
const THAY = path.join(goc, "src", "thay")
const NGUON = path.join(goc, "nguon", "src")
const KHUNG = path.join(goc, "src", "khung")
const DUOI = ["", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".css", "/index.ts", "/index.tsx"]

function timTep(goc_: string, rel: string): string | null {
  for (const d of DUOI) {
    const f = path.join(goc_, rel + d)
    if (fs.existsSync(f) && fs.statSync(f).isFile()) return f
  }
  return null
}

/** `@/x` → lớp phủ rồi mới tới nppsale; `@goc/x` → nppsale; `@khung/x` → khung portal. */
export function lopPhu(): Plugin {
  return {
    name: "npp-lop-phu",
    enforce: "pre",
    resolveId(id) {
      const [rel0, hoi] = id.split("?")
      const kem = hoi ? `?${hoi}` : ""
      if (rel0.startsWith("@/")) {
        const rel = rel0.slice(2)
        const f = timTep(THAY, rel) ?? timTep(NGUON, rel)
        return f ? f + kem : null
      }
      if (rel0.startsWith("@goc/")) {
        const f = timTep(NGUON, rel0.slice(5))
        return f ? f + kem : null
      }
      if (rel0.startsWith("@khung/")) {
        const f = timTep(KHUNG, rel0.slice(7))
        return f ? f + kem : null
      }
      return null
    },
  }
}

const k = (p: string) => path.join(KHUNG, p)

export default defineConfig(({ command }) => ({
  base: command === "build" ? "/assets/nppsale/portal/app/" : "/",
  plugins: [lopPhu(), react()],
  publicDir: path.join(goc, "nguon", "public"),
  resolve: {
    alias: [
      { find: /^next\/navigation$/, replacement: k("next/navigation.tsx") },
      { find: /^next\/link$/, replacement: k("next/link.tsx") },
      { find: /^next\/image$/, replacement: k("next/image.tsx") },
      { find: /^next\/dynamic$/, replacement: k("next/dynamic.tsx") },
      { find: /^next\/font\/google$/, replacement: k("next/font.ts") },
      { find: /^next\/server$/, replacement: k("next/server.ts") },
      { find: /^next\/headers$/, replacement: k("next/headers.ts") },
      { find: /^next$/, replacement: k("next/index.ts") },
      { find: /^@supabase\/supabase-js$/, replacement: path.join(THAY, "lib/supabase/cong/index.ts") },
      { find: /^@supabase\/ssr$/, replacement: path.join(THAY, "lib/supabase/cong/index.ts") },
    ],
  },
  define: {
    "process.env.NEXT_PUBLIC_SUPABASE_URL": JSON.stringify(""),
    "process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY": JSON.stringify(""),
    "process.env.NEXT_PUBLIC_APP_URL": JSON.stringify(""),
    "process.env.MAINTENANCE_MODE": "undefined",
  },
  build: {
    outDir: path.join(goc, "..", "nppsale", "public", "portal", "app"),
    emptyOutDir: true,
    manifest: true,
    sourcemap: false,
    target: "es2020",
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      input: k("main.tsx"),
    },
  },
  server: {
    port: 5173,
    // Chạy thử: Frappe ở cổng 8000 lo /api, /rest, /files; Vite lo phần còn lại.
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/rest": "http://127.0.0.1:8000",
      "/files": "http://127.0.0.1:8000",
      "/private": "http://127.0.0.1:8000",
    },
  },
}))
