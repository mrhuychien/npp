/** Thay `next/dynamic`: React.lazy + Suspense, giữ tuỳ chọn `loading`. */
import { lazy, Suspense, type ComponentType, type ReactNode } from "react"

type Nap<P> = () => Promise<{ default: ComponentType<P> } | ComponentType<P>>

export default function dynamic<P = Record<string, unknown>>(nap: Nap<P>, opts?: { ssr?: boolean; loading?: (p: { isLoading?: boolean; error?: unknown }) => ReactNode }) {
  const L = lazy(async () => {
    const m: any = await nap()
    return { default: (m && m.default) || m }
  })
  function DongGoi(props: P) {
    return (
      <Suspense fallback={opts?.loading ? opts.loading({ isLoading: true }) : null}>
        <L {...(props as any)} />
      </Suspense>
    )
  }
  return DongGoi as ComponentType<P>
}
