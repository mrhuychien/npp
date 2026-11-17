/**
 * Lớp phủ M2 (đặc tả kho_mua §3.8, §3.9, §7.3 điểm 2 / 41): sửa phiếu trả NCC ĐÃ XUẤT đi MỘT RPC `sua_phieu_tra_ncc` (không còn huỷ → ghi thẳng
 * `status 'draft'` → dòng → gửi), id mới được báo cho màn đang đứng; phiếu mới / nháp / đã huỷ giữ đúng bản nppsale; khôi phục báo id mới; POS
 * trả NCC tìm lô của phiếu nhập gốc theo mã GỐC của chuỗi amend.
 */
import { afterEach, describe, expect, it, vi } from "vitest"
import { createClient } from "@/lib/supabase/cong"
import { savePosSupplierReturn, LY_DO_SUA_POS } from "@/lib/pos/save"
import { loadReceiptLinesForReturn, maPhieuGoc } from "@/lib/pos/load"
import { khoiPhucPhieuNcc } from "@/lib/purchasing/khoi-phuc"
import { SU_KIEN_DOI_ID, duongIdMoi, type DoiId } from "@/lib/purchasing/doi-id"
import type { PosLine } from "@/lib/pos/types"

type Goi = { duong: string; phuong: string; than: any }

