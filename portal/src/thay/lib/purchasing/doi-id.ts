/**
 * ĐỔI ID CHỨNG TỪ MUA HÀNG SAU KHI SỬA / KHÔI PHỤC (bản Frappe — đặc tả kho_mua §3.4, §3.8, §3.9, §7.3 điểm 2).
 *
 * nppsale sửa / khôi phục phiếu nhập và phiếu trả NCC GIỮ NGUYÊN id (cùng dòng, đổi trạng thái tại chỗ). Bản Frappe làm theo CFD-01: tờ cũ
 * huỷ, tờ amend `PTNCC-0042-1` / `PN-0042-1` là tờ còn hiệu lực — RPC trả `id` MỚI. Màn nào đang đứng ở id cũ phải sang id mới, không thì
 * `load()` lại tờ đã huỷ và lần bấm sau báo "đã huỷ".
 *
 * Lớp phủ gọi RPC (lib/pos/save.ts, lib/purchasing/khoi-phuc.ts, lib/purchasing/sua-phieu-tra.ts, lib/purchasing/save-receipt.ts — M7) phát sự
 * kiện `npp:doi-id-chung-tu`; trang bọc của màn (app/pos/tra-ncc/[id]…, app/pos/nhap-hang/[id]…, app/(dashboard)/purchase-returns/[id],
 * purchasing/receipts/[id]) nghe và `router.replace` sang đường dẫn của id mới; mở SAU ở id cũ (đã biết trong phiên) cũng chuyển ngay. Trang bọc dựng lại màn gốc theo `key={id}` — lượt `load()` còn dở của id cũ rơi vào màn đã gỡ, không đè dữ liệu mới.
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

/**
 * Đổi id đã biết trong phiên (M7): màn mở SAU ở id cũ — màn sửa phiếu nhập `router.push` về chi tiết id cũ ngay sau `sua_phieu_nhap`, nút lùi của trình
 * duyệt — cũng sang tờ còn hiệu lực (sự kiện chỉ tới màn đang mở). Khoá `<bảng>:<id cũ>`.
 */
const ID_MOI = new Map<string, string>()

/** Báo các màn đang mở: tờ `cu` nay là `moi` (và ghi nhớ cho màn mở sau). Không đổi gì thì im. */
export function baoDoiId(bang: BangChungTu, cu: string, moi: string | null | undefined): void {
  if (!moi || moi === cu) return
  ID_MOI.set(`${bang}:${cu}`, moi)
  if (typeof window === "undefined") return
  window.dispatchEvent(new CustomEvent<DoiId>(SU_KIEN_DOI_ID, { detail: { bang, cu, moi } }))
}

/** Tờ còn hiệu lực đã biết của `id` (đi hết chuỗi đổi — sửa nhiều lần); null = không đổi. */
export function idMoiCua(bang: BangChungTu, id: string | undefined): string | null {
  let x = id
  for (let i = 0; x && i < 50; i++) {
    const y = ID_MOI.get(`${bang}:${x}`)
    if (!y || y === x) break
    x = y
  }
  return x && x !== id ? x : null
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
    const da = idMoiCua(bang, id)
    if (da) {
      router.replace(duongIdMoi(mau, da))
      return
    }
    const nghe = (e: Event) => {
      const d = (e as CustomEvent<DoiId>).detail
      if (d && d.bang === bang && d.cu === id && d.moi !== id) router.replace(duongIdMoi(mau, d.moi))
    }
    window.addEventListener(SU_KIEN_DOI_ID, nghe)
    return () => window.removeEventListener(SU_KIEN_DOI_ID, nghe)
  }, [bang, id, mau, router])
}
