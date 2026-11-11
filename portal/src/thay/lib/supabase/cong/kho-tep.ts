/**
 * `supabase.storage` tối thiểu: ảnh điểm bán / ảnh POD lưu thành File riêng tư của Frappe qua method của app
 * (`nppsale.api.tep.*`, mục 7 bản bàn bạc). Đường xem là method có kiểm quyền, không phải URL công khai.
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
      const q = new URLSearchParams({ bucket, path })
      return { data: { publicUrl: `/api/method/nppsale.api.tep.xem?${q.toString()}` } }
    },
    async remove(paths: string[]) {
      const res = await fetch("/api/method/nppsale.api.tep.xoa", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-Frappe-CSRF-Token": csrfHienTai(), Accept: "application/json" },
        body: JSON.stringify({ bucket, paths }),
      }).catch((e) => e as Error)
      if (res instanceof Error) return { data: null, error: { message: `${res.name}: ${res.message}` } }
      const body = await res.json().catch(() => ({}))
      return body?.message?.error ? { data: null, error: body.message.error } : { data: paths.map((p) => ({ name: p })), error: null }
    },
  }
}

export const storage = { from: kho }
