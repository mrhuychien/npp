"""Cổng tương thích nppsale (quyết định Q1, docs/chuyen-doi/blueprint/00_quyet_dinh_trien_khai.md).

Giao diện React của nppsale gọi dữ liệu bằng cú pháp kiểu PostgREST (`.from(bang).select(...).eq(...)`, `.rpc(ten)`). Cổng này
nhận đúng yêu cầu ấy (lớp `createClient()` ở portal dựng sẵn thành JSON), dịch sang SQL trên bảng ERPNext / DocType của app qua
một sổ đăng ký bảng, kèm vế lọc RLS theo vai — để mã giao diện chạy nguyên.

Các mô-đun thuần (không import frappe, có unit test): `chon` (chuỗi select), `loc` (bộ lọc, biểu thức or), `dang_ky` (khai bảng),
`sql` (dựng câu). Phần chạm sổ: `truy_van`, `ghi`, `api`.
"""
