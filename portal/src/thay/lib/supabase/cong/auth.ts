/**
 * `supabase.auth` tối thiểu cho portal trên Frappe (mục 3.6 bản bàn bạc): đăng nhập bằng SĐT + mật khẩu qua /api/method/login,
 * đăng xuất qua /api/method/logout, phiên lấy từ NPP_CONTEXT; báo các tab khác bằng sự kiện `storage` (thay onAuthStateChange).
 */
import { lamMoiCsrf, nguCanh } from "./phien"

type SuKien = "INITIAL_SESSION" | "SIGNED_IN" | "SIGNED_OUT" | "TOKEN_REFRESHED" | "USER_UPDATED"
type NguoiDung = { id: string; email: string; phone?: string; user_metadata: Record<string, unknown>; app_metadata: Record<string, unknown> }
type Phien = { user: NguoiDung; access_token: string; expires_at?: number }
/** Như AuthError của supabase-js (để `error ? error.message : …` của nppsale qua được kiểu). */
type LoiDangNhap = { message: string; status?: number; name?: string }

const KHOA_TAB = "npp:phien"
const nghe = new Set<(e: SuKien, s: Phien | null) => void>()

function phienHienTai(): Phien | null {
  const nc = nguCanh()
  if (!nc.user || nc.user === "Guest") return null
  const hs = (nc.ho_so ?? {}) as Record<string, unknown>
  return {
    access_token: nc.csrf_token || "frappe",
    user: { id: nc.user, email: nc.user, phone: (hs.phone as string) ?? undefined, user_metadata: hs, app_metadata: {} },
  }
}

function phat(e: SuKien) {
  const p = phienHienTai()
  for (const f of nghe) {
    try {
      f(e, p)
    } catch {
      /* một nơi nghe hỏng không chặn nơi khác */
    }
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("storage", (ev) => {
    if (ev.key !== KHOA_TAB || !ev.newValue) return
    void lamMoiCsrf().then(() => phat(ev.newValue!.startsWith("out") ? "SIGNED_OUT" : "SIGNED_IN"))
  })
}

function baoTabKhac(loai: "in" | "out") {
  try {
    localStorage.setItem(KHOA_TAB, `${loai}:${Date.now()}`)
  } catch {
    /* chế độ riêng tư */
  }
}

export const auth = {
  async getSession(): Promise<{ data: { session: Phien | null }; error: LoiDangNhap | null }> {
    return { data: { session: phienHienTai() }, error: null }
  },
  async getUser(): Promise<{ data: { user: NguoiDung | null }; error: LoiDangNhap | null }> {
    const p = phienHienTai()
    return p ? { data: { user: p.user }, error: null } : { data: { user: null }, error: { message: "Auth session missing!", status: 400 } }
  },
  async signInWithPassword(c: { email?: string; phone?: string; password: string }) {
    const usr = (c.phone ?? c.email ?? "").trim()
    const res = await fetch("/api/method/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ usr, pwd: c.password }),
    })
    if (!res.ok) {
      return { data: { user: null, session: null }, error: { message: "Invalid login credentials", status: res.status } }
    }
    await lamMoiCsrf()
    baoTabKhac("in")
    phat("SIGNED_IN")
    const p = phienHienTai()
    return { data: { user: p?.user ?? null, session: p }, error: null }
  },
  async signOut() {
    await fetch("/api/method/logout", { method: "POST", credentials: "same-origin", headers: { Accept: "application/json" } }).catch(() => undefined)
    const nc = nguCanh()
    nc.user = null
    nc.ho_so = null
    baoTabKhac("out")
    phat("SIGNED_OUT")
    return { error: null }
  },
  onAuthStateChange(f: (e: SuKien, s: Phien | null) => void) {
    nghe.add(f)
    setTimeout(() => f("INITIAL_SESSION", phienHienTai()), 0)
    return { data: { subscription: { unsubscribe: () => nghe.delete(f) } } }
  },
  async refreshSession() {
    await lamMoiCsrf()
    return { data: { session: phienHienTai(), user: phienHienTai()?.user ?? null }, error: null }
  },
  async verifyOtp() {
    return { data: { user: null, session: null }, error: { message: "verifyOtp không dùng trên Frappe — QR đi qua nppsale.api.qr", status: 400 } }
  },
}
