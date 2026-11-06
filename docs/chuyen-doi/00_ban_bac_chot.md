# Chuyển npp.sale → app `nppsale` trên ERPNext v16 — bản bàn bạc để chốt

Phiên bản 3.4 · 06/11/2026 · em soạn, **anh đã chốt** (mục 0a); v3.3 ghi thêm kết quả **PoC P0** (các chỗ đánh dấu *[PoC]*, chi tiết ở `poc/00_ket_qua_poc.md`); v3.4 đính chính các chỗ ấy theo vòng soát độc lập và lượt đo lại ngày 06/11. Bản này giữ nguyên nội dung bàn bạc làm hồ sơ "vì sao"; phần thực thi theo mục 0a.

Lịch sử bản: v1 (04/11) đề xuất ban đầu → v2 sửa theo vòng kiểm chứng lõi ERPNext (22 khẳng định) → **v3** sửa thêm theo vòng kiểm chứng nền Frappe (12 khẳng định) và bốn agent soát thiếu (bảng / RPC, màn hình, luật `CLAUDE.md`, góc nhìn chuyên gia ERPNext) — 61 chỗ thiếu, 14 câu em viết sai về chính nppsale hoặc về Frappe đã được sửa → **v3.3** (05/11) ghi kết quả đo thật của PoC P0 trên bench v16 → **v3.4** (06/11) đính chính theo vòng soát độc lập (đối chiếu từng số với sổ PoC) và đo lại / đo thêm: thuế + làm tròn, dòng hai lô thật, đồng thời phần Xuất HĐ, đổi mã lô, Sửa HĐ = amend. Bằng chứng từng dòng ở `khao-sat/04_kiem_chung_erpnext.md`; số đo ở `poc/00_ket_qua_poc.md`, nguyên văn máy in ra ở `poc/01_bang_chung.md`.

Tài liệu đi kèm (khảo sát tự động từ mã nguồn nppsale, nhánh `claude/elegant-hamilton-ak996q`, HEAD `58158b1`):
- `khao-sat/01_man_hinh.md` — 180 trang, menu, POS, thư viện component.
- `khao-sat/02_du_lieu.md` — 82 bảng, 74 RPC công khai, trigger, RLS, đánh số chứng từ, quy ước tiền / đơn vị.
- `khao-sat/03_nghiep_vu.md` — luật nghiệp vụ ngoài `CLAUDE.md` (máy trạng thái, công thức, mã lỗi).
- `khao-sat/04_kiem_chung_erpnext.md` — 34 khẳng định về lõi: đúng / sai / đúng một phần kèm tệp:dòng; 69 ràng buộc lõi phát hiện thêm; 61 chỗ thiếu do agent soát ra.

---

## 0a. Quyết định đã chốt (chủ nhà trả lời 18 câu, 05/11/2026)

| # | Câu | Chốt | Hệ quả trong tài liệu |
|---|---|---|---|
| 1 | Repo và tên app | **App độc lập tên `nppsale`**, không phải app `npp` đang chạy; portal ở **`/nppsale`** | Mọi chỗ ghi `/ban-hang`, `npp.sale.api`, "module NPP Sale trong app npp" đọc thành `/nppsale`, `nppsale.api`, app `nppsale`. Mã nguồn nằm ở repo `mrhuychien/npp` (tên repo khác tên app — bench đọc tên app từ `pyproject.toml`; kiểm ở P0 rằng `bench get-app` đặt đúng thư mục `apps/nppsale`) |
| 2 | Mỗi NPP một site | **Đồng ý** | 2.1 A |
| 3 | Độ sâu lõi | **Lai (H)** | 2.2 |
| 4 | Giao diện | **Dùng lại mã React** | 2.3 R |
| 5 | CFD-01 … 13 | **Duyệt tất cả**; riêng CFD-05 chọn **B** | xem 14, 15 |
| 6 | Mảng di sản | **Bê hết**: 23 màn báo cáo cũ + phân tích, khuyến mãi, hoa hồng giữ nguyên dạng danh mục (chuyến giao vẫn bỏ theo quyết định 24/09/2026 — nếu anh muốn khác thì nói) | mục 1 |
| 7 | Lương | Port riêng; doanh số lương theo HĐ − hàng trả (giữ); **thưởng số đơn đếm hoá đơn ghi sổ**; cấu hình "Thưởng tháng" giữ (theo tinh thần "bê hết") | 4.5 |
| 8 | Dữ liệu | **H3** (danh mục + số dư đầu kỳ + lịch sử vào bảng lưu trữ chỉ đọc) | mục 8 |
| 9 | Kế toán | Hệ thống tài khoản VN (TT200) | 3.11 |
| 10 | Hạ tầng | **VPS Google Cloud** (bench tự dựng; cấu hình máy, nginx, Cloudflare chốt ở P2 — PoC chạy trên container, xem `poc/00_ket_qua_poc.md` mục 4) | 3.7, 3.10 |
| 11 | Nhịp duyệt | Duyệt **từng tệp** blueprint | mục 9 P1 |
| 12 | Đặt tên DocType | `NPP …` không dấu, fieldname ASCII | 3.3 |
| 13 | Số phiếu thu | `PTH-.YY.MM.DD.-.####`; phiếu trả giữ `PT-####` | 6.6 |
| 14 | Bán vượt tồn theo lô | **B**: mặt hàng cần bán vượt tồn thì **không theo dõi lô** (`has_batch_no = 0`, bật tồn âm cho riêng mặt hàng ấy) — không hạn dùng, không FIFO theo lô, không kho cận date cho các mặt hàng đó; mặt hàng còn lại theo lô và **chặn** xuất khi lô không đủ. Cờ này **không đổi được** sau khi có sổ kho → danh sách mặt hàng theo lô / không lô là một bước của chuyển dữ liệu (anh duyệt danh sách) | CFD-05, CFD-06 |
| 15 | Sửa / huỷ phiếu nhập đã bán | Giữ luật cũ cho mặt hàng **không lô** (cancel + amend được khi tồn âm cho phép); mặt hàng theo lô: chỉ sửa giá (LCV), không huỷ khi lô đã xuất | CFD-06 |
| 16 | Kiểm kê + giảm đầu phiếu nhập | Đồng ý cách đề xuất và dự phòng | CFD-09, CFD-11 |
| 17 | Nhập kho kèm công nợ NCC | **Purchase Invoice có nhập kho** (màn Nhập kho của thủ kho lưu thành phiếu nhập PN khi có NCC) | CFD-13 |
| 18 | Số PN và SKU | Số `PN-` cấp ngay lúc lập nháp; SKU bất biến sau khi có chứng từ | CFD-01, CFD-10 |

Bước kế tiếp đã được phép: **P0 (PoC đo mười điểm)** và **P1 (blueprint, duyệt từng tệp, bắt đầu từ `01_business_model.md`)**.

---

## 0. Đọc trong ba phút

**nppsale hôm nay.** 177.000 dòng TypeScript, 180 trang (≈160 màn thật, 12 màn luồng cũ đã chặn), 228 component, 82 bảng Postgres, 74 RPC công khai + ~160 hàm phụ / trigger, 260 migration. Luật nghiệp vụ đã chốt nằm ở `CLAUDE.md` của nppsale và ~140 khối "VÌ SAO" trong migration. Hệ thống đang chạy thật cho một NPP.

**Em đề xuất.**
1. **ERPNext giữ sổ**: Item / Customer / Supplier / Warehouse / Batch / Sales Order / Sales Invoice (có trừ kho) / Payment Entry / Purchase Invoice (có nhập kho) / Stock Entry / Journal Entry. Đây là phần nppsale tự viết bằng 234 hàm SQL; ERPNext đã có sẵn, có sổ cái, có kiểm toán.
2. **App `npp` bọc luật nppsale**: ~25 DocType riêng (phiếu trả, tuyến, phân công khách, ảnh điểm bán, bàn giao, soạn hàng, kiểm kê, lương, HĐĐT MISA, ma trận quyền…), Custom Field trên DocType lõi, và **mọi thao tác tiền / kho / trạng thái đi qua whitelisted method Python** (đúng luật "không ghi thẳng từ trình duyệt" của nppsale, đúng kiểu NPP của bộ skill nextcode). App **tự chọn lô**, **tự lập tờ ghi có độc lập**, **tự tính nợ theo hoá đơn**, **tự lọc dữ liệu theo đúng vế RLS cũ** — không giao bốn việc đó cho máy tự động của lõi, vì lõi làm khác luật nppsale (mục 5).
3. **Giao diện bê nguyên mã React/Tailwind/shadcn** của nppsale thành một SPA chạy ngoài Desk tại `/nppsale/…`, giữ nguyên từng đường dẫn, phím tắt POS, máy quét, in A5, Excel, offline. Chỉ thay tầng dữ liệu (Supabase → `frappe.call`). **Không** viết lại tay 160 màn bằng vanilla JS.

**Hai điều lõi ERPNext v16 không làm được mà nppsale đang làm** (đã kiểm bằng mã nguồn, không phải phỏng đoán):
- **Bán / xuất vượt tồn với hàng theo lô**: lõi chặn lô âm vô điều kiện, kể cả khi bật mọi cài đặt tồn âm. Luật `allow_oversell` (mig 086 / 222 / 238) phải đổi — CFD-05, câu 14.
- **Tờ ghi có gắn vào hoá đơn**: chỉ được chứa mặt hàng của hoá đơn ấy, số lượng ≤ đã xuất, đơn giá ≤ giá đã bán, không trừ quá số còn nợ. nppsale cho trả bất kỳ hàng (mig 158), giá trả tới trần theo vai (mig 230), trả nhiều hơn xuất thành nợ âm (mig 186) → em đổi cách bọc: tờ ghi có **độc lập**, liên kết hoá đơn bằng trường riêng, nợ theo hoá đơn do app tính — người dùng không thấy khác (CFD-03).

**Cần anh duyệt**: 13 chỗ lõi buộc khác (mục 5) và 18 câu hỏi (mục 10), mỗi câu có đề xuất sẵn.

**Tiến độ**: anh đã chốt 18 câu (mục 0a, 05/11/2026) → **P0 PoC đã xong** trên bench v16 thật (đo 05/11, soát độc lập và đo lại 06/11 — kết quả ở `poc/00_ket_qua_poc.md`, nguyên văn ở `poc/01_bang_chung.md`; chỗ nào bản này đổi theo PoC có dấu *[PoC]*) → đang P1: 6 tệp blueprint theo `nextcode-design`, duyệt từng tệp (`blueprint/01_business_model.md` chờ anh duyệt) → build theo giai đoạn ở mục 9.

---

## 1. Hiện trạng: mảng nào còn sống, mảng nào di sản

| Mảng | Màn | Trạng thái ở nppsale | Hướng khi sang ERPNext |
|---|---|---|---|
| POS máy tính (`/pos/*`: đơn, xuất hàng / HĐ, phiếu trả, nhập hàng, trả NCC) | 11 | Lõi, dùng hằng ngày | Bê nguyên |
| Bán hàng điện thoại (`/sell/*`) | 10 | Lõi (NVBH) | Bê nguyên |
| Đơn hàng, Hoá đơn bán, Trả hàng | 13 | Lõi | Bê nguyên; dưới là SO / SI / tờ ghi có |
| Công nợ, Phiếu thu, Phiếu chi, Nợ đầu kỳ | 14 | Lõi | Payment Entry + sổ cái; màn giữ nguyên |
| Khách hàng (tuyến, PJP, ghé thăm, ảnh + GPS + duyệt, bàn giao, hàng đã lấy, lọc trùng SĐT) | 9 | Lõi, nhiều luật riêng | DocType riêng + Customer |
| Sản phẩm (đơn vị, bảng giá, mã vạch, nhập Excel kèm tồn đầu kỳ) | 2 | Lõi | Item + UOM + Item Price |
| Kho (lô / date, phiếu kho, kiểm kê, thẻ kho, soạn hàng, tra soát) | 15 (+5 chặn) | Lõi | Batch + Stock Entry; kiểm kê và soạn hàng riêng |
| Mua hàng (phiếu nhập, trả NCC, công nợ NCC, phiếu chi NCC, bảng giá nhập, đề xuất đặt) | 18 | Lõi | Purchase Invoice (± debit note) + Payment Entry |
| HĐĐT MISA (`/invoices`, đối soát, cấu hình) | 5 + 1 | Lõi (kế toán) | DocType riêng + Python theo skill `einvoice-misa-sync` |
| Báo cáo tổng hợp 6 màn + Tổng quan + trang chủ NVBH | 8 | Lõi | Bê nguyên; nguồn dòng thô = method Python |
| Báo cáo cũ `/reports/*` (14) + Phân tích `/analytics/*` (9) | 23 | Chạy song song, chủ nhà từng nói "chỉ gỡ khi màn mới dùng ổn" | **Hỏi anh** (câu 6) |
| Nhân sự / lương (chấm công, cấu hình, bảng lương, phiếu lương của tôi, thưởng tháng) | 9 | Dùng; doanh số lương đã theo HĐ − hàng trả (mig 126); chỉ thưởng số đơn còn đếm đơn | Port riêng (câu 7) |
| Khuyến mãi | 3 | Chỉ là danh mục, POS không áp | **Hỏi anh** (câu 6) |
| Hoa hồng | 4 | Chỉ cấu hình, chưa có máy tính / chi | **Hỏi anh** (câu 6) |
| Người dùng, phân quyền, QR đăng nhập, tổ chức, ngưỡng cảnh báo, wizard | 10 | Lõi | User + Role + ma trận riêng |
| Chuyến giao (`/deliveries`, `stock-out`, `pending`) | 5 + | **Đã chặn** (chủ nhà 24/09/2026) | **Bỏ**, không port; cắt cả phần chuyến giao còn dính ở chi tiết phiếu thu / phiếu kho |
| Đơn mua PO, `workflow_sessions`, `hr_payroll` cũ, `merged_orders`, `cash_collections`, `swap_stock_movements`, `reports_config`, cột `completed_edit_days` | — | Di sản, chỉ tra cứu / không ai đọc | Bỏ (dữ liệu cũ nằm ở bản lưu trữ) |

Con số đáng nhớ: trình duyệt nppsale gọi Supabase ở **938 chỗ** (`.from(`) trong 306 tệp và **100 chỗ** `.rpc(`. Đó chính là khối lượng thay tầng dữ liệu khi bê giao diện (mục 7).

---

## 2. Ba quyết định lớn — quyết trước, mọi thứ khác theo sau

### 2.1 Mỗi NPP một site ERPNext (đề xuất) hay chung site với công ty anh?

| | A. Mỗi NPP một site (`npp1.local`, `npp2.local`…), cùng một bench, cài app `npp` | B. Một site chung: mỗi NPP là một Company |
|---|---|---|
| Cô lập dữ liệu | Tuyệt đối (khác database) — tương đương `org_id` + RLS hôm nay | Customer / Item / Supplier / User là **danh mục toàn site**; cô lập phải tự làm bằng User Permission ở mọi DocType, rất dễ hở |
| Danh mục hàng | Mỗi NPP tự có hàng của mình (nhiều hãng, như nppsale `user_suppliers`) | Chung — chỉ hợp nếu mọi NPP bán đúng một bộ hàng |
| Mã vạch / mã lô / số chứng từ | Duy nhất trong site = trong NPP | Duy nhất **toàn site**: hai NPP cùng mã lô `PN-0001-001`, cùng mã vạch hay cùng dãy `HD-` là đụng nhau |
| Sao lưu / khôi phục / nâng cấp | Từng site, `bench backup` sẵn | Một cục |
| Đổi luật cho một NPP | Chỉnh cài đặt của site đó | Phải phân nhánh theo Company |

**Đề xuất A.** Nếu sau này anh muốn đơn đặt hàng của NPP chảy thẳng vào ERPNext của công ty anh (NPP đặt → Hoàng Giang nhận Sales Order), đó là **tích hợp site-với-site qua API**, không cần nhốt chung một site.

### 2.2 Dùng lõi ERPNext sâu tới đâu?

