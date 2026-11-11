/** Thay `next/link`: React Router <Link> (tự gắn basename "/nppsale" vào href, kể cả khi target="_blank"). */
import { forwardRef, type AnchorHTMLAttributes, type ReactNode } from "react"
import { Link as RRLink } from "react-router-dom"

type DiaChi = string | { pathname?: string; query?: Record<string, string | number | boolean | undefined>; hash?: string }

export type LinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  href: DiaChi
  prefetch?: boolean | null
  replace?: boolean
  scroll?: boolean
  shallow?: boolean
  legacyBehavior?: boolean
  passHref?: boolean
  locale?: string | false
  children?: ReactNode
}

function chuoi(href: DiaChi): string {
  if (typeof href === "string") return href
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(href.query ?? {})) if (v !== undefined) q.set(k, String(v))
  const s = q.toString()
  return `${href.pathname ?? ""}${s ? `?${s}` : ""}${href.hash ? `#${href.hash}` : ""}`
}

const Link = forwardRef<HTMLAnchorElement, LinkProps>(function Link(
  { href, prefetch: _p, replace, scroll: _s, shallow: _sh, legacyBehavior: _l, passHref: _ph, locale: _lo, ...rest },
  ref
) {
  const to = chuoi(href)
  if (/^([a-z]+:|\/\/|#)/i.test(to)) return <a ref={ref} href={to} {...rest} />
  return <RRLink ref={ref} to={to} replace={replace} {...rest} />
})

export default Link
