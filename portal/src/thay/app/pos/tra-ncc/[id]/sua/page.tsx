"use client"

/**
 * [Portal Frappe] MÀN 12 — SỬA PHIẾU TRẢ NCC: bọc bản nppsale để đi theo id MỚI sau khi sửa phiếu đã xuất (RPC `sua_phieu_tra_ncc` trả tờ amend
 * `PTNCC-0042-1` — CFD-01; lib/purchasing/doi-id.ts). Dựng lại màn theo `key={id}`.
 */
import { useParams } from "next/navigation"
import PosSupplierReturnEditPageGoc from "@goc/app/pos/tra-ncc/[id]/sua/page"
import { useDiTheoIdMoi } from "@/lib/purchasing/doi-id"

export default function PosSupplierReturnEditPage() {
  const { id } = useParams<{ id: string }>()
  useDiTheoIdMoi("supplier_returns", id, "/pos/tra-ncc/{id}/sua")
  return <PosSupplierReturnEditPageGoc key={id} />
}
