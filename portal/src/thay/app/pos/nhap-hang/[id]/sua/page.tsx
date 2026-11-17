"use client"

/**
 * [Portal Frappe] MÀN 10 — SỬA PHIẾU NHẬP: bọc bản nppsale để đi theo id MỚI sau khi sửa phiếu đã hoàn thành chưa xuất (RPC `sua_phieu_nhap` trả tờ
 * amend `PN-0042-1` — CFD-01, đặc tả kho_mua §3.3; lib/purchasing/save-receipt.ts phát sự kiện). Dựng lại màn theo `key={id}`.
 */
import { useParams } from "next/navigation"
import PosPurchaseEditPageGoc from "@goc/app/pos/nhap-hang/[id]/sua/page"
import { useDiTheoIdMoi } from "@/lib/purchasing/doi-id"

export default function PosPurchaseEditPage() {
  const { id } = useParams<{ id: string }>()
  useDiTheoIdMoi("purchase_invoices", id, "/pos/nhap-hang/{id}/sua")
  return <PosPurchaseEditPageGoc key={id} />
}
