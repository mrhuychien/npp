/**
 * Lớp phủ M7 (đặc tả kho_mua §3.3, §7.3 điểm 2): sửa phiếu nhập ĐÃ HOÀN THÀNH — RPC `sua_phieu_nhap` trả `id` tờ còn hiệu lực (chưa xuất lô nào: tờ
 * amend `PN-0042-1`; đã xuất: chỉ sửa giá, id giữ). Màn đang đứng ở id cũ (POS — lib/pos/save.ts của nppsale gọi `suaPhieuNhapDaXong`) nhận sự kiện
 * đổi id; màn mở SAU ở id cũ (màn sửa `router.push` về chi tiết id cũ) đọc được id mới đã ghi nhớ.
 */
import { afterEach, describe, expect, it, vi } from "vitest"
import { createClient } from "@/lib/supabase/cong"
import { savePosPurchase } from "@/lib/pos/save"
import { suaPhieuNhapDaXong } from "@/lib/purchasing/save-receipt"
import { SU_KIEN_DOI_ID, idMoiCua, baoDoiId, type DoiId } from "@/lib/purchasing/doi-id"
import { percentToRatio } from "@/lib/purchasing/return-form"
import type { PosLine } from "@/lib/pos/types"

type Goi = { duong: string; phuong: string; than: any }

function congGia(tra: (g: Goi) => unknown) {
  const goi: Goi[] = []
  const f = vi.fn(async (u: RequestInfo | URL, i?: RequestInit) => {
    const url = new URL(String(u), "http://x")
    const phuong = i?.method ?? "GET"
    const than = phuong === "GET" ? JSON.parse(url.searchParams.get("q") || "{}") : JSON.parse(String(i?.body || "{}"))
    const g = { duong: url.pathname, phuong, than }
    goi.push(g)
    const kq = (tra(g) ?? { data: null }) as { data?: unknown }
    if (than?.mot && Array.isArray(kq.data)) kq.data = kq.data[0] ?? null
    return new Response(JSON.stringify(kq), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  return { sb: createClient(undefined, undefined, { global: { fetch: f as unknown as typeof fetch } }), goi }
}

function ngheDoiId(): DoiId[] {
  const ds: DoiId[] = []
  const nghe = (e: Event) => ds.push((e as CustomEvent<DoiId>).detail)
  window.addEventListener(SU_KIEN_DOI_ID, nghe)
  afterEach(() => window.removeEventListener(SU_KIEN_DOI_ID, nghe))
  return ds
}

const DONG: PosLine = {
  key: "k1", productId: "SPA", sku: "SPA", name: "Hàng A", unit: "thùng", units: [{ unit_name: "hộp", conversion: 1 }, { unit_name: "thùng", conversion: 24 }],
  qty: 2, price: 264000, discount: { value: 0, unit: "vnd" }, note: "",
}

describe("sửa phiếu nhập đã hoàn thành — id tờ còn hiệu lực", () => {
  it("POS (bản nppsale gọi suaPhieuNhapDaXong của lớp phủ): một RPC, dòng như linePayloadOf, báo đổi id + ghi nhớ", async () => {
    const doi = ngheDoiId()
    const { sb, goi } = congGia((g) =>
      g.duong === "/rest/v1/purchase_invoices" ? { data: [{ status: "completed" }] }
        : g.duong === "/rest/v1/rpc/sua_phieu_nhap" ? { data: { id: "PN-0042-1", total: 528000, paid: 0, so_dong: 1, doi_gia_lo: 1 } } : { data: null })
    const kq = await savePosPurchase(sb as any, { receiptId: "PN-0042", orgId: "org", userId: "u@x", supplierId: "NCC-0001", invoiceNumber: " HD-9 ",
      invoiceDate: "2026-11-17", zone: "sale", discount: 0, notes: " sửa ", lines: [DONG], complete: true, subtotal: 528000, vat: 0, total: 528000 })
    expect(kq).toEqual({ receiptId: "PN-0042" }) // bản gốc trả id đã gửi — màn đi theo SỰ KIỆN
    expect(goi.map((g) => g.duong)).toEqual(["/rest/v1/purchase_invoices", "/rest/v1/rpc/sua_phieu_nhap"])
    expect(goi[1].than).toEqual({
      p_invoice_id: "PN-0042",
      p_head: { supplier_id: "NCC-0001", invoice_number: "HD-9", invoice_date: "2026-11-17", warehouse_zone: "sale", discount: 0, vat_override: null,
        notes: "sửa" },
      p_lines: [{ product_id: "SPA", unit_name: "thùng", quantity: 2, unit_price: 264000, line_discount: 0, vat_rate: 0, conversion_factor: 24,
        line_total: 528000, notes: null, sort_order: 1 }],
    })
    expect(doi).toEqual([{ bang: "purchase_invoices", cu: "PN-0042", moi: "PN-0042-1" }])
    expect(idMoiCua("purchase_invoices", "PN-0042")).toBe("PN-0042-1")
  })

  it("chỉ sửa giá (id giữ): không báo; lỗi máy chủ ném nguyên câu", async () => {
    const doi = ngheDoiId()
    const { sb } = congGia(() => ({ data: { id: "PN-0050", total: 1, paid: 0, so_dong: 1, doi_gia_lo: 1 } }))
    const kq = await suaPhieuNhapDaXong(sb as any, "PN-0050", { supplier_id: "NCC-0001", invoice_number: null, invoice_date: "2026-11-17",
      warehouse_zone: "sale", discount: 0, vat_override: null, notes: null }, [], percentToRatio)
    expect(kq.id).toBe("PN-0050")
    expect(doi).toEqual([])
    expect(idMoiCua("purchase_invoices", "PN-0050")).toBeNull()
    const loi = congGia(() => ({ data: null, error: { message: "PHIEU_DA_XUAT_CHI_SUA_GIA: Lô của phiếu đã xuất ở HD-0001 — …", code: "P0001" } }))
    await expect(suaPhieuNhapDaXong(loi.sb as any, "PN-0050", { supplier_id: "NCC-0001", invoice_number: null, invoice_date: "2026-11-17",
      warehouse_zone: "sale", discount: 0, vat_override: null, notes: null }, [], percentToRatio)).rejects.toThrow(/^PHIEU_DA_XUAT_CHI_SUA_GIA: /)
  })

  it("đổi id đi hết chuỗi (sửa nhiều lần), theo bảng", () => {
    baoDoiId("purchase_invoices", "PN-0060", "PN-0060-1")
    baoDoiId("purchase_invoices", "PN-0060-1", "PN-0060-2")
    expect(idMoiCua("purchase_invoices", "PN-0060")).toBe("PN-0060-2")
    expect(idMoiCua("purchase_invoices", "PN-0060-2")).toBeNull()
    expect(idMoiCua("supplier_returns", "PN-0060")).toBeNull()
    baoDoiId("purchase_invoices", "PN-0061", null)
    expect(idMoiCua("purchase_invoices", "PN-0061")).toBeNull()
  })
})
