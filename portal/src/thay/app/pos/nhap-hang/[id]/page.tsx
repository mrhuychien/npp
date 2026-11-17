"use client"

/**
 * [Portal Frappe] MÀN 9 — PHIẾU NHẬP HÀNG: bọc bản nppsale để đi theo id MỚI sau khi sửa phiếu đã hoàn thành chưa xuất (RPC `sua_phieu_nhap` trả tờ
 * amend `PN-0042-1` — CFD-01, đặc tả kho_mua §3.3; lib/purchasing/save-receipt.ts phát sự kiện). Dựng lại màn theo `key={id}`.
 */
import { useParams } from "next/navigation"
import PosPurchasePageGoc from "@goc/app/pos/nhap-hang/[id]/page"
import { useDiTheoIdMoi } from "@/lib/purchasing/doi-id"

export default function PosPurchasePage() {
  const { id } = useParams<{ id: string }>()
  useDiTheoIdMoi("purchase_invoices", id, "/pos/nhap-hang/{id}")
  return <PosPurchasePageGoc key={id} />
}
