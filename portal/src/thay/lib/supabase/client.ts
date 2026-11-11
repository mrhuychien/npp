/**
 * Client dữ liệu của portal — cùng tên hàm với nppsale (`createClient()`), nhưng đi qua cổng tương thích trên Frappe
 * (portal/src/lib/supabase/cong). Giữ bộ hẹn giờ `fetchCoHetGio` của nppsale (chủ nhà 22/10/2026, 03/11/2026).
 */
import { createClient as taoCong, type SupabaseClient } from "@/lib/supabase/cong"
import { fetchCoHetGio } from "@/lib/supabase/fetch-het-gio"

let motBan: SupabaseClient | null = null

export function createClient(): SupabaseClient {
  // Một bản cho cả trang: nppsale gọi createClient() ở hàng trăm chỗ — mỗi bản cũ chỉ là cấu hình, ở đây cũng vậy.
  if (!motBan) motBan = taoCong(undefined, undefined, { global: { fetch: fetchCoHetGio } })
  return motBan
}