| | N. "ERPNext thuần": mọi chứng từ là DocType lõi, luật bằng Property Setter + hook | P. "Frappe làm nền": chép 82 bảng thành DocType riêng, lõi chỉ giữ danh mục | **H. Lai (đề xuất)** |
|---|---|---|---|
| Nguyên tắc | Tin lõi, đổi thói quen người dùng theo ERPNext | Tin nppsale, ERPNext chỉ là khung | Lõi giữ **sổ** (kho, công nợ, chứng từ gốc); app giữ **luật và màn** (bọc lõi bằng DocType riêng + method) |
| Giữ nguyên chức năng nppsale | Khó: ~20 luật va lõi (phiếu trả Chờ xử lý, chọn lô theo vùng, sửa phiếu nhập đã bán, quyền từng người…) | Dễ nhất, nhưng mất lý do dùng ERPNext: không sổ cái, không báo cáo kho / công nợ chuẩn, không tích hợp với hệ ERPNext khác | Giữ được ≈ 90 %; 13 chỗ còn lại ở mục 5, trong đó 3 chỗ buộc đổi luật thật (bán vượt tồn theo lô, sửa phiếu nhập đã bán, ngày chứng từ lùi) |
| Khối lượng | Thấp ở backend, cao ở "dạy" người dùng | Cao nhất (viết lại 234 hàm SQL thành Python, không tận dụng gì) | Trung bình: viết lại ~45 RPC nghiệp vụ thành method gọi lõi; ~30 RPC kho / công nợ **biến mất** vì lõi đã làm |
| Hiệu năng | Lõi ghi sổ cái + sổ kho + bundle lô: nặng hơn RPC thuần | Nhẹ | Như N ở chứng từ lõi (*[PoC: ~1 s / HĐ 15 dòng; Xuất hàng cùng lúc nối đuôi theo số HĐ — 3.10]*) |
| Về sau | Nâng cấp ERPNext dễ | Nâng cấp dễ (ít đụng lõi) nhưng tự gánh mọi báo cáo | Nâng cấp vừa; phần bọc phải theo dõi thay đổi lõi |

**Đề xuất H.** Ranh giới cụ thể ở mục 3 và 4: cái gì là lõi, cái gì là DocType riêng.

### 2.3 Giao diện: dùng lại mã React hay viết lại vanilla theo "kiểu NPP"?

