/**
 * [Portal Frappe] Bọc `posTargetFor` của nppsale: thẻ `<a>` do React Router dựng mang tiền tố /nppsale, nên bỏ tiền tố trước
 * khi so lối POS. Đích trả về vẫn không có tiền tố — `window.open` / `<a>` được khung thêm tiền tố (src/khung/cua-so.ts).
 */
import { posTargetFor as posTargetForGoc } from "@goc/lib/nav/pos-preview"
import { boGocApp } from "@khung/duong"

export * from "@goc/lib/nav/pos-preview"

export function posTargetFor(href: string): string | null {
  return posTargetForGoc(boGocApp(href))
}
