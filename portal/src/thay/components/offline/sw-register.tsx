/**
 * [Portal Frappe] Đăng ký service worker dưới phạm vi /nppsale/ (tệp do nppsale.portal.tinh phục vụ, không cache, kèm
 * Service-Worker-Allowed). Chỉ bản build; trình duyệt không hỗ trợ / lỗi thì bỏ qua.
 */
import { useEffect } from "react"

export function ServiceWorkerRegister() {
  useEffect(() => {
    if (!import.meta.env.PROD || !("serviceWorker" in navigator)) return
    const dangKy = () => {
      navigator.serviceWorker.register("/nppsale/sw.js", { scope: "/nppsale/" }).catch((e) => console.warn("[sw] đăng ký hỏng:", e))
    }
    if (document.readyState === "complete") dangKy()
    else window.addEventListener("load", dangKy, { once: true })
  }, [])
  return null
}
