import { describe, expect, it } from "vitest"
import { laTrangDanhSach } from "@/lib/nav/mobile-chrome"
import { laTrangDanhSach as goc } from "@goc/lib/nav/mobile-chrome"

const UUID = "3f1c2a9e-8b7d-4c6e-9a1b-2c3d4e5f6a7b"

describe("laTrangDanhSach với id là mã thật (bản Frappe)", () => {
  it("trang chi tiết theo mã chứng từ / mã khách / email NV là chi tiết (←), không phải danh sách (☰)", () => {
    for (const p of ["/orders/DH-0042", "/customers/KH-00042", "/settings/users/0909123456@nppsale.local",
      "/settings/users/0909123456@nppsale.local/permissions", "/sales-invoices/HD-0042-1", "/receivables/by-customer/KH-00042",
      "/products/SP001945", "/inventory/stock-card/SP001945"]) {
      expect(laTrangDanhSach(p), p).toBe(false)
    }
  })
  it("trang danh sách / route tĩnh cùng cấp với [id] vẫn là danh sách", () => {
    for (const p of ["/orders", "/customers", "/customers/missing-photos", "/customers/ban-giao", "/customers/hang-da-lay",
      "/settings/users", "/sales-invoices", "/products"]) {
      expect(laTrangDanhSach(p), p).toBe(true)
    }
  })
  it("giữ nguyên kết quả bản gốc trên đường dẫn UUID và /new /edit /print", () => {
    for (const p of [`/orders/${UUID}`, `/customers/${UUID}/edit`, "/orders/new", "/customers/new", "/home", "/", "/in/hoa-don/x/print"]) {
      if (!goc(p)) expect(laTrangDanhSach(p), p).toBe(false)
    }
  })
})
