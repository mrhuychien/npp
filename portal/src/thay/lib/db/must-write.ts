/**
 * LỚP PHỦ của lib/db/must-write.ts (nppsale) — bản Frappe chỉ thêm MỘT việc vào `ghiPhaiTrungDong`: báo các dòng lời ghi trả về
 * (`npp:ghi-trung-dong` — lib/inventory/doi-id-lo.ts) để màn đang đứng ở id cũ đi theo id mới (dòng lô `<mã>::<vùng>` đổi id khi sửa mã / hạn — đặc
 * tả kho_mua §4.6, P4 M5). Luật "0 dòng là bị từ chối" giữ nguyên văn bản gốc.
 */
import { GHI_BI_TU_CHOI, type ChoSelect } from "@goc/lib/db/must-write"
import { baoDongDaGhi } from "@/lib/inventory/doi-id-lo"

export * from "@goc/lib/db/must-write"

export async function ghiPhaiTrungDong(q: ChoSelect, thongBao = GHI_BI_TU_CHOI): Promise<void> {
  const { data, error } = await q.select("*")
  if (error) throw error
  if (!Array.isArray(data) || data.length === 0) throw new Error(thongBao)
  baoDongDaGhi(data)
}
