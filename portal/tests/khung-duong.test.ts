import { describe, expect, it, vi } from "vitest"
import { boGocApp, duongApp } from "@khung/duong"
import { doiYeuCau, laApiCu } from "@khung/api-cu"
import { posTargetFor } from "@/lib/nav/pos-preview"
import { posTargetFor as posTargetForGoc } from "@goc/lib/nav/pos-preview"

describe("đường dẫn portal dưới /nppsale", () => {
  it("duongApp chỉ thêm tiền tố cho đường dẫn của app", () => {
    expect(duongApp("/sales-invoices/1")).toBe("/nppsale/sales-invoices/1")
    expect(duongApp("/")).toBe("/nppsale")
    expect(duongApp("/nppsale/orders")).toBe("/nppsale/orders")
    expect(duongApp("/api/method/x")).toBe("/api/method/x")
    expect(duongApp("/assets/a.png")).toBe("/assets/a.png")
    expect(duongApp("https://x.vn/a")).toBe("https://x.vn/a")
    expect(duongApp("//cdn/x")).toBe("//cdn/x")
    expect(duongApp("orders")).toBe("orders")
  })

  it("boGocApp ngược lại duongApp", () => {
    expect(boGocApp("/nppsale/sell/edit/1?x=1")).toBe("/sell/edit/1?x=1")
    expect(boGocApp("/nppsale")).toBe("/")
    expect(boGocApp("/nppsalex/a")).toBe("/nppsalex/a")
  })

  it("posTargetFor của lớp phủ nhận cả thẻ <a> đã có tiền tố, kết quả như bản gốc", () => {
    for (const h of ["/sell/edit/abc", "/sales-invoices/new?order=o1", "/orders"]) {
      expect(posTargetFor(duongApp(h))).toBe(posTargetForGoc(h))
    }
    expect(posTargetForGoc("/sell/edit/abc")).not.toBeNull()
  })
})

describe("route /api cũ của Next → nppsale.api.tuyen.goi", () => {
  it("nhận diện đúng", () => {
    expect(laApiCu("/api/admin/users/1/password")).toBe(true)
    expect(laApiCu("/api/method/login")).toBe(false)
    expect(laApiCu("/rest/v1/x")).toBe(false)
  })
  it("giữ đường dẫn + phương thức gốc trong header, ghi kèm CSRF", () => {
    ;(window as any).NPP_CONTEXT = { user: "u", csrf_token: "c1" }
    const [u, i] = doiYeuCau("/api/einvoice/publish?x=1", { method: "PATCH", body: "{}", headers: { "Content-Type": "application/json" } })
    expect(u).toBe("/api/method/nppsale.api.tuyen.goi")
    expect(i.method).toBe("POST")
    const h = new Headers(i.headers)
    expect(h.get("X-Npp-Duong")).toBe("/api/einvoice/publish?x=1")
    expect(h.get("X-Npp-Phuong-Thuc")).toBe("PATCH")
    expect(h.get("X-Frappe-CSRF-Token")).toBe("c1")
    const [, g] = doiYeuCau("/api/do-nap")
    expect(g.method).toBe("GET")
  })
})

describe("cửa sổ: window.open + thẻ <a> thường", () => {
  it("thêm tiền tố khi mở tab và khi bấm thẻ", async () => {
    const mo = vi.fn(() => null)
    window.open = mo as unknown as typeof window.open
    const { caiCuaSo } = await import("@khung/cua-so")
    caiCuaSo()
    window.open("/pos/hoa-don/moi?order=1", "_blank")
    expect(mo).toHaveBeenCalledWith("/nppsale/pos/hoa-don/moi?order=1", "_blank", undefined)
    const a = document.createElement("a")
    a.setAttribute("href", "/home")
    document.body.appendChild(a)
    a.addEventListener("click", (e) => e.preventDefault())
    a.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
    expect(a.getAttribute("href")).toBe("/nppsale/home")
  })
})
