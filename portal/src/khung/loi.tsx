/** errorElement của route: redirect() / notFound() của Next → chuyển trang / trang 404; lỗi khác → error.tsx gần nhất của nppsale. */
import { type ComponentType } from "react"
import { Navigate, useRouteError } from "react-router-dom"
import { LoiChuyenHuong, LoiKhongThay } from "./next/navigation"

type TrangLoi = ComponentType<{ error: Error & { digest?: string }; reset: () => void }>

export function BoLoi({ Loi, KhongThay }: { Loi?: TrangLoi; KhongThay?: ComponentType }) {
  const e = useRouteError() as any
  if (e instanceof LoiChuyenHuong || e?.message === "NEXT_REDIRECT") return <Navigate to={e.href} replace />
  if (e instanceof LoiKhongThay || e?.message === "NEXT_NOT_FOUND" || e?.status === 404) return KhongThay ? <KhongThay /> : <p className="p-6">Không tìm thấy trang.</p>
  const err = e instanceof Error ? e : new Error(String(e?.statusText ?? e?.message ?? e))
  if (Loi) return <Loi error={err} reset={() => window.location.reload()} />
  return (
    <div className="p-6">
      <p className="font-semibold">Có lỗi khi mở trang.</p>
      <pre className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">{err.message}</pre>
    </div>
  )
}
