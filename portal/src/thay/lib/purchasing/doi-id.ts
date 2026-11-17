/**
 * ĐỔI ID CHỨNG TỪ MUA HÀNG SAU KHI SỬA / KHÔI PHỤC (bản Frappe — đặc tả kho_mua §3.4, §3.8, §3.9, §7.3 điểm 2).
 *
 * nppsale sửa / khôi phục phiếu nhập và phiếu trả NCC GIỮ NGUYÊN id (cùng dòng, đổi trạng thái tại chỗ). Bản Frappe làm theo CFD-01: tờ cũ
 * huỷ, tờ amend `PTNCC-0042-1` / `PN-0042-1` là tờ còn hiệu lực — RPC trả `id` MỚI. Màn nào đang đứng ở id cũ phải sang id mới, không thì
 * `load()` lại tờ đã huỷ và lần bấm sau báo "đã huỷ".
 *
 * Lớp phủ gọi RPC (lib/pos/save.ts, lib/purchasing/khoi-phuc.ts, lib/purchasing/sua-phieu-tra.ts) phát sự kiện `npp:doi-id-chung-tu`;
 * trang bọc của màn (app/pos/tra-ncc/[id]…, app/(dashboard)/purchase-returns/[id], purchasing/receipts/[id]) nghe và `router.replace` sang
 * đường dẫn của id mới. Trang bọc dựng lại màn gốc theo `key={id}` — lượt `load()` còn dở của id cũ rơi vào màn đã gỡ, không đè dữ liệu mới.
 */
import { useEffect } from "react"
import { useRouter } from "next/navigation"

export const SU_KIEN_DOI_ID = "npp:doi-id-chung-tu"

export type BangChungTu = "purchase_invoices" | "supplier_returns"

export interface DoiId {
  bang: BangChungTu
  /** id màn đang đứng (id đã gửi lên RPC). */
  cu: string
  /** id tờ còn hiệu lực RPC trả về. */
  moi: string
}

/** Báo các màn đang mở: tờ `cu` nay là `moi`. Không đổi gì thì im. */
export function baoDoiId(bang: BangChungTu, cu: string, moi: string | null | undefined): void {
  if (!moi || moi === cu || typeof window === "undefined") return
  window.dispatchEvent(new CustomEvent<DoiId>(SU_KIEN_DOI_ID, { detail: { bang, cu, moi } }))
}

/** `mau` có chỗ `{id}`: "/pos/tra-ncc/{id}/sua" → đường dẫn của id mới. */
export function duongIdMoi(mau: string, moi: string): string {
  return mau.replace("{id}", encodeURIComponent(moi))
}

/** Trang bọc: id màn đang đứng đổi sang tờ mới → `router.replace` theo `mau`. */
export function useDiTheoIdMoi(bang: BangChungTu, id: string | undefined, mau: string): void {
  const router = useRouter()
  useEffect(() => {
    if (!id) return
    const nghe = (e: Event) => {
      const d = (e as CustomEvent<DoiId>).detail
      if (d && d.bang === bang && d.cu === id && d.moi !== id) router.replace(duongIdMoi(mau, d.moi))
    }
    window.addEventListener(SU_KIEN_DOI_ID, nghe)
    return () => window.removeEventListener(SU_KIEN_DOI_ID, nghe)
  }, [bang, id, mau, router])
}
