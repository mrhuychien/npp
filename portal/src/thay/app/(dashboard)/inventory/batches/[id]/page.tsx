"use client"

/**
 * [Portal Frappe] CHI TIẾT LÔ: bọc bản nppsale để đi theo id MỚI sau khi sửa (đặc tả kho_mua §4.6 — P4 M5): id dòng lô của cổng là `<mã lô>::<vùng>`,
 * đổi mã lô / sửa hạn vào ngưỡng kho date làm id đổi (nppsale giữ uuid). lib/db/must-write.ts phát dòng trả về của lời ghi; dựng lại màn gốc theo
 * `key={id}` — lượt tải còn dở của id cũ không đè dữ liệu dòng mới.
 */
import { useParams } from "next/navigation"
import BatchDetailPageGoc from "@goc/app/(dashboard)/inventory/batches/[id]/page"
import { useDiTheoLoMoi } from "@/lib/inventory/doi-id-lo"

export default function BatchDetailPage() {
  const { id } = useParams<{ id: string }>()
  useDiTheoLoMoi(id)
  return <BatchDetailPageGoc key={id} />
}
