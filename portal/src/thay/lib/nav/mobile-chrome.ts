/**
 * [Portal Frappe] Bọc `laTrangDanhSach` của nppsale: bản gốc nhận trang CHI TIẾT bằng đoạn UUID trong đường dẫn; bản Frappe dùng mã
 * thật làm id (đơn DH-0042, khách KH-00042, NV là email kỹ thuật…) nên nhận thêm theo cây route — đoạn ứng với thư mục [id] của
 * nppsale (mẫu sinh tự động: src/khung/duong-chi-tiet.generated.ts). Đường dẫn UUID vẫn nhận như cũ.
 */
import { laTrangDanhSach as laTrangDanhSachGoc } from "@goc/lib/nav/mobile-chrome"
import { MAU_CHI_TIET } from "@khung/duong-chi-tiet.generated"

export * from "@goc/lib/nav/mobile-chrome"

export function laTrangDanhSach(pathname: string): boolean {
  if (!laTrangDanhSachGoc(pathname)) return false
  return !MAU_CHI_TIET.some((m) => m.test(pathname))
}
