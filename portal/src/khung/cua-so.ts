/**
 * Đường dẫn tuyệt đối mà mã nppsale đi bằng trình duyệt (không qua React Router) — thêm tiền tố /nppsale ở một chỗ:
 *   - `window.open("/sales-invoices/1")` (openInNewTab, nút "Phát hành HĐĐT ↗"…);
 *   - thẻ `<a href="/home">` thường (màn lỗi, khung POS, NewTabLink mở tab mới): sửa thuộc tính `href` ngay khi chuột rê /
 *     focus / bấm / bấm chuột giữa / mở menu chuột phải — trước khi trình duyệt đọc nó.
 * Bộ nghe gắn ở `window`, pha bắt (capture): chạy TRƯỚC bộ bắt lối POS của nppsale (`PosNewTab`, gắn ở `document`).
 * Đường lùi phía máy chủ: hooks.website_redirects đưa các đường dẫn cấp một của app về /nppsale/….
 */
import { duongApp } from "./duong"

function suaThe(e: Event) {
  const a = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null
  if (!a) return
  const h = a.getAttribute("href") || ""
  const moi = duongApp(h)
  if (moi !== h) a.setAttribute("href", moi)
}

let daCai = false

export function caiCuaSo() {
  if (daCai || typeof window === "undefined") return
  daCai = true
  const moGoc = window.open.bind(window)
  window.open = ((url?: string | URL, target?: string, features?: string) =>
    moGoc(typeof url === "string" ? duongApp(url) : url, target, features)) as typeof window.open
  for (const ev of ["mouseover", "focusin", "click", "auxclick", "contextmenu"]) {
    window.addEventListener(ev, suaThe, { capture: true, passive: true })
  }
}
