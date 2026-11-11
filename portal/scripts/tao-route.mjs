#!/usr/bin/env node
/**
 * Sinh bảng route React Router từ thư mục app của nppsale (nguon/src/app, quy ước Next App Router) cộng lớp phủ của portal
 * (src/thay/app — tệp cùng đường dẫn thắng) → src/khung/routes.generated.tsx.
 *   (nhóm) → không thêm đoạn đường dẫn; [id] → :id; [...slug] → * (handle.batTatCa = "slug"); [[...slug]] → * (tuỳ chọn)
 *   layout.tsx → phần tử bọc <Outlet/>; page.tsx → trang (tải lười); loading.tsx → fallback; error.tsx → errorElement;
 *   not-found.tsx gốc → route "*". Layout gốc (vẽ <html>) thay bằng khung/goc.tsx.
 * Trang / layout "async" (server component) bị liệt kê để chuyển tay.
 */
import fs from "node:fs"
import path from "node:path"

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..")
const NGUON_APP = path.join(ROOT, "nguon", "src", "app")
const THAY_APP = path.join(ROOT, "src", "thay", "app")
const OUT = path.join(ROOT, "src", "khung", "routes.generated.tsx")
if (!fs.existsSync(NGUON_APP)) {
  console.error("Chưa có nguon/ — chạy `node scripts/lay-nguon.mjs` trước.")
  process.exit(1)
}

const imports = []
const canhBao = []
let n = 0
const ten = (p) => `M${n++}_${p.replace(/[^A-Za-z0-9]/g, "_").slice(-40)}`
const goiApp = (f) => (f.startsWith(THAY_APP) ? THAY_APP : NGUON_APP)
const tuongDoi = (f) => "@/app/" + path.relative(goiApp(f), f).replace(/\\/g, "/").replace(/\.tsx?$/, "")

function laAsync(f) {
  const s = fs.readFileSync(f, "utf8")
  return /export\s+default\s+async\s+function/.test(s)
}

function doan(seg) {
  if (/^\(.*\)$/.test(seg)) return { path: null }
  let m = seg.match(/^\[\[\.\.\.(.+)\]\]$/)
  if (m) return { path: "*", handle: { batTatCa: m[1], tuyChon: true } }
  m = seg.match(/^\[\.\.\.(.+)\]$/)
  if (m) return { path: "*", handle: { batTatCa: m[1] } }
  m = seg.match(/^\[(.+)\]$/)
  if (m) return { path: `:${m[1]}` }
  return { path: seg }
}

/** `rel` là thư mục tương đối so với gốc app; lớp phủ thắng bản nppsale. */
function tep(rel, goc) {
  for (const app of [THAY_APP, NGUON_APP]) {
    for (const ext of [".tsx", ".ts", ".jsx", ".js"]) {
      const f = path.join(app, rel, goc + ext)
      if (fs.existsSync(f)) return f
    }
  }
  return null
}

function thuMucCon(rel) {
  const ten = new Set()
  for (const app of [NGUON_APP, THAY_APP]) {
    const d = path.join(app, rel)
    if (!fs.existsSync(d)) continue
    for (const x of fs.readdirSync(d, { withFileTypes: true })) if (x.isDirectory()) ten.add(x.name)
  }
  return [...ten].sort()
}

function dung(dir, laGoc, loiGanNhat, choGanNhat) {
  const page = tep(dir, "page")
  const layout = laGoc ? null : tep(dir, "layout")
  const loading = tep(dir, "loading")
  const error = tep(dir, "error")
  let loiNay = loiGanNhat
  if (error) {
    const id = ten(tuongDoi(error))
    imports.push(`import ${id} from "${tuongDoi(error)}"`)
    loiNay = id
  }
  let choNay = choGanNhat
  if (loading) {
    const id = ten(tuongDoi(loading))
    imports.push(`import ${id} from "${tuongDoi(loading)}"`)
    choNay = `<${id} />`
  }
  const con = []
  if (page) {
    if (laAsync(page)) canhBao.push(path.relative(ROOT, page))
    const id = ten(tuongDoi(page))
    imports.push(`const ${id} = lazy(() => import("${tuongDoi(page)}"))`)
    con.push(`{ index: true, element: <Trang C={${id}} cho={${choNay ?? "null"}} /> }`)
  }
  for (const ten_ of thuMucCon(dir)) {
    if (ten_.startsWith("_") || ten_.startsWith("@") || (dir === "" && ten_ === "api")) continue
    const r = dung(path.join(dir, ten_), false, loiNay, choNay)
    if (r) {
      const dd = doan(ten_)
      con.push(r.replace("__PATH__", dd.path === null ? "" : `path: ${JSON.stringify(dd.path)}, `).replace("__HANDLE__", dd.handle ? `handle: ${JSON.stringify(dd.handle)}, ` : ""))
    }
  }
  if (!page && !con.length) return null
  const phan = []
  phan.push(`__PATH____HANDLE__`)
  if (layout) {
    if (laAsync(layout)) canhBao.push(path.relative(ROOT, layout))
    const id = ten(tuongDoi(layout))
    imports.push(`import ${id} from "${tuongDoi(layout)}"`)
    phan.push(`element: <${id}><Outlet /></${id}>`)
  }
  if (error) phan.push(`errorElement: <BoLoi Loi={${loiNay}} KhongThay={KhongThay} />`)
  phan.push(`children: [\n${con.join(",\n")}\n]`)
  return `{ ${phan.join(", ").replace("__HANDLE__, ", "__HANDLE__")} }`
}

const notFound = tep("", "not-found")
if (notFound) imports.push(`import KhongThay from "${tuongDoi(notFound)}"`)
const gocLoi = tep("", "error")
let gocLoiId = null
if (gocLoi) {
  gocLoiId = ten(tuongDoi(gocLoi))
  imports.push(`import ${gocLoiId} from "${tuongDoi(gocLoi)}"`)
}
const than = dung("", true, gocLoiId, null)
  .replace("__PATH__", `path: "/", `)
  .replace("__HANDLE__", "")
  .replace(/^\{ /, gocLoi ? "{ element: <Goc />, " : `{ element: <Goc />, errorElement: <BoLoi KhongThay={${notFound ? "KhongThay" : "undefined"}} />, `)
// route "*" (không thấy) nằm cuối danh sách con của gốc
const ketQua = than.replace(/\n\]\s*\}$/, `,\n{ path: "*", element: ${notFound ? "<KhongThay />" : "<p>Không tìm thấy trang.</p>"} }\n] }`)

const out = `/* TỰ SINH bởi scripts/tao-route.mjs — đừng sửa tay. */
/* eslint-disable */
import { lazy } from "react"
import { Outlet, type RouteObject } from "react-router-dom"
import Goc from "./goc"
import { BoLoi } from "./loi"
import { Trang } from "./trang"
${imports.join("\n")}

export const routes: RouteObject[] = [
${ketQua}
]
`
fs.writeFileSync(OUT, out)
console.log(`routes: ${imports.filter((x) => x.includes("lazy(")).length} trang -> ${path.relative(ROOT, OUT)}`)
if (canhBao.length) {
  console.log(`CẦN CHUYỂN TAY (async / server component): ${canhBao.length}`)
  for (const c of canhBao) console.log("  - " + c)
}
