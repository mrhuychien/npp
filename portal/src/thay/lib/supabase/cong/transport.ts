/**
 * Gửi yêu cầu tới cổng dữ liệu trên Frappe (`/rest/v1/<bảng>`, `/rest/v1/rpc/<hàm>` — nppsale/portal/rest.py) và dựng lại
 * {data, error, count, status} như supabase-js. Đường dẫn giống hệt Supabase để lớp mạng của nppsale (`fetchCoHetGio`: hàm báo
 * cáo `/rest/v1/rpc/bao_cao_*` chờ 45 giây; `do-mang`: nhật ký theo đường dẫn) nhận diện câu như cũ.
 *
 * - Đọc: GET `?q=<JSON>` (Frappe không commit GET — `fetchCoHetGio` coi là câu đọc, hết giờ được gửi lại). Yêu cầu quá dài
 *   (hiếm: danh sách `in` rất lớn) thì POST kèm `X-Npp-Doc: 1` — khi ấy bộ hẹn giờ coi như câu ghi (chờ 60 giây, không gửi lại).
 * - Ghi: POST kèm `X-Frappe-CSRF-Token`; gặp CSRFTokenError (phiên mới sau đăng nhập / QR) thì lấy token mới và gửi lại một lần.
 * - Lỗi mạng (hết giờ, huỷ, mất mạng) trả đúng dạng postgrest-js: message = "<tên lỗi>: <câu>" — để `errorMessage`, `laHetGio`,
 *   `isAbortError` của nppsale đọc như cũ.
 */
import type { PostgrestResponse, Transport } from "./kieu"
import { csrfHienTai, lamMoiCsrf } from "./phien"

/** Độ dài tối đa của `q` gửi bằng GET (máy chủ cần nginx `large_client_header_buffers` ≥ 32k — xem tài liệu triển khai). */
const TRAN_GET = 24000

function loiMang(e: any): PostgrestResponse {
  return {
    data: null,
    count: null,
    status: 0,
    statusText: "",
    error: { message: `${e?.name ?? "FetchError"}: ${e?.message ?? e}`, details: `${e?.stack ?? ""}`, hint: "", code: `${e?.code ?? ""}` },
  }
}

function cauTuFrappe(body: any): string {
  try {
    if (body?._server_messages) {
      const ds = JSON.parse(body._server_messages) as string[]
      const m = ds.map((x) => {
        try {
          return JSON.parse(x).message as string
        } catch {
          return x
        }
      })
      if (m.length) return m.join("\n").replace(/<[^>]+>/g, "")
    }
  } catch {
    /* bỏ qua */
  }
  if (typeof body?.exception === "string") return body.exception.replace(/^[\w.]+: /, "")
  return body?.exc_type || "Lỗi máy chủ"
}

export function taoTransport(fetchFn: typeof fetch): Transport {
  async function guiMot(duong: string, than: unknown, doc: boolean, signal?: AbortSignal): Promise<Response> {
    const url = duong
    const json = JSON.stringify(than ?? {})
    if (doc && json.length < TRAN_GET) {
      return fetchFn(`${url}?q=${encodeURIComponent(json)}`, { method: "GET", headers: { Accept: "application/json" }, signal, credentials: "same-origin" })
    }
    return fetchFn(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-Frappe-CSRF-Token": csrfHienTai(),
        ...(doc ? { "X-Npp-Doc": "1" } : {}),
      },
      body: json,
      signal,
      credentials: "same-origin",
    })
  }

  return {
    async goi(duong, than, { doc, signal }) {
      let res: Response
      try {
        res = await guiMot(duong, than, doc, signal)
        if (res.status === 400 || res.status === 403) {
          const lai = res.clone()
          const body = await lai.json().catch(() => ({}))
          if (body?.exc_type === "CSRFTokenError") {
            await lamMoiCsrf()
            res = await guiMot(duong, than, doc, signal)
          }
        }
      } catch (e) {
        return loiMang(e)
      }
      let body: any = null
      try {
        body = await res.json()
      } catch {
        body = null
      }
      if (body?.error) {
        // Lỗi do cổng trả (đã đúng dạng PostgREST).
        return { data: null, count: null, status: res.status, statusText: res.statusText, error: body.error }
      }
      if (!res.ok) {
        const het = res.status === 401 || body?.exc_type === "SessionExpired" || body?.exc_type === "AuthenticationError"
        return {
          data: null,
          count: null,
          status: res.status,
          statusText: res.statusText,
          error: het
            ? { message: "JWT expired", code: "PGRST301", details: body?.exc_type ?? null, hint: null }
            : { message: cauTuFrappe(body), code: body?.exc_type === "PermissionError" ? "42501" : "FRAPPE", details: body?.exc_type ?? null, hint: null },
        }
      }
      return { data: body?.data ?? null, count: body?.count ?? null, status: res.status, statusText: "OK", error: null }
    },
  }
}
