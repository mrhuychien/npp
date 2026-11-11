/**
 * Lời gọi `/api/<đường>` của nppsale (route Next.js đã bỏ) → method Frappe `nppsale.api.tuyen.goi`.
 *
 * nppsale có ~20 chỗ `fetch("/api/admin/users/…")`, `fetch("/api/einvoice/publish")`… Giữ nguyên các chỗ ấy, đổi ở một nơi:
 * bọc `window.fetch`, đường dẫn `/api/…` không phải `/api/method/…` / `/api/resource/…` thì gửi sang method cổng kèm đường
 * dẫn + phương thức gốc; máy chủ (nppsale/api/tuyen.py) trả đúng dạng JSON + mã HTTP mà route cũ trả.
 */
import { csrfHienTai } from "@/lib/supabase/cong/phien"

const CONG = "/api/method/nppsale.api.tuyen.goi"

export function laApiCu(url: string): boolean {
  return url.startsWith("/api/") && !url.startsWith("/api/method/") && !url.startsWith("/api/resource/") && !url.startsWith("/api/v2/")
}

export function doiYeuCau(url: string, init: RequestInit = {}): [string, RequestInit] {
  const phuongThuc = (init.method ?? "GET").toUpperCase()
  const headers = new Headers(init.headers ?? {})
  headers.set("X-Npp-Duong", url)
  headers.set("X-Npp-Phuong-Thuc", phuongThuc)
  if (!headers.has("Accept")) headers.set("Accept", "application/json")
  const coThan = phuongThuc !== "GET" && phuongThuc !== "HEAD"
  if (coThan) headers.set("X-Frappe-CSRF-Token", csrfHienTai())
  return [CONG, { ...init, method: coThan ? "POST" : "GET", headers, credentials: "same-origin" }]
}

let daCai = false

export function caiApiCu() {
  if (daCai || typeof window === "undefined") return
  daCai = true
  const goc = window.fetch.bind(window)
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.pathname + input.search : input.url
    if (typeof url === "string" && laApiCu(url)) {
      const [u, i] = doiYeuCau(url, init ?? (input instanceof Request ? { method: input.method, headers: input.headers } : {}))
      return goc(u, i)
    }
    return goc(input, init)
  }
  // sendBeacon không gắn được header CSRF của Frappe → đường /api cũ đi bằng fetch keepalive (cũng sống qua lúc đóng trang).
  if (typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function") {
    const beaconGoc = navigator.sendBeacon.bind(navigator)
    navigator.sendBeacon = (url: string | URL, data?: BodyInit | null) => {
      const u = typeof url === "string" ? url : url.pathname + url.search
      if (!laApiCu(u)) return beaconGoc(url, data)
      void window.fetch(u, { method: "POST", body: data ?? null, keepalive: true, headers: { "content-type": "application/json" } }).catch(() => {})
      return true
    }
  }
}
