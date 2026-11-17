/**
 * LỚP PHỦ của lib/purchasing/save-receipt.ts (nppsale) — bản Frappe chỉ thay `suaPhieuNhapDaXong` (đặc tả kho_mua §3.3, §7.3 điểm 2 — M7).
 *
 * nppsale sửa phiếu nhập đã hoàn thành TẠI CHỖ (giữ id). Bản Frappe: phiếu chưa xuất lô nào = huỷ + amend `PN-0042-1` (CFD-01) — RPC `sua_phieu_nhap`
 * trả `id` MỚI; phiếu đã xuất = chỉ sửa giá, id giữ. Bọc: id trả về khác id đã gửi → phát `npp:doi-id-chung-tu` + ghi nhớ (lib/purchasing/doi-id.ts)
 * để màn đang đứng ở id cũ (POS `/pos/nhap-hang/<id>[/sua]` — lib/pos/save.ts của nppsale gọi hàm này) và màn mở SAU ở id cũ (màn sửa
 * `/purchasing/receipts/<id>/edit` sửa xong `router.push` về chi tiết id cũ) chuyển sang tờ còn hiệu lực. Dòng gửi lên = `linePayloadOf` của bản
 * gốc (không xuất ra — dùng bản chép `dongTraNcc` của lib/purchasing/sua-phieu-tra.ts, cùng mười cột).
 */
import type { SupabaseClient } from "@supabase/supabase-js"
import type { DauPhieuNhapSua } from "@goc/lib/purchasing/save-receipt"
import type { ReceiptLine } from "@/lib/purchasing/receipt-form"
import { baoDoiId } from "@/lib/purchasing/doi-id"
import { dongTraNcc } from "@/lib/purchasing/sua-phieu-tra"

export * from "@goc/lib/purchasing/save-receipt"

/** Kết quả `sua_phieu_nhap` (như nppsale): `id` = tờ còn hiệu lực sau sửa. */
export interface KetQuaSuaPhieuNhap {
  id: string
  total: number
  paid: number
  so_dong: number
  doi_gia_lo: number
}

export async function suaPhieuNhapDaXong(
  supabase: SupabaseClient,
  invoiceId: string,
  head: DauPhieuNhapSua,
  lines: ReceiptLine[],
  percentToRatio: (p: string | number | null | undefined) => number
): Promise<KetQuaSuaPhieuNhap> {
  const { data, error } = await supabase.rpc("sua_phieu_nhap", {
    p_invoice_id: invoiceId,
    p_head: head,
    p_lines: dongTraNcc(lines, percentToRatio),
  })
  if (error) throw new Error(error.message)
  const kq = data as KetQuaSuaPhieuNhap
  baoDoiId("purchase_invoices", invoiceId, kq?.id)
  return kq
}
