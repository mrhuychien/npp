/**
 * ĐẦU-CUỐI P4 (M9 — đặc tả kho_mua §6.9 V76–V79): MÃ MÀN của nppsale (lưu phiếu POS, bảng giá nhập, thẻ kho, lịch sử tồn, danh sách hoá đơn mua)
 * chạy qua CLIENT CỔNG của portal tới CỔNG THẬT của app (`tools/cong_that.py` — chính `nppsale.portal.rest.xu_ly` trên site, một giao dịch không
 * commit). Bỏ qua khi không có cổng thật (`NPP_CONG_THAT` trống) — `npm test` thường không cần bench:
 *
 *   (bench) cd /home/frappe/frappe-bench/sites && ../env/bin/python ../apps/nppsale/tools/cong_that.py --site poc.local --cong 8765
 *   (portal) NPP_CONG_THAT=http://127.0.0.1:8765 npx vitest run tests/dau-cuoi-kho-mua.test.ts
 *
 * Không có trình duyệt (không Playwright — không thêm thư viện): phần "bấm" của màn thay bằng chính hàm màn gọi (savePosPurchase, thayDoiGia,
 * napBangGiaNhap / giaNhapDonVi, manPhieuNcc, menhDeTimDanhSach, tonChayTheKho / tonSauTheoKho, canEnterHref) và CÂU ĐỌC chép nguyên từ trang
 * (`stock-card/[productId]/page.tsx`, `stock-history-drawer.tsx`, `purchasing/invoices/page.tsx`); chữ toast / nhãn nút nằm trong thân component
 * (không gọi được ngoài React) — nhãn trạng thái lấy từ `manPhieuNcc` như màn POS.
 */
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest"
import { createClient } from "@/lib/supabase/cong"
import { savePosPurchase } from "@/lib/pos/save"
import { manPhieuNcc } from "@/lib/pos/purchase"
import { themLenDau } from "@/lib/pos/them-dong"
import { giaNhapDonVi, napBangGiaNhap, thayDoiGia } from "@/lib/purchasing/bang-gia-nhap"
import { tonChayTheKho } from "@/lib/inventory/the-kho"
import { dieuKienDenNgay, tonSauTheoKho } from "@/lib/inventory/lich-su-ton"
import { menhDeTimDanhSach } from "@/lib/search/list-search"
import { canEnterHref } from "@/lib/nav/nav-permission"
import { napBienDong, napTonKho, tinhXnt } from "@/lib/bao-cao/nap-kho"
import { danhMucRong } from "@/lib/bao-cao/cong"
import type { PosLine } from "@/lib/pos/types"

const GOC = process.env.NPP_CONG_THAT || ""
let nguoi = "CHU"
let nen: Record<string, string> = {}

function goiThat(u: RequestInfo | URL, i?: RequestInit) {
  const url = new URL(String(u), GOC)
  const h = new Headers(i?.headers)
  h.set("X-Npp-Nguoi", nguoi)
  return fetch(`${GOC}${url.pathname}${url.search}`, { ...i, headers: h })
}

const sb = createClient(undefined, undefined, { global: { fetch: goiThat as unknown as typeof fetch } }) as any

async function la(p: string) {
  const r = await fetch(`${GOC}${p}`, { method: p === "/__lui" ? "POST" : "GET" })
  return r.json()
}

function homNay(n = 0): string {
  const d = new Date(Date.now() + 7 * 3600_000 + n * 86400_000)
  return d.toISOString().slice(0, 10)
}

async function rpc(ten: string, ts: Record<string, unknown>, ai = nguoi) {
  const truoc = nguoi
  nguoi = ai
  try {
    const { data, error } = await sb.rpc(ten, ts)
    if (error) throw new Error(`${ten}: ${error.code} ${error.message}`)
    return data
  } finally {
    nguoi = truoc
  }
}

type Hang = { base_unit: string; units: Array<{ unit_name: string; conversion: number }> }

/** Mặt hàng như POS nạp (đơn vị theo BẢN GHI UOM của sổ — "Hop" / "Thung" có sẵn thì là chúng): đơn vị cơ sở + đơn vị quy đổi. */
async function hang(sp: string): Promise<Hang> {
  const p = (await sb.from("products").select("id, base_unit, units:product_units(unit_name, conversion)").eq("id", sp).single()).data
  return { base_unit: p.base_unit, units: [{ unit_name: p.base_unit, conversion: 1 },
    ...p.units.map((u: any) => ({ unit_name: u.unit_name, conversion: Number(u.conversion) }))] }
}

