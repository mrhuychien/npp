/**
 * `supabase.channel(...).on("postgres_changes", { event, table, filter }, cb).subscribe()` trên cổng Frappe.
 *
 * Bản bàn bạc 3.7: chuông thông báo và khoá chứng từ dùng socket.io của Frappe; khi chưa có socket thì HẠ CẤP — hỏi định kỳ. Ở đây
 * là đường hạ cấp ấy, chạy được ngay không cần thêm thư viện: mỗi bộ (bảng + bộ lọc) một vòng hỏi chung, so ảnh chụp trước / sau
 * để sinh đúng sự kiện INSERT / UPDATE / DELETE với `payload.new` / `payload.old` như Supabase. Tab ẩn thì ngừng hỏi, hiện lại thì
 * hỏi ngay.
 */
export type GoiLai = (payload: any) => void
type HamDoc = (bang: string, cot: string, giaTri: string) => Promise<any[] | null>

/** Nhịp hỏi theo bảng (ms) — khoá chứng từ cần nhanh hơn chuông. */
const NHIP: Record<string, number> = { entity_locks: 8000, notifications: 30000 }
const NHIP_MAC_DINH = 30000

type Nghe = { su_kien: string; f: GoiLai }

class VongHoi {
  private anh = new Map<string, any>()
  private daCo = false
  private hen: ReturnType<typeof setTimeout> | null = null
  nghe = new Set<Nghe>()

  constructor(
    private doc: HamDoc,
    public bang: string,
    private cot: string,
    private giaTri: string
  ) {}

  batDau() {
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", this.khiDoiTrang)
    void this.hoi()
  }

  dung() {
    if (this.hen) clearTimeout(this.hen)
    this.hen = null
    if (typeof document !== "undefined") document.removeEventListener("visibilitychange", this.khiDoiTrang)
  }

  private khiDoiTrang = () => {
    if (typeof document !== "undefined" && document.visibilityState === "visible") void this.hoi()
  }

  private henLai() {
    if (this.hen) clearTimeout(this.hen)
    this.hen = setTimeout(() => void this.hoi(), NHIP[this.bang] ?? NHIP_MAC_DINH)
  }

  async hoi() {
    if (typeof document !== "undefined" && document.visibilityState === "hidden") {
      this.henLai()
      return
    }
    const ds = await this.doc(this.bang, this.cot, this.giaTri).catch(() => null)
    if (ds) {
      const moi = new Map<string, any>()
      for (const r of ds) moi.set(String(r.id), r)
      if (this.daCo) {
        for (const [id, r] of moi) {
          const cu = this.anh.get(id)
          if (!cu) this.phat("INSERT", { new: r, old: {} })
          else if (JSON.stringify(cu) !== JSON.stringify(r)) this.phat("UPDATE", { new: r, old: cu })
        }
        for (const [id, cu] of this.anh) if (!moi.has(id)) this.phat("DELETE", { new: {}, old: cu })
      }
      this.anh = moi
      this.daCo = true
    }
    this.henLai()
  }

  private phat(su_kien: string, p: { new: any; old: any }) {
    const payload = { schema: "public", table: this.bang, commit_timestamp: new Date().toISOString(), eventType: su_kien, ...p, errors: null }
    for (const n of this.nghe) {
      if (n.su_kien === "*" || n.su_kien === su_kien) {
        try {
          n.f(payload)
        } catch (e) {
          console.error("[realtime] nơi nghe lỗi:", e)
        }
      }
    }
  }
}

const VONG = new Map<string, VongHoi>()

/** "user_id=eq.<uid>" → ["user_id", "<uid>"]; chỉ hỗ trợ eq (nppsale chỉ dùng eq). */
export function docBoLoc(filter: string | undefined): [string, string] | null {
  if (!filter) return null
  const m = filter.match(/^([a-z_][a-z0-9_]*)=eq\.(.+)$/)
  return m ? [m[1], m[2]] : null
}

export class Kenh {
  private dk: Array<{ bang: string; loc: [string, string] | null; nghe: Nghe }> = []
  private dangKy: Array<{ khoa: string; nghe: Nghe }> = []

  constructor(
    public ten: string,
    private doc?: HamDoc
  ) {}

  on(loai: string, loc: any, f?: GoiLai) {
    if (loai === "postgres_changes" && loc && typeof loc === "object" && typeof f === "function") {
      this.dk.push({ bang: loc.table, loc: docBoLoc(loc.filter), nghe: { su_kien: loc.event ?? "*", f } })
    }
    return this
  }

  subscribe(f?: (trangThai: string) => void) {
    if (this.doc) {
      for (const d of this.dk) {
        if (!d.loc) continue // không có bộ lọc: không hỏi cả bảng (nppsale không dùng)
        const khoa = `${d.bang}|${d.loc[0]}|${d.loc[1]}`
        let v = VONG.get(khoa)
        const moi = !v
        if (!v) {
          v = new VongHoi(this.doc, d.bang, d.loc[0], d.loc[1])
          VONG.set(khoa, v)
        }
        v.nghe.add(d.nghe)
        this.dangKy.push({ khoa, nghe: d.nghe })
        if (moi) v.batDau()
      }
    }
    setTimeout(() => f?.("SUBSCRIBED"), 0)
    return this
  }

  async unsubscribe() {
    for (const { khoa, nghe } of this.dangKy) {
      const v = VONG.get(khoa)
      if (!v) continue
      v.nghe.delete(nghe)
      if (v.nghe.size === 0) {
        v.dung()
        VONG.delete(khoa)
      }
    }
    this.dangKy = []
    return "ok"
  }

  async send() {
    return "ok"
  }
}

/** Cho test: số vòng hỏi đang chạy. */
export const soVongHoi = () => VONG.size
