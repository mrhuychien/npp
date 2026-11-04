# Chuyển npp.sale → app `npp` trên ERPNext v16 — bản bàn bạc để chốt

Phiên bản 1 · 04/11/2026 · em soạn, anh chốt. Chưa có dòng code nào được viết; tệp này chỉ để **bàn và chốt** trước khi tiến hành.

Tài liệu đi kèm (khảo sát tự động từ mã nguồn nppsale, nhánh `claude/elegant-hamilton-ak996q`, HEAD `58158b1`):
- `khao-sat/01_man_hinh.md` — 180 trang, menu, POS, thư viện component.
- `khao-sat/02_du_lieu.md` — 82 bảng, 74 RPC công khai, trigger, RLS, đánh số chứng từ, quy ước tiền / đơn vị.
- `khao-sat/03_nghiep_vu.md` — luật nghiệp vụ ngoài `CLAUDE.md` (máy trạng thái, công thức, mã lỗi).

---

## 0. Đọc trong hai phút

**nppsale hôm nay.** 177.000 dòng TypeScript, 180 trang (≈160 màn thật, 12 màn luồng cũ đã chặn), 228 component, 82 bảng Postgres, 74 RPC công khai + ~160 hàm phụ / trigger, 260 migration. Luật nghiệp vụ đã chốt nằm ở `CLAUDE.md` của nppsale và ~140 khối "VÌ SAO" trong migration. Hệ thống đang chạy thật cho một NPP.

**Em đề xuất.**
1. **ERPNext giữ sổ**: Item / Customer / Supplier / Warehouse / Batch / Sales Order / Sales Invoice (có trừ kho) / Payment Entry / Purchase Invoice (có nhập kho) / Stock Entry / Stock Reconciliation. Đây là phần nppsale tự viết bằng 234 hàm SQL; ERPNext đã có sẵn, có kiểm toán và sổ cái.
2. **App `npp` bọc luật nppsale**: ~25 DocType riêng (phiếu trả, tuyến, phân công khách, ảnh điểm bán, bàn giao, soạn hàng, lương, HĐĐT MISA, ma trận quyền…), Custom Field trên DocType lõi, và **mọi thao tác tiền / kho / trạng thái đi qua whitelisted method Python** (đúng luật "không ghi thẳng từ trình duyệt" của nppsale, đúng kiểu NPP của bộ skill nextcode).
3. **Giao diện bê nguyên mã React/Tailwind/shadcn** của nppsale thành một SPA chạy ngoài Desk tại `/<tiền tố>/…`, giữ nguyên từng đường dẫn, phím tắt POS, máy quét, in A5, Excel, offline. Chỉ thay tầng dữ liệu (Supabase → `frappe.call`). **Không** viết lại tay 160 màn bằng vanilla JS.

**Chỗ lõi ERPNext buộc khác** (mục 5, cần anh duyệt từng mục): 8 mục — sửa chứng từ đã ghi sổ thành tờ mới đuôi `-1`, trường sửa được sau ghi sổ phải khai trước, phiếu trả "Chờ xử lý" là hai chứng từ lõi dưới một phiếu, tiền thu dư nằm ở phiếu thu, bán âm phải âm trên một lô cụ thể, sửa phiếu nhập đã bán khi đang tắt tồn âm, giá vốn tính lại chạy nền, quyền hai lớp + mỗi NPP một site.

**13 câu hỏi** ở mục 10, mỗi câu có đề xuất sẵn để anh chỉ cần "đồng ý" hoặc sửa.

**Sau khi anh chốt**: em dựng PoC một tuần (bench v16 + khung app + đo thật nút Xuất hàng với lô) → viết 6 tệp blueprint theo `nextcode-design` (duyệt từng tệp) → build theo giai đoạn ở mục 9.

---

## 1. Hiện trạng: mảng nào còn sống, mảng nào di sản

| Mảng | Màn | Trạng thái ở nppsale | Hướng khi sang ERPNext |
|---|---|---|---|
| POS máy tính (`/pos/*`: đơn, xuất hàng / HĐ, phiếu trả, nhập hàng, trả NCC) | 11 | Lõi, dùng hằng ngày | Bê nguyên |
| Bán hàng điện thoại (`/sell/*`) | 10 | Lõi (NVBH) | Bê nguyên |
| Đơn hàng, Hoá đơn bán, Trả hàng | 13 | Lõi | Bê nguyên; dưới là SO / SI / credit note |
| Công nợ, Phiếu thu, Phiếu chi, Nợ đầu kỳ | 14 | Lõi | Payment Entry + sổ cái; màn giữ nguyên |
| Khách hàng (tuyến, PJP, ghé thăm, ảnh + GPS + duyệt, bàn giao, hàng đã lấy, lọc trùng SĐT) | 9 | Lõi, nhiều luật riêng | DocType riêng + Customer |
| Sản phẩm (đơn vị, bảng giá, mã vạch, nhập Excel) | 2 | Lõi | Item + UOM + Item Price |
| Kho (lô / date, phiếu kho, kiểm kê, thẻ kho, soạn hàng, tra soát) | 15 (+5 chặn) | Lõi | Batch + Stock Entry + Stock Reconciliation; soạn hàng riêng |
| Mua hàng (phiếu nhập, trả NCC, công nợ NCC, phiếu chi NCC, bảng giá nhập, đề xuất đặt) | 18 | Lõi | Purchase Invoice (± return) + Payment Entry |
| HĐĐT MISA (`/invoices`, đối soát, cấu hình) | 5 + 1 | Lõi (kế toán) | DocType riêng + Python theo skill `einvoice-misa-sync` |
| Báo cáo tổng hợp 6 màn + Tổng quan + trang chủ NVBH | 8 | Lõi | Bê nguyên; nguồn dòng thô = method Python |
| Báo cáo cũ `/reports/*` (14) + Phân tích `/analytics/*` (9) | 23 | Chạy song song, chủ nhà từng nói "chỉ gỡ khi màn mới dùng ổn" | **Hỏi anh** (câu 6) |
| Nhân sự / lương (chấm công, cấu hình, bảng lương, phiếu lương của tôi) | 9 | Dùng; lương đang tính theo ĐƠN (trái luật doanh thu theo HĐ) | Port riêng, sửa luôn nguồn doanh thu (câu 7) |
| Khuyến mãi | 3 | Chỉ là danh mục, POS không áp | **Hỏi anh** (câu 6) |
| Hoa hồng | 4 | Chỉ cấu hình, chưa có máy tính / chi | **Hỏi anh** (câu 6) |
| Người dùng, phân quyền, QR đăng nhập, tổ chức, ngưỡng cảnh báo, wizard | 10 | Lõi | User + Role + ma trận riêng |
| Chuyến giao (`/deliveries`, `stock-out`, `pending`) | 5 + | **Đã chặn** (chủ nhà 24/09/2026) | **Bỏ**, không port |
| Đơn mua PO, `workflow_sessions`, `hr_payroll` cũ, `merged_orders`, `cash_collections` | — | Di sản, chỉ tra cứu / không dùng | Bỏ (dữ liệu cũ nằm ở bản lưu trữ) |

Con số đáng nhớ: trình duyệt nppsale gọi Supabase ở **938 chỗ** (`.from(`) trong 306 tệp và **100 chỗ** `.rpc(`. Đó chính là khối lượng thay tầng dữ liệu khi bê giao diện (mục 7).

---

## 2. Ba quyết định lớn — quyết trước, mọi thứ khác theo sau

### 2.1 Mỗi NPP một site ERPNext (đề xuất) hay chung site với công ty anh?

| | A. Mỗi NPP một site (`npp1.local`, `npp2.local`…), cùng một bench, cài app `npp` | B. Một site chung: mỗi NPP là một Company |
|---|---|---|
| Cô lập dữ liệu | Tuyệt đối (khác database) — tương đương `org_id` + RLS hôm nay | Customer / Item / Supplier / User là **danh mục toàn site**; cô lập phải tự làm bằng User Permission ở mọi DocType, rất dễ hở |
| Danh mục hàng | Mỗi NPP tự có hàng của mình (nhiều hãng, như nppsale `user_suppliers`) | Chung — chỉ hợp nếu mọi NPP bán đúng một bộ hàng |
| Sao lưu / khôi phục / nâng cấp | Từng site, `bench backup` sẵn | Một cục |
| Sức máy | Mỗi site nhẹ; bench chia tài nguyên | Một database lớn dần |
| Đổi luật cho một NPP | Chỉnh cài đặt của site đó | Phải phân nhánh theo Company |

