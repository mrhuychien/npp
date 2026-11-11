/**
 * Đường dẫn trong portal: app chạy dưới `/nppsale` trên Frappe. React Router (`<Link>`, `router.push`) tự thêm tiền tố;
 * chỗ nào đi bằng trình duyệt trực tiếp (`window.open`, `location.href`, thẻ `<a>` thường) thì qua `duongApp`.
 */
export const GOC_APP = "/nppsale"

const KHONG_DOI = /^(\/nppsale(\/|$|\?|#)|\/api\/|\/assets\/|\/files\/|\/private\/)/

/** "/orders/1" → "/nppsale/orders/1"; địa chỉ ngoài, đường dẫn tương đối, "/api/…", "/assets/…" giữ nguyên. */
export function duongApp(href: string): string {
  if (!href.startsWith("/") || href.startsWith("//") || KHONG_DOI.test(href)) return href
  return GOC_APP + (href === "/" ? "" : href)
}

/** Ngược lại `duongApp`: "/nppsale/orders" → "/orders" (đọc `href` của thẻ `<a>` do React Router dựng — đã có tiền tố). */
export function boGocApp(href: string): string {
  let h = href
  if (typeof window !== "undefined" && h.startsWith(window.location.origin)) h = h.slice(window.location.origin.length)
  if (h === GOC_APP) return "/"
  if (h.startsWith(GOC_APP + "/") || h.startsWith(GOC_APP + "?") || h.startsWith(GOC_APP + "#")) {
    const con = h.slice(GOC_APP.length)
    return con.startsWith("/") ? con : "/" + con
  }
  return h
}
