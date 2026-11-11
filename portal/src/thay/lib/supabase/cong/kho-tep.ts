/**
 * `supabase.storage` tối thiểu: ảnh điểm bán lưu thành File RIÊNG TƯ của Frappe qua method `nppsale.api.tep.tai_len`.
 * `getPublicUrl` giữ đúng khuôn đường dẫn Supabase (`/storage/v1/object/public/<bucket>/<path>`, tính tại chỗ không gọi mạng) để
 * `photoStoragePath` / luật FILE_SAI của nppsale chạy nguyên; máy chủ phục vụ đường ấy SAU khi kiểm đăng nhập + thấy được khách
 * (nppsale/portal/kho_anh.py) — ảnh không còn mở được bằng link trần như bucket public cũ.
 * `remove` từ trình duyệt không xoá gì (như nppsale sau mig 207); xoá file đi qua /api/customers/photo-cleanup.
 */
import { csrfHienTai } from "./phien"

function kho(bucket: string) {
  return {
    async upload(path: string, file: Blob | File, opts?: { upsert?: boolean; contentType?: string; cacheControl?: string }) {
      const fd = new FormData()
      fd.append("bucket", bucket)
      fd.append("path", path)
      fd.append("upsert", opts?.upsert ? "1" : "0")
      fd.append("file", file, (file as File).name ?? path.split("/").pop() ?? "tep")
      const res = await fetch("/api/method/nppsale.api.tep.tai_len", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Frappe-CSRF-Token": csrfHienTai(), Accept: "application/json" },
        body: fd,
      }).catch((e) => e as Error)
      if (res instanceof Error) return { data: null, error: { message: `${res.name}: ${res.message}` } }
      const body = await res.json().catch(() => ({}))
      if (!res.ok || body?.message?.error) return { data: null, error: { message: body?.message?.error?.message ?? "Tải ảnh lên hỏng" } }
      return { data: { path, id: body?.message?.data?.id ?? path, fullPath: `${bucket}/${path}` }, error: null }
    },
    getPublicUrl(path: string) {
      const duong = path.split("/").map(encodeURIComponent).join("/")
      return { data: { publicUrl: `/storage/v1/object/public/${bucket}/${duong}` } }
    },
    async remove(_paths: string[]) {
      return { data: [] as Array<{ name: string }>, error: null }
    },
  }
}

export const storage = { from: kho }
