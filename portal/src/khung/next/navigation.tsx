/**
 * Thay `next/navigation` bằng React Router (portal chạy dưới basename "/nppsale"; mọi đường dẫn trong mã nppsale vẫn không tiền tố).
 * redirect() / notFound() ném lỗi riêng — errorElement của từng route (khung/loi.tsx) bắt và chuyển trang / hiện trang 404.
 */
import { useMemo } from "react"
import { useLocation, useMatches, useNavigate, useParams as useRRParams, useSearchParams as useRRSearchParams } from "react-router-dom"

export type ReadonlyURLSearchParams = URLSearchParams

export class LoiChuyenHuong extends Error {
  constructor(public href: string) {
    super("NEXT_REDIRECT")
  }
}
export class LoiKhongThay extends Error {
  constructor() {
    super("NEXT_NOT_FOUND")
  }
}

export const RedirectType = { push: "push", replace: "replace" } as const

export function useRouter() {
  const nav = useNavigate()
  return useMemo(
    () => ({
      push: (href: string, _o?: unknown) => diToi(nav, href, false),
      replace: (href: string, _o?: unknown) => diToi(nav, href, true),
      back: () => nav(-1),
      forward: () => nav(1),
      refresh: () => window.dispatchEvent(new CustomEvent("npp:lam-moi")),
      prefetch: (_href: string) => undefined,
    }),
    [nav]
  )
}

function diToi(nav: ReturnType<typeof useNavigate>, href: string, thay: boolean) {
  if (/^[a-z]+:\/\//i.test(href)) {
    if (thay) window.location.replace(href)
    else window.location.assign(href)
    return
  }
  nav(href, { replace: thay })
}

export function usePathname(): string {
  return useLocation().pathname
}

export function useSearchParams(): ReadonlyURLSearchParams {
  const [sp] = useRRSearchParams()
  return sp
}

/** Tham số route như Next: [id] → id; [...slug] / [[...slug]] → mảng (splat "*" của React Router đổi tên theo handle). */
export function useParams<T extends Record<string, any> = Record<string, string | string[]>>(): T {
  const p = useRRParams()
  const matches = useMatches()
  const kq: Record<string, any> = { ...p }
  const h = [...matches].reverse().find((m) => (m.handle as any)?.batTatCa)?.handle as { batTatCa: string; tuyChon?: boolean } | undefined
  if (h && "*" in kq) {
    const v = (kq["*"] as string) ?? ""
    kq[h.batTatCa] = v ? v.split("/").filter(Boolean).map(decodeURIComponent) : h.tuyChon ? undefined : []
    delete kq["*"]
  }
  return kq as T
}

export function redirect(href: string, _type?: unknown): never {
  throw new LoiChuyenHuong(href)
}
export function permanentRedirect(href: string, _type?: unknown): never {
  throw new LoiChuyenHuong(href)
}
export function notFound(): never {
  throw new LoiKhongThay()
}
export function useSelectedLayoutSegment(): string | null {
  return null
}
export function useSelectedLayoutSegments(): string[] {
  return []
}