**Đề xuất A.** Nếu sau này anh muốn đơn đặt hàng của NPP chảy thẳng vào ERPNext của công ty anh (NPP đặt → Hoàng Giang nhận Sales Order), đó là **tích hợp site-với-site qua API**, không cần nhốt chung một site.

### 2.2 Dùng lõi ERPNext sâu tới đâu?

| | N. "ERPNext thuần": mọi chứng từ là DocType lõi, luật bằng Property Setter + hook | P. "Frappe làm nền": chép 82 bảng thành DocType riêng, lõi chỉ giữ danh mục | **H. Lai (đề xuất)** |
|---|---|---|---|
| Nguyên tắc | Tin lõi, đổi thói quen người dùng theo ERPNext | Tin nppsale, ERPNext chỉ là khung | Lõi giữ **sổ** (kho, công nợ, chứng từ gốc); app giữ **luật và màn** (bọc lõi bằng DocType riêng + method) |
| Giữ nguyên chức năng nppsale | Khó: ~20 luật va lõi (phiếu trả Chờ xử lý, chọn lô theo vùng, sửa phiếu nhập đã bán, quyền từng người…) | Dễ nhất, nhưng mất lý do dùng ERPNext: không sổ cái, không báo cáo kho / công nợ chuẩn, không tích hợp với hệ ERPNext khác | Giữ được ≈ 95%; 8 chỗ còn lại ở mục 5 |
| Khối lượng | Thấp ở backend, cao ở "dạy" người dùng | Cao nhất (viết lại 234 hàm SQL thành Python, không tận dụng gì) | Trung bình: viết lại ~45 RPC nghiệp vụ thành method gọi lõi; ~30 RPC kho / công nợ **biến mất** vì lõi đã làm |
| Hiệu năng | Lõi ghi sổ cái + sổ kho + bundle lô: nặng hơn RPC thuần | Nhẹ | Như N ở chứng từ lõi (đo ở PoC) |
| Về sau | Nâng cấp ERPNext dễ | Nâng cấp dễ (ít đụng lõi) nhưng tự gánh mọi báo cáo | Nâng cấp vừa; phần bọc phải theo dõi thay đổi lõi |

**Đề xuất H.** Ranh giới cụ thể ở mục 3 và 4: cái gì là lõi, cái gì là DocType riêng.

### 2.3 Giao diện: dùng lại mã React hay viết lại vanilla theo "kiểu NPP"?

