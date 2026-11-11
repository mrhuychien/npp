/** `next/server` chỉ dùng ở route API / middleware của nppsale — portal đã chuyển chúng thành method Frappe. Giữ để biên dịch. */
export class NextResponse extends Response {
  static json(body: unknown, init?: ResponseInit) {
    return new Response(JSON.stringify(body), { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } })
  }
  static redirect(url: string | URL, status = 307) {
    return new Response(null, { status, headers: { Location: String(url) } })
  }
  static next() {
    return new Response(null)
  }
}
export type NextRequest = Request & { nextUrl: URL; cookies: { get(n: string): { value: string } | undefined } }
