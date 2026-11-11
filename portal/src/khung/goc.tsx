/**
 * Khung gốc thay src/app/layout.tsx của nppsale (layout ấy tự vẽ <html>/<body> — ở portal phần vỏ HTML do Frappe dựng:
 * nppsale/www/nppsale/index.html mang metadata, viewport, manifest, font). Giữ đúng các thành phần cấp gốc của nppsale.
 */
import { Suspense } from "react"
import { Outlet, ScrollRestoration } from "react-router-dom"
import "@/app/globals.css"
import { Toaster } from "@/components/ui/toaster"
import { AuthProvider } from "@/hooks/use-auth"
import { ServiceWorkerRegister } from "@/components/offline/sw-register"
import { GhiKhoMan } from "@/components/nav/ghi-kho-man"

export default function Goc() {
  return (
    <AuthProvider>
      <Suspense fallback={null}>
        <Outlet />
      </Suspense>
      <Toaster />
      <ServiceWorkerRegister />
      <GhiKhoMan />
      <ScrollRestoration />
    </AuthProvider>
  )
}