| | **R. Dùng lại mã React (đề xuất)** | V. Viết lại vanilla JS no-build theo `frappe-portal-spa` |
|---|---|---|
| Cách làm | Tách `src/` của nppsale thành một ứng dụng Vite + React Router (`basename="/nppsale"`); thay `createClient()` Supabase bằng một lớp `goi()` → `frappe.call`; bỏ phần riêng của Next (middleware, route handler, `next/*`); build ra `public/nppsale/` với tên tệp băm; một www page phục vụ `index.html` + bơm `NPP_CONTEXT` | Dựng lại 160 màn + 228 component bằng template literal, CSS prefix, hash router |
| Giống nppsale | Pixel-giống; giữ `design-ux-ui`, phím tắt, máy quét, in A5, Excel, offline, 387 tệp unit test, 151 tệp e2e (đổi sổ giả) | "Gần giống" — mỗi màn là một lần dịch lại, lệch dần |
| Khối lượng | ~1 phần: viết lớp dữ liệu + sửa 306 tệp có truy vấn, bỏ `next/*` ở 171 tệp, 12 tệp dựng URL tuyệt đối | ~3–4 phần |
| Rủi ro | Build step (Vite) trong vòng đời app Frappe — em xử lý bằng cách **commit sản phẩm build** vào repo, `bench build` không phải biết tới Vite | Rất nhiều chi tiết nhỏ (camera, bảng dòng POS, tab POS) phải làm lại, khó kiểm hết |
| Bẫy cache `/assets` 1 năm | Không có: tên tệp băm thay đổi theo nội dung, không cần import map | Phải import map + build marker (luật vàng #1, #2) |
| Đúng "kiểu NPP" | Khác house style ở tầng trình duyệt (React thay vì vanilla), **giống** ở tầng backend (Python whitelisted, fixtures, guard) | Đúng hoàn toàn |

**Đề xuất R.** Lý do chính: cái quý nhất của nppsale là 7 tháng mài giao diện theo lời anh (POS tab mới, quét mã, phiếu trả, lọc trùng khách…). Viết lại là ném đi phần đó rồi mài lại từ đầu.

---

## 3. Kiến trúc đích (theo A + H + R)

### 3.1 Sơ đồ

```
Trình duyệt (điện thoại / máy tính)
  SPA React (mã nppsale)  ──  /api/method/nppsale.api.*  ──►  app npp (Python)
     │ socket.io (chuông, khoá chứng từ)                     │  guard quyền (ma trận NPP + vai) + lọc theo vế RLS cũ
                                                             │  luật nppsale (giá, giảm giá, hệ số, chọn lô, phiếu trả, nợ theo HĐ…)
                                                             ▼
                                                   DocType lõi ERPNext      DocType riêng NPP
                                                   SO · SI · PE · PI · SE   Phiếu trả · Tuyến · Phân công ·
                                                   JE · Batch · Item · …    Ảnh điểm bán · Soạn hàng · Kiểm kê · Lương · …
                                                             ▼
                                                   MariaDB + sổ kho (SLE) + sổ cái (GL)
```

### 3.2 Backend — tám nguyên tắc (theo `frappe-app-build-profile`)
1. **Một màn một lượt gọi**: mỗi màn / khối có một method trả đủ dữ liệu (như `bao_cao_so_ban`, `goiMotLuot` hôm nay). Hết cảnh 10–90 câu PostgREST một màn.
2. **Ghi chỉ qua method, và method ghi phải là POST**: trình duyệt không bao giờ `frappe.client.save` lên chứng từ; vai NPP **không có quyền ghi / ghi sổ** trên SI / PI / PE / SE / JE ở lớp Frappe, method tự kiểm rồi `ignore_permissions` (gotcha #9). Frappe **rollback mọi request GET** dù không lỗi → method ghi khai `methods=["POST"]`; việc nền (HĐĐT, thông báo) xếp hàng với `enqueue_after_commit=True`.
3. **Luật ở máy chủ, trình duyệt chỉ tính để hiện**: giá bảng theo đơn vị, trần / sàn giá, trần giảm giá theo người (chỉ kiểm khi **tăng** khoản giảm so với bản đang có — luật mig 226), hệ số quy đổi tờ cũ, thuế theo dòng, làm tròn — chép từ các RPC / trigger sang Python (`nppsale/luat/*.py`, thuần, có unit test, không import frappe).
4. **App tự quyết bốn việc lõi làm khác luật nppsale**: (a) **chọn lô** cho mọi dòng xuất (FIFO theo ngày nhập, chỉ kho bán; trả NCC và hụt kiểm kê theo hạn cũ trước) — không dùng máy tự chọn của lõi (nó xếp theo ngày tạo lô và lấy từ mọi kho); (b) **tờ ghi có độc lập** cho hàng trả (CFD-03); (c) **nợ theo hoá đơn** = số còn nợ của HĐ − Σ tờ ghi có gắn HĐ (âm được) và **nợ của khách** = số dư phải thu theo sổ cái (HĐ + tờ ghi có + tiền chưa phân bổ + bút toán) — một method `no_khach` cho POS, hạn mức, danh sách; (d) **lọc dữ liệu cho NVBH đúng vế RLS cũ** ngay trong method (xem 3.5).
5. **Một hợp đồng mã lỗi**: method ném `NppLoi(ma, cau)` và trả `error_code` → `goi()` ánh xạ về đúng chuỗi mã nppsale (`INSUFFICIENT_STOCK`, `LOCKED_HAS_PAYMENT`, `BAD_RECEIVABLE_LINE`, `REASON_REQUIRED`…) để `explainInvoiceError`, `errorMessage`, `kiemLaiSauLoiXuat` chạy nguyên; lỗi tiếng Anh của lõi lọt ra là lỗi của app, không được hiện ở POS.
6. **Idempotent**: `client_request_id` (đơn offline), `client_key` (phiếu thu) là Custom Field duy nhất; gửi lại trả bản đã có (giữ `kiemLaiSauLoiXuat`).
7. **Thời gian theo giờ VN**: `System Settings.time_zone = Asia/Ho_Chi_Minh`, hệ điều hành và MariaDB cùng múi giờ; mọi "hôm nay" (`vn_today`) là `nowdate()` của site.
8. **Không Server Script / Client Script rải**; fixtures export, fieldname ASCII; `py_compile` + `validate_shipped_docs.py` trước mỗi lần cài.

### 3.3 DocType riêng (dự kiến ~26; chốt chi tiết ở blueprint)

| Nhóm | DocType | Thay cho bảng nppsale |
|---|---|---|
| Cài đặt | `NPP Cai Dat` (Single): ngày tự chuyển kho date, ngưỡng cảnh báo đơn, đầu trang in, độ dài chờ, số phiên danh mục… | `organizations.settings`, `pricing_rules`, `approval_rules`, `danh_muc_ban_phien` |
| Người dùng | `NPP Nhan Vien` (1–1 User): vai NPP, cờ giảm giá / sửa giá + trần, công ty được làm (child), nghỉ việc, QR token (băm) | `users` (cột riêng), `user_suppliers`, `qr_login_tokens` |
| Quyền | `NPP Quyen Vai` (child: vai × ô × hành động), `NPP Quyen Rieng` (người × ô × hành động) | `role_permissions`, `user_permission_overrides` |
| Khách | `NPP Tuyen`, `NPP Phan Cong Khach`, `NPP Lich Tuyen` (PJP), `NPP Ghe Tham`, `NPP Anh Diem Ban`, `NPP Yeu Cau Anh Diem Ban`, `NPP Ban Giao Khach` (log) | `sales_routes`, `customer_assignments`, `pjp_routes`, `visit_logs`, `customer_photos`, `customer_photo_requests`, `ban_giao_khach_log` |
| Bán | `NPP Phieu Tra` (+ dòng) — **bọc** tờ ghi có độc lập + phiếu nhập kho; `NPP Luot Soan`; `NPP Khoa Chung Tu` | `returns`, `return_lines`, `luot_soan`, `entity_locks` |
| Tiền | `NPP Phieu Chi` (+ danh mục chi phí → tài khoản chi phí); phiếu thu / phiếu chi NCC là Payment Entry (+ Journal Entry cấn trừ nội bộ) | `expenses`, `expense_categories`; `cash_receipts`, `payments`, `supplier_payments`, `payable_payments` |
| Kho | `NPP Kiem Ke` (đếm → duyệt → phiếu nhập / xuất điều chỉnh theo lô + phiếu chi hao hụt) | `stock_entries` type stocktake |
| HĐĐT | `NPP HDDT`, `NPP MISA Cau Hinh` (Single, mật khẩu kiểu Password), `NPP MISA Log`, `NPP MISA Snapshot` | `invoices`, `company_einvoice_config`, `einvoice_logs`, `misa_invoice_snapshots` |
| Nhân sự | `NPP Cham Cong`, `NPP Cau Hinh Luong`, `NPP Thuong Thang` (cấu hình thưởng theo kỳ), `NPP Bac KPI`, `NPP Thuong So Don`, `NPP Thuong Hoat Dong`, `NPP Ky Luong` (+ dòng) | `hr_*`, `salary_*`, `monthly_activity_bonuses`, `payroll_run*` |
| Khác | `NPP Thong Bao`; `NPP Do Nap` (số đo thời gian nạp thay log Vercel); `NPP Khuyen Mai`, `NPP Chinh Sach Hoa Hong` (nếu giữ — câu 6) | `notifications`, `/api/do-nap`, `promotions`, `commission_*` |
| Lưu trữ | `NPP LS Hoa Don`, `NPP LS Phieu Tra`, `NPP LS Phieu Thu`… (chỉ đọc, nếu chọn phương án dữ liệu H3 — mục 8) | lịch sử trước ngày cắt chuyển |

Tên DocType: tiếng Việt không dấu, tiền tố `NPP ` (câu 12). Fieldname ASCII.

### 3.4 Custom Field trên DocType lõi (ship bằng fixtures)
- **Customer** (đặt tên bằng dãy `KH-.#####`, không lấy tên cửa hàng làm khoá — hai cửa hàng trùng tên là chuyện thường; SĐT là khoá duy nhất): tên chủ, SĐT (duy nhất, chuẩn hoá), địa chỉ / tỉnh / quận / phường, tuyến (Link `NPP Tuyen`), hạn mức (của nppsale — **không** dùng bảng Customer Credit Limit của lõi), điều khoản TT, trạng thái, GPS, ngày duyệt ảnh, thông tin xuất HĐĐT, người tạo, khoá tìm `tim_kd`.
- **Supplier**: dãy `NCC-.####`, các trường pháp lý / ngân hàng, khoá tìm.
- **Item**: `item_code` = SKU **bất biến** (đổi SKU = đổi tên bản ghi, kéo theo mọi chứng từ — câu 18), vị trí kệ, bán trực tiếp, hãng / NCC chính (Item Default), hạn dùng ngày (`shelf_life_in_days` có sẵn), ảnh, mã vạch (child có sẵn, nhiều mã), khoá tìm.
- **Sales Order**: `npp_trang_thai` (Nháp / Phiếu tạm / Hoàn thành / Đã huỷ — huỷ Phiếu tạm là đổi trường này, giữ bản ghi và mã, vì tờ nháp của lõi không "cancel" được), NV được gán, người tạo, `client_request_id`, lần sửa, lý do cảnh báo, lý do huỷ.
- **Sales Invoice / Sales Invoice Item**: NV được gán, NV giữ nợ (`giao_tu_nv`), số gốc (`invoice_seq`), lý do huỷ, đã soạn hàng, dòng hàng đổi, ghi chú dòng, mã lỗi MISA, khoá tìm; trên tờ ghi có: **HĐ gắn** (Link, thay cho `return_against`), **phiếu trả** (Link `NPP Phieu Tra`), ngày trừ doanh số.
- **Payment Entry**: người thu, `npp_trang_thai` (Chờ xác nhận / Đã nhận — chỉ là dấu, không ảnh hưởng nợ), người xác nhận, `client_key`, lý do huỷ, nguồn (NVBH / văn phòng), bút toán cấn trừ đi kèm (Link Journal Entry).
- **Purchase Invoice**: kho nhận (sale / date), số HĐ đầu vào (có sẵn `bill_no`), lý do huỷ, khoá tìm.
- **Batch**: không cần thêm (hạn dùng, ngày sản xuất, NCC có sẵn; vùng = kho).

### 3.5 Vai và quyền
- Role Frappe: `NPP Chu`, `NPP Quan Ly`, `NPP Ke Toan`, `NPP NVBH`, `NPP Thu Kho` (desk_access = 0 → người dùng kiểu Website User, không vào `/desk`); `Role.home_page` của từng vai trỏ `/nppsale/...`; `/login` của Frappe chuyển về trang đăng nhập của app.
- **Luật chính là ma trận NPP + vế lọc trong method.** Vòng soát thiếu chỉ ra User Permission của Frappe **không** tái hiện được RLS của nppsale: nó không lọc Payment Entry (trường khách là Dynamic Link), không biết "khách có đơn / HĐ đứng tên mình" (mig 154 / 260), và sau bàn giao "chuyển hẳn" NV cũ sẽ mất quyền xem chính HĐ của mình. Vì vậy mỗi method danh sách chép **đúng vế RLS của bảng ấy**: khách = phân công ∪ người tạo ∪ khách có đơn / HĐ đứng tên mình ∪ `customer.view_all`; HĐ / nợ / phiếu trả theo `sales_user_id`; hàng theo công ty được làm; nháp đơn theo **người đứng tên** (mig 161). Một bộ test so **tập dòng từng người** như `scripts/sql/thu-260-rls-khach-tinh-mot-lan.sql`.
- Lớp Frappe (DocPerm) = **sàn an toàn**: vai NPP được cấp **đọc** danh mục ở lớp Frappe (lõi tự kiểm quyền đọc Item khi lập chứng từ, cờ bỏ qua quyền của tờ không lan sang), nhưng các cửa đọc chung của lõi (`frappe.client.*`, `frappe.desk.reportview.get`, `frappe.desk.search.*`) bị **chặn cho vai NPP** (`override_whitelisted_methods` / kiểm trong `before_request`) để không lộ hàng của công ty khác hay HĐ của NV khác; mọi đọc đi qua method của app đã lọc. **Không** dùng User Permission theo Item / Brand (sẽ chặn chính HĐ có mặt hàng ngoài công ty của NV). Ghi chứng từ tiền / kho **không cấp** cho ai (chỉ method).
- Giữ nguyên `permissions.ts` + `permissions-features.ts` (chạy cùng mã ở hai nơi: TS cho menu, Python cho guard, một bộ test so khớp).

### 3.6 Đăng nhập và phiên
- Frappe User, đăng nhập bằng **SĐT + mật khẩu** (`System Settings.allow_login_using_mobile_number`; lõi so `mobile_no` **nguyên văn** → lưu đúng dạng `0xxxxxxxxx` như `chuanHoaSdt`), email kỹ thuật `<sđt>@<site>` như hôm nay. Phản hồi đăng nhập của Website User là `"No App"` + `home_page` → trang đăng nhập của app xử lý như thành công và đi theo `trangSauDangNhap` của nppsale.
- **QR đăng nhập**: method `allow_guest` có `rate_limit` (như 10 lượt / phút / IP hôm nay) kiểm token (băm, không hết hạn, xoay / thu hồi) **và** `User.enabled` + `left_at` (lõi `login_as` không tự kiểm) → `login_manager.login_as(user)` → về `/nppsale/orders` (không phải `/orders` — ERPNext đã chiếm đường ấy cho portal của nó). Quản lý QR chỉ chủ NPP.
- **"Đăng nhập thay"** giữ đúng cách nppsale: method chỉ **trả URL QR** của nhân viên cho chủ NPP, giao diện mở bằng trình duyệt khác (`linkTrinhDuyetRieng`) để phiên của chủ không bị thay; không `login_as` trong phiên của chủ.
- Phiên: cookie `sid` + CSRF bơm vào trang; sau `login_as` là phiên mới → `goi()` lấy lại CSRF; `goi()` dịch `SessionExpired` / 401 / `CSRFTokenError` về trang đăng nhập app kèm `next`, phát sự kiện `storage` để các tab POS khác khoá ngay (thay `onAuthStateChange` của Supabase). Cài đặt: `session_expiry` dài cho NVBH chỉ có QR (mặc định ~7 ngày không dùng là văng ra — hàng đợi đơn offline chỉ gửi khi còn đăng nhập), `deny_multiple_sessions = 0` (chủ dùng điện thoại + máy POS), nới `allow_consecutive_login_attempts` vì cả văn phòng chung một IP (10 lần sai là khoá cả văn phòng 60 giây). "Quên mật khẩu" qua email không bao giờ tới (email kỹ thuật) → đặt lại mật khẩu do chủ NPP hoặc phát QR mới; tạo User với `send_welcome_email = 0` và tắt email thông báo.
- Tài khoản khoá: `User.enabled = 0` + `left_at` trên `NPP Nhan Vien`.

### 3.7 Portal được phục vụ thế nào (các điểm dưới đã qua kiểm chứng nền Frappe)
- `www/nppsale/index.html` + `index.py`: **`no_cache = 1` bắt buộc** (Frappe cache HTML trang www 30 phút theo đường dẫn, không theo người — quên là hồ sơ + quyền + CSRF của người A trả cho người B), header `Cache-Control: no-store`, Guest → chuyển về trang đăng nhập app kèm `next`; `index.html` là tài liệu trọn vẹn (có `</body>`) để lõi không bọc vào khung web Bootstrap. `website_route_rules` `/nppsale/<path:app_path>` → một trang (lõi dùng y hệt cho `/desk`), phủ cả `/nppsale/in/*`; đổi rule phải `bench clear-cache`. *[PoC: đã chạy thật — vỏ trả cho mọi đường dẫn con với `Cache-Control: no-store,no-cache,must-revalidate,max-age=0`, có `csrf_token` + người dùng khi đã đăng nhập.]*
- Tệp JS/CSS do Vite build, tên băm, nằm `public/nppsale/`; `bench build` chỉ sao chép. Không cần import map vì không có tệp trùng tên khác nội dung. Trang in `/in/*` là **entry Vite riêng, nhẹ** (không nạp provider POS / danh mục) để nút In trong khung ẩn không tải lại cả SPA.
- **`sw.js` và `manifest.webmanifest` không phục vụ được từ `www/`** (lõi chỉ phục vụ tĩnh tệp nhị phân; tệp `.js` rơi vào trang Jinja có cache 30 phút). Cách làm: hook `page_renderer` của app trả `sw.js` từ `public/` với `Content-Type: application/javascript`, `Cache-Control: no-cache` và `Service-Worker-Allowed: /nppsale/`; manifest cũng vậy (`start_url`, `scope`, `id` dưới `/nppsale/`). Luật cache của SW như hôm nay; **không cache phản hồi chuyển hướng**. *[PoC: `/nppsale/sw.js` trả `application/javascript`, `Cache-Control: no-cache, must-revalidate`, `Service-Worker-Allowed: /nppsale/`; renderer phải nhìn `frappe.local.request.path` vì route rule đã đổi endpoint thành `nppsale` **trước** khi tới renderer; `/assets/*` bị cache 12 giờ (dev) / 1 năm (nginx của bench) nên `sw.js` không được nằm đó — `nppsale/portal/tinh.py`.]*
- **Chuyển thẳng máy tính vào POS**: `index.py` chép luật `dichPosMayChu` (cookie `npp_kho`, lượt mở trang theo `Sec-Fetch-*`) có unit test Python so với bản TS, trả **307 + `Cache-Control: no-store`** (chuyển hướng mặc định của Frappe là 301 — trình duyệt nhớ vĩnh viễn, máy từng rộng sau thu nhỏ vẫn bị đẩy vào POS), tách `app_path` khỏi tiền tố trước khi so; `PosDesktopRedirect` giữ làm đường lùi.
- `X-Frame-Options: SAMEORIGIN` **không phải của Frappe** mà do nginx của bench đặt; frappe_docker / Cloudflare có thể khác → câu 10 ghi rõ: hạ tầng phải không `DENY`, không CSP `frame-ancestors 'none'`; em kiểm bằng `curl -I` trên máy chủ thật ở **P2** (PoC chỉ xác nhận được mẫu nginx của bench có `add_header X-Frame-Options "SAMEORIGIN"` và Frappe không tự đặt header này).
- Thời gian thực: chuông thông báo và khoá chứng từ (hôm nay là Supabase realtime) → `frappe.publish_realtime` + `socket.io` của Frappe (xác thực bằng cookie `sid`, không cần Desk); nếu hạ tầng không mở socket thì hạ cấp: chuông hỏi định kỳ, khoá dựa nhịp 60 giây.
- Hai kênh chẩn đoán của anh giữ nguyên: `/api/client-error` → method `allow_guest` + rate limit ghi Error Log (tra được trên Desk); `/api/do-nap` → `NPP Do Nap` (bench không có màn tìm log như Vercel).

### 3.8 Những gì giữ y nguyên ở trình duyệt
POS nhiều tab, phím tắt F2–F9, dòng mới lên đầu, khối hàng đổi trả có trần cuộn, thẻ khách / NCC mở sửa tại chỗ, máy quét USB + camera (ZXing đã vá), in A5 trong khung ẩn, Excel (danh sách + "như mẫu in"), giỏ hàng + tab POS trong `localStorage`, hàng đợi đơn offline trong IndexedDB, danh mục nhớ theo số phiên, thanh nav dưới theo vai, đầu trang xanh điện thoại, lọc trùng SĐT trước khi tạo khách, cookie khổ màn để mở thẳng POS, gợi ý giá bán gần nhất, hàng hay lấy, đặt lại đơn, nhập Excel sản phẩm kèm tồn đầu kỳ, sáu route chuyển hướng cũ (`/orders/new?customerId=`, `/warehouse/*`, `/operations/*`, `/hr/overview`, `/hr/payroll`, `/analytics`) vì dấu trang / tin nhắn hướng dẫn của NV.

### 3.9 Việc theo lịch (hooks `scheduler_events`) và hook tức thì
01:00 VN mỗi ngày: đồng bộ HĐĐT, nhắc ảnh điểm bán (thứ Hai), nhắc khách chưa tuyến, kéo snapshot MISA, quét lô cũ đã tới ngưỡng cận date, nhả khoá chứng từ cũ. **Tức thì** (hook sau ghi sổ): lô vừa nhập đã trong ngưỡng cận date → nhận thẳng vào Kho cận date (giữ luật trigger `batches_auto_zone`, mig 028 — không chờ đêm); tự xếp hàng tính lại giá vốn ngay sau chứng từ sửa / huỷ (CFD-07); tăng số phiên danh mục; "Rà soát kho date" = chạy tay việc quét lô.

### 3.10 Hiệu năng — nói trước để khỏi bất ngờ
- Nút Xuất hàng trên ERPNext làm nhiều việc hơn RPC của nppsale: ghi sổ kho theo lô, sổ cái, bundle lô, cập nhật đơn. Trên máy 4 vCPU / 8 GB em từng ước **0,4–1,2 s** một hoá đơn 10–20 dòng (sổ thật của anh đang 1,3 s trên Supabase Micro), hẹn quá 1,5 s thì báo trước khi build. *[PoC: máy 4 vCPU / 16 GB, HĐ 15 dòng: riêng phần Xuất HĐ ~0,98 s, tính cả lập đơn TB **1,30 s** (1,16–1,78 s) — ở cận trên của ước lượng; trung bình chưa tới 1,5 s nhưng lượt chậm nhất đã 1,78 s. nppsale trên sổ khoẻ chỉ 19 ms cho cùng việc, nên ERPNext nặng hơn nhiều lần về bản chất; số trên VPS đo ở P2.]*
- Lõi khoá dòng `Batch` (`FOR UPDATE`), sổ kho tương lai **và dòng cấp số `HD-`** suốt giao dịch → nhiều máy POS xuất hàng cùng lúc sẽ xếp hàng theo khoá; giao dịch phải ngắn. *[PoC 06/11: 5 phiên cùng Xuất HĐ thì nối đuôi ~0,7 s / HĐ **kể cả khi hàng khác nhau** (hàng `tabSeries` của dãy số bị giữ tới khi ghi xong) — người thứ năm chờ ~3,4–4,4 s; hàng trùng mà app không khoá `Bin` thì lô âm hoặc bế tắc (CFD-05). Cách cấp số (giữ khoá, hay SEQUENCE không khoá nhưng lỗ số khi ghi hỏng) anh chọn ở blueprint 05.]*
- Tìm kiếm: giữ **cột khoá tìm `tim_kd`** do hook ghi (chép `viValueKey`, có chỉ mục) — collation MariaDB gộp dấu thanh nhưng chưa chắc gộp `đ` / `d` và không có sẵn "mọi từ"; không đánh cược vào collation.
- Báo cáo: một method = một lượt mạng; JIT / RLS không còn là vấn đề.

### 3.11 Cài đặt site bắt buộc (rút từ hai vòng kiểm chứng — làm ở P2, kiểm bằng script)
| Cài đặt | Giá trị | Vì sao |
|---|---|---|
| System Settings `time_zone` | `Asia/Ho_Chi_Minh` (+ OS, MariaDB) | ngày HĐ / phiếu thu / cron theo giờ VN |
| System Settings `allow_login_using_mobile_number`, `session_expiry`, `deny_multiple_sessions`, `allow_consecutive_login_attempts` | bật · ≥ 30 ngày · 0 · nới | mục 3.6 |
| System Settings `currency_precision` / định dạng VND | **0** *[PoC]* | lõi làm tròn đơn giá và tiền từng dòng; nppsale làm tròn đơn giá sau giảm về đồng và tổng ở cuối. PoC đo lại 06/11 (100 HĐ 10–20 dòng, thuế 0/5/8/10 %, giảm dòng %, so từng đồng với công thức nppsale làm tròn nửa xa 0): precision 0 + app gửi đơn giá sau giảm → **khớp 100/100 HĐ** (1.458 dòng, có và không giảm đơn); precision 2 → VAT có số lẻ ở 99/100 HĐ. Bản 05/11 ghi "lệch 1 đ" là lỗi của phép so (làm tròn nửa về số chẵn). `round_row_wise_tax` để 0 (mặc định) |
| System Settings `rounding_method`; Currency VND `smallest_currency_fraction_value` | **Commercial Rounding**; để trống / 0 | mặc định của Frappe là làm tròn ngân hàng (x,5 về chẵn) — lệch 1 đ mỗi HĐ so với `Math.round` của nppsale, kéo theo công nợ và số đẩy MISA; đặt 100 là tổng HĐ tròn tới trăm đồng |
| Company `round_off_account`, `round_off_cost_center`, `round_off_for_opening` | tài khoản chênh lệch làm tròn (TT200: 711 / 811 hoặc 642 — anh chốt ở câu 9) | nppsale làm tròn ở tổng nên HĐ nào cũng có khoản làm tròn; thiếu là ghi sổ HĐ đầu tiên đã lỗi |
| Fiscal Year | tạo năm dương lịch cho năm cắt chuyển và **mọi năm có chứng từ đầu kỳ / lịch sử** | lõi từ chối mọi ngày ghi sổ ngoài năm tài chính đang có |
| Thuế suất từng dòng (0 / 5 / 8 / 10 %) | `Item.taxes` **để trống** mọi mặt hàng; method đặt `item_tax_template` cho từng dòng (mặc định theo `products.vat_rate`); mỗi Item Tax Template `VAT n% - NPP` mang **cả hai** tài khoản thuế đầu ra và đầu vào *[PoC]* | lõi đè thuế suất dòng bằng template của mặt hàng khi dòng mang template không nằm trong `Item.taxes` — màn hiện 10 % mà lõi tính 8 %. PoC: `Item.taxes` trống thì lõi tôn trọng template dòng (100 HĐ trộn bốn mức thuế, VAT khớp từng đồng); template chỉ có tài khoản đầu ra → phiếu nhập tính VAT = 0 không báo gì |
| Accounts Settings `enable_immutable_ledger` | tắt | bật là huỷ / lập lại HĐ bị khoá theo ngày huỷ |
| Mặt hàng ngừng bán | Custom Field `npp_ngung_ban`, **không** dùng `Item.disabled` | `disabled` chặn cả tờ ghi có, Sửa HĐ cũ, kiểm kê có mặt hàng ấy; nppsale vẫn nhận trả / thanh lý hàng ngừng bán |
| Email | `send_welcome_email = 0` khi tạo User; tắt email ở Notification Settings hoặc `mute_emails` | không có hộp thư gửi đi thì Error Log đầy; email kỹ thuật `<sđt>@<site>` không nhận được gì |
| Kho, nhóm hàng | tên Warehouse luôn mang đuôi " - <viết tắt công ty>"; Item Group mặc định | lõi bắt buộc |
| Stock Settings `enable_serial_and_batch_no_for_item` | bật **trước** khi tạo mặt hàng có lô; **không tắt lại được** | lõi chặn `has_batch_no` và bundle lô khi chưa bật |
| Stock Settings `allow_negative_stock`, `allow_negative_stock_for_batch` | để **tắt** (bật cũng không cho lô âm — CFD-05) | tránh hiểu nhầm |
| Stock Settings `pick_serial_and_batch_based_on` | FIFO (không dùng tới — app tự gán lô mọi dòng) | máy tự chọn của lõi xếp theo ngày tạo lô, lấy mọi kho |
| Stock Reposting Settings `enable_parallel_reposting` | bật (15 phút) + app tự xếp hàng ngay | mặc định tính lại giá vốn **mỗi giờ**. PoC: huỷ HĐ 15 dòng sinh **15 việc theo mặt hàng + kho** (không mang số HĐ — màn "đang tính lại" đếm việc Queued / In Progress), chạy hết 4,2 s; LCV trên phiếu nhập 30 dòng: **30** việc (mỗi mặt hàng một việc), 16,8 s |
| Document Naming Settings `default_amend_naming` | `Amend Counter` (mặc định) | để tờ sửa ra `HD-0042-1` thay vì số mới |
| Accounts Settings `unlink_payment_on_cancellation_of_invoice` | bật (mặc định) | huỷ HĐ gỡ phân bổ phiếu thu thay vì chặn |
| Accounts Settings `over_billing_allowance` + `role_allowed_to_over_bill`; Stock Settings `role_allowed_to_over_deliver_receive` | vai dịch vụ của app được vượt | xuất vượt số đặt / đổi giá trên dòng nối đơn không bị chặn |
| Selling Settings `maintain_same_sales_rate` | tắt | bật là chặn đổi giá dòng nối đơn |
| Selling Settings `allow_multiple_items`, Buying Settings `allow_multiple_items` | bật cả hai | HĐ "1 thùng + 3 lon" cùng mã; phiếu nhập mỗi dòng một lô. PoC: tắt là lõi từ chối "Item … entered multiple times" |
| Selling / Buying Settings `cust_master_name` / `supp_master_name` | Naming Series (`KH-.#####`, `NCC-.####`) | tên cửa hàng trùng nhau là thường; đổi tên không đổi khoá |
| Hạn mức tín dụng của lõi | **trống** ở cả Customer, Customer Group và Company | lõi tra tầng; có là chặn ghi sổ SO / SI, kể cả lúc mở lại SO đã đóng |
| Sales Invoice: `is_cash_or_non_trade_discount` + `additional_discount_account` | mẫu HĐ bật sẵn | giảm giá cả đơn **không** hạ thuế (đúng mig 183) — xem CFD-11 |
| Mode of Payment Tiền mặt / Chuyển khoản / Ví gắn tài khoản 111 / 112 / 113 | method tự điền `reference_no` = mã phiếu thu, `reference_date` = ngày thu cho tài khoản Bank | lõi bắt số / ngày tham chiếu khi thu vào tài khoản ngân hàng |
| Role `home_page` 5 vai NPP; `website_redirects` `/login` → `/nppsale/login`, chặn `/me`, `/update-profile` | theo `trangGoc` / `trangSauDangNhap` | mục 3.6 |
| Item: `has_expiry_date` chỉ bật cho hàng có hạn; `create_new_batch` = 0 | app tự tạo Batch theo phiếu nhập | lõi đòi `shelf_life_in_days` > 0 khi bật đủ ba cờ; không có kiểu hạn "2099-12-31" |
| Item Barcode `barcode_type` | **để trống** với mã nội bộ *[PoC]* | đặt EAN / UPC là lõi kiểm checksum, mã tự đặt của NPP bị từ chối |
| System Settings `session_expiry` | ghi dạng `hh:mm`, ví dụ `720:00` (30 ngày) *[PoC]* | ghi `30d` là lỗi |
| Hệ thống tài khoản khi tạo công ty | app ship mẫu **TT200** làm `chart_of_accounts` *[PoC]* | v16 không có mẫu Việt Nam; PoC tạm dùng "Standard" |
| Sao lưu | `bench backup --with-files` theo lịch + script đẩy lên Drive (rclone / age như GitHub Actions hôm nay) kèm `site_config.json` | v16 **không còn** tích hợp Google Drive / Dropbox / S3 trong lõi; mất `encryption_key` trong `site_config.json` là mất mật khẩu MISA |

---

## 4. Bảng ánh xạ nghiệp vụ

Ký hiệu: ✅ giữ nguyên luật và cảm nhận người dùng · ≈ khác nhẹ (mục 6, em tự xử lý) · ⚠ lõi buộc khác (mục 5, cần anh duyệt).

### 4.1 Danh mục
| nppsale | ERPNext / app npp | Mức |
|---|---|---|
| `organizations` (+ settings, allow_oversell) | Company + `NPP Cai Dat`; bán vượt tồn: xem CFD-05 | ⚠ CFD-05 |
| `users` (vai, cờ giảm giá / sửa giá, nghỉ việc, QR) | User + Role NPP + `NPP Nhan Vien` | ✅ |
| `role_permissions`, `user_permission_overrides`, RLS từng bảng | `NPP Quyen Vai`, `NPP Quyen Rieng` + vế lọc trong method + DocPerm sàn | ⚠ CFD-08 |
| `customers` (tên trùng được, SĐT duy nhất) | Customer đặt tên `KH-.#####` + Custom Field; lọc trùng SĐT đúng số (`search_customer_dupes`) = method | ✅ |
| `customer_groups` | Customer Group, mỗi nhóm một Price List mặc định | ✅ |
| `customer_assignments`, `claim_customer_for_me`, `giao_cong_no_npp` | `NPP Phan Cong Khach` + method nhận khách / giao nợ; vế lọc khách của NVBH trong method | ✅ |
| `sales_routes`, `pjp_routes`, `visit_logs` (Haversine 100 m / 500 m) | `NPP Tuyen`, `NPP Lich Tuyen`, `NPP Ghe Tham` | ✅ |
| `customer_photos`, `customer_photo_requests`, duyệt ảnh + vị trí (mig 244), nén 1024 px | `NPP Anh Diem Ban` + File riêng tư (method tự lưu File sau guard — Website User bị giới hạn khi tải thẳng), `NPP Yeu Cau Anh Diem Ban`; xoá file qua method | ✅ |
| `ban_giao_khach` (chung / chuyển hẳn, mốc 3/6/12 tháng), `hang_khach_da_lay` | method + `NPP Ban Giao Khach`; dấu `giao_tu_nv` là Custom Field trên SI | ✅ |
| `products` (sku sửa được, barcode trùng chỉ cảnh báo, base_unit, vat_rate, shelf_life, NCC chính, kệ, ảnh) | Item (`item_code` = SKU **bất biến**, `stock_uom` = đơn vị cơ sở, `has_batch_no`, Item Barcode **duy nhất**, Brand, Item Default supplier, `Item.taxes` để trống — thuế đặt theo dòng); hạn dùng chỉ bật cho hàng có hạn; ngừng bán = `npp_ngung_ban` (không phải `Item.disabled`) | ⚠ CFD-10 |
| `product_units` (hệ số nguyên) | UOM + UOM Conversion Detail (số thực — cho phép lẻ) | ✅ |
| `price_lists` (4 bậc tra giá, giá theo ĐÚNG đơn vị, nhóm NULL = chung, **không có lịch sử**) | Price List "Giá chuẩn" + "Giá nhóm X"; Item Price **một dòng** cho mỗi mặt hàng × bảng × đơn vị, sửa tại chỗ, app luôn lấy dòng hiện hành (không theo ngày chứng từ); **bộ tra giá 4 bậc viết trong app** (`ignore_pricing_rule = 1`, không để lõi đè giá) | ✅ |
| `purchase_price_lists` (một giá / mặt hàng / đơn vị, cập nhật từ phiếu nhập) | Price List "Giá nhập" (buying) + hook sau khi ghi sổ PI | ✅ |
| `suppliers` (gộp, xoá kèm hàng) | Supplier `NCC-.####` + Custom Field; gộp = rename-merge của Frappe; xoá kèm hàng = method | ✅ |
| `user_suppliers` (NVBH chỉ thấy hàng công ty mình) | child trên `NPP Nhan Vien` + lọc ở method danh mục (không cấp đọc Item trực tiếp) | ✅ |
| `expense_categories`, `hr_monthly_bonus` | tài khoản chi phí (Account) + nhóm bucket; `NPP Thuong Thang` | ≈ |
| `approval_rules`, `pricing_rules.date_warehouse_threshold_days`, `danh_muc_ban_phien` | `NPP Cai Dat` (số phiên tăng bằng hook) | ✅ |
| `payments` (khoản thu theo từng khoản nợ), `reports_config`, `swap_stock_movements`, `giam_don_goc` | dòng tham chiếu của Payment Entry; bỏ; bỏ; không cần bảng (method nhận cả đơn một lượt, luật "chỉ kiểm khi tăng giảm giá" giữ) | ✅ |

### 4.2 Bán hàng
| nppsale | ERPNext / app npp | Mức |
|---|---|---|
| `sales_orders` Nháp → Phiếu tạm (sửa thoải mái) → Hoàn thành / Đã huỷ; nháp chỉ **người đứng tên** thấy (mig 161); NVBH sửa đơn của mình; chủ / QL mới gán đơn cho người khác (mig 153 / 155); xoá đơn nháp của mình / đã huỷ kèm dọn phiếu trả | Sales Order **giữ docstatus 0** suốt Nháp / Phiếu tạm / Đã huỷ (`npp_trang_thai`; huỷ Phiếu tạm là đổi trường, giữ mã), tự điền ngày giao ≥ ngày đặt (lõi đòi ngay khi lưu), **ghi sổ ngay trước khi lập HĐ** trong cùng method rồi Hoàn thành (lõi: Completed hoặc Closed); SO đã ghi sổ mà HĐ bị huỷ → docstatus 2. Nháp lọc theo người đứng tên, guard gán người, xoá đơn = method dọn `NPP Phieu Tra` nháp rồi `delete_doc` | ✅ (mã đơn: ≈) |
| Mã `DH-0001`, sửa lần n → `DH-0001-n` (đổi tại chỗ) | naming series `DH-.####`; sửa nháp không đổi tên → hiện "sửa lần n" bằng cột riêng | ≈ |
| `create_order_with_lines` (idempotent; trigger trần giá / giảm giá; luật mig 226 "có sẵn giảm thì chỉ kiểm khi tăng") | method `tao_don` / `sua_don` + luật thuần Python so khoản giảm mới với cũ | ✅ |
| Hạn mức: nợ sẵn có + đơn này so `credit_limit`, **chỉ cảnh báo** | giữ ở method với `no_khach` (gồm tiền chưa phân bổ); hạn mức lõi để trống ba cấp (3.11) | ✅ |
| Tồn khả dụng = kho bán − đã đặt (Phiếu tạm) | method tính từ Bin kho bán − dòng SO Phiếu tạm | ✅ |
| Gợi ý giá gần nhất (`loadLastPrices`, bỏ hàng đổi), Hàng hay lấy (90 ngày), Đặt lại đơn (giá hôm nay, bỏ hàng ngừng bán) | method `gia_gan_nhat`, `hang_hay_lay`, `dat_lai_don` | ✅ |
| `post_invoice` — **Xuất hàng**: trừ kho FIFO kho bán, HĐ, công nợ, phiếu trả kèm, đơn Hoàn thành, một giao dịch; xuất thiếu = xong; một đơn một HĐ; HĐ mới tra hệ số danh mục (mig 174) | method `xuat_hang`: cập nhật hệ số dòng SO theo danh mục → ghi sổ SO → Sales Invoice `update_stock = 1` từ kho bán, **app gán lô FIFO cho từng dòng**, tờ ghi có độc lập cho hàng trả kèm (CFD-03), đóng SO = Hoàn thành, chặn HĐ thứ hai; một request = một giao dịch. Phần vượt số đặt / đổi giá / đổi đơn vị: vai dịch vụ được vượt (3.11) hoặc dòng không nối | ✅ |
| `sales_invoices` posted / cancelled, `HD-0001`, sửa → `HD-0001-1` | Sales Invoice docstatus 1 / 2; amend tạo đúng `HD-0001-1` (cài đặt Amend Counter) | ✅ |
| Dòng HĐ: `unit_price` sau giảm, `line_discount` ghi nhớ, `conversion_factor` chụp, `vat_rate` chụp, `is_exchange` | Sales Invoice Item: `price_list_rate` = giá bảng theo nhóm, `discount_amount` (tuyệt đối, đã làm tròn — không gửi %), `rate`, `uom` + `conversion_factor`, Item Tax Template; cờ hàng đổi | ✅ |
| Thuế theo dòng, giảm giá cả đơn **sau** thuế (không hạ nền thuế), % tính trên tiền gộp, làm tròn ở tổng | Sales Taxes template "VAT theo mặt hàng" (lõi cộng từng dòng rồi làm tròn một lần ở dòng thuế — cùng dạng `round(Σ dòng × suất)`), giảm giá cả đơn bằng `is_cash_or_non_trade_discount` + số tiền tuyệt đối do app tính (% của lõi tính trên tổng gồm VAT), `rounded_total` | ✅ (so số ở PoC: ≈) |
| `invoice_date` DATE giờ VN, ghi lùi / tiến tự do; hạn nợ = ngày + NETn | `posting_date` (+ `set_posting_time`), Payment Terms Template COD / NET7…60 → `due_date`; **ngày tương lai bị lõi chặn, lùi ngày chỉ khi lô đủ tại ngày đó** | ⚠ CFD-12 |
| **Sửa HĐ** (`reissue_invoice`): huỷ + lập lại, giữ số gốc đuôi `-n`, phiếu thu đi theo, giữ hệ số tờ cũ (mig 247), hỏi "huỷ phiếu nhập trước?" | method `sua_hoa_don`, đúng thứ tự lõi đòi: mở SO đã đóng → huỷ tờ ghi có kèm (+ bút toán cấn trừ nội bộ nếu có) → huỷ SI (lõi gỡ phân bổ phiếu thu) → amend (chép hệ số tờ cũ = hệ số SO, dọn trường no_copy) → ghi sổ → lập lại tờ ghi có → **phân bổ lại** tiền phiếu thu sang tờ mới (Payment Reconciliation, số phiếu thu không đổi) → đóng SO | ⚠ CFD-01, CFD-04, CFD-07, CFD-12 |
| **Huỷ HĐ** → hoàn kho đúng lô, xoá nợ, đơn Đã huỷ, phiếu trả Nháp / Chờ xử lý huỷ; khoá khi có tiền thu / đã phát hành HĐĐT / **đã có phiếu trả nhập kho** (`LOCKED_RETURN_DONE`) | mở SO đã đóng → huỷ tờ ghi có → huỷ SI (lõi tự trả kho về đúng lô) → huỷ SO; ba khoá kiểm ở method (tờ ghi có độc lập nên lõi không tự chặn khi phiếu trả đã nhập kho — app phải chặn) | ✅ |
| `assign_doc_seller` (đổi người đứng tên **HĐ / phiếu trả**, nợ đi theo; đơn thì sửa đơn) | Custom Field `allow_on_submit` + method | ⚠ CFD-02 |
| `returns` **tự sinh** (Chờ xử lý: nợ trừ ngay, kho treo) / **tự lập** (hoàn thành = nhập kho + trừ nợ), trả bất kỳ hàng (mig 158), giá trả tới trần theo vai (mig 230), trả vượt HĐ → nợ âm (mig 186), phí trả hàng, nhập lại vào lô mới nhất / lô `RESTOCK-…` với giá vốn lô đã xuất (mig 127), `PT-0001` | `NPP Phieu Tra` (PT-.####) bọc **tờ ghi có độc lập** (không `return_against`; HĐ gắn bằng trường riêng): tự sinh = tờ ghi có không kho lập ngay lúc Xuất hàng + Stock Entry nhập kho khi Hoàn thành (huỷ nhập = huỷ SE, về Chờ xử lý); tự lập = tờ ghi có có kho (nhập kho + ghi có cùng lúc, app chọn lô nhập lại và `incoming_rate` theo luật mig 127). Nợ theo HĐ do app tính (có thể âm) | ⚠ CFD-03 |
| Hàng đổi (xuất 0đ, nhập lại không tính tiền) | dòng SI 0đ cờ hàng đổi + Stock Entry nhập lại (dòng bán phải SL dương; dòng đổi cùng mặt hàng cùng lô với dòng bán thì gộp hoặc dùng lô khác) | ≈ |
| `near_expiry_skipped`, `short_qty` | `near_expiry_skipped` tính trong method sau khi chọn lô; `short_qty` **không còn** (CFD-05) | ⚠ CFD-05 |
| `luot_soan` (nhặt tổng → chia rổ A–Z, không trừ kho), mã `SH-dd/mm-NN` | `NPP Luot Soan` (`SH-.DD.MM.-.##` — dãy Frappe không nhận `/`) + cờ đã soạn trên SI | ✅ |
| `entity_locks` (khoá sửa đồng thời, nhịp 60 s, nhả là người chờ lấy ngay qua realtime) | `NPP Khoa Chung Tu` + method heartbeat + `publish_realtime` | ✅ |
| `order_activity_log`, `order_status_history` | Frappe Version (track_changes, kể cả child; chỉ sinh khi method dùng `doc.save()`) + `NPP Thong Bao` cho hành động chéo chứng từ (xuất / huỷ HĐ) | ≈ |
| Chênh lệch giá nhân viên (so **giá bảng chung hiện hành** đúng đơn vị, không phải giá chụp lúc bán — chủ nhà 01/10/2026) | method báo cáo đọc Item Price "Giá chuẩn" theo UOM **tại lúc chạy**, không đọc `price_list_rate` chụp trên SI; giữ nguyên `src/lib/analytics/chenh-lech.ts` | ✅ |
| `workflow_sessions` | bỏ (POS / giỏ đã giữ trạng thái ở trình duyệt) | bỏ |

### 4.3 Tiền
| nppsale | ERPNext / app npp | Mức |
|---|---|---|
| `receivables`: một dòng / HĐ ghi sổ; **có thể âm**; `paid > amount` = dư có; trạng thái do trigger | `outstanding_amount` của Sales Invoice − Σ tờ ghi có gắn HĐ (trường riêng) do app cộng = "nợ theo HĐ" (âm được); dư có = tờ ghi có độc lập / tiền chưa phân bổ của phiếu thu | ⚠ CFD-03, CFD-04 |
| Nợ của khách = Σ(amount − paid) không kẹp 0, gồm cả trả dư (mig 212); theo NV (`sales_user_id`, `giao_tu_nv`, về NPP khi nghỉ) | method `no_khach` = số dư phải thu theo sổ cái của Customer (HĐ + tờ ghi có + tiền chưa phân bổ + bút toán), dùng cho POS, hạn mức, danh sách; Custom Field NV giữ nợ trên SI / tờ đầu kỳ | ✅ |
| Nợ đầu kỳ (Excel, upsert theo `id`; sửa tự do khi chưa thu) | Opening Invoice Creation Tool hoặc method của app lập SI `is_opening = Yes` (giữ **mã HĐ cũ** bằng `set_name` / hook `autoname` — lõi xoá tên tự đặt khi không có cờ nhập liệu, kiểm ở P0; ngày HĐ gốc / hạn; NV giữ nợ ghi thêm sau; dãy `HD-` đặt điểm bắt đầu lớn hơn số cũ); **sửa số tiền = huỷ + amend** (`HD-0012-1`), khoá khi đã thu; công cụ ghi từng tờ (lỗi giữa chừng để lại phần đã ghi — app báo rõ) ; báo cáo của app tự loại `is_opening` | ⚠ CFD-01 |
| `/receivables/[id]`: xác nhận thanh toán tay, xoá khoản nợ | tờ đầu kỳ: thu bằng Payment Entry; xoá = huỷ + xoá SI chưa có phiếu thu; HĐ thật: không ghi tay (nợ suy từ sổ) | ≈ |
| Tuổi nợ 0 / 1–30 / 31–60 / > 60 (và 5 bậc ở Báo cáo tổng hợp) | method tính từ `due_date` | ✅ |
| `cash_receipts`: **trừ nợ ngay lúc lập** cho mọi vai có `receivables.create` (status `received`; `pending` chỉ còn ở luồng chuyến giao cũ); một khách; phân bổ do người chọn; `use_credit`; `client_key`; huỷ có lý do; in TT200 | Payment Entry (Receive) **ghi sổ ngay** khi lập (nợ giảm như hôm nay); "Chờ xác nhận / Đã nhận" = dấu `npp_trang_thai` + người xác nhận (`allow_on_submit`), không ảnh hưởng nợ; huỷ = cancel PE (giữ vết + lý do); tham chiếu nhiều HĐ; Mode of Payment cash / transfer / ewallet; **"dùng dư có" = bút toán cấn trừ nội bộ** (Journal Entry qua Payment Reconciliation) lập cùng lúc, in chung một phiếu | ⚠ CFD-04 (số phiếu: câu 13) |
| Thu vượt số nợ → chặn (`BAD_RECEIVABLE_LINE`) | lõi cũng chặn phân bổ vượt số còn nợ của từng tờ; phần thừa = tiền chưa phân bổ | ⚠ CFD-04 |
| `payables`, `payables_by_supplier` (gộp − trả − đã TT) | outstanding của Purchase Invoice (+ debit note độc lập mang nợ âm riêng); bảng theo NCC = method | ✅ |
| `record_payable_payment` ("Ghi trả" / "Bù trừ" một dòng nợ NCC), `/payables/new` (ghi nợ NCC tay), `/payables/[id]` (đặt lại trạng thái mở, xoá) | ghi trả một dòng = Payment Entry (Pay) tham chiếu đúng một PI; bù trừ debit note vào PI = bút toán cấn trừ nội bộ (như CFD-04 phía khách; huỷ phiếu trả NCC = huỷ bút toán trước — tương đương khoá `DA_CAN_TRU`); ghi nợ tay = PI `is_opening` / Journal Entry qua method; "đặt lại trạng thái mở" **bỏ** (trạng thái suy từ số còn nợ) | ⚠ CFD-04 |
| `supplier_payments` `PCNCC-0001`: trả khoản cũ nhất trước, dư thành trả trước, tự trừ phiếu nhập sau | Payment Entry (Pay) + phân bổ cũ-trước trong method; dư = tiền ứng trước, `allocate_advances_automatically` khi ghi sổ PI mới | ✅ |
| `expenses` (phiếu chi chi phí, trả lúc / chưa trả), hao hụt kiểm kê ghi chi phí | `NPP Phieu Chi` → Journal Entry (tiền ↔ tài khoản chi phí); `NPP Kiem Ke` khi duyệt sinh kèm phiếu chi hao hụt (chưa trả) | ≈ |
| `finance_pnl`, `finance_cash_flow`, `finance_balance_sheet` (kiểu nppsale) | method đọc chứng từ như hôm nay; sổ cái ERPNext **có thêm** báo cáo kế toán chuẩn (câu 9) | ✅ |

### 4.4 Kho và mua hàng
| nppsale | ERPNext / app npp | Mức |
|---|---|---|
| `batches`: lô / hạn dùng, `unit_cost` theo đơn vị cơ sở, vùng sale / date, tự sang date **ngay lúc nhập** khi gần hạn | Batch (hạn dùng, NSX) + giá vốn theo lô (bình quân trong lô — bằng giá dòng nhập khi mỗi dòng một lô như nppsale); hai Warehouse **Kho bán** / **Kho cận date**; hook sau ghi sổ nhận thẳng lô gần hạn vào kho date; việc đêm quét lô cũ | ✅ |
| `/inventory/batches/new` (tạo lô tay), `/inventory/batches/[id]` (sửa mã lô / HSD, xoá), "Rà soát kho date" | tạo lô tay = Stock Entry Material Receipt tạo Batch kèm (method); sửa HSD = sửa `Batch.expiry_date`; **đổi mã lô khi đã có sổ kho** = method app gọi `rename_doc("Batch", cũ, mới, force=True)` (*[PoC 06/11: đổi trọn vẹn; Desk / đường thường thì bị chặn]*); xoá chỉ khi chưa có sổ; rà soát = chạy tay việc quét lô | ≈ |
| FIFO theo ngày nhập, chỉ kho bán; trả NCC / hụt kiểm kê xuất hạn cũ trước | app tự chọn lô (sắp xếp theo luật từng chứng từ) rồi gán vào dòng; không dùng máy tự chọn của lõi | ✅ |
| Bán / xuất âm khi bật `allow_oversell`, phần thiếu không gắn lô (mig 086 / 222 / 238) | **không có tương đương**: lõi chặn lô âm vô điều kiện | ⚠ CFD-05 |
| Giá vốn / COGS theo lô, `stock_line_consumptions` | Stock Ledger Entry + bundle lô (huỷ trả đúng lô) | ✅ |
| `stock_entries` import / export / transfer; draft → posted → cancelled; màn Nhập kho **kèm công nợ NCC** khi chọn NCC + tiền (`post_stock_import` với `payable`) | Stock Entry Material Receipt / Issue / Transfer; docstatus; Stock Entry của lõi **không sinh nợ NCC** → nhập kho có NCC + tiền phải là Purchase Invoice (chính là phiếu nhập PN) hoặc bỏ ô công nợ ở màn Nhập kho | ⚠ CFD-13 |
| Kiểm kê: đếm → chờ duyệt → `post_stock_adjustment` (hụt FEFO, giá trị hụt ghi chi phí) / từ chối | `NPP Kiem Ke` → **phiếu nhập / xuất điều chỉnh theo lô** (Stock Entry) + phiếu chi hao hụt khi duyệt; không dùng Stock Reconciliation | ⚠ CFD-09 |
| Thẻ kho, tồn kho hiện tại (`ton_kho_trang`), tra soát, `stock_value_summary` | Stock Ledger / Bin + method phân trang | ✅ (hình thức phiếu: ≈) |
| Hàng cận date không bán (mig 138) | kho bán / kho cận date; thêm: hàng **quá hạn** không xuất được trên HĐ (lõi chặn), thanh lý qua phiếu xuất kho | ⚠ CFD-10 |
| `purchase_invoices` `PN-0001` (số cấp **lúc hoàn thành**, nháp chưa có số) draft → completed → cancelled; mỗi dòng một lô `PN-xxxx-NNN`; giảm dòng trừ thật; `vat_override`; giảm đầu phiếu sau thuế không vào giá vốn; nợ NCC | Purchase Invoice `update_stock = 1`, kho nhận theo phiếu, Batch tạo theo dòng (giữ cách đặt mã), `discount_amount` dòng, thuế gõ tay = dòng thuế kiểu Actual, outstanding = nợ NCC; **số cấp lúc lập nháp** (câu 18); **giảm đầu phiếu**: xem CFD-11 | ⚠ CFD-11 |
| `sua_phieu_nhap` (sửa tại chỗ phiếu đã bán, giữ lô, tính lại giá vốn phần đã bán, sửa nợ), huỷ khi bật tồn âm, **khôi phục phiếu đã huỷ** (mig 241) | chưa xuất lô nào: huỷ + amend (`PN-0042-1`), lô giữ nguyên tên; khôi phục = amend từ tờ huỷ (số mới `-1`); **đã xuất**: sửa giá bằng Landed Cost Voucher (tăng hoặc giảm giá vốn, tờ PN giữ số) + debit note / bút toán cho công nợ NCC; sửa số lượng / lô / NCC không được; huỷ không được | ⚠ CFD-01, CFD-06, CFD-07 |
| `supplier_returns` `PTNCC-0001`, FIFO theo hạn qua nhiều phiếu nhập, nợ NCC âm, sửa = huỷ rồi gửi lại giữ số, khôi phục | Purchase Invoice `is_return = 1` **độc lập** (không `return_against`) `update_stock = 1`, app gán lô; nợ âm nằm trên chính tờ; sửa / khôi phục = huỷ + amend `-1` | ⚠ CFD-01 |
| Bảng giá nhập, đề xuất đặt hàng (Σ đặt chưa xuất − tồn, theo NCC chính) | Price List "Giá nhập"; method đề xuất | ✅ |
| Nhập Excel sản phẩm kèm "Tồn kho" / "Giá vốn" → phiếu nhập tồn đầu kỳ (`opening-stock-plan.ts`) | method `nhap_ton_dau_ky` tạo Batch + Stock Entry theo thứ tự ngày | ✅ |
| Đơn mua PO (di sản) | bỏ | bỏ |

### 4.5 Khác
| nppsale | ERPNext / app npp | Mức |
|---|---|---|
| HĐĐT MISA (publish / sync / refresh / snapshot / đối soát 4 tầng / khoá sửa HĐ đã phát hành) | DocType riêng + Python theo skill `einvoice-misa-sync` (đã chạy thật trên app `ketoan`); việc nền xếp hàng sau commit | ✅ |
| Lương: doanh số = HĐ ghi sổ − hàng trả theo `revenue_date` (mig 126 / 192), bậc KPI, dưới 60 %, BHXH 10,5 %, khoá kỳ, phiếu lương của tôi, chấm công tay; **thưởng số đơn đếm ĐƠN** theo `order_date` | DocType riêng, công thức chép từ mig 096 / 126 / 173 — nguồn doanh số **giữ nguyên**; thưởng số đơn: đếm đơn như cũ hay đếm HĐ (câu 7) | ✅ (một tham số: hỏi) |
| Khuyến mãi, Hoa hồng (chỉ danh mục) | DocType riêng y như cũ, hoặc bỏ | hỏi (câu 6) |
| Thông báo chuông (in-app, realtime) | `NPP Thong Bao` + `publish_realtime` | ✅ |
| QR đăng nhập, đăng nhập thay (mở trình duyệt khác), nhân viên nghỉ việc | mục 3.6 + method | ✅ |
| Sao lưu (GitHub Actions → age → Drive) | `bench backup` theo lịch + script đẩy Drive kèm `site_config.json` (3.11) | ≈ |
| Bảo trì (rewrite 503 + cookie bỏ qua) | `maintenance_mode` của bench + trang riêng | ≈ |
| Service worker, PWA, offline đơn hàng | giữ luật; cách phục vụ `sw.js` / manifest theo 3.7 (phục vụ đã thử ở PoC; header qua nginx / Cloudflare thật kiểm ở P2) | ≈ |
| `/api/client-error`, `/api/do-nap` | method ghi Error Log / `NPP Do Nap` | ✅ |
| Chuyến giao | bỏ | bỏ |

---

## 5. Lõi ERPNext buộc phải khác — cần anh duyệt từng mục

Mỗi mục ghi: nppsale đang làm gì → lõi làm gì (đã kiểm bằng mã nguồn) → em đề xuất → người dùng thấy gì.

### CFD-01 · Sửa chứng từ đã ghi sổ = huỷ tờ cũ + tờ mới có đuôi `-1`, `-2`
- **nppsale**: Hoá đơn bán đã làm đúng thế (`HD-0042-1`, mig 128 / 151). Nhưng **phiếu nhập NCC** sửa tại chỗ giữ `PN-0042` (mig 235), **phiếu trả NCC** "huỷ rồi gửi lại giữ số" (mig 240), **khôi phục** phiếu nhập / trả NCC đã huỷ về đúng số cũ (mig 241), **nợ đầu kỳ** nhập lại Excel là cập nhật tại chỗ (mig 102), **đơn hàng** sửa tại chỗ nhưng đổi mã `DH-0042-1`.
- **Lõi**: chứng từ đã ghi sổ là bất biến; sửa hay khôi phục = Cancel + Amend, tờ mới tên `PN-0042-1` (khi Document Naming Settings giữ `Amend Counter` — mặc định), tờ cũ còn nguyên ở trạng thái Đã huỷ (tra được, không in nhầm); tờ huỷ không "bỏ huỷ" được. *[PoC 06/11: HĐ `…00101` → `…00101-1` → `…00101-2`, tờ cũ Đã huỷ; tờ amend **không mang gói lô cũ** — lõi tự chọn lô theo luật của lõi, nên method Sửa HĐ phải gán lô lại theo luật app.]*
- **Đề xuất**: một luật cho mọi chứng từ ghi sổ: "sửa / khôi phục là ra tờ `-n`, số gốc giữ" (như HĐ bán hôm nay); nợ đầu kỳ đổi số tiền cũng vậy (khoá khi đã thu). Đơn hàng (chưa ghi sổ) sửa tại chỗ, **không đổi mã**, hiện thêm "sửa lần n".
- **Người dùng thấy**: phiếu nhập / trả NCC / tờ đầu kỳ sau khi sửa hoặc khôi phục mang đuôi `-1`; danh sách ẩn tờ đã huỷ theo mặc định (có nút hiện).

### CFD-02 · Trường sửa được sau khi ghi sổ phải khai trước
- **nppsale**: sau khi ghi sổ vẫn đổi được người đứng tên HĐ / phiếu trả (`assign_doc_seller`), ngày phiếu trả hiển thị, ngày nhập kho phiếu tự sinh, ghi chú, cờ soạn hàng, trạng thái HĐĐT, dấu xác nhận phiếu thu.
- **Lõi**: chỉ trường khai `allow_on_submit` mới ghi được sau ghi sổ (gotcha #7); tiền, kho, ngày ghi sổ, khách hàng thì không.
- **Đề xuất**: khai sẵn nhóm trường "mềm": NV được gán, NV giữ nợ, ghi chú, cờ soạn hàng, các trường MISA, ngày hiển thị của phiếu trả, HĐ gắn / phiếu trả gắn trên tờ ghi có, dấu xác nhận phiếu thu. Còn **ngày ghi sổ, tiền, số lượng, lô, kho**: muốn đổi là huỷ + lập lại (nppsale cũng vậy với tiền / kho; riêng *ngày HĐ* hôm nay sửa qua `reissue_invoice` — vẫn giữ được vì đó là huỷ + lập lại, trong giới hạn CFD-12).

### CFD-03 · Phiếu trả: mọi tờ ghi có là tờ **độc lập**, "Chờ xử lý" là hai chứng từ lõi dưới một phiếu
- **nppsale**: phiếu tự sinh trừ nợ vào HĐ ngay lúc xuất, kho treo ở Chờ xử lý; hoàn thành = nhập kho; huỷ nhập kho = về Chờ xử lý (mig 191 / 216). Phiếu trả được chứa **bất kỳ mặt hàng** (mig 158), đơn giá trả tới **trần theo vai** — chủ / kế toán không giới hạn (mig 230), trả **nhiều hơn xuất** thành nợ âm trên HĐ (mig 186), ngày phiếu tự sinh = ngày HĐ, hàng về **lô mới nhất cùng mặt hàng** hoặc lô `RESTOCK-…` với giá vốn của lô đã xuất (mig 127). (Ô "phí trả hàng" ở màn POS chỉ để tính tiền trả khách tại quầy, **không lưu** vào sổ — tiền ghi có luôn là Σ dòng trả — nên không có gì để ánh xạ.)
- **Lõi** (đã kiểm): tờ ghi có **gắn HĐ** (`return_against`) bị trói: chỉ mặt hàng của HĐ ấy, số lượng ≤ đã xuất, **đơn giá ≤ giá đã bán**, giờ ghi sổ ≥ giờ HĐ, và chỉ trừ thẳng vào HĐ khi tiền trả ≤ số còn nợ của HĐ — vượt là lõi tự tách thành tờ ghi có mang nợ âm riêng; số còn nợ của HĐ không bao giờ âm vì hàng trả. Tờ ghi có không kho cũng không thể "nhập kho sau": kho hoặc cùng lúc, hoặc không bao giờ. **Nhập lại một lô đã hết hạn** (Material Receipt / PI có ghi `batch_no` ở dòng) bị lõi chặn `BatchExpiredError` — hàng trả quá date là ca thường ngày của NPP. **Giá vốn nhập lại** của tờ ghi có độc lập có kho: lõi chỉ lấy bình quân lô **trong kho nhận**; lô đã bán hết hoặc trả về kho khác kho xuất → lõi rơi về **giá bán** của dòng trả (sai giá vốn và lãi gộp) nếu app không tự điền. *[PoC: đặt `incoming_rate` 8.105,52 → sổ ghi đúng 8.105,52; gửi 0 hoặc không gửi mà lô chưa có / đã hết ở kho nhận → **11.150,7 = giá bán** dòng trả; không gửi mà lô đang có ở kho nhận → 9.628,11 = bình quân lô tại kho ấy; giá vốn sai còn **lan sang HĐ bán sau** lô ấy (hai HĐ bán tiếp lô bị tính 11.150,7).]*
- **Đề xuất**: người dùng vẫn chỉ thấy **một** `NPP Phiếu trả PT-0042` với đúng trạng thái và đúng luật nppsale. Dưới sổ: (a) tờ ghi có **độc lập** (không `return_against`; HĐ gắn ghi ở trường riêng) nên bất kỳ hàng / bất kỳ giá trong trần của app / bất kỳ số tiền đều lập được; (b) với phiếu tự sinh: tờ ghi có không kho lập ngay lúc Xuất hàng (giờ ghi sổ sau HĐ vài giây), phiếu nhập kho (Stock Entry, lô và giá vốn theo luật mig 127) khi Hoàn thành, huỷ được để về Chờ xử lý; phiếu tự lập = một tờ ghi có có kho (nhập kho + ghi có cùng lúc); (c) app **luôn tự điền** `incoming_rate` / `basic_rate` = giá vốn lô đã xuất (đọc từ gói lô — `Serial and Batch Entry` — của HĐ gốc, không từ `SLE.batch_no` vốn trống với dòng có gói lô) cho từng dòng nhập lại; hàng trả **quá hạn**: nhập bằng bundle Inward do app lập, không ghi `batch_no` ở dòng — *[PoC đã chứng minh: Material Receipt kèm bundle Inward và cả tờ ghi có có kho đều nhận lô đã hết hạn; chỉ dòng ghi `batch_no` mới bị `BatchExpiredError`]*; (d) **nợ theo HĐ** = số còn nợ của HĐ − Σ tờ ghi có gắn HĐ, do app tính — âm được như nppsale; tổng nợ khách lấy từ sổ cái vẫn đúng.
- **Người dùng thấy**: không khác. Kế toán mở sổ cái ERPNext sẽ thấy từng tờ ghi có mang số riêng (`HDT-0042`), nợ của HĐ gốc trên Desk là số **chưa trừ** hàng trả (số đã trừ chỉ ở portal và báo cáo của app).

### CFD-04 · Phiếu thu, tiền thu dư, dư có và bút toán cấn trừ (cả phía khách lẫn phía NCC)
- **nppsale**: phiếu thu **trừ nợ ngay lúc lập** cho mọi vai được lập (kể cả NVBH ở màn Thu tiền); nút "Xác nhận" chỉ là dấu kế toán; `receivables.paid > amount` ngay trên dòng nợ của HĐ là hợp lệ (dư có); phiếu thu có ô "Dùng số dư có"; sửa / huỷ phiếu trả đã dùng dư có vẫn được, nợ tự tăng lại (mig 191); phía NCC có "Ghi trả / Bù trừ" từng dòng nợ và khoá `DA_CAN_TRU`.
- **Lõi** (đã kiểm): Payment Entry nháp **không ghi sổ** (nợ không giảm) — nên không dùng nháp làm "Chờ xác nhận"; Payment Entry **phải có tiền > 0**, không phân bổ quá số còn nợ của từng tờ, phần thừa là **tiền chưa phân bổ** (tiền ứng trước); cấn dư có **không thu tiền** không lập được bằng Payment Entry mà bằng bút toán đối trừ (Journal Entry qua Payment Reconciliation); tờ ghi có đã được phân bổ trong một phiếu thu nhiều dòng thì không huỷ được cho tới khi phiếu thu ấy được lập lại.
- **Đề xuất**: phiếu thu của app = Payment Entry **ghi sổ ngay** (nợ giảm tức thì như hôm nay) **+ bút toán cấn trừ nội bộ** cho phần dư có, lập và huỷ cùng nhau, in chung một tờ TT200; "Chờ xác nhận / Đã nhận" là dấu trên tờ (không chạm sổ); dư có **không bao giờ** nằm trong Payment Entry → huỷ / sửa phiếu trả đã dùng dư có = app tự huỷ bút toán nội bộ rồi lập lại, **số phiếu thu không đổi**. Cùng luật cho NCC: "Ghi trả" một dòng = Payment Entry (Pay); "Bù trừ" debit note = bút toán nội bộ; huỷ phiếu trả NCC đã bù trừ = huỷ bút toán trước. Màn Công nợ hiện thêm dòng "Tiền thừa chưa phân bổ" và `no_khach` gồm cả khoản ấy (đúng mig 212). "Sửa HĐ có tiền thu": lõi gỡ phân bổ khi huỷ HĐ, app phân bổ lại sang tờ mới, số phiếu thu không đổi (đúng ý mig 184).
- **Người dùng thấy**: như cũ; khác duy nhất là cục dư có hiện ở dòng riêng thay vì "đã thu vượt" trên HĐ.

### CFD-05 · Bán / xuất vượt tồn với hàng theo lô — **lõi không cho**
- **nppsale**: bật "Cho phép bán vượt tồn kho" thì Xuất hàng, xuất kho lẻ, trả NCC đều ghi được khi thiếu hàng, phần thiếu không gắn lô (mig 086 / 138 / 222); huỷ phiếu nhập đã xuất bớt cũng được khi bật (mig 238).
- **Lõi** (đã kiểm): mọi dòng xuất của mặt hàng theo lô phải có lô; số dư hiện tại của lô **không bao giờ** được âm — kiểm hai lớp, bỏ qua mọi cài đặt (`allow_negative_stock_for_batch` chỉ tha cho âm **trong quá khứ** do ghi lùi ngày, số dư hiện tại vẫn phải ≥ 0). Tồn âm chỉ có với mặt hàng **không theo lô**. *[PoC]* Thêm một hệ quả: app **chọn lô** bằng câu đọc thường nên đọc theo **ảnh chụp cũ của giao dịch** (MariaDB REPEATABLE READ), còn lõi **kiểm** số dư lô bằng câu đọc có khoá (`FOR UPDATE`, thấy số mới nhất) — 5 phiên cùng bấm Xuất hàng trên hàng trùng lô, lô gần hết: **4/5 hỏng** `BatchNegativeStockError` (lượt làm nóng không đồng bộ cũng hỏng 4/5); lô còn nhiều thì 1/5 **bế tắc** (MariaDB 1213). App khoá hàng `Bin` của từng mặt hàng (`SELECT … FOR UPDATE`, theo thứ tự tên) làm **câu đầu tiên** của giao dịch Xuất hàng → 5/5 ghi được, nối đuôi ~0,7–1 s / HĐ. Đây là luật bắt buộc của method `xuat_hang` (và xuất kho lẻ, trả NCC, điều chỉnh kiểm kê, Sửa HĐ), kèm thử lại một lần khi gặp lô âm hoặc bế tắc — như `post_invoice` của nppsale khoá dòng đơn.
- **Ba đường, anh chọn một** (câu 14 — anh đã chọn **B**, mục 0a):
  - **A (đề xuất)**: **bỏ luật bán vượt tồn** cho hàng theo lô. Đơn hàng (Phiếu tạm) vẫn đặt vượt tồn như hôm nay; nút **Xuất hàng** / xuất kho / trả NCC chặn khi lô không đủ, câu báo nói rõ thiếu bao nhiêu và hàng đang ở kho nào — nhập kho rồi xuất. Đây là cách ERPNext thiết kế và cũng là trạng thái mặc định của nppsale (`allow_oversell = false`).
  - **B**: mặt hàng nào cần bán âm thì **không theo dõi lô** (mất hạn dùng, FIFO theo lô, kho cận date cho mặt hàng đó); quyết theo từng mặt hàng.
  - **C**: app tự lập **phiếu nhập đệm** vào một lô tạm trong cùng giao dịch cho phần thiếu, giá vốn tạm theo giá nhập gần nhất; NPP nhập phiếu nhập thật sau và app đối trừ lô đệm. Giữ được thói quen nhưng tồn / giá trị kho tạm thời ảo và phải đối chiếu — em không khuyến nghị.
- **Người dùng thấy** (A): thao tác xuất hàng khi thiếu tồn bị chặn thay vì cảnh báo "xuất thiếu"; dải cảnh báo `short_qty` biến mất.

### CFD-06 · Sửa / huỷ phiếu nhập mà hàng đã bán
- **nppsale**: sửa tại chỗ được miễn SL mới ≥ đã xuất, giá vốn phần đã bán tính lại ngay (mig 235); huỷ khi bật tồn âm (mig 238); khôi phục phiếu đã huỷ (mig 241).
- **Lõi** (đã kiểm): huỷ tờ nhập đã có lô xuất đi → lô âm tức thì → **chặn bất kể cài đặt** (hệ quả của CFD-05); không có cách "cho âm tạm trong một giao dịch". Sửa **giá** có công cụ riêng: Landed Cost Voucher (tăng hoặc giảm giá trị nhập theo lô, tự tính lại giá vốn phần đã bán, tờ PN giữ nguyên số). *[PoC: LCV −30.000 đ trên phiếu nhập 30 dòng đã bán được nhận, số phiếu giữ nguyên, **30** việc tính lại giá vốn (mỗi mặt hàng một việc) chạy 16,8 s; giá nhập lô SP001-L1 **8.109 → 8.105,52 đ** và HĐ đã xuất lô ấy được tính lại theo đúng giá mới (đọc qua gói lô; cột `valuation_rate` của sổ kho là bình quân mặt hàng tại kho, không phải giá vốn lô). Mới chạy LCV âm; LCV dương đo ở P2.]*
- **Đề xuất**: lô chưa xuất gì → huỷ + amend (`PN-0042-1`) như CFD-01; lô đã xuất → **chỉ sửa được giá** (LCV + điều chỉnh công nợ NCC bằng debit note / bút toán), **không sửa số lượng / lô / NCC, không huỷ**; muốn sửa số lượng thì huỷ các HĐ đã lấy lô ấy trước (app liệt kê giúp) hoặc lập phiếu điều chỉnh bổ sung.
- **Người dùng thấy**: màn "Sửa phiếu nhập" của tờ đã bán chỉ mở ô giá; nút Huỷ báo "lô đã xuất ở HĐ …".

### CFD-07 · Giá vốn tính lại chạy nền theo lịch
- **nppsale**: sửa phiếu nhập → giá vốn phần đã bán tính lại ngay trong RPC.
- **Lõi** (đã kiểm): chứng từ **không lùi ngày** được định giá ngay trong lượt ghi; nhưng sửa / huỷ chứng từ có chứng từ sau nó (Sửa HĐ, LCV, huỷ PN…) sinh việc "Repost Item Valuation" chạy nền: mặc định **mỗi giờ**, 15 phút nếu bật tính lại song song; app có thể tự xếp hàng ngay (vài giây tới vài phút). Trong lúc việc này chưa xong, chứng từ liên quan **tạm không huỷ được** ("Sửa HĐ" hai lần liền có thể phải chờ). *[PoC: huỷ HĐ 15 dòng mất 1,25 s, sinh 15 việc theo mặt hàng + kho, app gọi chạy ngay hết 4,2 s.]*
- **Đề xuất**: bật tính lại song song + app tự xếp hàng ngay sau mỗi lượt sửa / huỷ; màn báo cáo hiện "đang tính lại giá vốn (N chứng từ)"; nút Sửa HĐ báo "chờ tính lại giá vốn xong" thay vì lỗi lạ.

### CFD-08 · Quyền hai lớp, lọc dữ liệu trong method, không Desk
- Lớp Frappe là sàn (không ghi chứng từ tiền / kho; không đọc trực tiếp danh mục / chứng từ qua `frappe.client.*`); lớp NPP (ma trận ô × hành động theo vai, ghi đè từng người) + **vế lọc RLS chép lại trong từng method** là luật chính. User Permission của Frappe không dùng làm hàng rào chính (lý do ở 3.5).
- "Nháp đơn chỉ người đứng tên thấy, chủ NPP cũng không" (mig 161): giữ ở method; ở lớp Frappe chủ NPP đọc được (không ai thấy vì không có Desk).
- Mỗi NPP một site (mục 2.1): hết `org_id`, hết RLS; bù lại khi anh muốn xem nhiều NPP một chỗ thì phải gom qua API.

### CFD-09 · Kiểm kê không dùng Stock Reconciliation; hao hụt vẫn ra chi phí
- **nppsale**: kiểm kê → phiếu điều chỉnh chờ duyệt → duyệt là chênh lệch vào kho (hụt trừ lô theo hạn, giá trị hụt ghi `expenses` → lãi lỗ); sau đó vẫn huỷ / sửa HĐ cũ bình thường.
- **Lõi** (đã kiểm): phiếu Stock Reconciliation trên một lô **khoá toàn bộ lịch sử trước nó** của lô đó: mọi ghi sổ / huỷ chứng từ có ngày trước phiếu kiểm kê đều bị từ chối → sau một lần kiểm kê sẽ không huỷ / sửa được HĐ, phiếu nhập cũ hơn của các lô đã kiểm.
- **Đề xuất**: `NPP Kiem Ke` khi duyệt lập **phiếu nhập / xuất điều chỉnh theo lô** (Stock Entry Material Receipt / Issue, tài khoản điều chỉnh kho) thay cho Stock Reconciliation — kết quả kho như nhau, không khoá lịch sử — và lập kèm `NPP Phieu Chi` "Hao hụt kiểm kê" (chưa trả) để lãi lỗ kiểu nppsale vẫn có khoản ấy; thừa ghi thu nhập khác. ERPNext sẽ không có "phiếu kiểm kê" chuẩn của nó (màn kiểm kê của người dùng giữ nguyên).

### CFD-10 · Ràng buộc danh mục và lô của lõi
- **Mã vạch duy nhất toàn site**: nppsale chỉ cảnh báo trùng mã vạch giữa hai mặt hàng; lõi từ chối. Đề xuất: chuyển dữ liệu báo danh sách mã vạch trùng để anh xử lý trước ngày cắt chuyển; form sản phẩm chặn trùng thay vì cảnh báo.
- **SKU là khoá của mặt hàng**: đổi SKU = đổi tên bản ghi và mọi chứng từ đi theo (lõi cho, nhưng nặng). Đề xuất: SKU bất biến sau khi có chứng từ; cần đổi thì tạo mặt hàng mới + ngừng bán mặt hàng cũ (câu 18).
- **Hàng quá hạn không xuất được trên hoá đơn**: lõi chặn lô có hạn dùng trước ngày ghi sổ (phiếu xuất kho / chuyển kho thì được). Đề xuất: giữ luật lõi; thanh lý hàng quá hạn qua phiếu xuất kho lẻ; màn bán báo "lô … đã hết hạn".
- **Hàng không có hạn dùng**: không còn kiểu hạn giả "2099-12-31"; những mặt hàng đó không bật hạn dùng, lô vẫn có.
- **Tên khách / NCC**: lõi mặc định lấy tên làm khoá (trùng tên là `-1`, đổi tên là đổi khoá) → dùng dãy số (3.11); người dùng không thấy khác.
- **Đổi mã lô** *[PoC 06/11 — đính chính bản 05/11]*: đường thường / Desk bị chặn ("Batch not allowed to be renamed" — Batch không khai `allow_rename`), nhưng lõi chỉ chặn khi không ép: method của app gọi `rename_doc(..., force=True)` thì đổi trọn vẹn (lô có 27 dòng gói lô + phiếu nhập đổi theo trong 0,43 s; dò 10.371 cột chữ không còn chỗ nào giữ mã cũ). → **Không còn là chỗ khác**: giữ tính năng sửa mã lô của nppsale qua method có kiểm vai; giữ bài thử làm hồi quy khi nâng bản lõi (lõi cố ý không cho đổi ở Desk).

### CFD-11 · Giảm giá cả phiếu ở phiếu nhập NCC làm đổi thuế và giá vốn
- **nppsale**: giảm đầu phiếu nhập trừ **sau thuế**, không vào giá vốn lô (`unit_cost` tính từ dòng, mig 145).
- **Lõi** (đã kiểm): Sales Invoice có cờ "giảm giá không ảnh hưởng thuế" (`is_cash_or_non_trade_discount`) nên HĐ bán giữ đúng luật mig 183. **Purchase Invoice không có cờ ấy**: giảm cả phiếu được phân bổ vào từng dòng → thuế GTGT tính lại trên tiền đã giảm và **giá vốn lô thấp hơn** (giảm đã nằm trong giá nhập).
- **Đề xuất** *[PoC đã chứng minh — chốt]*: ghi khoản giảm đầu phiếu thành một **dòng thuế trừ** (Actual, Deduct) trên Purchase Invoice: tiền hàng từng dòng (200.000 / 210.000 / 220.000), VAT theo dòng và giá vốn lô (20.000 / 21.000 / 22.000, cùng thứ tự dòng) **giữ nguyên** như nppsale, tổng phải trả vẫn trừ đủ 50.000; cách `apply_discount_on` của lõi hạ cả ba (tiền hàng 185.303…, VAT 46.696 thay vì 50.400, giá vốn 18.530…). Không cần phương án dự phòng. Sổ cái: khoản giảm ghi **Có vào tài khoản của dòng trừ** (vào thẳng lãi lỗ, không hạ giá trị kho) — PoC tạm dùng "Miscellaneous Expenses"; tài khoản thật (thu nhập khác 711 hay ghi giảm giá vốn 632) anh chốt cùng hệ thống tài khoản TT200.

### CFD-12 · Ngày chứng từ lùi / tiến
- **nppsale**: `post_invoice` nhận `invoice_date` bất kỳ (lùi hay tiến), FIFO lấy theo tồn **hiện tại**; Sửa HĐ đổi được ngày; phiếu trả không sau hôm nay; nhập tồn đầu kỳ lùi ngày.
- **Lõi** (đã kiểm): chứng từ kho **không được ghi ngày tương lai**; ghi lùi ngày thì tồn lô tính **tại thời điểm đó** (lô nhập sau ngày HĐ không dùng được dù kho đang có), và sinh việc tính lại giá vốn (CFD-07).
- **Đề xuất**: ngày HĐ / phiếu trả / phiếu kho ≤ hôm nay; ghi lùi chỉ khi lô đủ tại ngày ấy, câu báo riêng "lô … nhập sau ngày chứng từ"; tờ lùi ngày đặt giờ ghi sổ sau các phiếu nhập cùng ngày; Sửa HĐ đổi ngày về trước ngày nhập lô → chặn.
- **Người dùng thấy**: không ghi được HĐ ngày mai; HĐ ghi lùi về trước ngày nhập hàng bị từ chối.

### CFD-13 · Nhập kho kèm công nợ NCC ở màn Nhập kho
- **nppsale**: màn `/inventory/stock-in` (thủ kho) chọn NCC + tiền là ghi luôn công nợ NCC cùng phiếu nhập kho (`post_stock_import` với `payable`), không qua phiếu nhập PN.
- **Lõi**: Stock Entry không sinh công nợ; nợ NCC chỉ có từ Purchase Invoice / bút toán.
- **Đề xuất**: nhập kho có NCC + tiền → chính là **phiếu nhập PN** (Purchase Invoice có kho) — màn Nhập kho của thủ kho giữ giao diện nhưng lưu thành PN khi có NCC; nhập kho không NCC / tồn đầu kỳ → Stock Entry. Hoặc bỏ ô công nợ ở màn Nhập kho (câu 17).

---

## 6. Khác nhẹ — em tự xử lý, không cần duyệt
1. Thuế: lõi cộng từng dòng rồi làm tròn một lần ở dòng thuế (cùng dạng `round(Σ dòng × suất)` của nppsale); khác biệt là lõi làm tròn **đơn giá và tiền từng dòng** theo `currency_precision` và mặc định làm tròn **kiểu ngân hàng** → đặt `rounding_method = Commercial Rounding` (3.11), app gửi đơn giá sau giảm đã làm tròn đồng theo luật nppsale + khoản giảm tuyệt đối (không để lõi tự tính từ %). *[PoC 06/11: precision 0 + cách này khớp từng đồng 100/100 HĐ (1.458 dòng); để lõi tự tính từ % thì 13 dòng lệch 1 đ vì lõi làm tròn **tiền giảm** còn nppsale làm tròn **đơn giá**; lõi xoá `discount_percentage` ở đúng các dòng ấy nên % giảm để in / báo cáo giữ ở trường riêng.]* So lại trên hoá đơn thật ở P2.
2. Thẻ kho hiện chứng từ gốc (HĐ `HD-…`, phiếu nhập `PN-…`) thay vì phiếu `XK-…` / `NK-…` tự sinh; màn Phiếu kho liệt kê theo chứng từ gốc.
3. Dòng nối đơn phải trùng đơn vị + hệ số với dòng đơn: `xuat_hang` cập nhật hệ số dòng SO theo danh mục trước khi ghi sổ (đúng mig 174), Sửa HĐ chép hệ số tờ cũ (mig 247); xuất vượt số đặt / đổi giá: vai dịch vụ được vượt (3.11); đổi đơn vị so với đơn thì dòng mất nối (báo cáo Đặt hàng "đã xuất" cộng thêm theo mã hàng).
4. Hàng đổi: dòng 0 đ trên HĐ có cờ riêng (báo cáo bỏ qua như hôm nay) + phiếu nhập lại; dòng bán / dòng trả phải đúng dấu số lượng của lõi. Ô "phí trả hàng" của POS giữ như cũ (chỉ hiển thị, không lưu).
5. Đơn hàng không mang đuôi `-n` khi sửa (CFD-01); Sales Order đòi ngày giao ≥ ngày đặt ngay khi lưu nháp → tự điền ngày giao dự kiến hoặc ngày đặt; huỷ Phiếu tạm = đổi `npp_trang_thai` (giữ mã, không docstatus 2).
6. Số chứng từ: cùng dãy `DH / HD / PT / PN / PTNCC / PCNCC`, đặt điểm bắt đầu tiếp nối số cuối của nppsale; dãy cho tờ app tự lập: tờ ghi có `HDT-.####`, Stock Entry theo mục đích (`XKL-`, `CKL-`, `DCK-`, `NL-`), phiếu chi `PC-.####`, lượt soạn `SH-.DD.MM.-.##`; Payment Entry thu `PTH-…` / chi `PCNCC-…` (câu 13); bảng đầy đủ ở blueprint.
7. Khoá tìm `tim_kd` giữ nguyên, do hook `before_save` ghi bằng Python (chép `viValueKey`), có chỉ mục — không dựa vào collation.
8. Số phiên danh mục (`danh_muc_ban_phien`) tăng bằng hook thay trigger; cùng khoá `dungLaiSanPham` / `dungLaiKhach`.
9. `near_expiry_skipped` tính trong method sau khi chọn lô (so hạn lô đã lấy với lô còn lại).
10. Chi phí (phiếu chi) đi vào sổ cái bằng Journal Entry; báo cáo tài chính kiểu nppsale vẫn đọc từ `NPP Phieu Chi` để số không đổi cách tính.
11. Tờ ghi có tự sinh cùng ngày HĐ: lõi đòi giờ ghi sổ ≥ giờ HĐ → app đặt giờ ghi sổ muộn hơn HĐ vài giây trong cùng giao dịch; cờ `update_outstanding_for_self` và các trường no_copy được app đặt lại tường minh mỗi lần lập / lập lại.
12. Huỷ / sửa HĐ: lõi đòi mở Sales Order đã đóng trước, đóng lại sau — thứ tự nằm trong method, người dùng không thấy; câu nhắc của lõi (`_server_messages`) được method lọc để không hiện lên POS.
13. Nhập tồn đầu kỳ theo lô: tạo Batch **đúng thứ tự ngày nhập** (lõi xếp theo ngày tạo lô) dù app tự chọn lô — để Desk / báo cáo lõi cũng ra đúng thứ tự.
14. Hồ sơ người dùng và quyền bơm sẵn trong HTML (`NPP_CONTEXT`); `index.py` không cache (3.7).
15. Không port: `workflow_sessions`, `merged_orders`, `cash_collections`, `purchase_orders`, `hr_payroll` cũ, `swap_stock_movements`, `reports_config`, cột `completed_edit_days`; màn `/purchasing/invoices` (tra cứu đã gỡ menu), `/hr/payroll/[id]` (bảng lương đời đầu); phần chuyến giao trong chi tiết phiếu thu / phiếu kho; trang `/debug`, `/backup/*`.

---

## 7. Giao diện: bê thế nào (phương án R)

**Giữ**: toàn bộ `src/components`, `src/lib` (luật thuần: giá, giảm giá, tổng tiền, đơn vị, quyền, nav, báo cáo, chênh lệch, Excel, in), `src/store`, `src/hooks`, `tests/`, phần lớn `e2e/`.

**Thay**:
| Next.js / Supabase | Portal trên Frappe |
|---|---|
| App Router (`src/app/**/page.tsx`) | React Router `basename="/nppsale"`, một bảng route chép đúng đường dẫn cũ; mọi bảng đường dẫn (`NAV_PERMISSION`, `CUA_VAO`, `PAGE_TITLES`, `posHref`…) giữ **không tiền tố**; một hàm `duongDanApp()` cho 12 tệp dựng URL ngoài router (`window.open`, `iframe.src`, `sendBeacon`, `sw.js`) + test cấm chuỗi `"/pos/` thô |
| `createClient()` + `.from()/.rpc()` (938 + 100 chỗ) | một lớp `goi("nppsale.api.<mô-đun>.<hàm>", tham_so)` bọc `frappe.call` (hẹn giờ, thử lại, dịch lỗi tiếng Việt — chép luật `fetchCoHetGio`; ánh xạ `error_code` về mã nppsale; `SessionExpired` / CSRF → đăng nhập lại kèm `next`, báo các tab khác); mỗi màn một method |
| Middleware (POS theo cookie khổ màn, bảo trì, phiên) | `index.py` chép `dichPosMayChu` (307 + no-store), Guest → đăng nhập; bảo trì = `maintenance_mode` |
| 17 route handler `/api/*` | whitelisted method (admin users, QR, MISA, cron, đo nạp, dọn ảnh, lỗi trình duyệt) |
| `layHoSoMayChu` + `NapHoSo` | `NPP_CONTEXT` bơm sẵn trong HTML (hồ sơ + quyền + cài đặt, không gọi thêm) |
| Supabase Auth (`signInWithPassword`, magiclink QR, `onAuthStateChange`) | `/api/method/login` bằng SĐT; QR qua method riêng; sự kiện `storage` giữa tab |
| Supabase realtime (chuông, khoá chứng từ) | `socket.io` của Frappe + `publish_realtime` |
| Supabase Storage (ảnh điểm bán) | File riêng tư của Frappe (`/private/files`), lưu qua method |
| `public/sw.js`, `manifest.webmanifest` | `page_renderer` của app phục vụ từ `public/` với header đúng (3.7) |
| `next/link`, `next/image`, `next/font`, `next/navigation` (171 tệp) | `<Link>` của router, `<img>`, font tự nạp, `useNavigate` |

**Cách làm theo lớp để kiểm được từng bước**: (1) dựng khung Vite + router + `goi()` + trang đăng nhập, mở được `/home`; (2) chuyển từng mô-đun theo thứ tự của mục 9, mỗi mô-đun = thay các `.from()` bằng method + viết method; (3) e2e chạy với **sổ giả Frappe** (`e2e/fake-frappe.mjs` thay `fake-supabase.mjs`), cùng kịch bản.

**Điều sẽ khác với người dùng**: địa chỉ có tiền tố (`/nppsale/orders`), trang đăng nhập là của app (không phải trang Frappe), còn lại giống.

---

## 8. Dữ liệu và cắt chuyển

Ba phương án lịch sử:

| | H1. Nhập lại toàn bộ lịch sử thành chứng từ thật trong ERPNext | **H2. Danh mục + số dư đầu kỳ; lịch sử giữ ở nppsale chỉ đọc** | **H3 (đề xuất). Như H2 + nhập lịch sử vào bảng lưu trữ chỉ đọc của app** |
|---|---|---|---|
| Việc | Phát lại ~2.700 HĐ, phiếu trả, phiếu thu, phiếu nhập theo thứ tự thời gian (sổ kho / sổ cái dựng lại từ đầu) | Khách, hàng, giá, NCC, người dùng, tuyến, phân công, ảnh; tồn kho theo lô (phiếu nhập đầu kỳ theo từng lô, **tạo lô đúng thứ tự ngày nhập**, giữ mã lô, hạn, giá vốn); nợ phải thu từng HĐ còn nợ (tờ đầu kỳ giữ mã HĐ, ngày HĐ gốc, hạn, NV); dư có; nợ NCC; trả trước NCC | H2 + chép HĐ / dòng HĐ / phiếu trả / phiếu thu / phiếu nhập cũ vào `NPP LS *` để báo cáo nhiều kỳ, "hàng khách đã lấy 12 tháng", bậc lương theo lịch sử vẫn chạy |
| Rủi ro | Cao: giá vốn / FIFO khó khớp từng đồng; mất nhiều tuần | Báo cáo so kỳ trước mất mốc trong vài tháng đầu; phải giữ Supabase thêm | Vừa: bảng lưu trữ không đụng sổ kho / sổ cái; báo cáo nối hai nguồn ở một chỗ (hàm dòng thô) |
| Đề xuất | Không | Tối thiểu | **Chọn** |

Các bước cắt chuyển (chung cho H2 / H3): (1) chạy song song trên site thử với bản sao dữ liệu, so số từng màn (nợ theo khách, tồn theo lô, doanh thu tháng); (2) rà **mã vạch trùng** và **lô đang âm** trong nppsale (lõi không nhận) — báo anh xử lý trước; (3) ngày D: khoá tạo đơn offline, chờ mọi hàng đợi offline trên điện thoại NV đồng bộ về 0 (đơn offline nằm ở trình duyệt cũ, khoá Supabase là mất), rồi khoá nppsale, xuất lần cuối, nhập, kiểm chữ ký số liệu; (4) người dùng đặt lại mật khẩu (mật khẩu Supabase không chuyển được) hoặc dùng QR mới, cài lại PWA (giỏ / tab POS / danh mục nhớ không chuyển được giữa hai địa chỉ); nppsale chỉ đọc 3–6 tháng và chuyển hướng `/<đường dẫn>` → `https://<site>/nppsale/<đường dẫn>` cho link Zalo cũ.

---

## 9. Lộ trình và nghiệm thu

| Giai đoạn | Việc | Nghiệm thu |
|---|---|---|
| **P0 — PoC** — **đã xong 05/11/2026, soát và đo lại 06/11**, kết quả ở `poc/00_ket_qua_poc.md` | bench v16 (frappe 16.55.2 / erpnext 16.53.0, Python 3.14.6, Node 24.11, MariaDB 10.11), site `poc.local`, app khung `nppsale`, cài đặt 3.11 bằng `nppsale/poc/setup.py`, Xuất hàng thật với lô FIFO (`nppsale/poc/do.py`); **đo mười điểm**: (1) thời gian Xuất hàng 10–20 dòng, 1 và 5 phiên bấm cùng lúc (khoá lô + khoá dãy số); (2) thuế + làm tròn trên 50 HĐ thật so với nppsale ở hai mức `currency_precision` với Commercial Rounding, kèm ca đổi thuế suất một dòng; (3) giảm đầu phiếu nhập bằng dòng thuế trừ (CFD-11); (4) Landed Cost Voucher âm trên lô đã bán (CFD-06; LCV dương chưa chạy — đo ở P2); (5) tờ ghi có độc lập có kho: lô nhập lại + `incoming_rate` theo luật mig 127 ở hai ca "lô đã bán hết" và "trả về kho cận date"; (6) nhịp tính lại giá vốn khi app tự xếp hàng; (7) phục vụ `sw.js` / manifest qua `page_renderer`, header khung in trên hạ tầng thật; (8) HĐ "1 thùng + 3 lon" cùng mã cùng lô, đổi mã lô đã có sổ; (9) nhập lại **lô đã hết hạn** bằng bundle Inward không ghi `batch_no` ở dòng; (10) tờ đầu kỳ giữ mã HĐ cũ | ✔ bảng số đo + kết luận mười điểm (`poc/00_ket_qua_poc.md`); 06/11 soát độc lập, đo lại điểm 2, đo thêm dòng hai lô thật (1c), đồng thời chỉ phần Xuất HĐ (1d), Sửa HĐ = amend (11); nguyên văn ở `poc/01_bang_chung.md`; phần chỉ đo được trên VPS (nginx / Cloudflare / gunicorn thật, dữ liệu thật) dời sang P2 |
| **P1 — Blueprint** | 6 tệp theo `nextcode-design` (nghiệp vụ, DocType, quyền, trạng thái, tích hợp lõi, fixtures) + bảng mã lỗi + bảng dãy số | anh duyệt từng tệp |
| **P2 — Nền** | app, vai, ma trận quyền + vế lọc, đăng nhập (SĐT + QR), `NPP Nhan Vien`, cài đặt, khung portal (Vite + router + `goi()` + socket), danh mục: khách (lọc trùng, phân công, tuyến), hàng (đơn vị, giá, mã vạch), NCC, người dùng | đăng nhập 5 vai, CRUD danh mục bằng mã nppsale, test tập dòng từng người |
| **P3 — Bán hàng lõi** | đơn hàng (POS + điện thoại + offline), Xuất hàng, HĐ (xem / sửa / huỷ), phiếu trả hai loại, công nợ, phiếu thu (+ bút toán cấn trừ), in A5, Excel, HĐĐT MISA | so số với nppsale trên cùng kịch bản e2e |
| **P4 — Kho và mua** | nhập hàng, trả NCC, công nợ NCC, phiếu chi (NCC + chi phí), lô / kho date, phiếu kho, kiểm kê (phiếu điều chỉnh + chi hao hụt), thẻ kho, soạn hàng, bảng giá nhập, đề xuất đặt, sửa giá phiếu nhập đã bán (LCV) | tồn theo lô khớp, giá vốn khớp |
| **P5 — Khách hàng mở rộng** | PJP / ghé thăm, ảnh + GPS + duyệt, bàn giao, hàng đã lấy, thông báo, việc theo lịch | |
| **P6 — Báo cáo** | 6 màn tổng hợp, tổng quan, trang chủ NVBH, chênh lệch giá NV, báo cáo cũ được giữ (câu 6) | từng con số đối chiếu với nppsale |
| **P7 — Nhân sự và phần còn lại** | lương, chấm công, thưởng tháng, khuyến mãi / hoa hồng (nếu giữ), wizard, trợ giúp | |
| **P8 — Dữ liệu và cắt chuyển** | công cụ nhập, chạy song song, đào tạo, cắt chuyển | ba ngày không lệch số |

Khối lượng tương đối (P2 = 1): P3 ≈ 2,5 · P4 ≈ 1,5 · P5 ≈ 1 · P6 ≈ 1,2 · P7 ≈ 0,8 · P8 ≈ 1. Tính theo công làm liên tục em ước **cỡ 5–6 tháng**; làm nhiều mô-đun song song bằng agent rút được thời gian viết, nhưng **nút cổ chai là nghiệm thu số liệu** — nên mỗi giai đoạn em sẽ gửi bảng so số để anh duyệt thay vì chờ cuối.

---

## 10. Câu hỏi cần anh trả lời (mỗi câu đã có đề xuất)

1. **Repo và tên app.** Repo `mrhuychien/npp` hiện chỉ có tệp `hello`. App `npp` đang chạy thật (module "NPP Portal", `/npp`, cổng tự phục vụ cho NPP khách hàng của công ty anh) có phải là cùng một app không? → *Đề xuất*: anh đẩy mã app `npp` đang chạy lên repo này (nhánh `main`); em thêm **module mới `NPP Sale`** trong cùng app, portal bán hàng ở tiền tố **`/nppsale`** (vì `/npp` đã dùng). Nếu anh muốn app riêng, đặt tên khác (`npp_sale`) để không đụng app `npp` trên cùng bench.
2. **Mỗi NPP một site** (mục 2.1 A) — đồng ý?
3. **Độ sâu lõi: phương án H** (mục 2.2) — đồng ý?
4. **Giao diện: dùng lại mã React** (mục 2.3 R) — đồng ý? Hay anh vẫn muốn vanilla theo house style (em sẽ ước lại khối lượng ×3–4)?
5. **CFD-01, 02, 03, 04, 07, 08, 10, 12** (mục 5) — duyệt từng mục; mục nào anh muốn làm khác thì ghi. (CFD-05 / 06 / 09 / 11 / 13 hỏi riêng ở câu 14–17.)
6. **Mảng di sản**: (a) 23 màn báo cáo cũ `/reports/*` + `/analytics/*` — bê hết, hay chỉ bê những màn anh còn mở (anh liệt kê), còn lại dựa vào 6 màn tổng hợp? (b) Khuyến mãi và Hoa hồng — bê nguyên dạng danh mục, hay bỏ tới khi cần thật? (c) Chuyến giao — bỏ hẳn (đề xuất).
7. **Lương**: port riêng không dùng HRMS (đề xuất) — đồng ý? Doanh số lương **giữ nguyên** nguồn HĐ − hàng trả (đã đúng luật từ mig 126, em viết sai ở bản 1 — xin lỗi anh). Một tham số còn phải chốt: **thưởng số đơn** đếm **đơn đặt** (như hôm nay) hay đếm **hoá đơn ghi sổ**? Và cấu hình "Thưởng tháng" (`/hr/bonus-config`) có còn dùng không?
8. **Dữ liệu**: H3 (đề xuất) hay H2 / H1? Ngày cắt chuyển dự kiến?
9. **Kế toán**: tạo site với hệ thống tài khoản Việt Nam (TT200) để sổ cái ERPNext dùng được về sau — đồng ý? Giai đoạn đầu báo cáo tài chính vẫn theo kiểu nppsale.
10. **Hạ tầng**: bench v16 chạy ở đâu (VPS tự host hiện tại? cấu hình? Node 24 + Python 3.14), domain cho site NPP, nginx do bench sinh hay frappe_docker / Cloudflare phía trước (quyết header khung in `X-Frame-Options`, cache `sw.js` / HTML, socket.io).
11. **Nhịp duyệt**: duyệt 6 tệp blueprint từng tệp (chuẩn `nextcode-design`) hay gộp một lần? Em đề xuất từng tệp, mỗi tệp ngắn.
12. **Đặt tên**: DocType tiếng Việt không dấu với tiền tố `NPP ` (`NPP Phieu Tra`), fieldname ASCII, nhãn tiếng Việt có dấu — đồng ý?
13. **Số phiếu thu**: nppsale đang `PT-YYMMDD-NNNN` ngẫu nhiên và trùng tiền tố `PT-` với phiếu trả. → *Đề xuất*: phiếu thu `PTH-.YY.MM.DD.-.####` chạy liên tục trong ngày; phiếu trả giữ `PT-####`.
14. **Bán vượt tồn với hàng theo lô (CFD-05)**: A (bỏ luật, chặn lúc xuất — đề xuất), B (hàng cần bán âm không theo lô), hay C (phiếu nhập đệm tự động)?
15. **Sửa / huỷ phiếu nhập đã bán (CFD-06)**: chấp nhận "chỉ sửa được giá, không sửa số lượng / không huỷ khi lô đã xuất"? Hay anh muốn giữ `has_batch_no` tắt cho một số hàng để giữ luật cũ (kéo theo B ở câu 14)?
16. **Kiểm kê bằng phiếu điều chỉnh theo lô + phiếu chi hao hụt (CFD-09)** và **giảm đầu phiếu nhập (CFD-11)**: đồng ý cách em đề xuất và phương án dự phòng?
17. **Nhập kho kèm công nợ NCC (CFD-13)**: màn Nhập kho có NCC + tiền lưu thành phiếu nhập PN (đề xuất), hay bỏ ô công nợ ở màn ấy?
18. **Số phiếu nhập và SKU**: (a) số `PN-` cấp ngay lúc lập nháp (đề xuất; nháp xoá đi là lỗ số) hay nháp mang số tạm rồi đổi tên lúc hoàn thành? (b) SKU bất biến sau khi có chứng từ (đề xuất) — đồng ý?

Anh trả lời ngắn theo số (ví dụ: "1 đẩy mã lên, tiền tố /nppsale · 2 ok · 3 ok · 4 ok · 5 ok · 6a chỉ giữ … · 6b bỏ · 7 ok, thưởng đếm HĐ, bỏ thưởng tháng · 8 H3, cắt 01/01 · 9 ok · 10 … · 11 từng tệp · 12 ok · 13 ok · 14 A · 15 ok · 16 ok · 17 PN · 18a cấp ngay, 18b ok").

---

## 11. Rủi ro và điều em chưa chắc

- **Kích cỡ**: đây là dự án lớn nhất của bộ skill nextcode tới giờ (177 k dòng TS, 234 hàm SQL). Rủi ro lớn nhất không phải viết mà là **nghiệm thu số**: em sẽ dựng bộ so số tự động (cùng kịch bản chạy trên nppsale và trên app, so tổng công nợ / tồn / doanh thu, so tập dòng từng người) trước khi port màn.
- ~~**Mười điểm cần PoC** trước khi hứa (mục 9, P0).~~ Đã đo 05/11, soát và đo lại 06/11 (`poc/00_ket_qua_poc.md`). Rủi ro mới lộ ra: **đồng thời** (app chọn lô bằng câu đọc thường, lõi kiểm bằng câu đọc có khoá — method phải khoá `Bin`, không thì lô âm hoặc bế tắc, CFD-05), **số HĐ khoá suốt giao dịch** (Xuất hàng cùng lúc nối đuôi ~0,7 s / HĐ kể cả hàng khác nhau — 3.10) và **giá vốn hàng trả** (lõi rơi về giá bán khi lô không còn ở kho nhận, giá sai lan sang HĐ bán sau — app phải tự điền, CFD-03).
- **Ba luật nppsale buộc đổi thật** (CFD-05, CFD-06, CFD-12): nếu anh không chấp nhận, đường còn lại là bỏ theo dõi lô cho mặt hàng đó — nghĩa là mất hạn dùng / FIFO theo lô / kho cận date cho chính những mặt hàng ấy.
- **Frappe v16 còn mới** (Python 3.14, **Node ≥ 24**): bộ skill đã đối chiếu source v16 nhưng vẫn có thể gặp lỗi lõi; kế hoạch dự phòng là ghim phiên bản v16 cụ thể cho cả bench. *[PoC: bench dựng được trọn trên Python 3.14.6 + Node 24.11 + MariaDB 10.11; ghim frappe 16.55.2 / erpnext 16.53.0.]*
- **Hạ tầng quyết vài thứ app không tự quyết được**: header khung in, phục vụ `sw.js`, socket.io, cache HTML qua Cloudflare — phải kiểm trên máy chủ thật, không trên máy dev.
- **Mật khẩu người dùng không chuyển được** từ Supabase; cần đặt lại / phát QR mới ngày cắt chuyển.
- **Hai hệ thống chạy song song** vài tháng (đọc lịch sử ở nppsale): chi phí Supabase + Vercel còn trong thời gian đó.
- **Những ca lõi chặn mà nppsale coi là thường ngày** (nhập lại lô quá hạn, bán vượt tồn theo lô, sửa phiếu nhập đã bán) là chỗ dễ sinh "phiếu kẹt" nhất sau chuyển đổi; P0 đã chạy các ca ấy trên dữ liệu mẫu (`poc/00_ket_qua_poc.md`); còn phải chạy lại trên dữ liệu thật của anh ở P2 khi có công cụ nhập, không chỉ dữ liệu đẹp.

---

*Anh đã chốt mục 10 (mục 0a); P0 xong và đã soát lại (`poc/00_ket_qua_poc.md`, nguyên văn `poc/01_bang_chung.md`); `blueprint/01_business_model.md` đang chờ anh duyệt để em viết tiếp `02_doctype_blueprint.md`.*
