import { describe, expect, it, vi } from "vitest"
import { createClient } from "@/lib/supabase/cong"
import { taoTransport } from "@/lib/supabase/cong/transport"
import { motDong } from "@/lib/supabase/cong/truy-van"

function giaFetch(tra: unknown, status = 200) {
  return vi.fn(async (_u: RequestInfo | URL, _i?: RequestInit) => new Response(JSON.stringify(tra), { status, headers: { "Content-Type": "application/json" } }))
}

describe("cổng dữ liệu — bộ dựng truy vấn", () => {
  it("đọc đi GET /rest/v1/<bảng>?q=<JSON> đúng thứ tự lọc / sắp / phân trang", async () => {
    const f = giaFetch({ data: [{ id: "1" }], count: 7 })
    const sb = createClient(undefined, undefined, { global: { fetch: f as unknown as typeof fetch } })
    const { data, count, error } = await sb
      .from("sales_orders")
      .select("id, customer:customers(store_name)", { count: "exact" })
      .eq("status", "draft")
      .in("customer_id", ["a", "b"])
      .or("code.ilike.*DH*,note.is.null")
      .order("created_at", { ascending: false })
      .range(0, 49)
    expect(error).toBeNull()
    expect(data).toEqual([{ id: "1" }])
    expect(count).toBe(7)
    const [url, init] = f.mock.calls[0]
    expect(init?.method).toBe("GET")
    const u = new URL(String(url), "http://x")
    expect(u.pathname).toBe("/rest/v1/sales_orders")
    const yc = JSON.parse(u.searchParams.get("q")!)
    expect(yc).toMatchObject({
      bang: "sales_orders",
      hanh_dong: "select",
      select: "id, customer:customers(store_name)",
      count: "exact",
      range: [0, 49],
      loc: [
        { op: "eq", cot: "status", gt: "draft" },
        { op: "in", cot: "customer_id", gt: ["a", "b"] },
        { op: "or", bieu_thuc: "code.ilike.*DH*,note.is.null", bang_ngoai: null },
      ],
      thu_tu: [{ cot: "created_at", tang: false, null_dau: null, bang_ngoai: null }],
    })
  })

  it("ghi đi POST kèm CSRF; lỗi của cổng trả nguyên dạng PostgREST", async () => {
    ;(window as any).NPP_CONTEXT = { user: "a@b.c", csrf_token: "tok" }
    const f = giaFetch({ error: { message: "permission denied", code: "42501", details: "", hint: "" } }, 403)
    const sb = createClient(undefined, undefined, { global: { fetch: f as unknown as typeof fetch } })
    const { error } = await sb.from("receivables").update({ paid: 1 }).eq("id", "x")
    expect(error?.code).toBe("42501")
    const [url, init] = f.mock.calls[0]
    expect(String(url)).toBe("/rest/v1/receivables")
    expect(init?.method).toBe("POST")
    expect((init?.headers as Record<string, string>)["X-Frappe-CSRF-Token"]).toBe("tok")
    expect(JSON.parse(String(init?.body))).toMatchObject({ hanh_dong: "update", gia_tri: { paid: 1 } })
  })

  it("rpc { get: true } đi GET; lọc / sắp / phân trang sau hàm đi trong `sau`", async () => {
    const f = giaFetch({ data: [{ product_id: "p1" }], count: 1 })
    const sb = createClient(undefined, undefined, { global: { fetch: f as unknown as typeof fetch } })
    await sb
      .rpc("committed_stock_by_product", { p_exclude_order: null }, { count: "exact", get: true })
      .select("product_id, committed_base")
      .order("product_id")
      .range(0, 999)
    const [url, init] = f.mock.calls[0]
    expect(init?.method).toBe("GET")
    const u = new URL(String(url), "http://x")
    expect(u.pathname).toBe("/rest/v1/rpc/committed_stock_by_product")
    expect(JSON.parse(u.searchParams.get("q")!)).toEqual({ p_exclude_order: null })
    expect(JSON.parse(u.searchParams.get("sau")!)).toEqual({
      select: "product_id, committed_base",
      thu_tu: [{ cot: "product_id", tang: true, null_dau: null, bang_ngoai: null }],
      range: [0, 999],
      count: "exact",
    })
  })

  it("rpc không get đi POST — đường dẫn /rest/v1/rpc/bao_cao_* giữ nguyên để bộ hẹn giờ nhận ra", async () => {
    const f = giaFetch({ data: [] })
    const sb = createClient(undefined, undefined, { global: { fetch: f as unknown as typeof fetch } })
    await sb.rpc("post_invoice", { p_order_id: "o1" })
    expect(f.mock.calls[0][1]?.method).toBe("POST")
    expect(String(f.mock.calls[0][0])).toBe("/rest/v1/rpc/post_invoice")
  })

  it(".single() trên nhiều dòng → PGRST116 như PostgREST", () => {
    const kq = motDong({ data: [1, 2], error: null, count: null, status: 200, statusText: "OK" }, "one")
    expect(kq.error?.code).toBe("PGRST116")
    expect(motDong({ data: [], error: null, count: null, status: 200, statusText: "OK" }, "maybe").data).toBeNull()
  })

  it("lỗi mạng giữ dạng `<tên>: <câu>` để errorMessage / laHetGio của nppsale đọc như cũ", async () => {
    const t = taoTransport((async () => {
      throw Object.assign(new Error("Fetch is aborted"), { name: "AbortError" })
    }) as unknown as typeof fetch)
    const kq = await t.goi("/rest/v1/x", {}, { doc: true })
    expect(kq.error?.message).toBe("AbortError: Fetch is aborted")
  })
})
