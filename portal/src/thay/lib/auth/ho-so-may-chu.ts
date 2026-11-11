import type { User } from "@/types"

export interface HoSoMayChu {
  /** Người của phiên. */
  uid: string
  /** Hồ sơ gửi kèm trang; `null` khi máy chủ đọc hỏng — trình duyệt tự đọc lại như cũ. */
  hoSo: User | null
}

/**
 * PORTAL TRÊN FRAPPE: hồ sơ do vỏ trang (nppsale/www/nppsale/index.py) đọc ở máy chủ và gửi kèm trong
 * `window.NPP_CONTEXT` — cùng vai trò `layHoSoMayChu` của nppsale (layout Next đọc cookie rồi hỏi `users`), nhưng
 * đọc đồng bộ: khung React không còn server component. `null` = chưa đăng nhập.
 */
export function layHoSoMayChu(): HoSoMayChu | null {
  if (typeof window === "undefined") return null
  const nc = (window as unknown as { NPP_CONTEXT?: { user?: string; ho_so?: User | null } }).NPP_CONTEXT
  const uid = nc?.user
  if (!uid || uid === "Guest") return null
  return { uid, hoSo: nc?.ho_so ?? null }
}
