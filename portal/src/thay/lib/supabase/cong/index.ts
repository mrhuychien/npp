/**
 * Thay `@supabase/supabase-js` / `@supabase/ssr` (alias ở vite.config.ts): cùng `createClient()` / kiểu `SupabaseClient`,
 * nhưng mọi lời gọi đi qua cổng tương thích của app nppsale trên Frappe (quyết định Q1, blueprint/00_quyet_dinh_trien_khai.md).
 */
import { auth } from "./auth"
import { storage } from "./kho-tep"
import { Kenh } from "./thoi-gian-thuc"
import { taoTransport } from "./transport"
import { QueryBuilder, RpcBuilder } from "./truy-van"

export type { PostgrestError, PostgrestResponse } from "./kieu"

export interface TuyChon {
  global?: { fetch?: typeof fetch; headers?: Record<string, string> }
  auth?: Record<string, unknown>
  [k: string]: unknown
}

export class SupabaseClient<_DB = any, _S = any, _X = any> {
  private t
  auth = auth
  storage = storage
  constructor(_url?: string, _key?: string, opts?: TuyChon) {
    const f = opts?.global?.fetch ?? ((...a: Parameters<typeof fetch>) => fetch(...a))
    this.t = taoTransport(f)
  }
  from<T = any[]>(bang: string): QueryBuilder<T> {
    return new QueryBuilder<T>(this.t, bang)
  }
  schema(_s: string) {
    return this
  }
  rpc<T = any>(ten: string, thamSo?: object, opts?: { get?: boolean; head?: boolean; count?: "exact" | "planned" | "estimated" }): RpcBuilder<T> {
    return new RpcBuilder<T>(this.t, ten, thamSo, Boolean(opts?.get || opts?.head), opts?.count, Boolean(opts?.head))
  }
  channel(ten: string) {
    // Đường hạ cấp của realtime: kênh tự hỏi bảng qua chính cổng dữ liệu (xem thoi-gian-thuc.ts)
    return new Kenh(ten, async (bang, cot, giaTri) => {
      const { data, error } = await this.from(bang).select("*").eq(cot, giaTri).order("created_at", { ascending: false }).limit(50)
      if (error) {
        // bảng không có created_at (entity_locks) → hỏi không sắp
        const lai = await this.from(bang).select("*").eq(cot, giaTri).limit(50)
        return lai.error ? null : (lai.data as any[])
      }
      return data as any[]
    })
  }
  removeChannel(k: Kenh) {
    return k.unsubscribe()
  }
  removeAllChannels() {
    return Promise.resolve([])
  }
}

export function createClient<DB = any>(url?: string, key?: string, opts?: TuyChon): SupabaseClient<DB> {
  return new SupabaseClient<DB>(url, key, opts)
}

/** @supabase/ssr */
export const createBrowserClient = createClient
export const createServerClient = createClient
