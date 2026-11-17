/**
 * ĐỔI ID DÒNG LÔ SAU KHI SỬA (bản Frappe — đặc tả kho_mua §4.6, P4 M5).
 *
 * nppsale: một dòng `batches` có id uuid KHÔNG đổi khi sửa mã lô / sửa hạn (trigger lật vùng tại chỗ). Bản Frappe: cổng dựng dòng lô theo (Batch × kho)
 * với id `<mã lô>::<vùng>` — đổi mã lô (`rename_doc`) hay sửa hạn vào ngưỡng kho date (phiếu `CKL-` chuyển tồn kho bán sang kho date) làm id dòng đổi.
 * Lời ghi của cổng trả dòng SAU khi ghi (id mới) nhưng màn `/inventory/batches/[id]` của nppsale bỏ dữ liệu trả về (`ghiPhaiTrungDong`) rồi tải lại
 * theo id cũ → "Không tìm thấy lô hàng" / dòng kho bán tồn 0.
 *
 * Lớp phủ `lib/db/must-write.ts` phát `npp:ghi-trung-dong` kèm các dòng trả về; trang bọc `app/(dashboard)/inventory/batches/[id]` nghe và
 * `router.replace` sang id mới khi dòng trả về là dòng lô có id khác (dựng lại màn gốc theo `key={id}` — lượt tải dở của id cũ không đè).
 */
import { useEffect } from "react"
import { useRouter } from "next/navigation"

export const SU_KIEN_GHI = "npp:ghi-trung-dong"

/** Báo các màn đang mở: lời ghi vừa trả các dòng này (dòng SAU khi ghi). */
export function baoDongDaGhi(dong: unknown): void {
  if (typeof window === "undefined" || !Array.isArray(dong)) return
  window.dispatchEvent(new CustomEvent<unknown[]>(SU_KIEN_GHI, { detail: dong }))
}

/** id dòng lô mới sau lời ghi trên màn đang đứng ở `id` — null khi không đổi / không phải dòng lô (một dòng, có `batch_code` + `warehouse_zone`). */
export function idLoSauGhi(id: string | undefined, dong: unknown): string | null {
  if (!id || !Array.isArray(dong) || dong.length !== 1) return null
  const r = dong[0] as Record<string, unknown> | null
  if (!r || typeof r !== "object" || typeof r.id !== "string" || !("batch_code" in r) || !("warehouse_zone" in r)) return null
  return r.id !== id ? r.id : null
}

/** Trang bọc màn chi tiết lô: lời ghi trả dòng lô có id khác → sang đường dẫn của id mới. */
export function useDiTheoLoMoi(id: string | undefined): void {
  const router = useRouter()
  useEffect(() => {
    if (!id) return
    const nghe = (e: Event) => {
      const moi = idLoSauGhi(id, (e as CustomEvent<unknown[]>).detail)
      if (moi) router.replace(`/inventory/batches/${encodeURIComponent(moi)}`)
    }
    window.addEventListener(SU_KIEN_GHI, nghe)
    return () => window.removeEventListener(SU_KIEN_GHI, nghe)
  }, [id, router])
}
