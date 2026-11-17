/**
 * LỚP PHỦ của lib/pos/load.ts (nppsale) — bản Frappe chỉ thay `loadReceiptLinesForReturn` (đặc tả kho_mua §7.3 điểm 41, soát thiếu S16, V87).
 *
 * POS trả NCC tìm lô của phiếu nhập gốc bằng `batch_code LIKE '<receipt_code>-%'`. Bản Frappe: khôi phục / sửa phiếu nhập = tờ amend
 * `PN-0042-1` (CFD-01) mà lô vẫn là `PN-0042-NNN` (nhập lại vào ĐÚNG lô cũ) → tìm theo mã tờ amend ra danh sách lô RỖNG. Cắt đuôi amend trước
 * `LIKE` — một chỗ, như chú thích gốc dặn ("Nếu sau này thêm cột ấy thì đổi ở ĐÂY").
 */
import type { SupabaseClient } from "@supabase/supabase-js"
import type { SourceReceiptLine } from "@goc/lib/pos/load"
import { fetchAllForAggregate } from "@/lib/supabase/aggregate"

export * from "@goc/lib/pos/load"

/** Mã phiếu nhập gốc của chuỗi amend: `PN-0042-1` → `PN-0042` (dãy `PN-.####` không có gạch nối khác); mã khác giữ nguyên. */
export function maPhieuGoc(code: string): string {
  const m = /^([A-Z]+-\d+)(-\d+)+$/.exec(code)
  return m ? m[1] : code
}

/** Chép `nhanHan` của bản gốc (không xuất ra): 2099-12-31 = quy ước "không hạn". */
function nhanHan(expires: string | null | undefined): string {
  if (!expires) return ""
  if (expires.startsWith("2099")) return ""
  const [y, m] = expires.split("-")
  return m && y ? `${m}/${y.slice(2)}` : ""
}

/** Như bản gốc (lib/pos/load.ts:312–368) — khác MỘT chỗ: tìm lô theo mã phiếu GỐC của chuỗi amend. */
export async function loadReceiptLinesForReturn(
  sb: SupabaseClient,
  receiptId: string
): Promise<{ lines: SourceReceiptLine[]; receiptCode: string | null }> {
  const [h, l] = await Promise.all([
    sb.from("purchase_invoices").select("id, receipt_code").eq("id", receiptId).maybeSingle(),
    sb
      .from("purchase_invoice_lines")
      .select("product_id, unit_name, quantity, unit_price, conversion_factor, product:products(name, sku)")
      .eq("invoice_id", receiptId)
      .order("sort_order", { ascending: true }),
  ])
  if (l.error) throw l.error
  if (h.error) throw h.error
  const code = ((h.data as unknown) as { receipt_code?: string | null } | null)?.receipt_code ?? null

  const rows = ((l.data as unknown) as Array<{
    product_id: string
    unit_name: string
    quantity: number
    unit_price: number
    conversion_factor: number | null
    product?: { name?: string | null; sku?: string | null } | null
  }>) ?? []

  let lots: Array<{ id: string; product_id: string; batch_code: string; expires_at: string | null }> = []
  if (code) {
    const res = await fetchAllForAggregate<(typeof lots)[number]>((from, to) =>
      sb
        .from("batches")
        .select("id, product_id, batch_code, expires_at", { count: "exact" })
        .like("batch_code", `${maPhieuGoc(code)}-%`)
        .order("id")
        .range(from, to)
    )
    if (res.error) throw new Error(`Lô của phiếu nhập: ${res.error}`)
    lots = res.rows
  }

  return {
    receiptCode: code,
    lines: rows.map((r) => ({
      productId: r.product_id,
      sku: r.product?.sku ?? "",
      name: r.product?.name ?? "Sản phẩm đã xoá",
      unitName: r.unit_name,
      conversion: Number(r.conversion_factor) || 1,
      receivedQty: Number(r.quantity) || 0,
      unitPrice: Number(r.unit_price) || 0,
      lots: lots
        .filter((b) => b.product_id === r.product_id)
        .map((b) => ({ id: b.id, code: b.batch_code, expiry: nhanHan(b.expires_at) })),
    })),
  }
}
