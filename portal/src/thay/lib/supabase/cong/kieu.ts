/** Kiểu dữ liệu giống @supabase/postgrest-js để mã nppsale không phải đổi chữ ký (chuỗi rỗng thay cho null như thư viện khai). */
export type PostgrestError = { message: string; code: string; details: string; hint: string }

export type PostgrestResponse<T = any> = {
  data: T | null
  error: PostgrestError | null
  count: number | null
  status: number
  statusText: string
}

/** Một yêu cầu gửi về cổng `/rest/v1/<bảng>` (nppsale/portal/rest.py → nppsale/cong). */
export interface YeuCau {
  bang: string
  hanh_dong: "select" | "insert" | "update" | "upsert" | "delete"
  select?: string | null
  loc: Array<Record<string, unknown>>
  thu_tu: Array<Record<string, unknown>>
  range?: [number, number]
  limit?: number
  count?: string | null
  head?: boolean
  mot?: "one" | "maybe" | null
  gia_tri?: unknown
  on_conflict?: string
  bo_qua_trung?: boolean
}

export interface Transport {
  /** Gửi tới `duong` ("/rest/v1/orders", "/rest/v1/rpc/post_invoice"); `doc` = chỉ đọc (GET, thử lại an toàn). */
  goi(duong: string, than: unknown, opts: { doc: boolean; signal?: AbortSignal }): Promise<PostgrestResponse>
}
