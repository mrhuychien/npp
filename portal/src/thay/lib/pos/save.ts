/**
 * LỚP PHỦ của lib/pos/save.ts (nppsale) — bản Frappe chỉ thay `savePosSupplierReturn` ở nhánh PHIẾU ĐÃ XUẤT (đặc tả kho_mua §3.8, §7.3 điểm 2).
 *
 * nppsale: phiếu `completed` → `cancel_supplier_return` → `update … status 'draft'` (ghi thẳng) → ghi lại dòng → `complete_supplier_return`
 * (hoặc dừng ở nháp khi "lưu nháp") — ba lời gọi rời, cùng id, giữ số phiếu. Bản Frappe: cổng cấm ghi thẳng `status` (USE_RPC) và sửa = huỷ +
 * amend (CFD-01) → gọi MỘT RPC `sua_phieu_tra_ncc` (một giao dịch; hỏng thì phiếu cũ vẫn nguyên — không còn trạng thái nửa chừng của K11) rồi
 * trả `returnId` = tờ còn hiệu lực; trang bọc của POS (app/pos/tra-ncc/[id]…) nghe `npp:doi-id-chung-tu` và chuyển sang id mới.
 * Phiếu mới / phiếu nháp / phiếu đã huỷ: đúng bản nppsale.
 */
import type { SupabaseClient } from "@supabase/supabase-js"
import { savePosSupplierReturn as savePosSupplierReturnGoc, posLinesToReceipt } from "@goc/lib/pos/save"
import { percentToRatio } from "@/lib/purchasing/return-form"
import { suaPhieuTraNcc } from "@/lib/purchasing/sua-phieu-tra"

export * from "@goc/lib/pos/save"

/** Lý do huỷ tờ cũ khi sửa từ POS — chuỗi nppsale gửi `cancel_supplier_return` (save.ts:582–597). */
export const LY_DO_SUA_POS = "Sửa phiếu từ POS — lập lại"

type ThamSoPhieuTra = Parameters<typeof savePosSupplierReturnGoc>[1]

async function docTrangThai(sb: SupabaseClient, id: string): Promise<string> {
  const { data, error } = await sb.from("supplier_returns").select("status").eq("id", id).maybeSingle()
  if (error) throw error
  const st = (data as { status?: string } | null)?.status
  if (!st) throw new Error("Không đọc được phiếu — có thể đã bị xoá, hoặc bạn không có quyền với phiếu này.")
  return st
}

export async function savePosSupplierReturn(sb: SupabaseClient, o: ThamSoPhieuTra): Promise<{ returnId: string }> {
  if (!o.returnId) return savePosSupplierReturnGoc(sb, o)
  const trangThai = await docTrangThai(sb, o.returnId)
  if (trangThai !== "completed") return savePosSupplierReturnGoc(sb, o) // nháp: ghi thẳng như nppsale; đã huỷ: bản gốc báo lỗi
  const kq = await suaPhieuTraNcc(
    sb,
    o.returnId,
    {
      supplier_id: o.supplierId,
      return_date: o.returnDate,
      warehouse_zone: o.zone,
      reason: o.reason || null,
      notes: o.notes.trim() || null,
      discount: o.discount,
      /* như bản gốc: thuế cả phiếu đi qua `vat_override` (dòng POS mang `vat_rate = 0`) */
      vat_override: o.vat > 0 ? o.vat : null,
    },
    posLinesToReceipt(o.lines),
    percentToRatio,
    { lyDo: LY_DO_SUA_POS, chiLuuNhap: !o.complete }
  )
  return { returnId: kq.id || o.returnId }
}
