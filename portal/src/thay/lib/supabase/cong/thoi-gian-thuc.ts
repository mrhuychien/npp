/**
 * `supabase.channel()` tối thiểu — chuông thông báo và khoá chứng từ (mục 7 bản bàn bạc: socket.io của Frappe +
 * publish_realtime). Chưa nối socket thì kênh vẫn "SUBSCRIBED" nhưng không có sự kiện: chuông hỏi định kỳ, khoá dựa nhịp 60 giây
 * (đường hạ cấp đã ghi ở bản bàn bạc).
 */
type GoiLai = (payload: any) => void

export class Kenh {
  private nghe: Array<{ loai: string; loc: any; f: GoiLai }> = []
  constructor(public ten: string) {}
  on(loai: string, loc: any, f?: GoiLai) {
    this.nghe.push({ loai, loc, f: (f ?? loc) as GoiLai })
    return this
  }
  subscribe(f?: (trangThai: string) => void) {
    setTimeout(() => f?.("SUBSCRIBED"), 0)
    return this
  }
  async unsubscribe() {
    this.nghe = []
    return "ok"
  }
  async send() {
    return "ok"
  }
  /** Gọi từ bộ nối socket.io khi có sự kiện (P3). */
  phat(loai: string, payload: any) {
    for (const n of this.nghe) if (n.loai === loai || n.loai === "*") n.f(payload)
  }
}