const dv = (h: Hang, hs: number) => h.units.find((u) => u.conversion === hs)!.unit_name

function dong(o: Partial<PosLine> & Pick<PosLine, "productId" | "unit" | "qty" | "price">): PosLine {
  return { key: `${o.productId}-${o.unit}`, sku: o.productId, name: o.productId, units: [], discount: { value: 0, unit: "vnd" }, note: "", ...o } as PosLine
}

/** Phiếu nhập qua đúng hàm POS (lưu tạm hoặc hoàn thành) — dòng thêm sau lên ĐẦU (`themLenDau` như màn). */
async function luuPhieu(o: { id?: string | null; dong: PosLine[]; giam?: number; vat?: number; xong: boolean; tong?: [number, number, number] }) {
  const [subtotal, vat, total] = o.tong ?? [0, o.vat ?? 0, 0]
  return savePosPurchase(sb, {
    receiptId: o.id ?? null, orgId: nen.org, userId: nen[`u:${nguoi}`], supplierId: nen.S1, invoiceNumber: "", invoiceDate: homNay(),
    zone: "sale", discount: o.giam ?? 0, notes: "", lines: o.dong, complete: o.xong, subtotal, vat, total,
  })
}

async function ban(sp: string, sl: number, donVi: string): Promise<string> {
  const don = await rpc("create_order_with_lines", { p: { client_request_id: crypto.randomUUID(), order: { order_code: "TAM-1",
    customer_id: nen.K1, payment_terms: "COD", expected_delivery: null, subtotal: sl * 12000, vat: 0, total: sl * 12000, notes: null,
    status: "submitted", approval_reason: null, sales_user_id: null }, lines: [{ product_id: sp, unit_name: donVi, quantity: sl, unit_price: 12000,
    line_discount: 0, conversion_factor: 1, vat_rate: 0, line_total: sl * 12000 }], returns: null, return_lines: [] } })
  const dd = (await sb.from("sales_order_lines").select("id, product_id, unit_name, conversion_factor, quantity, unit_price, line_discount, vat_rate")
    .eq("order_id", don[0].order_id)).data
  const hd = await rpc("post_invoice", { p: { order_id: don[0].order_id, lines: dd.map((r: any) => ({ order_line_id: r.id, product_id: r.product_id,
    unit_name: r.unit_name, conversion_factor: r.conversion_factor, quantity: r.quantity, unit_price: r.unit_price, line_discount: r.line_discount,
    vat_rate: r.vat_rate, is_exchange: false })) } })
  return hd[0].invoice_id
}

/** Phiếu xuất lẻ / chuyển kho NHÁP ghi thẳng qua cổng như màn /inventory/stock-issue rồi ghi sổ bằng RPC (dưới thủ kho). */
async function phieuKho(loai: "XKL" | "CKL", sl: number, donVi: string, dich: string | null = null): Promise<string> {
  const truoc = nguoi
  nguoi = "TK"
  try {
    const r = (await sb.from("stock_entries").insert({ org_id: nen.org, entry_code: loai, type: loai === "CKL" ? "transfer" : "export",
      warehouse_zone: "sale", dest_warehouse_zone: dich, issue_reason: loai === "CKL" ? null : "damaged", notes: null, status: "draft",
      created_by: nen["u:TK"] }).select("id")).data[0].id
    await sb.from("stock_entry_lines").insert({ entry_id: r, product_id: nen.A, batch_id: null, unit_name: donVi, quantity: sl, qty_in_base_uom: sl,
      qty_in_transaction_uom: sl, transaction_uom: donVi, conversion_factor_snapshot: 1, unit_cost: 0, notes: null }).select("id")
    await rpc(loai === "CKL" ? "post_stock_transfer" : "post_stock_issue", { p_entry_id: r })
    return r
  } finally {
    nguoi = truoc
  }
}

