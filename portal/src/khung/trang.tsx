/** Bọc trang của nppsale: truyền props `params` / `searchParams` như Next App Router, Suspense theo loading.tsx gần nhất. */
import { Suspense, type ComponentType, type ReactNode } from "react"
import { useParams, useSearchParams } from "./next/navigation"

export function Trang({ C, cho }: { C: ComponentType<any>; cho?: ReactNode }) {
  const params = useParams()
  const sp = useSearchParams()
  const searchParams: Record<string, string | string[]> = {}
  for (const k of new Set(sp.keys())) {
    const ds = sp.getAll(k)
    searchParams[k] = ds.length > 1 ? ds : ds[0]
  }
  return (
    <Suspense fallback={cho ?? null}>
      <C params={params} searchParams={searchParams} />
    </Suspense>
  )
}
