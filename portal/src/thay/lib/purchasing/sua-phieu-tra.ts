/**
 * SỬA PHIẾU TRẢ NCC ĐÃ XUẤT — RPC `sua_phieu_tra_ncc` của bản Frappe (đặc tả kho_mua §3.8, §7.3 điểm 2 — đề xuất, chờ chốt).
 *
 * nppsale làm BA lời gọi rời: `cancel_supplier_return` → `update supplier_returns set status 'draft'` (ghi thẳng — RLS cho) → ghi lại dòng →
 * `complete_supplier_return`. Hỏng ở bước gửi là phiếu nằm Nháp, hàng đã về kho, nợ đã xoá (K11). Bản Frappe: cổng cấm ghi thẳng `status`
 * (USE_RPC — BP §6.1) và CFD-01 (sửa = huỷ + amend `PTNCC-0042-1`), nên một RPC làm cả ba trong MỘT giao dịch: hỏng thì không đổi gì.
 * `chiLuuNhap` = POS "lưu nháp" phiếu đã xuất (huỷ + dừng ở tờ amend nháp).
 *
 * Trả `id` tờ còn hiệu lực và phát `npp:doi-id-chung-tu` (lib/purchasing/doi-id.ts) để màn đang đứng ở id cũ chuyển sang.
 */
import type { SupabaseClient } from "@supabase/supabase-js"
import { lineDiscountAmountOf, lineTotalOf, type ReceiptLine } from "@/lib/purchasing/receipt-form"
import { baoDoiId } from "@/lib/purchasing/doi-id"

/** Đầu phiếu gửi `sua_phieu_tra_ncc` — đúng bộ cột màn sửa / POS ghi lên `supplier_returns`. `vat_override` null = máy chủ tự cộng thuế. */
export interface DauPhieuTraSua {
  supplier_id: string
  return_date: string
  warehouse_zone: string
  reason: string | null
  notes: string | null
  discount: number
  vat_override: number | null
}

export interface KetQuaSuaPhieuTra {
  id: string
  trang_thai: string
}

/**
 * Dòng gửi RPC — CHÍNH `linePayloadOf` của lib/purchasing/save-receipt.ts (hàm ấy không xuất ra): giảm dòng là TIỀN, thuế là TỈ LỆ,
 * `sort_order` = STT 1-based người dùng thấy.
 */
export function dongTraNcc(
  lines: ReceiptLine[],
  percentToRatio: (p: string | number | null | undefined) => number
) {
  return lines.map((l, i) => ({
    product_id: l.product_id,
    unit_name: l.unit_name || l.base_unit,
    quantity: Number(l.quantity) || 0,
    unit_price: Number(l.unit_price) || 0,
    line_discount: lineDiscountAmountOf(l),
    vat_rate: percentToRatio(l.vat_percent),
    conversion_factor: Number(l.conversion_factor) || 1,
    line_total: lineTotalOf(l),
    notes: l.note.trim() || null,
    sort_order: i + 1,
  }))
}

export async function suaPhieuTraNcc(
  sb: SupabaseClient,
  returnId: string,
  head: DauPhieuTraSua,
  lines: ReceiptLine[],
  percentToRatio: (p: string | number | null | undefined) => number,
  o: { lyDo: string; chiLuuNhap?: boolean }
): Promise<KetQuaSuaPhieuTra> {
  const { data, error } = await sb.rpc("sua_phieu_tra_ncc", {
    p_return_id: returnId,
    p_head: head,
    p_lines: dongTraNcc(lines, percentToRatio),
    p_reason: o.lyDo,
    p_chi_luu_nhap: !!o.chiLuuNhap,
  })
  if (error) throw new Error(error.message)
  const kq = data as KetQuaSuaPhieuTra
  baoDoiId("supplier_returns", returnId, kq?.id)
  return kq
}
