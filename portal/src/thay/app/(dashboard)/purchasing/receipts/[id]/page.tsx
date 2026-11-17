"use client"

/**
 * [Portal Frappe] CHI TIẾT PHIẾU NHẬP: bọc bản nppsale để đi theo id MỚI sau khi khôi phục phiếu đã hoàn thành (RPC `khoi_phuc_phieu_nhap` trả
 * tờ amend `PN-0042-1` — CFD-01, đặc tả kho_mua §3.4; lib/purchasing/khoi-phuc.ts phát sự kiện). Dựng lại màn theo `key={id}`.
 */
import { useParams } from "next/navigation"
import ReceiptDetailPageGoc from "@goc/app/(dashboard)/purchasing/receipts/[id]/page"
import { useDiTheoIdMoi } from "@/lib/purchasing/doi-id"

export default function ReceiptDetailPage() {
  const { id } = useParams<{ id: string }>()
  useDiTheoIdMoi("purchase_invoices", id, "/purchasing/receipts/{id}")
  return <ReceiptDetailPageGoc key={id} />
}
