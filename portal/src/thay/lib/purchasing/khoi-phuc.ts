/**
 * LỚP PHỦ của lib/purchasing/khoi-phuc.ts (nppsale) — bản Frappe chỉ bọc `khoiPhucPhieuNcc` (đặc tả kho_mua §3.4, §3.9 ⚠K, CFD-01).
 *
 * nppsale khôi phục GIỮ id (phiếu đổi trạng thái tại chỗ). Bản Frappe: khôi phục phiếu đã ghi sổ = tờ amend `PN-0042-1` / `PTNCC-0042-1` — RPC trả
 * `id` mới; màn chi tiết vẫn `load()` id cũ (tờ đã huỷ). Bọc: id trả về khác id đã gửi → phát `npp:doi-id-chung-tu` để trang bọc của màn chi tiết
 * (app/(dashboard)/purchase-returns/[id], purchasing/receipts/[id]) chuyển sang tờ còn hiệu lực.
 */
import type { SupabaseClient } from "@supabase/supabase-js"
import { khoiPhucPhieuNcc as khoiPhucPhieuNccGoc, type KetQuaKhoiPhuc, type LoaiPhieuNcc } from "@goc/lib/purchasing/khoi-phuc"
import { baoDoiId } from "@/lib/purchasing/doi-id"

export * from "@goc/lib/purchasing/khoi-phuc"

export async function khoiPhucPhieuNcc(sb: SupabaseClient, loai: LoaiPhieuNcc, id: string): Promise<KetQuaKhoiPhuc> {
  const kq = await khoiPhucPhieuNccGoc(sb, loai, id)
  baoDoiId(loai === "tra" ? "supplier_returns" : "purchase_invoices", id, kq?.id)
  return kq
}
