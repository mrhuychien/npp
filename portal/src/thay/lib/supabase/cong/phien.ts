/**
 * Phiên đăng nhập Frappe ở trình duyệt: CSRF token + hồ sơ người dùng bơm sẵn trong HTML (`window.NPP_CONTEXT`, do
 * nppsale/www/nppsale/index.py dựng). Sau đăng nhập / QR là phiên mới → lấy lại token qua method `nppsale.api.phien.ngu_canh`.
 */
export interface NguCanhNpp {
  user: string | null
  csrf_token: string
  ho_so?: Record<string, unknown> | null
  quyen?: unknown
  cai_dat?: Record<string, unknown> | null
  phien_ban?: string
}

declare global {
  interface Window {
    NPP_CONTEXT?: NguCanhNpp
  }
}

export function nguCanh(): NguCanhNpp {
  if (typeof window === "undefined") return { user: null, csrf_token: "" }
  if (!window.NPP_CONTEXT) {
    const meta = document.querySelector('meta[name="csrf_token"]') as HTMLMetaElement | null
    window.NPP_CONTEXT = { user: null, csrf_token: meta?.content ?? "" }
  }
  return window.NPP_CONTEXT
}

export function csrfHienTai(): string {
  return nguCanh().csrf_token || ""
}

export async function lamMoiCsrf(): Promise<NguCanhNpp> {
  const res = await fetch("/api/method/nppsale.api.phien.ngu_canh", { method: "GET", credentials: "same-origin", headers: { Accept: "application/json" } })
  const body = await res.json().catch(() => ({}))
  const m = (body?.message ?? {}) as NguCanhNpp
  window.NPP_CONTEXT = { ...nguCanh(), ...m }
  return window.NPP_CONTEXT
}
