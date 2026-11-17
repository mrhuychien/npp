/**
 * Lớp phủ M5 (đặc tả kho_mua §4.6): sửa lô ở màn `/inventory/batches/[id]` đổi id dòng lô (`<mã>::<vùng>` — đổi mã / sửa hạn vào ngưỡng kho date) →
 * `ghiPhaiTrungDong` báo dòng trả về, màn đi theo id mới; luật "0 dòng là bị từ chối" giữ nguyên bản nppsale.
 */
import { afterEach, describe, expect, it, vi } from "vitest"
import { ghiPhaiTrungDong, GHI_BI_TU_CHOI } from "@/lib/db/must-write"
import { SU_KIEN_GHI, idLoSauGhi } from "@/lib/inventory/doi-id-lo"

function cau(data: unknown, error: unknown = null) {
  return { select: vi.fn(async (_c: string) => ({ data, error })) }
}

describe("ghiPhaiTrungDong (lớp phủ)", () => {
  const nghe = vi.fn()
  afterEach(() => {
    window.removeEventListener(SU_KIEN_GHI, nghe)
    nghe.mockReset()
  })

  it("xin `*`, báo dòng trả về", async () => {
    window.addEventListener(SU_KIEN_GHI, nghe)
    const q = cau([{ id: "R0-MOI::sale", batch_code: "R0-MOI", warehouse_zone: "sale" }])
    await ghiPhaiTrungDong(q)
    expect(q.select).toHaveBeenCalledWith("*")
    expect(nghe).toHaveBeenCalledTimes(1)
    expect((nghe.mock.calls[0][0] as CustomEvent).detail).toEqual([{ id: "R0-MOI::sale", batch_code: "R0-MOI", warehouse_zone: "sale" }])
  })

  it("0 dòng / lỗi → ném như bản nppsale, không báo", async () => {
    window.addEventListener(SU_KIEN_GHI, nghe)
    await expect(ghiPhaiTrungDong(cau([]))).rejects.toThrow(GHI_BI_TU_CHOI)
    await expect(ghiPhaiTrungDong(cau(null), "câu riêng")).rejects.toThrow("câu riêng")
    const loi = { message: "SO_KHO_KHOA: …", code: "P0001" }
    await expect(ghiPhaiTrungDong(cau(null, loi))).rejects.toBe(loi)
    expect(nghe).not.toHaveBeenCalled()
  })
})

describe("idLoSauGhi", () => {
  it("dòng lô có id khác → id mới", () => {
    expect(idLoSauGhi("R0::sale", [{ id: "R0-MOI::sale", batch_code: "R0-MOI", warehouse_zone: "sale" }])).toBe("R0-MOI::sale")
    expect(idLoSauGhi("L5::sale", [{ id: "L5::date", batch_code: "L5", warehouse_zone: "date" }])).toBe("L5::date")
  })

  it("không đổi / không phải dòng lô / nhiều dòng → null", () => {
    expect(idLoSauGhi("L5::sale", [{ id: "L5::sale", batch_code: "L5", warehouse_zone: "sale" }])).toBeNull()
    expect(idLoSauGhi("L5::sale", [{ id: "KH-0001", name: "Khách" }])).toBeNull()
    expect(idLoSauGhi("L5::sale", [{ id: "a", batch_code: "a", warehouse_zone: "sale" }, { id: "b", batch_code: "b", warehouse_zone: "sale" }]))
      .toBeNull()
    expect(idLoSauGhi(undefined, [{ id: "L5::date", batch_code: "L5", warehouse_zone: "date" }])).toBeNull()
    expect(idLoSauGhi("L5::sale", null)).toBeNull()
  })
})
