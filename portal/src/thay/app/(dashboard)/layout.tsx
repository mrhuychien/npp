/**
 * [Portal Frappe] Khung (dashboard) — bản nppsale là server component đọc hồ sơ bằng cookie. Ở đây hồ sơ đã đi kèm vỏ trang
 * (`window.NPP_CONTEXT`, nppsale/www/nppsale/index.py) nên đọc đồng bộ, rồi dựng đúng các thành phần như bản gốc.
 */
import type { ReactNode } from "react"
import { redirect } from "next/navigation"
import { DashboardShell } from "@/components/layout/dashboard-shell"
import { NapHoSo } from "@/hooks/use-auth"
import { layHoSoMayChu } from "@/lib/auth/ho-so-may-chu"
import type { Role } from "@/types"

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const phien = layHoSoMayChu()
  if (!phien) redirect("/login")
  const role = (phien.hoSo?.role ?? "sales") as Role
  return (
    <>
      <NapHoSo hoSo={phien.hoSo} />
      <DashboardShell role={role}>{children}</DashboardShell>
    </>
  )
}
