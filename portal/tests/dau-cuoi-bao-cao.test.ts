/**
 * ĐẦU-CUỐI P6 (M1 — đặc tả báo cáo §5.5 VB-E02; CLAUDE.md đợt 7: "Bấm thật so HAI đường trên cùng dữ liệu … phải bằng nhau"): MÃ NẠP của Báo cáo tổng
 * hợp (`napSoBan` — src/lib/bao-cao/nap-ban-hang.ts: một lượt `bao_cao_so_ban` qua `goiMotLuot`; sổ chưa có hàm thì đọc TỪNG BẢNG `docTungBang` —
 * sales_invoices / sales_invoice_lines / returns / return_lines / stock_entries / stock_entry_lines) + danh mục (`napDanhMuc`) chạy qua CLIENT CỔNG của
 * portal tới CỔNG THẬT của app (`tools/cong_that.py --nen bao_cao` — bộ E2E + Sổ BC của bài vàng báo cáo, một giao dịch không commit). Lần hai thay
 * `rpc('bao_cao_so_ban')` bằng lỗi PGRST202 (như cổng chưa đăng ký hàm) → `napSoBan` tự lùi về đọc từng bảng; dòng bán / HĐ / phiếu trả của hai lần
 * phải Y HỆT (tiền, giá vốn, phân bổ giảm giá, chênh theo bảng giá, NV đoán của phiếu trả) dưới từng người (RLS + che giá vốn). Bỏ qua khi không có
 * cổng thật (`NPP_CONG_THAT` trống) — `npm test` thường không cần bench:
 *
 *   (bench) cd /home/frappe/frappe-bench/sites && ../env/bin/python ../apps/nppsale/tools/cong_that.py --site poc.local --cong 8766 --nen bao_cao
 *   (portal) NPP_CONG_THAT=http://127.0.0.1:8766 npx vitest run tests/dau-cuoi-bao-cao.test.ts
 *
 * Không có trình duyệt (không Playwright — không thêm thư viện): "chụp chữ trong <main>" của nppsale thay bằng so dữ liệu màn dựng bảng; phần bảng
 * "Hàng bán theo nhân viên" (/bao-cao/nhan-vien) tính trong thân trang React — số của nó kiểm bằng mã TS thật ở bài vàng (test_bao_cao_vang, `ts:ban_hang`).
 */
import { beforeAll, describe, expect, it } from "vitest"
import { createClient } from "@/lib/supabase/cong"
import { napSoBan, type SoBan } from "@/lib/bao-cao/nap-ban-hang"
import { napDanhMuc } from "@/lib/bao-cao/nap-danh-muc"

const GOC = process.env.NPP_CONG_THAT || ""
let nguoi = ""
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let nen: any = {}

function goiThat(u: RequestInfo | URL, i?: RequestInit) {
  const url = new URL(String(u), GOC)
  const h = new Headers(i?.headers)
  h.set("X-Npp-Nguoi", nguoi)
  return fetch(`${GOC}${url.pathname}${url.search}`, { ...i, headers: h })
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const sb = createClient(undefined, undefined, { global: { fetch: goiThat as unknown as typeof fetch } }) as any
const LOI_202 = { code: "PGRST202", message: "Could not find the function public.bao_cao_so_ban(p_den, p_tu) in the schema cache", details: null, hint: null }
let goiHam = 0
/** Client "sổ chưa có hàm": `bao_cao_so_ban` trả PGRST202 như cổng chưa đăng ký — mọi câu khác đi thẳng cổng thật. */
const sbThieuHam = new Proxy(sb, {
  get(t, k) {
    if (k === "rpc")
      return (ten: string, ts: unknown, o: unknown) => {
        if (ten !== "bao_cao_so_ban") return t.rpc(ten, ts, o)
        goiHam++
        // builder giả: `.abortSignal()` / then như PostgrestBuilder (goiMotLuot có thể nối thêm)
        const kq = { data: null, error: LOI_202, status: 404, statusText: "Not Found", count: null }
        const b: Record<string, unknown> = { then: (ok: (v: unknown) => unknown, hong?: (e: unknown) => unknown) => Promise.resolve(kq).then(ok, hong) }
        b.abortSignal = () => b
        return b
      }
    const v = Reflect.get(t, k)
    return typeof v === "function" ? v.bind(t) : v
  },
})

/** Phần của bộ (site dùng chung có chứng từ thử khác cùng kỳ) — dòng / HĐ / phiếu trả của khách bộ, xếp để so như tập. */
function cuaBo(x: SoBan, khach: Set<string>) {
  const xep = (ds: unknown[]) => ds.map((d) => JSON.stringify(d)).sort()
  return {
    dong: xep(x.dong.filter((d) => khach.has(d.kh))),
    hoaDon: xep([...x.hoaDon.values()].filter((h) => khach.has(h.kh))),
    phieuTra: xep(x.phieuTra.filter((p) => khach.has(p.kh))),
    thieu: x.thieu,
  }
}

describe.skipIf(!GOC)("Báo cáo tổng hợp — hai đường đọc số bán ra Y HỆT (VB-E02 qua cổng thật)", () => {
  beforeAll(async () => {
    nen = await (await fetch(`${GOC}/__nen`)).json()
  })

  const ca: Array<[string, string, string, string, string]> = [
    ["E2E", "CHU", "2026-09-29", "2026-09-29", "Chủ — bộ e2e một lượt (VB-E01 / E02: hàng đổi, giảm giá đơn, HĐ huỷ, phiếu trả không NV)"],
    ["S1", "CHU", "2026-11-01", "2026-11-30", "Chủ — Sổ BC tháng 11"],
    ["S1", "NV_AN", "2026-11-01", "2026-11-30", "NV An — RLS NVBH + che giá vốn (VB-A06)"],
    ["S1", "NV_BINH", "2026-11-01", "2026-11-30", "NV Bình — RLS NVBH (VB-A07)"],
    ["S1", "TK", "2026-10-01", "2026-12-31", "Thủ kho — cả quý (HĐ ghi lùi 31/10, phiếu trả trừ 02/12)"],
  ]
  for (const [bo, ai, a, b, ten] of ca) {
    it(ten, async () => {
      nguoi = nen[bo].nguoi[ai]
      const khach = new Set<string>(Object.values(nen[bo].khach))
      const dm = (await napDanhMuc(sb, nen.org)).dm
      const truoc = goiHam
      const motLuot = cuaBo(await napSoBan(sb, nen.org, a, b, dm), khach)
      expect(goiHam).toBe(truoc)
      const tungBang = cuaBo(await napSoBan(sbThieuHam, nen.org, a, b, dm), khach)
      expect(goiHam).toBe(truoc + 1) // đường lùi THẬT đã chạy (không phải hai lần một lượt)
      expect(motLuot.dong.length).toBeGreaterThan(0)
      expect([motLuot.thieu, tungBang.thieu]).toEqual([false, false])
      expect(tungBang).toEqual(motLuot)
    })
  }
})
