/** `next/headers` chỉ chạy ở máy chủ Next — portal không có; trả kho rỗng để biên dịch (mã gọi tới đây phải đã được chuyển). */
export function cookies() {
  return { get: (_n: string) => undefined as { value: string } | undefined, getAll: () => [] as Array<{ name: string; value: string }>, set: () => undefined }
}
export function headers() {
  return new Headers()
}