/** Cổng giả: ghi lại mọi lời gọi, trả theo đường dẫn (`/rest/v1/<bảng>` đọc GET ?q=, ghi POST; `/rest/v1/rpc/<hàm>` POST thân = tham số). */
function congGia(tra: (g: Goi) => unknown) {
  const goi: Goi[] = []
  const f = vi.fn(async (u: RequestInfo | URL, i?: RequestInit) => {
    const url = new URL(String(u), "http://x")
    const phuong = i?.method ?? "GET"
    const than = phuong === "GET" ? JSON.parse(url.searchParams.get("q") || "{}") : JSON.parse(String(i?.body || "{}"))
    const g = { duong: url.pathname, phuong, than }
    goi.push(g)
    const kq = (tra(g) ?? { data: null }) as { data?: unknown }
    if (than?.mot && Array.isArray(kq.data)) kq.data = kq.data[0] ?? null // `.maybeSingle()` — cổng trả MỘT dòng (ap_mot phía máy chủ)
    return new Response(JSON.stringify(kq), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  return { sb: createClient(undefined, undefined, { global: { fetch: f as unknown as typeof fetch } }), goi }
}

const DONG: PosLine = {
  key: "k1", productId: "SPM", sku: "SPM", name: "Sữa hộp", unit: "thùng", units: [{ unit_name: "hộp", conversion: 1 }, { unit_name: "thùng", conversion: 24 }],
  qty: 2, price: 24000, discount: { value: 1000, unit: "vnd" }, note: " ghi dòng ",
}

function thamSo(o: Partial<Parameters<typeof savePosSupplierReturn>[1]> = {}) {
  return {
    returnId: "PTNCC-0007", orgId: "org", userId: "u@x", supplierId: "NCC-0001", returnDate: "2026-11-17", zone: "date", reason: "damaged",
    notes: " ghi chú ", discount: 500, lines: [DONG], complete: true, subtotal: 47000, vat: 4700, total: 51200, ...o,
  }
}

function ngheDoiId(): DoiId[] {
  const ds: DoiId[] = []
  const nghe = (e: Event) => ds.push((e as CustomEvent<DoiId>).detail)
  window.addEventListener(SU_KIEN_DOI_ID, nghe)
  afterEach(() => window.removeEventListener(SU_KIEN_DOI_ID, nghe))
  return ds
}

describe("savePosSupplierReturn (lớp phủ) — phiếu ĐÃ XUẤT đi MỘT RPC", () => {
  it("phiếu đã gửi → sua_phieu_tra_ncc (đầu phiếu + dòng như linePayloadOf, lý do POS, gửi lại) → id tờ amend, báo đổi id", async () => {
    const doi = ngheDoiId()
    const { sb, goi } = congGia((g) =>
      g.duong === "/rest/v1/supplier_returns" ? { data: [{ status: "completed" }] }
        : g.duong === "/rest/v1/rpc/sua_phieu_tra_ncc" ? { data: { id: "PTNCC-0007-1", trang_thai: "completed" } } : { data: null })
    const kq = await savePosSupplierReturn(sb as any, thamSo())
    expect(kq).toEqual({ returnId: "PTNCC-0007-1" })
    expect(goi.map((g) => g.duong)).toEqual(["/rest/v1/supplier_returns", "/rest/v1/rpc/sua_phieu_tra_ncc"])
    expect(goi[1].phuong).toBe("POST")
    expect(goi[1].than).toEqual({
      p_return_id: "PTNCC-0007",
      p_head: { supplier_id: "NCC-0001", return_date: "2026-11-17", warehouse_zone: "date", reason: "damaged", notes: "ghi chú", discount: 500,
        vat_override: 4700 },
      p_lines: [{ product_id: "SPM", unit_name: "thùng", quantity: 2, unit_price: 24000, line_discount: 1000, vat_rate: 0, conversion_factor: 24,
        line_total: 47000, notes: "ghi dòng", sort_order: 1 }],
      p_reason: LY_DO_SUA_POS,
      p_chi_luu_nhap: false,
    })
    expect(LY_DO_SUA_POS).toBe("Sửa phiếu từ POS — lập lại")
    expect(doi).toEqual([{ bang: "supplier_returns", cu: "PTNCC-0007", moi: "PTNCC-0007-1" }])
    // KHÔNG còn lối của nppsale: huỷ rời + ghi thẳng status 'draft'
    expect(goi.some((g) => g.duong.endsWith("/cancel_supplier_return") || g.than?.hanh_dong === "update")).toBe(false)
  })

  it("'lưu nháp' phiếu đã xuất → cùng RPC với p_chi_luu_nhap; lỗi máy chủ ném nguyên câu", async () => {
    const { sb, goi } = congGia((g) =>
      g.duong === "/rest/v1/supplier_returns" ? { data: [{ status: "completed" }] }
        : { data: null, error: { message: "INSUFFICIENT_STOCK | Sữa hộp (hộp): cần 48, kho hàng date còn 0.000000, kho hàng bán còn 0", code: "P0001" } })
    await expect(savePosSupplierReturn(sb as any, thamSo({ complete: false, vat: 0 }))).rejects.toThrow("INSUFFICIENT_STOCK | Sữa hộp")
    expect(goi[1].than).toMatchObject({ p_chi_luu_nhap: true, p_head: { vat_override: null } })
  })

  it("phiếu NHÁP → đúng bản nppsale: ghi thẳng đầu phiếu + dòng rồi complete_supplier_return (không gọi RPC sửa)", async () => {
    const { sb, goi } = congGia((g) => {
      if (g.duong === "/rest/v1/supplier_returns" && g.phuong === "GET") return { data: [{ status: "draft" }] }
      if (g.duong === "/rest/v1/supplier_returns") return { data: [{ id: "PTNCC-0007" }] }
      if (g.duong === "/rest/v1/supplier_return_lines" && g.than.hanh_dong === "insert") return { data: [{ id: "d1" }] }
      if (g.duong === "/rest/v1/rpc/complete_supplier_return") return { data: "PTNCC-0007" }
      return { data: [] }
    })
    expect(await savePosSupplierReturn(sb as any, thamSo())).toEqual({ returnId: "PTNCC-0007" })
    const duong = goi.map((g) => `${g.duong}:${g.than?.hanh_dong ?? ""}`)
    expect(duong).toContain("/rest/v1/supplier_returns:update")
    expect(duong).toContain("/rest/v1/supplier_return_lines:insert")
    expect(duong[duong.length - 1]).toBe("/rest/v1/rpc/complete_supplier_return:")
    expect(duong.some((d) => d.includes("sua_phieu_tra_ncc"))).toBe(false)
    expect(goi.find((g) => g.than?.hanh_dong === "update")?.than.gia_tri.status).toBeUndefined()
  })

  it("phiếu đã huỷ → câu của nppsale; phiếu mới → chèn như nppsale", async () => {
    const huy = congGia(() => ({ data: [{ status: "cancelled" }] }))
    await expect(savePosSupplierReturn(huy.sb as any, thamSo())).rejects.toThrow("Phiếu trả NCC này đã huỷ — không sửa được.")
    expect(huy.goi.every((g) => g.phuong === "GET" && g.duong === "/rest/v1/supplier_returns")).toBe(true) // chỉ đọc trạng thái, không ghi
    const moi = congGia((g) => (g.duong === "/rest/v1/supplier_returns" ? { data: [{ id: "PTNCC-0008" }] }
      : g.duong === "/rest/v1/supplier_return_lines" && g.than.hanh_dong === "insert" ? { data: [{ id: "d" }] } : { data: [] }))
    expect(await savePosSupplierReturn(moi.sb as any, thamSo({ returnId: null, complete: false }))).toEqual({ returnId: "PTNCC-0008" })
    expect(moi.goi[0].than).toMatchObject({ hanh_dong: "insert", gia_tri: { status: "draft", org_id: "org" } })
  })
})

describe("khôi phục + điều hướng theo id mới", () => {
  it("khoiPhucPhieuNcc báo đổi id khi RPC trả tờ amend; giữ nguyên kết quả cho thông báo", async () => {
    const doi = ngheDoiId()
    const { sb } = congGia(() => ({ data: { id: "PTNCC-0007-1", trang_thai: "completed", da_khoi_phuc: true } }))
    expect(await khoiPhucPhieuNcc(sb as any, "tra", "PTNCC-0007")).toEqual({ id: "PTNCC-0007-1", trang_thai: "completed", da_khoi_phuc: true })
    const nhap = congGia(() => ({ data: { id: "PN-0003-1", trang_thai: "completed", da_khoi_phuc: true, so_lo: 1 } }))
    await khoiPhucPhieuNcc(nhap.sb as any, "nhap", "PN-0003")
    const giu = congGia(() => ({ data: { id: "PN-0004", trang_thai: "draft", da_khoi_phuc: true, so_lo: 0 } }))
    await khoiPhucPhieuNcc(giu.sb as any, "nhap", "PN-0004")
    expect(doi).toEqual([{ bang: "supplier_returns", cu: "PTNCC-0007", moi: "PTNCC-0007-1" },
      { bang: "purchase_invoices", cu: "PN-0003", moi: "PN-0003-1" }])
    expect(duongIdMoi("/pos/tra-ncc/{id}/sua", "PTNCC-0007-1")).toBe("/pos/tra-ncc/PTNCC-0007-1/sua")
  })
})

describe("loadReceiptLinesForReturn (lớp phủ) — lô của phiếu nhập gốc khi phiếu là tờ amend", () => {
  it("maPhieuGoc cắt đuôi amend", () => {
    expect([maPhieuGoc("PN-0042-1"), maPhieuGoc("PN-0042-12"), maPhieuGoc("PN-0042"), maPhieuGoc("PN-10000-2-1"), maPhieuGoc("X")])
      .toEqual(["PN-0042", "PN-0042", "PN-0042", "PN-10000", "X"])
  })

  it("tìm lô `PN-0001-%` cho phiếu PN-0001-1 (V87) — không rỗng", async () => {
    const { sb, goi } = congGia((g) => {
      if (g.duong === "/rest/v1/purchase_invoices") return { data: [{ id: "PN-0001-1", receipt_code: "PN-0001-1" }] }
      if (g.duong === "/rest/v1/purchase_invoice_lines") return { data: [{ product_id: "SPA", unit_name: "thùng", quantity: 2, unit_price: 240000,
        conversion_factor: 24, product: { name: "Hàng A", sku: "SPA" } }] }
      if (g.duong === "/rest/v1/batches") return { data: [{ id: "PN-0001-001::sale", product_id: "SPA", batch_code: "PN-0001-001",
        expires_at: "2099-12-31" }], count: 1 }
      return { data: [] }
    })
    const kq = await loadReceiptLinesForReturn(sb as any, "PN-0001-1")
    const loc = goi.find((g) => g.duong === "/rest/v1/batches")!.than.loc
    expect(loc).toEqual([{ op: "like", cot: "batch_code", gt: "PN-0001-%" }])
    expect(kq.lines[0].lots).toEqual([{ id: "PN-0001-001::sale", code: "PN-0001-001", expiry: "" }])
    expect(kq.receiptCode).toBe("PN-0001-1")
  })
})
