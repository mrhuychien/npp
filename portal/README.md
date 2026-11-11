# portal — giao diện nppsale chạy trên Frappe

Giao diện React của nppsale (Next.js) chạy dưới `/nppsale` của site Frappe, dữ liệu đi qua cổng tương thích của app
(`/rest/v1/<bảng>`, `/rest/v1/rpc/<hàm>` — `nppsale/portal/rest.py`, `nppsale/cong`). Quyết định: `docs/chuyen-doi/blueprint/00_quyet_dinh_trien_khai.md` (Q1, Q4).

## Cấu trúc

| Đường dẫn | Nội dung |
|---|---|
| `nguon.json` | Repo + commit ghim của nppsale. Đổi `ref` = cập nhật giao diện. |
| `nguon/` | **Không commit.** `src/ public/ tests/ tailwind.config.ts components.json` của commit ghim (`scripts/lay-nguon.mjs`). |
| `src/thay/` | Lớp phủ — cùng đường dẫn tương đối với `nguon/src`. `@/x` tìm ở `src/thay/x` trước rồi mới tới `nguon/src/x`; `@goc/x` luôn là bản nppsale. |
| `src/khung/` | Điểm vào (`main.tsx`), khung gốc, bọc trang, lớp thay `next/*`, tiền tố `/nppsale` (`duong.ts`, `cua-so.ts`), route `/api` cũ (`api-cu.ts`). |
| `scripts/tao-route.mjs` | Sinh `src/khung/routes.generated.tsx` (không commit) từ thư mục `app` của nppsale + lớp phủ. |
| `vite.config.ts` | Bí danh + plugin lớp phủ; build ra `../nppsale/public/portal/app` (Frappe phục vụ `/assets/nppsale/portal/app/`). |

Lớp phủ hiện có: `lib/supabase/client.ts` + `lib/supabase/cong/*` (client dữ liệu cùng giao diện supabase-js), `lib/auth/ho-so-may-chu.ts`
(hồ sơ đi kèm vỏ trang), `app/page.tsx`, `app/(dashboard)/layout.tsx`, `app/pos/layout.tsx` (bản nppsale là server component),
`components/offline/sw-register.tsx` (phạm vi `/nppsale/`), `lib/nav/pos-preview.ts` (bỏ tiền tố trước khi nhận lối POS).

## Lệnh

```bash
NPPSALE_SRC=/đường/dẫn/repo/nppsale npm run build   # lấy nguon (nếu chưa có) → sinh route → vite build
npm run typecheck                                    # tsc trên toàn bộ mã nppsale + lớp phủ
npm test                                             # test của portal (tests/)
cd nguon && npx vitest run --config ../vitest.nguon.config.ts   # bộ test của nppsale trên nền portal
```

Không đặt `NPPSALE_SRC` thì `lay-nguon.mjs` clone repo trong `nguon.json` — máy build cần quyền đọc repo nppsale.
`bench build --app nppsale` gọi `yarn build` ở gốc app → `cd portal && npm run build`.

Máy chủ cần nhận URL dài (đọc là GET `?q=<JSON>`): nginx `large_client_header_buffers 4 32k;`.

## Mốc test (11/11/2026, nppsale 58158b1)

- `tsc --noEmit`: 0 lỗi.
- Test portal: 12/12.
- Bộ test nppsale trên nền portal: 3.836 / 3.898 ca xanh. 44 ca đỏ + các tệp không nạp được đều do test đọc tệp ngoài `src/`
  (`supabase/migrations/*.sql`, `CLAUDE.md`, `vercel.json`, `scripts/`, `e2e/`) hoặc dùng `@supabase/postgrest-js` thật, và
  `ho-so-gui-kem.test.ts` (kiểm bản server của `layHoSoMayChu` — lớp phủ đọc vỏ trang). Luật trong các tệp SQL ấy được chuyển
  thành test Python của app khi viết RPC tương ứng.
