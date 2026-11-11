#!/usr/bin/env node
/**
 * Chép mã giao diện nppsale vào portal/nguon/ tại commit ghim trong nguon.json.
 *   - NPPSALE_SRC=<đường dẫn repo nppsale đã clone>: lấy bằng `git archive <ref>` từ repo ấy (không cần mạng).
 *   - Không có: `git clone` repo trong nguon.json (máy chủ cần quyền đọc repo — khoá triển khai / token do chủ nhà cấp ở máy chủ).
 * nguon/ có sẵn đúng commit (tệp nguon/.ref) thì bỏ qua. Chạy tự động trước `vite build` (package.json: prebuild).
 */
import { execFileSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..")
const cfg = JSON.parse(fs.readFileSync(path.join(ROOT, "nguon.json"), "utf8"))
const DICH = path.join(ROOT, "nguon")
const DAU = path.join(DICH, ".ref")

if (fs.existsSync(DAU) && fs.readFileSync(DAU, "utf8").trim() === cfg.ref && !process.argv.includes("--ep")) {
  console.log(`nguon: đã có ${cfg.ref.slice(0, 7)}`)
  process.exit(0)
}

function git(args, cwd) {
  return execFileSync("git", args, { cwd, stdio: ["ignore", "pipe", "inherit"], maxBuffer: 1 << 30 })
}

let repo = process.env.NPPSALE_SRC
let tam = null
if (!repo) {
  tam = fs.mkdtempSync(path.join(os.tmpdir(), "nppsale-"))
  git(["clone", "--filter=blob:none", "--no-checkout", cfg.repo, tam])
  repo = tam
}
try {
  git(["cat-file", "-e", `${cfg.ref}^{commit}`], repo)
} catch {
  git(["fetch", "origin", cfg.ref], repo)
}
fs.rmSync(DICH, { recursive: true, force: true })
fs.mkdirSync(DICH, { recursive: true })
const tar = git(["archive", "--format=tar", cfg.ref, ...cfg.tep], repo)
execFileSync("tar", ["-x", "-C", DICH], { input: tar, maxBuffer: 1 << 30 })
fs.writeFileSync(DAU, cfg.ref + "\n")
if (tam) fs.rmSync(tam, { recursive: true, force: true })
console.log(`nguon: đã chép ${cfg.ref.slice(0, 7)} (${cfg.tep.join(", ")})`)
