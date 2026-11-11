import { redirect } from "next/navigation"
import { layHoSoMayChu } from "@/lib/auth/ho-so-may-chu"
import { trangGoc } from "@/lib/nav/trang-dau"

export default function Home() {
  // Portal Frappe: phiên + vai đi kèm vỏ trang (window.NPP_CONTEXT), không hỏi mạng.
  const phien = layHoSoMayChu()
  if (phien) {
    // Nhân viên về Trang chủ, khối văn phòng về Tổng quan (chủ nhà 26/09/2026).
    redirect(trangGoc(phien.hoSo?.role))
  } else {
    redirect("/login")
  }
}