| | **R. Dùng lại mã React (đề xuất)** | V. Viết lại vanilla JS no-build theo `frappe-portal-spa` |
|---|---|---|
| Cách làm | Tách `src/` của nppsale thành một ứng dụng Vite + React Router; thay `createClient()` Supabase bằng một lớp `goi()` → `frappe.call`; bỏ phần riêng của Next (middleware, route handler, `next/*`); build ra `public/<tiền tố>/` với tên tệp băm; một www page phục vụ `index.html` + bơm `NPP_CONTEXT` | Dựng lại 160 màn + 228 component bằng template literal, CSS prefix, hash router |
| Giống nppsale | Pixel-giống; giữ `design-ux-ui`, phím tắt, máy quét, in A5, Excel, offline, 389 tệp unit test, 157 tệp e2e (đổi sổ giả) | "Gần giống" — mỗi màn là một lần dịch lại, lệch dần |
| Khối lượng | ~1 phần: viết lớp dữ liệu + sửa 306 tệp có truy vấn, bỏ `next/*` ở 171 tệp | ~3–4 phần |
| Rủi ro | Build step (Vite) trong vòng đời app Frappe — em xử lý bằng cách **commit sản phẩm build** vào repo, `bench build` không phải biết tới Vite | Rất nhiều chi tiết nhỏ (camera, bảng dòng POS, tab POS) phải làm lại, khó kiểm hết |
| Bẫy cache `/assets` 1 năm | Không có: tên tệp băm thay đổi theo nội dung, không cần import map | Phải import map + build marker (luật vàng #1, #2) |
| Đúng "kiểu NPP" | Khác house style ở tầng trình duyệt (React thay vì vanilla), **giống** ở tầng backend (Python whitelisted, fixtures, guard) | Đúng hoàn toàn |

**Đề xuất R.** Lý do chính: cái quý nhất của nppsale là 7 tháng mài giao diện theo lời anh (POS tab mới, quét mã, phiếu trả, lọc trùng khách…). Viết lại là ném đi phần đó rồi mài lại từ đầu.

---

## 3. Kiến trúc đích (theo A + H + R)

### 3.1 Sơ đồ

```
Trình duyệt (điện thoại / máy tính)
  SPA React (mã nppsale)  ──  /api/method/npp.sale.api.*  ──►  app npp (Python)
                                                             │  guard quyền (ma trận NPP + vai)
                                                             │  luật nppsale (giá, giảm giá, hệ số, phiếu trả, …)
                                                             ▼
                                                   DocType lõi ERPNext      DocType riêng NPP
                                                   SO · SI · PE · PI · SE   Phiếu trả · Tuyến · Phân công ·
                                                   SR · Batch · Item · …    Ảnh điểm bán · Soạn hàng · Lương · …
                                                             ▼
                                                   MariaDB + sổ kho (SLE) + sổ cái (GL)
```

### 3.2 Backend — năm nguyên tắc (theo `frappe-app-build-profile`)
1. **Một màn một lượt gọi**: mỗi màn / khối có một method trả đủ dữ liệu (như `bao_cao_so_ban`, `goiMotLuot` hôm nay). Hết cảnh 10–90 câu PostgREST một màn.
2. **Ghi chỉ qua method**: trình duyệt không bao giờ `frappe.client.save` lên chứng từ; vai NPP **không có quyền ghi / ghi sổ** trên SI / PI / PE / SE ở lớp Frappe, method tự kiểm rồi `ignore_permissions` (gotcha #9) — đúng tinh thần mig 170 / 214.
3. **Luật ở máy chủ, trình duyệt chỉ tính để hiện**: giá bảng theo đơn vị, trần / sàn giá, trần giảm giá theo người, hệ số quy đổi tờ cũ, thuế theo dòng, làm tròn — chép từ các RPC / trigger sang Python (`npp/sale/luat/*.py`, thuần, có unit test, không import frappe).
4. **Idempotent**: `client_request_id` (đơn offline), `client_key` (phiếu thu) là Custom Field duy nhất; gửi lại trả bản đã có (giữ `kiemLaiSauLoiXuat`).
5. **Không Server Script / Client Script rải**; fixtures export, fieldname ASCII; `py_compile` + `validate_shipped_docs.py` trước mỗi lần cài.

### 3.3 DocType riêng (dự kiến ~25; chốt chi tiết ở blueprint)

| Nhóm | DocType | Thay cho bảng nppsale |
|---|---|---|
| Cài đặt | `NPP Cai Dat` (Single): bán vượt tồn, ngày tự chuyển kho date, ngưỡng cảnh báo đơn, số ngày sửa đơn, đầu trang in… | `organizations.settings`, `pricing_rules`, `approval_rules` |
| Người dùng | `NPP Nhan Vien` (1–1 User): vai NPP, cờ giảm giá / sửa giá + trần, công ty được làm (child), nghỉ việc, QR token (băm) | `users` (cột riêng), `user_suppliers`, `qr_login_tokens` |
| Quyền | `NPP Quyen Vai` (child: vai × ô × hành động), `NPP Quyen Rieng` (người × ô × hành động) | `role_permissions`, `user_permission_overrides` |
| Khách | `NPP Tuyen`, `NPP Phan Cong Khach`, `NPP Lich Tuyen` (PJP), `NPP Ghe Tham`, `NPP Anh Diem Ban`, `NPP Yeu Cau Anh Diem Ban`, `NPP Ban Giao Khach` (log) | `sales_routes`, `customer_assignments`, `pjp_routes`, `visit_logs`, `customer_photos`, `customer_photo_requests`, `ban_giao_khach_log` |
| Bán | `NPP Phieu Tra` (+ dòng) — **bọc** credit note + phiếu nhập kho; `NPP Luot Soan`; `NPP Khoa Chung Tu` | `returns`, `return_lines`, `luot_soan`, `entity_locks` |
| Tiền | `NPP Phieu Chi` (+ danh mục chi phí → tài khoản chi phí) | `expenses`, `expense_categories` |
| Kho | `NPP Kiem Ke` (đếm → duyệt → Stock Reconciliation) | `stock_entries` type stocktake |
| HĐĐT | `NPP HDDT`, `NPP MISA Cau Hinh` (Single, mật khẩu kiểu Password), `NPP MISA Log`, `NPP MISA Snapshot` | `invoices`, `company_einvoice_config`, `einvoice_logs`, `misa_invoice_snapshots` |
| Nhân sự | `NPP Cham Cong`, `NPP Cau Hinh Luong`, `NPP Bac KPI`, `NPP Thuong So Don`, `NPP Thuong Hoat Dong`, `NPP Ky Luong` (+ dòng) | `hr_*`, `salary_*`, `monthly_activity_bonuses`, `payroll_run*` |
| Khác | `NPP Thong Bao`; `NPP Khuyen Mai`, `NPP Chinh Sach Hoa Hong` (nếu giữ — câu 6) | `notifications`, `promotions`, `commission_*` |
| Lưu trữ | `NPP LS Hoa Don`, `NPP LS Phieu Tra`, `NPP LS Phieu Thu`… (chỉ đọc, nếu chọn phương án dữ liệu H3 — mục 8) | lịch sử trước ngày cắt chuyển |

Tên DocType: tiếng Việt không dấu, tiền tố `NPP ` (câu 12). Fieldname ASCII.

### 3.4 Custom Field trên DocType lõi (ship bằng fixtures)
- **Customer**: tên chủ, SĐT (duy nhất, chuẩn hoá), địa chỉ / tỉnh / quận / phường, tuyến (Link `NPP Tuyen`), hạn mức (của nppsale — không bật hạn mức chặn của ERPNext), điều khoản TT, trạng thái, GPS, ngày duyệt ảnh, thông tin xuất HĐĐT, người tạo.
- **Item**: vị trí kệ, bán trực tiếp, hạn dùng ngày (`shelf_life_in_days` có sẵn), hãng / NCC chính (Item Default), ảnh (có sẵn), mã vạch (child có sẵn, nhiều mã).
- **Sales Order**: `npp_trang_thai` (Nháp / Phiếu tạm / Hoàn thành / Đã huỷ), NV được gán, người tạo, `client_request_id`, lần sửa, lý do cảnh báo.
- **Sales Invoice / Sales Invoice Item**: NV được gán, NV giữ nợ (`giao_tu_nv`), số gốc (`invoice_seq`), lý do huỷ, đã soạn hàng, dòng hàng đổi, ghi chú dòng, mã lỗi MISA.
- **Payment Entry**: người thu, `client_key`, lý do huỷ, nguồn (NVBH / văn phòng).
- **Purchase Invoice**: kho nhận (sale / date), số HĐ đầu vào (có sẵn `bill_no`), lý do huỷ.
- **Batch**: không cần thêm (hạn dùng, ngày sản xuất, NCC có sẵn; vùng = kho).

### 3.5 Vai và quyền
- Role Frappe: `NPP Chu`, `NPP Quan Ly`, `NPP Ke Toan`, `NPP NVBH`, `NPP Thu Kho` (desk_access = 0, không vào Desk).
- Lớp Frappe (DocPerm) = **sàn an toàn**: đọc theo vai; ghi chứng từ tiền / kho **không cấp** cho ai (chỉ method). NVBH thêm **User Permission theo Customer** sinh từ `NPP Phan Cong Khach` → `frappe.get_list` tự lọc như RLS.
- Lớp NPP (ma trận ô × hành động theo vai + ghi đè từng người) = **luật chính**, kiểm ở dòng đầu mỗi method và ở menu / nút của portal. Giữ nguyên `permissions.ts` + `permissions-features.ts` (chạy cùng mã ở hai nơi: TS cho menu, Python cho guard, một bộ test so khớp).

### 3.6 Đăng nhập
- Frappe User, đăng nhập bằng **SĐT + mật khẩu** (`System Settings.allow_login_using_mobile_number` — có sẵn trong v16), email kỹ thuật `<sđt>@<site>` như hôm nay.
- **QR đăng nhập**: method `allow_guest` kiểm token (băm, không hết hạn, xoay / thu hồi) → `login_manager.login_as(user)` → về `/orders`. Quản lý QR chỉ chủ NPP.
- "Đăng nhập thay" của chủ NPP: method guard vai chủ → `login_as`.
- Phiên: cookie `sid` của Frappe + CSRF token bơm vào trang. Tài khoản khoá: `User.enabled = 0` + `left_at` trên `NPP Nhan Vien`.

### 3.7 Portal được phục vụ thế nào
- `www/<tiền tố>/index.html` (+ `index.py` bơm `NPP_CONTEXT`: người dùng, hồ sơ, quyền, cài đặt, CSRF, build) + `website_route_rules` để `/<tiền tố>/sales-invoices/HD-0042` vẫn tới SPA (history routing, **giữ nguyên đường dẫn nppsale**, chỉ thêm tiền tố).
- Tệp JS/CSS do Vite build, tên băm, nằm `public/<tiền tố>/`; `bench build` chỉ sao chép. Không cần import map vì không có tệp trùng tên khác nội dung.
- `sw.js` phục vụ từ `www/` (Frappe phục vụ tệp tĩnh trong `www`), scope `/<tiền tố>/`; luật cache như hôm nay (tĩnh cache-first, trang network-first, không cache `/api`).
- `X-Frame-Options: SAMEORIGIN` là mặc định của Frappe → nút In trong khung ẩn của POS chạy được.
- Tiền tố đường dẫn: app `npp` hiện có đã chiếm `/npp` cho NPP Portal của khách hàng → em đề xuất `/ban-hang` (câu 1).

### 3.8 Những gì giữ y nguyên ở trình duyệt
POS nhiều tab, phím tắt F2–F9, dòng mới lên đầu, khối hàng đổi trả có trần cuộn, thẻ khách / NCC mở sửa tại chỗ, máy quét USB + camera (ZXing đã vá), in A5 trong khung ẩn, Excel (danh sách + "như mẫu in"), giỏ hàng + tab POS trong `localStorage`, hàng đợi đơn offline trong IndexedDB, danh mục nhớ theo số phiên, thanh nav dưới theo vai, đầu trang xanh điện thoại, lọc trùng SĐT trước khi tạo khách, cookie khổ màn để mở thẳng POS.

### 3.9 Việc theo lịch (hooks `scheduler_events`)
01:00 VN mỗi ngày: đồng bộ HĐĐT, nhắc ảnh điểm bán (thứ Hai), nhắc khách chưa tuyến, kéo snapshot MISA; thêm: chuyển lô cận date sang kho date (thay trigger `batches_auto_zone`), nhả khoá chứng từ cũ.

### 3.10 Hiệu năng — nói trước để khỏi bất ngờ
- Nút Xuất hàng trên ERPNext làm nhiều việc hơn RPC của nppsale: ghi sổ kho theo lô, sổ cái, bundle lô, cập nhật đơn. Trên máy 4 vCPU / 8 GB em ước **0,4–1,2 s** một hoá đơn 10–20 dòng (sổ thật của anh đang 1,3 s trên Supabase Micro). Con số thật đo ở PoC — nếu quá 1,5 s em báo trước khi build.
- Danh sách / tìm kiếm: MariaDB `utf8mb4_unicode_ci` tự so không dấu → bỏ được cả cơ chế `tim_kd` (mig 177 / 205 / 249).
- Báo cáo: một method = một lượt mạng; JIT / RLS không còn là vấn đề.

---

## 4. Bảng ánh xạ nghiệp vụ

Ký hiệu: ✅ giữ nguyên luật và cảm nhận người dùng · ≈ khác nhẹ (mục 6, em tự xử lý) · ⚠ lõi buộc khác (mục 5, cần anh duyệt).

### 4.1 Danh mục
| nppsale | ERPNext / app npp | Mức |
|---|---|---|
| `organizations` (+ settings, allow_oversell, completed_edit_days) | Company + `NPP Cai Dat`; bán vượt tồn = Stock Settings `allow_negative_stock` + `allow_negative_stock_for_batch` | ✅ |
| `users` (vai, cờ giảm giá / sửa giá, nghỉ việc, QR) | User + Role NPP + `NPP Nhan Vien` | ✅ |
| `role_permissions`, `user_permission_overrides` | `NPP Quyen Vai`, `NPP Quyen Rieng` + DocPerm sàn | ⚠ CFD-08 |
| `customers` | Customer + Custom Field; SĐT duy nhất; lọc trùng SĐT đúng số (`search_customer_dupes`) = method | ✅ |
| `customer_groups` | Customer Group, mỗi nhóm một Price List mặc định | ✅ |
| `customer_assignments`, `claim_customer_for_me`, `giao_cong_no_npp` | `NPP Phan Cong Khach` + User Permission (Customer) tự sinh; method nhận khách / giao nợ | ✅ |
| `sales_routes`, `pjp_routes`, `visit_logs` (Haversine 100 m / 500 m) | `NPP Tuyen`, `NPP Lich Tuyen`, `NPP Ghe Tham` | ✅ |
| `customer_photos`, `customer_photo_requests`, duyệt ảnh + vị trí (mig 244), nén 1024 px | `NPP Anh Diem Ban` + File riêng tư, `NPP Yeu Cau Anh Diem Ban`; xoá file qua method (như `/api/customers/photo-cleanup`) | ✅ |
| `ban_giao_khach` (chung / chuyển hẳn, mốc 3/6/12 tháng), `hang_khach_da_lay` | method + `NPP Ban Giao Khach`; dấu `giao_tu_nv` là Custom Field trên SI | ✅ |
| `products` (sku, barcode, base_unit, vat_rate, shelf_life, NCC chính, kệ, ảnh) | Item (`item_code` = SKU, `stock_uom` = đơn vị cơ sở, `has_batch_no` + `has_expiry_date`, Item Barcode, Brand, Item Default supplier, Item Tax Template theo thuế suất) | ✅ |
| `product_units` (hệ số nguyên) | UOM + UOM Conversion Detail (số thực — cho phép lẻ) | ✅ |
| `price_lists` (4 bậc tra giá, giá theo ĐÚNG đơn vị, nhóm NULL = chung) | Price List "Giá chuẩn" + "Giá nhóm X"; Item Price theo UOM; **bộ tra giá 4 bậc viết trong app** (không dùng `get_item_details` / Pricing Rule của lõi, `ignore_pricing_rule = 1`) | ✅ |
| `purchase_price_lists` (một giá / mặt hàng / đơn vị, cập nhật từ phiếu nhập) | Price List "Giá nhập" (buying) + hook sau khi ghi sổ PI | ✅ |
| `suppliers` (gộp, xoá kèm hàng) | Supplier + Custom Field; gộp = rename-merge của Frappe; xoá kèm hàng = method | ✅ |
| `user_suppliers` (NVBH chỉ thấy hàng công ty mình) | child trên `NPP Nhan Vien` + lọc ở method danh mục | ✅ |
| `expense_categories` | tài khoản chi phí (Account) + nhóm bucket | ≈ |
| `approval_rules`, `pricing_rules.date_warehouse_threshold_days` | `NPP Cai Dat` | ✅ |
| `danh_muc_ban_phien` (số phiên danh mục cho máy NVBH) | hook `on_update` Item / Item Price / Customer / … tăng số phiên trong `NPP Cai Dat` | ✅ |

### 4.2 Bán hàng
| nppsale | ERPNext / app npp | Mức |
|---|---|---|
| `sales_orders` Nháp → Phiếu tạm (sửa thoải mái) → Hoàn thành / Đã huỷ; nháp chỉ người tạo thấy; NVBH sửa đơn của mình | Sales Order **giữ docstatus 0** suốt Nháp / Phiếu tạm (`npp_trang_thai`), **ghi sổ đúng lúc Xuất hàng** rồi Hoàn thành; huỷ = docstatus 2. Nháp lọc theo người ở method | ✅ (mã đơn: ≈) |
| Mã `DH-0001`, sửa lần n → `DH-0001-n` (đổi tại chỗ) | naming series `DH-.####`; sửa nháp không đổi tên → hiện "sửa lần n" bằng cột riêng | ≈ |
| `create_order_with_lines` (idempotent, trigger trần giá / giảm giá) | method `tao_don` + luật thuần Python (giá bảng, trần / sàn, trần giảm theo người) | ✅ |
| Hạn mức: nợ sẵn có + đơn này so `credit_limit`, **chỉ cảnh báo** | giữ ở method (không bật hạn mức chặn của ERPNext) | ✅ |
| Tồn khả dụng = kho bán − đã đặt (Phiếu tạm) | method tính từ Bin kho bán − dòng SO Phiếu tạm | ✅ |
| `post_invoice` — **Xuất hàng**: trừ kho FIFO kho bán, HĐ, công nợ, phiếu trả kèm, đơn Hoàn thành, một giao dịch; xuất thiếu = xong; một đơn một HĐ | method `xuat_hang`: ghi sổ SO → tạo Sales Invoice `update_stock = 1` từ kho bán, chọn lô FIFO trong app (`use_serial_batch_fields`), credit note cho hàng trả kèm, đóng SO (Closed) = Hoàn thành, chặn HĐ thứ hai; một request = một giao dịch | ✅ (phần vượt số đặt: ≈) |
| `sales_invoices` posted / cancelled, `HD-0001`, sửa → `HD-0001-1` | Sales Invoice docstatus 1 / 2; amend tạo đúng `HD-0001-1` | ✅ |
| Dòng HĐ: `unit_price` sau giảm, `line_discount` ghi nhớ, `conversion_factor` chụp, `vat_rate` chụp, `is_exchange` | Sales Invoice Item: `price_list_rate` = giá bảng, `discount_amount`, `rate`, `uom` + `conversion_factor`, Item Tax Template; cờ hàng đổi | ✅ |
| Thuế theo dòng, giảm giá cả đơn **sau** thuế, làm tròn ở tổng | Sales Taxes template "VAT theo mặt hàng" (On Net Total, thuế suất theo Item Tax Template), `apply_discount_on = Grand Total`, `rounded_total` | ✅ (so số ở PoC: ≈) |
| `invoice_date` DATE giờ VN; hạn nợ = ngày + NETn | `posting_date` (+ `set_posting_time`), Payment Terms Template COD / NET7…60 → `due_date` | ✅ |
| **Sửa HĐ** (`reissue_invoice`): huỷ + lập lại, giữ số gốc đuôi `-n`, phiếu thu đi theo, giữ hệ số tờ cũ, hỏi "huỷ phiếu nhập trước?" | method `sua_hoa_don`: huỷ credit note kèm → huỷ SI (gỡ tham chiếu phiếu thu — cài đặt `unlink_payment_on_cancellation_of_invoice`) → amend (chép hệ số tờ cũ) → ghi sổ → lập lại credit note → **phân bổ lại** tiền phiếu thu sang tờ mới (Payment Reconciliation, số phiếu thu không đổi) | ⚠ CFD-01, CFD-04 |
| **Huỷ HĐ** → hoàn kho đúng lô, xoá nợ, đơn Đã huỷ, phiếu trả Nháp / Chờ xử lý huỷ; khoá khi có tiền thu / đã phát hành HĐĐT | huỷ credit note → huỷ SI (lõi tự trả kho về đúng lô) → mở khoá + huỷ SO; khoá tiền thu / HĐĐT kiểm ở method | ✅ |
| `assign_doc_seller` (đổi người đứng tên HĐ / phiếu trả / đơn, nợ đi theo) | Custom Field `allow_on_submit` + method | ⚠ CFD-02 |
| `returns` **tự sinh** (Chờ xử lý: nợ trừ ngay, kho treo) / **tự lập** (hoàn thành = nhập kho + trừ nợ), `hanhDongPhieuTra`, `PT-0001` | `NPP Phieu Tra` (PT-.####) bọc: tự sinh = credit note `update_stock = 0` + `update_outstanding_for_self = 0` (trừ thẳng vào HĐ, kể cả thành âm) ngay lúc xuất; nhập kho sau = Stock Entry Material Receipt vào kho chọn, huỷ nhập = huỷ SE (về Chờ xử lý). Tự lập = credit note `update_stock = 1` (một tờ, nhập kho + trừ nợ), gắn HĐ hoặc độc lập (dư có) | ⚠ CFD-03 |
| Hàng đổi (xuất 0đ, nhập lại không tính tiền) | dòng SI 0đ cờ hàng đổi + Stock Entry nhập lại | ≈ |
| `near_expiry_skipped`, `short_qty` | tính trong method sau khi chọn lô | ✅ / ⚠ CFD-05 |
| `luot_soan` (nhặt tổng → chia rổ A–Z, không trừ kho) | `NPP Luot Soan` + cờ đã soạn trên SI | ✅ |
| `entity_locks` (khoá sửa đồng thời, nhịp 60 s) | `NPP Khoa Chung Tu` + method heartbeat | ✅ |
| `order_activity_log`, `order_status_history` | Frappe Version (track_changes, kể cả child) + `NPP Thong Bao` | ≈ |
| `workflow_sessions` | bỏ (POS / giỏ đã giữ trạng thái ở trình duyệt) | bỏ |

### 4.3 Tiền
| nppsale | ERPNext / app npp | Mức |
|---|---|---|
| `receivables`: một dòng / HĐ ghi sổ; **có thể âm**; `paid > amount` = dư có; trạng thái do trigger | `outstanding_amount` của Sales Invoice (+ credit note âm) + Payment Ledger; dư có = tờ ghi có / tiền chưa phân bổ | ⚠ CFD-04 |
| Nợ của khách = Σ(amount − paid) không kẹp 0; theo NV (`sales_user_id`, `giao_tu_nv`, về NPP khi nghỉ) | Σ outstanding (kể cả âm) theo Customer; Custom Field NV giữ nợ trên SI / tờ đầu kỳ | ✅ |
| Nợ đầu kỳ (Excel, upsert theo id) | Opening Invoice Creation Tool (SI `is_opening = Yes`, giữ mã / ngày / hạn / NV) — Excel giữ nguyên màn | ✅ |
| Tuổi nợ 0 / 1–30 / 31–60 / > 60 (và 5 bậc ở Báo cáo tổng hợp) | method tính từ `due_date` | ✅ |
| `cash_receipts` pending → received → voided; một khách; phân bổ do người chọn; `use_credit`; `client_key`; in TT200 | Payment Entry (Receive): NVBH lập **nháp** (Chờ xác nhận) → kế toán ghi sổ (Đã nhận) → huỷ (lý do); tham chiếu nhiều HĐ; dùng dư có = phân bổ tờ ghi có / tiền thừa; Mode of Payment cash / transfer / ewallet | ✅ (số phiếu: câu 13) |
| Thu vượt số nợ → chặn (`BAD_RECEIVABLE_LINE`) | lõi cũng chặn phân bổ vượt outstanding; phần thừa = tiền chưa phân bổ | ⚠ CFD-04 |
| `payables`, `payables_by_supplier` (gộp − trả − đã TT) | outstanding của Purchase Invoice (+ debit note âm); bảng theo NCC = method | ✅ |
| `supplier_payments` `PCNCC-0001`: trả khoản cũ nhất trước, dư thành trả trước, tự trừ phiếu nhập sau | Payment Entry (Pay) + phân bổ cũ-trước trong method; dư = tiền ứng trước, `allocate_advances_automatically` khi ghi sổ PI mới | ✅ |
| `expenses` (phiếu chi chi phí, trả lúc / chưa trả) | `NPP Phieu Chi` → Journal Entry (tiền ↔ tài khoản chi phí) | ≈ |
| `finance_pnl`, `finance_cash_flow`, `finance_balance_sheet` (kiểu nppsale) | method đọc chứng từ như hôm nay; sổ cái ERPNext **có thêm** báo cáo kế toán chuẩn (câu 9) | ✅ |

### 4.4 Kho và mua hàng
| nppsale | ERPNext / app npp | Mức |
|---|---|---|
| `batches`: lô / hạn dùng, `unit_cost` theo đơn vị cơ sở, vùng sale / date, tự sang date khi gần hạn | Batch (hạn dùng, NSX) + giá vốn theo lô (`use_batchwise_valuation`); hai Warehouse **Kho bán** / **Kho cận date**; việc theo lịch chuyển lô gần hạn | ✅ |
| FIFO theo ngày nhập, chỉ kho bán; trả NCC xuất hạn cũ trước | app tự chọn lô (sắp xếp theo luật từng chứng từ) rồi gán vào dòng | ✅ |
| Bán âm khi bật `allow_oversell`, phần thiếu không gắn lô | `allow_negative_stock` + `allow_negative_stock_for_batch` (v16 có); phần thiếu phải âm trên một lô | ⚠ CFD-05 |
| Giá vốn / COGS theo lô, `stock_line_consumptions` | Stock Ledger Entry + bundle lô (huỷ trả đúng lô) | ✅ |
| `stock_entries` import / export / transfer; draft → posted → cancelled | Stock Entry Material Receipt / Issue / Transfer; docstatus | ✅ |
| Kiểm kê: đếm → chờ duyệt → `post_stock_adjustment` (hụt FEFO, ghi chi phí) / từ chối | `NPP Kiem Ke` → Stock Reconciliation theo lô (chênh vào tài khoản điều chỉnh kho) | ✅ |
| Thẻ kho, tồn kho hiện tại (`ton_kho_trang`), tra soát, `stock_value_summary` | Stock Ledger / Bin + method phân trang | ✅ (hình thức phiếu: ≈) |
| `purchase_invoices` `PN-0001` draft → completed → cancelled; mỗi dòng một lô `PN-xxxx-NNN`; giảm dòng trừ thật; `vat_override`; giảm đầu phiếu sau thuế; nợ NCC | Purchase Invoice `update_stock = 1`, kho nhận theo phiếu, Batch tạo theo dòng (giữ cách đặt mã), `discount_amount` dòng, thuế gõ tay = dòng thuế kiểu Actual, `apply_discount_on = Grand Total`, outstanding = nợ NCC | ✅ |
| `sua_phieu_nhap` (sửa tại chỗ phiếu đã bán, giữ lô, tính lại giá vốn phần đã bán, sửa nợ), huỷ khi bật tồn âm, khôi phục | huỷ + amend (`PN-0042-1`), lô giữ nguyên tên, Repost Item Valuation tính lại giá vốn; khôi phục = amend từ tờ huỷ | ⚠ CFD-01, CFD-06, CFD-07 |
| `supplier_returns` `PTNCC-0001`, FIFO theo hạn, nợ NCC âm, sửa = huỷ rồi gửi lại giữ số | Purchase Invoice `is_return = 1` (debit note) `update_stock = 1`; sửa = huỷ + amend `-1` | ⚠ CFD-01 |
| Bảng giá nhập, đề xuất đặt hàng (Σ đặt chưa xuất − tồn, theo NCC chính) | Price List "Giá nhập"; method đề xuất | ✅ |
| Đơn mua PO (di sản) | bỏ | bỏ |

### 4.5 Khác
| nppsale | ERPNext / app npp | Mức |
|---|---|---|
| HĐĐT MISA (publish / sync / refresh / snapshot / đối soát 4 tầng / khoá sửa HĐ đã phát hành) | DocType riêng + Python theo skill `einvoice-misa-sync` (đã chạy thật trên app `ketoan`) | ✅ |
| Lương (bậc KPI, dưới 60 %, thưởng số đơn, BHXH 10,5 %, khoá kỳ, phiếu lương của tôi, chấm công tay) | DocType riêng, công thức chép từ mig 096 / 173; **nguồn doanh thu đổi sang HĐ − hàng trả** (câu 7) | ✅ (nguồn doanh thu: hỏi) |
| Khuyến mãi, Hoa hồng (chỉ danh mục) | DocType riêng y như cũ, hoặc bỏ | hỏi (câu 6) |
| Thông báo chuông (in-app) | `NPP Thong Bao` (+ có thể dùng Notification Log của Frappe) | ✅ |
| QR đăng nhập, đăng nhập thay, nhân viên nghỉ việc | mục 3.6 + method | ✅ |
| Sao lưu (GitHub Actions → age → Drive) | `bench backup` + Frappe Google Drive Settings | ✅ |
| Bảo trì (rewrite 503 + cookie bỏ qua) | `maintenance_mode` của bench + trang riêng | ≈ |
| Service worker, PWA, offline đơn hàng | giữ nguyên (mục 3.7) | ✅ |
| Chuyến giao | bỏ | bỏ |

---

## 5. Lõi ERPNext buộc phải khác — cần anh duyệt từng mục

### CFD-01 · Sửa chứng từ đã ghi sổ = huỷ tờ cũ + tờ mới có đuôi `-1`, `-2`
- **nppsale**: Hoá đơn bán đã làm đúng thế (`HD-0042-1`, mig 128 / 151). Nhưng **phiếu nhập NCC** sửa tại chỗ giữ `PN-0042` (mig 235), **phiếu trả NCC** "huỷ rồi gửi lại giữ số" (mig 240), **đơn hàng** sửa tại chỗ nhưng đổi mã `DH-0042-1`.
- **ERPNext**: chứng từ đã ghi sổ là bất biến; sửa = Cancel + Amend, tờ mới tên `PN-0042-1`, tờ cũ còn nguyên ở trạng thái Đã huỷ (tra được, không in nhầm).
- **Đề xuất**: áp một luật cho mọi chứng từ ghi sổ: "sửa là ra tờ `-n`, số gốc giữ" (như HĐ bán hôm nay). Đơn hàng (chưa ghi sổ) sửa tại chỗ, **không đổi mã**, hiện thêm "sửa lần n".
- **Người dùng thấy**: phiếu nhập / trả NCC sau khi sửa mang đuôi `-1`; danh sách ẩn tờ đã huỷ theo mặc định (có nút hiện).

### CFD-02 · Trường sửa được sau khi ghi sổ phải khai trước
- **nppsale**: sau khi ghi sổ vẫn đổi được người đứng tên HĐ / phiếu trả (`assign_doc_seller`), ngày phiếu trả hiển thị, ngày nhập kho phiếu tự sinh, ghi chú, cờ soạn hàng, trạng thái HĐĐT.
- **ERPNext**: chỉ trường khai `allow_on_submit` mới ghi được sau ghi sổ (gotcha #7); tiền, kho, ngày ghi sổ, khách hàng thì không.
- **Đề xuất**: khai sẵn nhóm trường "mềm": NV được gán, NV giữ nợ, ghi chú, cờ soạn hàng, các trường MISA, ngày hiển thị của phiếu trả. Còn **ngày ghi sổ, tiền, số lượng, lô, kho**: muốn đổi là huỷ + lập lại (nppsale cũng vậy với tiền / kho; riêng *ngày HĐ* hôm nay sửa qua `reissue_invoice` — vẫn giữ được vì đó là huỷ + lập lại).

### CFD-03 · Phiếu trả "Chờ xử lý" là hai chứng từ lõi dưới một phiếu
- **nppsale**: phiếu tự sinh trừ nợ vào HĐ ngay lúc xuất, kho treo ở Chờ xử lý; hoàn thành = nhập kho; huỷ nhập kho = về Chờ xử lý (mig 191 / 216).
- **ERPNext**: tờ ghi có (credit note) không thể "nhập kho sau": hoặc nhập kho cùng lúc (`update_stock = 1`) hoặc không bao giờ.
- **Đề xuất**: người dùng vẫn chỉ thấy **một** `NPP Phiếu trả PT-0042` với đúng trạng thái; dưới sổ nó là (a) tờ ghi có không kho, trừ thẳng vào HĐ (`update_outstanding_for_self = 0` — có sẵn), lập ngay lúc Xuất hàng; (b) phiếu nhập kho (Stock Entry) khi bấm Hoàn thành, huỷ được để về Chờ xử lý. Phiếu tự lập = một tờ ghi có có kho (nhập kho + trừ nợ cùng lúc, đúng mig 191).
- **Người dùng thấy**: không khác. Kế toán mở sổ cái ERPNext sẽ thấy tờ ghi có mang số riêng (`HDT-0042` chẳng hạn), không phải `PT-`.

### CFD-04 · Tiền thu dư / dư có nằm ở phiếu thu và tờ ghi có, không nằm trên dòng nợ của HĐ
- **nppsale**: `receivables.paid > amount` ngay trên dòng nợ của HĐ là hợp lệ (dư có); sửa HĐ nhỏ hơn số đã thu → `paid > amount` trên dòng mới.
- **ERPNext**: không phân bổ được quá outstanding của một HĐ; phần thừa là **tiền chưa phân bổ** trên Payment Entry (tiền ứng trước của khách), còn hàng trả vượt HĐ thì làm outstanding HĐ âm (như nppsale). Tổng nợ khách vẫn ra đúng số, chỉ khác chỗ "cục dư" nằm.
- **Đề xuất**: màn Công nợ hiện thêm dòng "Tiền thừa chưa phân bổ" của khách (lấy từ Payment Entry) cạnh các HĐ; "Sửa HĐ có tiền thu" = phiếu thu **giữ nguyên số**, tiền được phân bổ lại sang tờ mới (đúng ý mig 184).

### CFD-05 · Bán âm phải âm trên một lô cụ thể
- **nppsale**: bật bán vượt tồn thì phần thiếu ghi lên phiếu "không gắn lô", lô không âm (mig 138 / 222 / 238).
- **ERPNext v16**: cho tồn âm theo lô (`allow_negative_stock_for_batch`) nhưng mọi dòng xuất của mặt hàng theo lô **phải có lô**; không có khái niệm "phần không lô".
- **Đề xuất**: phần thiếu âm vào **lô mới nhất còn trong kho bán**; nếu mặt hàng chưa có lô nào thì tạo lô `AM-<mã hàng>` (hạn 2099) để âm. Phiếu nhập sau đó cộng vào lô mới của nó; lô âm được bù khi huỷ HĐ hoặc khi anh chuyển / kiểm kê. Em kiểm ở PoC xem lõi tự chọn lô để âm hay app phải chỉ định.

### CFD-06 · Sửa / huỷ phiếu nhập mà hàng đã bán, khi đang TẮT bán vượt tồn
- **nppsale**: sửa tại chỗ được miễn SL mới ≥ đã xuất (mig 235); huỷ chỉ khi bật tồn âm (mig 238).
- **ERPNext**: sửa = huỷ + amend; lúc huỷ, tồn của lô tạm âm cho tới khi tờ mới ghi sổ → lõi chặn nếu không cho âm. Trong một giao dịch (một request) em có thể cho âm tạm thời rồi kiểm lại "sau khi xong, không lô nào âm"; **cần PoC xác nhận** lõi chấp nhận cách này.
- **Đề xuất**: nếu PoC ổn → giữ nguyên luật nppsale. Nếu không → luật dự phòng: "sửa phiếu nhập đã bán phải bật tồn âm tạm" (giống luật huỷ của mig 238).

### CFD-07 · Giá vốn tính lại chạy nền
- **nppsale**: sửa phiếu nhập → giá vốn phần đã bán tính lại ngay trong RPC.
- **ERPNext**: sửa / huỷ chứng từ kho về quá khứ → Repost Item Valuation chạy **nền** (vài giây tới vài phút tuỳ số chứng từ sau nó); lãi gộp / giá trị tồn đúng sau khi repost xong.
- **Đề xuất**: chấp nhận; màn báo cáo hiện "đang tính lại giá vốn (N chứng từ)" khi còn việc repost chờ.

### CFD-08 · Quyền hai lớp và mỗi NPP một site
- Lớp Frappe là sàn (đọc theo vai, không ghi chứng từ tiền / kho); lớp NPP (ma trận ô × hành động theo vai, ghi đè từng người) kiểm ở method và menu. Nếu ai được mở Desk, họ thấy theo lớp Frappe (rộng hơn lớp NPP) → **vai NPP không vào Desk**.
- "Nháp đơn chỉ người tạo thấy, chủ NPP cũng không" (mig 161): giữ ở method; ở lớp Frappe chủ NPP đọc được (không ai thấy vì không có Desk).
- Mỗi NPP một site (mục 2.1): hết `org_id`, hết RLS; bù lại khi anh muốn xem nhiều NPP một chỗ thì phải gom qua API.

---

## 6. Khác nhẹ — em tự xử lý, không cần duyệt
1. Thuế: lõi cộng từng dòng rồi làm tròn ở cấp khoản thuế (một dòng VAT, thuế suất theo mặt hàng) — về lý thuyết bằng `round(Σ dòng × suất)` của nppsale; em so trên bộ hoá đơn thật ở PoC, lệch ≥ 1 đ thì báo.
2. Thẻ kho hiện chứng từ gốc (HĐ `HD-…`, phiếu nhập `PN-…`) thay vì phiếu `XK-…` / `NK-…` tự sinh; màn Phiếu kho liệt kê theo chứng từ gốc.
3. Xuất vượt số đặt / thêm hàng ngoài đơn lúc Xuất hàng: phần vượt tách thành dòng không nối đơn (lõi chặn giao quá số đặt trên dòng nối); báo cáo Đặt hàng "đã xuất" tính theo dòng nối.
4. Hàng đổi: dòng 0 đ trên HĐ có cờ riêng (báo cáo bỏ qua như hôm nay) + phiếu nhập lại; phí trả hàng = khoản trừ trên tờ ghi có.
5. Đơn hàng không mang đuôi `-n` khi sửa (CFD-01); Sales Order cần ngày giao → tự điền ngày đặt / ngày giao dự kiến.
6. Số chứng từ: cùng dãy `DH / HD / PT / PN / PTNCC / PCNCC`, đặt điểm bắt đầu tiếp nối số cuối của nppsale; phiếu thu xem câu 13.
7. Tìm không dấu bằng collation MariaDB (bỏ `tim_kd`); ô tìm vẫn "mọi từ, không dấu, không phân biệt hoa thường".
8. Số phiên danh mục (`danh_muc_ban_phien`) tăng bằng hook thay trigger; cùng khoá `dungLaiSanPham` / `dungLaiKhach`.
9. `near_expiry_skipped` tính trong method sau khi chọn lô (so hạn lô đã lấy với lô còn lại).
10. Chi phí (phiếu chi) đi vào sổ cái bằng Journal Entry; báo cáo tài chính kiểu nppsale vẫn đọc từ `NPP Phieu Chi` để số không đổi cách tính.
11. `workflow_sessions`, `merged_orders`, `cash_collections`, `purchase_orders`, `hr_payroll` cũ: không port; dữ liệu nằm ở bản lưu trữ.
12. Trang `/debug`, `/backup/*`: không port.

---

## 7. Giao diện: bê thế nào (phương án R)

**Giữ**: toàn bộ `src/components`, `src/lib` (luật thuần: giá, giảm giá, tổng tiền, đơn vị, quyền, nav, báo cáo, Excel, in), `src/store`, `src/hooks`, `tests/`, phần lớn `e2e/`.

**Thay**:
| Next.js / Supabase | Portal trên Frappe |
|---|---|
| App Router (`src/app/**/page.tsx`) | React Router, một bảng route chép đúng đường dẫn cũ (thêm tiền tố) |
| `createClient()` + `.from()/.rpc()` (938 + 100 chỗ) | một lớp `goi("npp.sale.api.<mô-đun>.<hàm>", tham_so)` bọc `frappe.call` (hẹn giờ, thử lại, dịch lỗi tiếng Việt — chép luật `fetchCoHetGio`); mỗi màn một method |
| Middleware (POS theo cookie khổ màn, bảo trì, phiên) | `index.py` đọc cookie `npp_kho` → trả thẳng đường POS; bảo trì = `maintenance_mode` |
| 17 route handler `/api/*` | whitelisted method (admin users, QR, MISA, cron, đo nạp, dọn ảnh) |
| `layHoSoMayChu` + `NapHoSo` | `NPP_CONTEXT` bơm sẵn trong HTML (hồ sơ + quyền + cài đặt, không gọi thêm) |
| Supabase Auth (`signInWithPassword`, magiclink QR) | `/api/method/login` bằng SĐT; QR qua method riêng |
| Supabase Storage (ảnh điểm bán) | File riêng tư của Frappe (`/private/files`), tải lên qua `upload_file` |
| `public/sw.js` | `www/sw.js`, cùng luật cache |
| `next/link`, `next/image`, `next/font`, `next/navigation` (171 tệp) | `<Link>` của router, `<img>`, font tự nạp, `useNavigate` |

**Cách làm theo lớp để kiểm được từng bước**: (1) dựng khung Vite + router + `goi()` + trang đăng nhập, mở được `/home`; (2) chuyển từng mô-đun theo thứ tự của mục 9, mỗi mô-đun = thay các `.from()` bằng method + viết method; (3) e2e chạy với **sổ giả Frappe** (`e2e/fake-frappe.mjs` thay `fake-supabase.mjs`), cùng kịch bản.

**Điều sẽ khác với người dùng**: địa chỉ có tiền tố (`/ban-hang/orders`), trang đăng nhập là của app (không phải trang Frappe), còn lại giống.

---

## 8. Dữ liệu và cắt chuyển

Ba phương án lịch sử:

| | H1. Nhập lại toàn bộ lịch sử thành chứng từ thật trong ERPNext | **H2. Danh mục + số dư đầu kỳ; lịch sử giữ ở nppsale chỉ đọc** | **H3 (đề xuất). Như H2 + nhập lịch sử vào bảng lưu trữ chỉ đọc của app** |
|---|---|---|---|
| Việc | Phát lại ~2.700 HĐ, phiếu trả, phiếu thu, phiếu nhập theo thứ tự thời gian (sổ kho / sổ cái dựng lại từ đầu) | Khách, hàng, giá, NCC, người dùng, tuyến, phân công, ảnh; tồn kho theo lô (Stock Reconciliation / nhập đầu kỳ giữ mã lô, hạn, giá vốn); nợ phải thu từng HĐ còn nợ (tờ đầu kỳ giữ mã HĐ, ngày, hạn, NV); dư có; nợ NCC; trả trước NCC | H2 + chép HĐ / dòng HĐ / phiếu trả / phiếu thu / phiếu nhập cũ vào `NPP LS *` để báo cáo nhiều kỳ, "hàng khách đã lấy 12 tháng", bậc lương theo lịch sử vẫn chạy |
| Rủi ro | Cao: giá vốn / FIFO khó khớp từng đồng; mất nhiều tuần | Báo cáo so kỳ trước mất mốc trong vài tháng đầu; phải giữ Supabase thêm | Vừa: bảng lưu trữ không đụng sổ kho / sổ cái; báo cáo nối hai nguồn ở một chỗ (hàm dòng thô) |
| Đề xuất | Không | Tối thiểu | **Chọn** |

Các bước cắt chuyển (chung cho H2 / H3): (1) chạy song song trên site thử với bản sao dữ liệu, so số từng màn (nợ theo khách, tồn theo lô, doanh thu tháng); (2) chốt ngày D: khoá nppsale, xuất lần cuối, nhập, kiểm chữ ký số liệu; (3) người dùng đặt lại mật khẩu (mật khẩu Supabase không chuyển được) hoặc dùng QR mới; (4) nppsale để chỉ đọc 3–6 tháng.

---

## 9. Lộ trình và nghiệm thu

| Giai đoạn | Việc | Nghiệm thu |
|---|---|---|
| **P0 — PoC** (sau khi anh chốt) | bench v16, site thử, app khung `npp` (module mới), Custom Field tối thiểu, một method `xuat_hang` thật với lô FIFO, đo thời gian; thử CFD-05 / CFD-06 / làm tròn thuế trên 50 HĐ thật | bảng số đo + trả lời 3 điểm "cần PoC" |
| **P1 — Blueprint** | 6 tệp theo `nextcode-design` (nghiệp vụ, DocType, quyền, trạng thái, tích hợp lõi, fixtures) | anh duyệt từng tệp |
| **P2 — Nền** | app, vai, ma trận quyền, đăng nhập (SĐT + QR), `NPP Nhan Vien`, cài đặt, khung portal (Vite + router + `goi()`), danh mục: khách (lọc trùng, phân công, tuyến), hàng (đơn vị, giá, mã vạch), NCC, người dùng | đăng nhập 5 vai, CRUD danh mục bằng mã nppsale |
| **P3 — Bán hàng lõi** | đơn hàng (POS + điện thoại + offline), Xuất hàng, HĐ (xem / sửa / huỷ), phiếu trả hai loại, công nợ, phiếu thu, in A5, Excel, HĐĐT MISA | so số với nppsale trên cùng kịch bản e2e |
| **P4 — Kho và mua** | nhập hàng, trả NCC, công nợ NCC, phiếu chi (NCC + chi phí), lô / kho date, phiếu kho, kiểm kê, thẻ kho, soạn hàng, bảng giá nhập, đề xuất đặt | tồn theo lô khớp, giá vốn khớp |
| **P5 — Khách hàng mở rộng** | PJP / ghé thăm, ảnh + GPS + duyệt, bàn giao, hàng đã lấy, thông báo, việc theo lịch | |
| **P6 — Báo cáo** | 6 màn tổng hợp, tổng quan, trang chủ NVBH, báo cáo cũ được giữ (câu 6) | từng con số đối chiếu với nppsale |
| **P7 — Nhân sự và phần còn lại** | lương, chấm công, khuyến mãi / hoa hồng (nếu giữ), wizard, trợ giúp | |
| **P8 — Dữ liệu và cắt chuyển** | công cụ nhập, chạy song song, đào tạo, cắt chuyển | ba ngày không lệch số |

Khối lượng tương đối (P2 = 1): P3 ≈ 2,5 · P4 ≈ 1,5 · P5 ≈ 1 · P6 ≈ 1,2 · P7 ≈ 0,8 · P8 ≈ 1. Tính theo công làm liên tục em ước **cỡ 5–6 tháng**; làm nhiều mô-đun song song bằng agent rút được thời gian viết, nhưng **nút cổ chai là nghiệm thu số liệu** — nên mỗi giai đoạn em sẽ gửi bảng so số để anh duyệt thay vì chờ cuối.

---

## 10. Câu hỏi cần anh trả lời (mỗi câu đã có đề xuất)

1. **Repo và tên app.** Repo `mrhuychien/npp` hiện chỉ có tệp `hello`. App `npp` đang chạy thật (module "NPP Portal", `/npp`, cổng tự phục vụ cho NPP khách hàng của công ty anh) có phải là cùng một app không? → *Đề xuất*: anh đẩy mã app `npp` đang chạy lên repo này (nhánh `main`); em thêm **module mới `NPP Sale`** trong cùng app, portal bán hàng ở tiền tố **`/ban-hang`** (vì `/npp` đã dùng). Nếu anh muốn app riêng, đặt tên khác (`npp_sale`) để không đụng app `npp` trên cùng bench.
2. **Mỗi NPP một site** (mục 2.1 A) — đồng ý?
3. **Độ sâu lõi: phương án H** (mục 2.2) — đồng ý?
4. **Giao diện: dùng lại mã React** (mục 2.3 R) — đồng ý? Hay anh vẫn muốn vanilla theo house style (em sẽ ước lại khối lượng ×3–4)?
5. **CFD-01 … CFD-08** (mục 5) — duyệt từng mục; mục nào anh muốn làm khác thì ghi.
6. **Mảng di sản**: (a) 23 màn báo cáo cũ `/reports/*` + `/analytics/*` — bê hết, hay chỉ bê những màn anh còn mở (anh liệt kê), còn lại dựa vào 6 màn tổng hợp? (b) Khuyến mãi và Hoa hồng — bê nguyên dạng danh mục, hay bỏ tới khi cần thật? (c) Chuyến giao — bỏ hẳn (đề xuất).
7. **Lương**: port riêng không dùng HRMS (đề xuất) — đồng ý? Và nhân dịp này **đổi nguồn doanh thu lương sang hoá đơn − hàng trả** cho đúng luật 24/09 (hiện lương vẫn cộng `sales_orders.total`)? Số lương sẽ đổi — cần anh quyết rõ.
8. **Dữ liệu**: H3 (đề xuất) hay H2 / H1? Ngày cắt chuyển dự kiến?
9. **Kế toán**: tạo site với hệ thống tài khoản Việt Nam (TT200) để sổ cái ERPNext dùng được về sau — đồng ý? Giai đoạn đầu báo cáo tài chính vẫn theo kiểu nppsale.
10. **Hạ tầng**: bench v16 chạy ở đâu (VPS tự host hiện tại của anh? cấu hình?), domain cho site NPP, có Cloudflare phía trước không (ảnh hưởng cache `sw.js` / HTML).
11. **Nhịp duyệt**: duyệt 6 tệp blueprint từng tệp (chuẩn `nextcode-design`) hay gộp một lần? Em đề xuất từng tệp, mỗi tệp ngắn.
12. **Đặt tên**: DocType tiếng Việt không dấu với tiền tố `NPP ` (`NPP Phieu Tra`), fieldname ASCII, nhãn tiếng Việt có dấu — đồng ý?
13. **Số phiếu thu**: nppsale đang `PT-YYMMDD-NNNN` ngẫu nhiên và trùng tiền tố `PT-` với phiếu trả. → *Đề xuất*: phiếu thu `PTH-.YY.MM.DD.-.####` chạy liên tục trong ngày; phiếu trả giữ `PT-####`.

Anh trả lời ngắn theo số (ví dụ: "1 đẩy mã lên, tiền tố /ban-hang · 2 ok · 3 ok · 4 ok · 5 ok trừ CFD-05 làm thế này… · 6a chỉ giữ … · 6b bỏ · 7 ok, đổi · 8 H3, cắt 01/01 · 9 ok · 10 … · 11 từng tệp · 12 ok · 13 ok").

---

## 11. Rủi ro và điều em chưa chắc

- **Kích cỡ**: đây là dự án lớn nhất của bộ skill nextcode tới giờ (177 k dòng TS, 234 hàm SQL). Rủi ro lớn nhất không phải viết mà là **nghiệm thu số**: em sẽ dựng bộ so số tự động (cùng kịch bản chạy trên nppsale và trên app, so tổng công nợ / tồn / doanh thu) trước khi port màn.
- **Ba điểm cần PoC** trước khi hứa: CFD-05 (lõi tự chọn lô âm?), CFD-06 (âm tạm thời trong một giao dịch?), làm tròn thuế.
- **Hiệu năng ghi sổ** trên máy chủ anh chọn — đo ở PoC; lõi ERPNext nặng hơn RPC thuần.
- **Frappe v16 còn mới** (Python 3.14, Node 20): bộ skill đã đối chiếu source v16 nhưng vẫn có thể gặp lỗi lõi; kế hoạch dự phòng là ghim phiên bản v16 cụ thể cho cả bench.
- **Mật khẩu người dùng không chuyển được** từ Supabase; cần đặt lại / phát QR mới ngày cắt chuyển.
- **Hai hệ thống chạy song song** vài tháng (đọc lịch sử ở nppsale): chi phí Supabase + Vercel còn trong thời gian đó.

---

*Sau khi anh chốt mục 10, em bắt đầu P0 (PoC) và gửi lại bảng số đo + bản blueprint đầu tiên (`01_business_model.md`).*