describe.skipIf(!GOC)("đầu-cuối kho + mua hàng qua cổng thật (V76–V79)", () => {
  beforeAll(async () => {
    nen = await la("/__nen")
  })
  beforeEach(async () => {
    nguoi = "CHU"
    await la("/__lui")
  })
  afterAll(async () => {
    await la("/__lui")
  })

  it("V78 POS phiếu nhập mới → Lưu tạm → mở lại → Hoàn thành & nhập kho", async () => {
    const hA = await hang(nen.A)
    const hB = await hang(nen.B)
    const thung = dv(hA, 24)
    await rpc("luu_gia_nhap", { p_dong: [{ product_id: nen.A, unit_name: thung, price: 480000 }] })
    // giá gợi ý khi thêm A (thùng) = giá bảng giá nhập của ĐÚNG đơn vị (bang-gia-nhap.ts)
    const { bang } = await napBangGiaNhap(sb)
    const hangA = { ...hA, gia_nhap: bang.get(nen.A) }
    expect(giaNhapDonVi(hangA, thung)).toBe(480000)
    const a = dong({ productId: nen.A, unit: thung, qty: 2, price: giaNhapDonVi(hangA, thung), units: hA.units,
      discount: { value: 10000, unit: "vnd" } })
    const b = dong({ productId: nen.B, unit: hB.base_unit, qty: 5, price: 20000, units: hB.units })
    const ds = themLenDau(themLenDau([], a), b) // B thêm sau → lên đầu
    const vat = Math.round((960000 - 10000 + 100000 - 5000) * 0.08)
    expect(vat).toBe(83600)
    const { receiptId: id } = await luuPhieu({ dong: ds, giam: 5000, vat, xong: false, tong: [1045000, vat, 1128600] })
    expect(id).toMatch(/^PN-\d{4,}$/) // màn chuyển sang /pos/nhap-hang/<id> — Frappe cấp số PN- ngay lúc lưu tạm (câu 18)
    const tam = (await sb.from("purchase_invoices").select("id, status, discount, vat_override, subtotal, total, lines:purchase_invoice_lines(product_id, "
      + "unit_name, quantity, sort_order, vat_rate)").eq("id", id).single()).data
    expect([tam.status, tam.discount, tam.vat_override]).toEqual(["draft", 5000, 83600])
    expect(tam.lines.sort((x: any, y: any) => x.sort_order - y.sort_order).map((d: any) => [d.product_id, d.sort_order, d.vat_rate]))
      .toEqual([[nen.B, 1, 0], [nen.A, 2, 0]])
    expect(manPhieuNcc("nhap", tam.status).nhan?.label).toBe("NHÁP")
    expect(manPhieuNcc("nhap", tam.status).luuNhap).toBe(true)
    // mở lại (cùng id) → Hoàn thành
    await luuPhieu({ id, dong: ds, giam: 5000, vat, xong: true, tong: [1045000, vat, 1128600] })
    const xong = (await sb.from("purchase_invoices").select("status, subtotal, vat, total").eq("id", id).single()).data
    expect([xong.status, xong.subtotal, xong.vat, xong.total]).toEqual(["completed", 1050000, 83600, 1128600])
    const m = manPhieuNcc("nhap", xong.status)
    expect([m.nhan?.label, m.luuNhap, m.daGhiNhan]).toEqual(["ĐÃ NHẬP KHO", false, true])
    const lo = (await sb.from("batches").select("batch_code, product_id, qty_on_hand, unit_cost").like("batch_code", `${id}-%`)).data
    expect(lo.map((r: any) => [r.batch_code, r.product_id, r.qty_on_hand, Math.round(r.unit_cost * 100) / 100]).sort()).toEqual([
      [`${id}-001`, nen.B, 5, 20000], [`${id}-002`, nen.A, 48, Math.round(((2 * 480000 - 10000) / 48) * 100) / 100]])
    const no = (await sb.from("payables").select("amount, paid, status").eq("stock_entry_id", id)).data
    expect(no).toEqual([{ amount: 1128600, paid: 0, status: "open" }])
  })

  it("V79 bảng giá nhập sửa tay (một giá + bỏ một giá) → giá gợi ý ở POS; thủ kho không vào màn", async () => {
    nguoi = "KT"
    const hA = await hang(nen.A)
    const [hop, thung] = [hA.base_unit, dv(hA, 24)]
    await rpc("luu_gia_nhap", { p_dong: [{ product_id: nen.A, unit_name: hop, price: 20000 }] })
    const cu = new Map((await napBangGiaNhap(sb)).dong.map((r) => [`${r.product_id}|${r.unit_name}`, Number(r.price)]))
    const p_dong = thayDoiGia(new Map([[`${nen.A}|${thung}`, "470000"], [`${nen.A}|${hop}`, ""]]), cu)
    expect(p_dong).toEqual([{ product_id: nen.A, unit_name: thung, price: 470000 }, { product_id: nen.A, unit_name: hop, price: null }])
    expect(await rpc("luu_gia_nhap", { p_dong })).toEqual({ luu: 1, bo: 1 }) // toast "Đã lưu bảng giá nhập — 1 giá, bỏ 1"
    const { bang } = await napBangGiaNhap(sb)
    expect(bang.get(nen.A)).toEqual([{ unit_name: thung, price: 470000 }])
    const hangA = { ...hA, gia_nhap: bang.get(nen.A) }
    expect(giaNhapDonVi(hangA, hop)).toBe(19583) // round(470.000 / 24)
    expect(giaNhapDonVi(hangA, thung)).toBe(470000)
    expect(canEnterHref("accountant", "/purchasing/price-list")).toBe(true)
    expect(canEnterHref("warehouse", "/purchasing/price-list")).toBe(false) // ô purchasing.invoices
  })

  it("V76 thẻ kho tổng + lịch sử tồn theo kho (PN → chuyển kho → xuất lẻ → HĐ)", async () => {
    nguoi = "TK"
    const hA = await hang(nen.A)
    const hop = hA.base_unit
    const a = dong({ productId: nen.A, unit: dv(hA, 24), qty: 2, price: 240000, units: hA.units })
    const { receiptId: pn } = await luuPhieu({ dong: [a], xong: true, tong: [480000, 0, 480000] })
    const ckl = await phieuKho("CKL", 4, hop, "date")
    const xkl = await phieuKho("XKL", 2, hop)
    nguoi = "CHU"
    const hd = await ban(nen.A, 1, hop)
    // thẻ kho tổng — câu đọc chép từ stock-card/[productId]/page.tsx (dòng phiếu ĐÃ GHI SỔ của mặt hàng, !inner + entry.status = posted)
    const dongKho = (await sb.from("stock_entry_lines").select("id, batch_id, unit_name, quantity, qty_in_base_uom, conversion_factor_snapshot, "
      + "unit_cost, notes, batch:batches(batch_code), entry:stock_entries!inner(id, entry_code, type, status, posted_at, created_at, warehouse_zone, "
      + "dest_warehouse_zone, supplier:suppliers(name), creator:users!stock_entries_created_by_fkey(full_name))").eq("product_id", nen.A)
      .eq("entry.status", "posted").order("id")).data
    const hdDong = (await sb.from("sales_invoice_lines").select("id, invoice:sales_invoices!inner(invoice_code, invoice_date, status, stock_entry_id, "
      + "customer:customers(store_name, billing_name))").eq("product_id", nen.A).order("id")).data
    const hdTheoPhieu: Record<string, { code: string; customer: string | null }> = {}
    for (const r of hdDong) {
      if (r.invoice?.stock_entry_id && r.invoice.status === "posted") {
        hdTheoPhieu[r.invoice.stock_entry_id] = { code: r.invoice.invoice_code, customer: r.invoice.customer?.billing_name || r.invoice.customer?.store_name || null }
      }
    }
    const cua = new Set([pn, ckl, xkl, hd])
    const rows = dongKho.filter((l: any) => cua.has(l.entry.id)).map((l: any) => ({ id: l.id, date: l.entry.posted_at || l.entry.created_at,
      entry_id: l.entry.id, entry_type: l.entry.type, quantity: l.qty_in_base_uom != null ? Number(l.qty_in_base_uom)
        : Number(l.quantity) * (Number(l.conversion_factor_snapshot) || 1), invoice_code: hdTheoPhieu[l.entry.id]?.code ?? null,
      customer_name: hdTheoPhieu[l.entry.id]?.customer ?? null })).sort((x: any, y: any) => x.date.localeCompare(y.date))
    const the = tonChayTheKho(rows, homNay(), "")
    // nhập +, xuất −, chuyển kho 0 vào tồn TỔNG; thứ tự theo mốc ghi sổ (cùng giây thì thứ tự đọc) — so tập + tồn cuối
    expect(the.dong.map((r: any) => [r.entry_id, r.entry_type, r.delta]).sort()).toEqual([[ckl, "transfer", 0], [hd, "export", -1],
      [pn, "import", 48], [xkl, "export", -2]].sort())
    expect([the.dauKy, the.nhap, the.xuat, the.dong.at(-1)?.running]).toEqual([0, 48, 3, 45])
    const dongHd: any = the.dong.find((r: any) => r.entry_id === hd)
    expect(dongHd?.invoice_code).toBe(hd) // dòng xuất HĐ hiện mã HĐ + khách
    expect(dongHd?.customer_name).toBeTruthy()
    expect(tonChayTheKho(rows, homNay(1), "").dauKy).toBe(45) // Từ ngày mai: tồn đầu kỳ = Σ biến động trước đó
    // ngăn "Lịch sử" — câu đọc chép từ stock-history-drawer.tsx: kho date, Đến ngày hôm qua → trống; tới hôm nay → +4 (chuyển kho)
    const lichSu = async (kho: string, den: string) => (await sb.from("v_stock_movements").select("id, product_id, warehouse_zone, posted_at, "
      + "created_at, entry_type, entry_status, entry_code, entry_id, transaction_uom, qty_in_transaction_uom, qty_in_base_uom, conversion_factor, "
      + "unit_cost, signed_qty_in_base_uom").eq("product_id", nen.A).eq("entry_status", "posted").eq("warehouse_zone", kho)
      .or(dieuKienDenNgay(den)).order("id")).data.filter((r: any) => cua.has(r.entry_id))
    expect(await lichSu("date", homNay(-1))).toEqual([])
    const date = tonSauTheoKho(await lichSu("date", homNay()), "")
    expect(date.dong.map((r: any) => [r.entry_id, r.signed_qty_in_base_uom, r.tonSau])).toEqual([[ckl, 4, 4]])
    const sale = tonSauTheoKho(await lichSu("sale", homNay()), "")
    expect(sale.dong.map((r: any) => [r.entry_id, r.signed_qty_in_base_uom]).sort()).toEqual([[ckl, -4], [hd, -1], [pn, 48], [xkl, -2]].sort())
    const cuoiCung: any = sale.dong.at(-1)
    expect([sale.dong[0].tonSau, cuoiCung?.entry_id, cuoiCung?.tonSau]).toEqual([41, pn, 48]) // mới nhất trước; cộng dồn từng kho
    expect(sale.dong.find((r: any) => r.entry_id === pn)).toMatchObject({ transaction_uom: dv(hA, 24), qty_in_transaction_uom: 2, conversion_factor: 24 })
  })

  it("V77 Hoá đơn mua tra cứu — tab Còn nợ + ô tìm (phiếu nhập kho có NCC + nợ = phiếu nhập)", async () => {
    nguoi = "TK"
    const hop = (await hang(nen.A)).base_unit
    const mot = async (soHd: string) => {
      const { receiptId } = await savePosPurchase(sb, { receiptId: null, orgId: nen.org, userId: nen["u:TK"], supplierId: nen.S1, invoiceNumber: soHd,
        invoiceDate: homNay(), zone: "sale", discount: 0, notes: "", lines: [dong({ productId: nen.A, unit: hop, qty: 1, price: 10000,
          units: [{ unit_name: hop, conversion: 1 }] })], complete: true, subtotal: 10000, vat: 0, total: 10000 })
      return receiptId
    }
    const p1 = await mot("HD01-A")
    const p2 = await mot("HD01-B")
    await mot("XX-1")
    nguoi = "KT" // công nợ NCC: thủ kho không đọc được (RLS chủ / quản lý / kế toán)
    const noP2 = (await sb.from("payables").select("id").eq("stock_entry_id", p2)).data[0].id
    await rpc("record_payable_payment", { p_payable_id: noP2, p_amount: 10000, p_method: "cash", p_notes: null })
    nguoi = "CHU"
    const nhap = await rpc("post_stock_import", { p: { entry_code: "IN-DC-77", supplier_id: nen.S1, warehouse_zone: "sale",
      payable: { amount: 20000, invoice_number: "HD01-C" }, lines: [{ product_id: nen.A, unit_name: hop, qty_tx: 2, conv: 1, base_qty: 2,
        base_cost: 10000 }] } })
    // câu của /purchasing/invoices (taoTruyVan + useListSearch): tra NCC + số HĐ NCC trước, rồi stock_entries import + nợ chưa trả
    const or = await menhDeTimDanhSach(sb, "stock_entries", "HD01", nen.org, ["entry_code"], [
      { column: "supplier_id", table: "suppliers", columns: ["name", "code"] },
      { column: "id", table: "payables", columns: ["invoice_number"], idColumn: "stock_entry_id" }])
    let q = sb.from("stock_entries").select("id, entry_code, posted_at, created_at, supplier:suppliers(name, code), debt:payables!inner(status)",
      { count: "exact" }).eq("type", "import")
    if (or.filter) q = q.or(or.filter)
    const { data, count, error } = await q.neq("debt.status", "paid").order("created_at", { ascending: false }).order("id")
    expect(error).toBeNull()
    expect([data.map((r: any) => r.id).sort(), count]).toEqual([[nhap[0].entry_id, p1].sort(), 2])
  })

  it("Báo cáo tổng hợp › Kho (V75 / §5.4 / §5.6 / §10): tồn một lượt qua bao_cao_ton_kho (GET) + XNT phân loại nhập / trả / bán / khác", async () => {
    nguoi = "TK"
    const hA = await hang(nen.A)
    const hop = hA.base_unit
    const { receiptId: pn } = await luuPhieu({ dong: [dong({ productId: nen.A, unit: dv(hA, 24), qty: 2, price: 240000, units: hA.units })], xong: true,
      tong: [480000, 0, 480000] })
    const ckl = await phieuKho("CKL", 4, hop, "date")
    const xkl = await phieuKho("XKL", 2, hop)
    nguoi = "CHU"
    const hd = await ban(nen.A, 1, hop)
    const pt = await rpc("create_return_with_lines", { p_head: { customer_id: nen.K1, reason: "damaged", status: "draft" }, p_lines: [{ product_id: nen.A,
      unit_name: hop, quantity: 1, unit_price: 12000, vat_rate: 0, is_exchange: false }] })
    await rpc("complete_return", { p_return_id: pt, p_zone: "sale" })
    // tồn: một lượt bao_cao_ton_kho (goiMotLuot — GET) → tinhTonTuTho
    const kq = await napTonKho(sb, nen.org, homNay(), danhMucRong())
    const tonA = kq.ton.find((t) => t.sp === nen.A)!
    expect([tonA.sl, tonA.giaTri, tonA.banCuoi]).toEqual([46, 460000, homNay()]) // 48 − 2 xuất lẻ − 1 bán + 1 khách trả (chuyển kho không đổi tồn tổng)
    expect(tonA.lo.map((l) => [l.id, l.sl, l.gia, l.hsd]).sort()).toEqual([[`${pn}-001::date`, 4, 10000, "2099-12-31"],
      [`${pn}-001::sale`, 42, 10000, "2099-12-31"]])
    nguoi = "NV" // NVBH: giá vốn lô che (❓ §7.3 điểm 21) → giá trị 0, số lượng như chủ
    const nv = (await napTonKho(sb, nen.org, homNay(), danhMucRong())).ton.find((t) => t.sp === nen.A)!
    expect([nv.sl, nv.giaTri]).toEqual([46, 0])
    nguoi = "CHU"
    // XNT: phiếu kho ghi sổ từ hôm nay (cổng stock_entries — ghi chú "Nhập lại từ phiếu trả …" §10 điểm 1, ref_order_ids mảng §10 điểm 2)
    const { ds } = await napBienDong(sb, nen.org, homNay())
    const cua = ds.filter((d) => d.sp === nen.A)
    const theo = (id: string) => cua.filter((d) => d.phieu === id).map((d) => [d.loai, d.sl])
    expect([theo(pn), theo(xkl), theo(hd), theo(ckl)]).toEqual([[["nhap", 48]], [["khac", -2]], [["ban", -1]], [["khac", 4]]])
    expect(cua.filter((d) => d.loai === "tra").map((d) => [d.sl, d.gia])).toEqual([[1, 10000]]) // tờ ghi có có kho của phiếu trả tự lập
    const xnt = tinhXnt(new Map([[nen.A, tonA.sl]]), cua, homNay(), homNay()).get(nen.A)!
    expect([xnt.nhap, xnt.tra, xnt.ban, xnt.khac, xnt.cuoi]).toEqual([48, 1, 1, -2, 46]) // khác = 2 xuất lẻ − 4 chuyển kho (luật nppsale)
  })
})
