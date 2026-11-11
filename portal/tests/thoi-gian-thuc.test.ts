import { afterEach, describe, expect, it, vi } from "vitest"
import { Kenh, docBoLoc, soVongHoi } from "@/lib/supabase/cong/thoi-gian-thuc"

describe("realtime hạ cấp — hỏi định kỳ, so ảnh chụp", () => {
  afterEach(() => vi.useRealTimers())

  it("đọc bộ lọc eq", () => {
    expect(docBoLoc("user_id=eq.a@b.c")).toEqual(["user_id", "a@b.c"])
    expect(docBoLoc("entity_id=eq.DH-0001")).toEqual(["entity_id", "DH-0001"])
    expect(docBoLoc("x=in.(1,2)")).toBeNull()
  })

  it("sinh INSERT / UPDATE / DELETE với new / old như Supabase, gỡ kênh là dừng hỏi", async () => {
    vi.useFakeTimers()
    let lan = 0
    const kq = [
      [{ id: "1", is_read: false }],
      [{ id: "1", is_read: true }, { id: "2", is_read: false }],
      [{ id: "2", is_read: false }],
    ]
    const doc = vi.fn(async () => kq[Math.min(lan++, kq.length - 1)])
    const sk: string[] = []
    const k = new Kenh("thong-bao", doc)
      .on("postgres_changes", { event: "*", schema: "public", table: "notifications", filter: "user_id=eq.u1" }, (p) =>
        sk.push(`${p.eventType}:${(p.new?.id ?? p.old?.id) as string}:${String(p.new?.is_read ?? "")}/${String(p.old?.is_read ?? "")}`)
      )
      .subscribe()
    await vi.advanceTimersByTimeAsync(0)
    expect(sk).toEqual([]) // lần đầu chỉ chụp
    await vi.advanceTimersByTimeAsync(30000)
    expect(sk).toEqual(["UPDATE:1:true/false", "INSERT:2:false/"])
    await vi.advanceTimersByTimeAsync(30000)
    expect(sk.at(-1)).toBe("DELETE:1:/true")
    expect(soVongHoi()).toBe(1)
    await k.unsubscribe()
    expect(soVongHoi()).toBe(0)
    const truoc = doc.mock.calls.length
    await vi.advanceTimersByTimeAsync(90000)
    expect(doc.mock.calls.length).toBe(truoc)
  })

  it("chỉ gọi nơi nghe đúng sự kiện", async () => {
    vi.useFakeTimers()
    let lan = 0
    const doc = vi.fn(async () => (lan++ === 0 ? [] : [{ id: "L1", entity_type: "sales_order" }]))
    const ins = vi.fn()
    const del = vi.fn()
    const k = new Kenh("khoa", doc)
      .on("postgres_changes", { event: "INSERT", table: "entity_locks", filter: "entity_id=eq.DH-1" }, ins)
      .on("postgres_changes", { event: "DELETE", table: "entity_locks", filter: "entity_id=eq.DH-1" }, del)
      .subscribe()
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(8000)
    expect(ins).toHaveBeenCalledTimes(1)
    expect(del).not.toHaveBeenCalled()
    await k.unsubscribe()
  })
})
