/**
 * [Portal Frappe] Khung /pos — như bản nppsale (các provider POS + PosShell), chỉ khác chỗ lấy hồ sơ: đọc đồng bộ từ vỏ trang
 * thay cho server component đọc cookie.
 */
import type { ReactNode } from "react"
import { NapHoSo } from "@/hooks/use-auth"
import { layHoSoMayChu } from "@/lib/auth/ho-so-may-chu"
import { PosShell } from "@/components/pos/pos-shell"
import { PosTabsProvider } from "@/store/pos/tabs"
import { PosSettingsProvider } from "@/store/pos/settings"
import { PosRefDataProvider } from "@/store/pos/ref-data"
import { PosProductSearchProvider } from "@/store/pos/product-search"

export default function PosLayout({ children }: { children: ReactNode }) {
  const phien = layHoSoMayChu()
  return (
    <PosSettingsProvider>
      <NapHoSo hoSo={phien?.hoSo ?? null} />
      <PosRefDataProvider>
        <PosTabsProvider>
          <PosProductSearchProvider>
            <PosShell>{children}</PosShell>
          </PosProductSearchProvider>
        </PosTabsProvider>
      </PosRefDataProvider>
    </PosSettingsProvider>
  )
}
