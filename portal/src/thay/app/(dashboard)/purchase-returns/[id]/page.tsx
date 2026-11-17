"use client"

/**
 * [Portal Frappe] CHI TIẾT PHIẾU TRẢ NCC: bọc bản nppsale để đi theo id MỚI sau khi khôi phục phiếu đã gửi (RPC trả tờ amend `PTNCC-0042-1` —
 * CFD-01, đặc tả kho_mua §3.9 ⚠K; lib/purchasing/khoi-phuc.ts phát sự kiện). Dựng lại màn theo `key={id}` — lượt `load()` còn dở của id cũ không
 * đè dữ liệu tờ mới.
 */
import { useParams } from "next/navigation"
import PurchaseReturnDetailPageGoc from "@goc/app/(dashboard)/purchase-returns/[id]/page"
import { useDiTheoIdMoi } from "@/lib/purchasing/doi-id"

export default function PurchaseReturnDetailPage() {
  const { id } = useParams<{ id: string }>()
  useDiTheoIdMoi("supplier_returns", id, "/purchase-returns/{id}")
  return <PurchaseReturnDetailPageGoc key={id} />
}
