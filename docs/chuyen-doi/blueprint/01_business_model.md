# 01 · Business Model — app `nppsale` trên ERPNext v16

Tệp 1/6 của blueprint theo `nextcode-design`. Mục đích: chốt **ai dùng, làm gì, với dữ liệu nào, nối với lõi ở đâu** trước khi vẽ DocType (tệp 02). Nguồn: `../khao-sat/*.md`, `../00_ban_bac_chot.md` (mục 0a — quyết định đã chốt 05/11/2026). Cổng duyệt: anh đọc xong tệp này và nói "duyệt 01" thì em sang tệp 02.

## 1. Bối cảnh

- **Đơn vị dùng**: một nhà phân phối hàng tiêu dùng (NPP) — bán sỉ cho điểm bán lẻ, nhập hàng từ nhiều hãng / nhà cung cấp, kho theo lô và hạn dùng, nhân viên bán hàng đi tuyến bằng điện thoại, văn phòng dùng POS trên máy tính. Quy mô hiện tại (sổ thật của NPP đang dùng nppsale): ~1.800 mặt hàng, ~600 khách, ~2.000 đơn / 2.700 hoá đơn tích luỹ, 5–15 người dùng; mỗi NPP một site ERPNext riêng.
- **Hệ đang chạy**: npp.sale (Next.js 14 + Supabase) — 180 trang, 82 bảng, 234 hàm SQL, 260 migration, 7 tháng luật nghiệp vụ do chủ nhà chốt (`CLAUDE.md` + khối "VÌ SAO" trong migration). Đây là **đặc tả hành vi** của app mới: giữ nguyên chức năng và cảm nhận người dùng; chỉ 13 chỗ lõi ERPNext buộc khác đã được duyệt (mục 5 của bản bàn bạc).
- **Vì sao chuyển**: đưa sổ sách (kho theo lô, công nợ, chứng từ) về lõi ERPNext có sổ cái và kiểm toán, dùng được báo cáo kế toán chuẩn và tích hợp với các hệ ERPNext khác (ví dụ site của công ty anh), thay vì tự giữ 234 hàm SQL; đồng thời giữ giao diện đã mài.
- **Không làm**: chuyến giao / tài xế (chủ nhà bỏ 24/09/2026), đơn mua PO đời đầu, các bảng di sản (`workflow_sessions`, `merged_orders`, `cash_collections`, `swap_stock_movements`, `reports_config`, `hr_payroll` cũ).

## 2. Actors và vai (Role Frappe)

| Actor (nppsale) | Role Frappe | Thiết bị chính | Làm gì |
|---|---|---|---|
| Chủ NPP (`owner`) | `NPP Chu` | máy tính + điện thoại | toàn quyền; cấu hình, phân quyền, duyệt ảnh điểm bán, bàn giao khách, nhân sự / lương, QR đăng nhập, xoá / gộp danh mục |
| Quản lý bán hàng (`manager`) | `NPP Quan Ly` | máy tính + điện thoại | xuất hàng, sửa / huỷ HĐ, hoàn thành / huỷ phiếu trả, lập / huỷ phiếu thu, quản khách / tuyến / bàn giao, khuyến mãi, báo cáo toàn NPP |
| Kế toán (`accountant`) | `NPP Ke Toan` | máy tính | công nợ khách / NCC, phiếu thu / chi, nợ đầu kỳ, HĐĐT MISA (cấu hình, phát hành, đối soát), lương, báo cáo tài chính |
| NV bán hàng (`sales`) | `NPP NVBH` | điện thoại (đi tuyến), đôi khi máy tính | tạo / sửa đơn của mình (kể cả offline), tạo khách qua bước lọc trùng SĐT, ghé thăm / PJP, chụp ảnh + ghim vị trí điểm bán, thu tiền tại điểm bán, xem công nợ / báo cáo bán / phiếu lương / hàng khách đã lấy **của mình**; không thấy giá vốn, không thấy khách / HĐ của NV khác |
| Thủ kho (`warehouse`) | `NPP Thu Kho` | máy tính / máy tính bảng | nhập hàng NCC, trả NCC, phiếu kho, kiểm kê, soạn hàng, xuất hàng theo đơn, hoàn thành phiếu trả (nhập kho) |
| Hệ thống | (scheduler, hook) | — | đồng bộ HĐĐT, nhắc ảnh / tuyến, chuyển lô cận date, tính lại giá vốn, nhả khoá |

Vai không vào Desk (`desk_access = 0`); ma trận quyền chi tiết (mô-đun × hành động + ô riêng + ghi đè từng người) giữ nguyên `permissions.ts` / `permissions-features.ts` của nppsale — đặc tả ở tệp 03.

## 3. Use case chính (US)

Mỗi dòng: *Actor làm gì để đạt gì* · luật khoá (nguồn) · chứng từ lõi phía dưới.

| # | Use case | Luật khoá (nguồn) | Lõi ERPNext |
|---|---|---|---|
| US-01 | NVBH lập đơn cho khách mình phụ trách trên điện thoại (kể cả mất mạng), giá theo nhóm khách và đúng đơn vị, giảm giá trong trần của mình, cảnh báo hạn mức | 4 bậc giá, trần giảm / sửa giá theo người, `client_request_id`, cảnh báo không chặn (03_nghiep_vu §1) | Sales Order nháp (`npp_trang_thai` Nháp / Phiếu tạm) |
| US-02 | Văn phòng / thủ kho **Xuất hàng**: một nút = trừ kho FIFO từ kho bán theo lô, lập HĐ, ghi công nợ, lập tờ ghi có cho hàng trả kèm, đơn Hoàn thành, in A5 | một đơn một HĐ; xuất thiếu = xong; doanh thu và công nợ theo HĐ (CLAUDE.md); mặt hàng theo lô chặn khi lô không đủ, mặt hàng không lô được âm (CFD-05 B) | SO submit + Sales Invoice `update_stock` + credit note độc lập |
| US-03 | Sửa HĐ đã ghi sổ: tờ mới `HD-0042-1`, giữ hệ số tờ cũ, phiếu thu đi theo, hỏi về phiếu nhập hàng trả | mig 128 / 151 / 184 / 210 / 247; CFD-01, 04, 07, 12 | cancel + amend SI, reconcile PE |
| US-04 | Huỷ HĐ → kho về đúng lô, nợ xoá, đơn Đã huỷ; khoá khi đã thu tiền / đã phát hành HĐĐT / phiếu trả đã nhập kho | mig 217, `LOCKED_*` | cancel credit notes → cancel SI → cancel SO |
| US-05 | Khách trả / đổi hàng: phiếu **tự sinh** (trừ nợ ngay, kho treo Chờ xử lý, nhập kho sau, huỷ nhập về Chờ xử lý) và phiếu **tự lập** (hoàn thành = nhập kho + trừ nợ); trả bất kỳ hàng, giá trong trần, có thể vượt HĐ → nợ âm | mig 158 / 186 / 191 / 216 / 230; CFD-03 | `NPP Phieu Tra` bọc credit note độc lập + Stock Entry |
| US-06 | Thu tiền: phiếu thu trừ nợ ngay lúc lập (NVBH tại điểm bán hay kế toán), phân bổ do người chọn, dùng dư có, xác nhận chỉ là dấu, huỷ có lý do, in TT200 | mig 120 / 212 / 215; CFD-04 | Payment Entry ghi sổ ngay + Journal Entry cấn trừ nội bộ |
| US-07 | Công nợ theo HĐ (âm được), theo khách, theo NV, tuổi nợ; nợ của khách gồm dư có và tiền chưa phân bổ; nợ đi theo NV nhận khi bàn giao | mig 186 / 195 / 199 / 212 / 246 | `no_khach` từ sổ cái + Custom Field NV giữ nợ |
| US-08 | Nhập hàng NCC (POS hoặc màn Nhập kho của thủ kho): mỗi dòng một lô có hạn, giá vốn theo lô, nợ NCC, bảng giá nhập tự cập nhật; sửa giá khi đã bán; trả NCC theo hạn cũ trước; phiếu chi NCC trả khoản cũ nhất trước, dư thành trả trước | mig 142 / 145 / 234 / 235 / 242; CFD-06, 11, 13; câu 17, 18 | Purchase Invoice `update_stock` (+ debit note độc lập, LCV, PE Pay) |
| US-09 | Kho: tồn theo lô / kho bán / kho cận date, phiếu nhập – xuất – chuyển, kiểm kê có duyệt (hụt ra chi phí), thẻ kho, tra soát, soạn hàng theo rổ A–Z | mig 028 / 138 / 123 / 225; CFD-09 | Batch + 2 Warehouse + Stock Entry; `NPP Kiem Ke`, `NPP Luot Soan` |
| US-10 | Khách hàng: tìm trùng **đúng SĐT** trước khi tạo (mọi lối), nhận khách về danh sách, phân công chính / phụ, tuyến, PJP tuần, ghé thăm có GPS, ảnh điểm bán ≤ 3 + ghim vị trí + duyệt, bàn giao chung / chuyển hẳn, hàng khách đã lấy | CLAUDE.md (03/11, 15/10, 12/10, 20/10/2026) | Customer `KH-…` + DocType riêng |
| US-11 | Sản phẩm: SKU bất biến, nhiều mã vạch (duy nhất), đơn vị quy đổi, bảng giá theo nhóm khách × đơn vị (không lịch sử), thuế suất, hạn dùng chỉ cho hàng có hạn, theo lô hay không lô (quyết lúc tạo), ngừng bán | CFD-10; câu 14, 18 | Item + UOM + Item Price + Item Barcode |
| US-12 | HĐĐT MISA: phát hành từ HĐ, làm mới trạng thái, đồng bộ đêm, kéo snapshot, đối soát 4 tầng, khoá sửa HĐ đã phát hành | 03_nghiep_vu §2; skill `einvoice-misa-sync` | `NPP HDDT` + Python |
| US-13 | Báo cáo: 6 màn tổng hợp (một lượt gọi, đào sâu tới chứng từ), tổng quan, trang chủ NVBH, chênh lệch giá nhân viên (so giá bảng chung hiện hành), 23 màn báo cáo / phân tích cũ, Excel | CLAUDE.md (doanh số thuần, chênh lệch, quy đổi đơn vị) | method SQL một lượt |
| US-14 | Nhân sự: chấm công tay, cấu hình lương / bậc KPI / thưởng số đơn (đếm **hoá đơn**) / thưởng hoạt động / thưởng tháng, tính và khoá kỳ lương, phiếu lương của tôi | mig 096 / 126 / 173 / 201; câu 7 | DocType riêng |
| US-15 | Người dùng: tạo NV với SĐT, mẫu quyền, QR đăng nhập (xoay / thu hồi), đăng nhập thay (mở trình duyệt khác), nghỉ việc (khách + nợ về NPP), phân quyền theo vai và từng người | mig 087 / 223 / 248 | User + `NPP Nhan Vien` + ma trận quyền |
| US-16 | Hệ thống: offline đơn hàng (hàng đợi IndexedDB), POS nhiều tab + phím tắt + in khung ẩn, quét mã (USB / camera), chuyển máy tính thẳng vào POS, thông báo chuông realtime, khoá sửa đồng thời, đo thời gian nạp | CLAUDE.md các mục POS / quét / tải trang | portal React + socket.io + `NPP Khoa Chung Tu` |
| US-17 | Chuyển đổi: nhập danh mục, tồn đầu kỳ theo lô (đúng thứ tự ngày nhập), nợ đầu kỳ giữ mã HĐ cũ, dư có, nợ NCC, lịch sử vào bảng lưu trữ (H3); chạy song song, so số, cắt chuyển | mục 8 bản bàn bạc | Opening invoices, Stock Entry đầu kỳ, `NPP LS *` |

## 4. Nguồn dữ liệu hiện có

- **Supabase (Postgres)** của nppsale: 82 bảng, xuất được toàn bộ (dump + Storage ảnh điểm bán). Đây là nguồn cho P8 (chuyển đổi) và cho bộ **so số** (cùng kịch bản chạy hai bên).
- **Mã nguồn nppsale**: luật nghiệp vụ (SQL + TS) và giao diện (React) — tái dùng trực tiếp phần TS thuần và toàn bộ component.
- **MISA meInvoice**: hệ bên ngoài, số hoá đơn do MISA cấp; cấu hình và lịch sử gọi API chuyển sang DocType riêng (mật khẩu nhập lại, không xuất từ Supabase).
- **Excel của NPP**: mẫu nhập khách / sản phẩm (kiểu KiotViet) / nợ đầu kỳ — giữ nguyên định dạng cột.

## 5. Phạm vi tích hợp với lõi ERPNext

| Mô-đun lõi | Dùng | Không dùng / tắt |
|---|---|---|
| Selling | Customer, Customer Group, Sales Order, Sales Invoice (+ return độc lập), Price List / Item Price, Payment Terms Template | Pricing Rule, Quotation, Delivery Note, POS Invoice / POS Profile, hạn mức tín dụng của lõi, Sales Person / Sales Team |
| Stock | Item, UOM, Batch (+ bundle do app lập), Warehouse (Kho bán / Kho cận date), Stock Entry (Receipt / Issue / Transfer), Landed Cost Voucher, Repost Item Valuation | Stock Reconciliation (CFD-09), Pick List, Stock Reservation, Serial No, auto-pick lô của lõi (lõi vẫn dùng thứ tự `pick_serial_and_batch_based_on` cho `get_batch_qty` mà app gọi, nên app tự xếp lô theo ngày nhập; muốn tắt thật việc lõi tự chọn lô thì phải tắt Stock Settings `auto_create_serial_and_batch_bundle_for_outward` — mặc định bật; PoC 11: cờ bật thì lõi vẫn tự chọn lô cho dòng app chưa gán; tắt thì dòng thiếu lô báo lỗi theo mã, chưa thử — quyết ở 3.11 của bản bàn bạc) |
| Buying | Supplier, Purchase Invoice `update_stock` (+ debit note độc lập), Price List mua | Purchase Order, Purchase Receipt, Request for Quotation |
| Accounts | GL, Payment Ledger, Payment Entry, Journal Entry, Payment Reconciliation, Opening Invoice Creation Tool, Fiscal Year, hệ thống tài khoản VN | Tax Withholding, Budget, Subscription, Dunning |
| Core Frappe | User / Role / DocPerm, File riêng tư, Version, Error Log, Scheduler, socket.io, naming series, Password field | Desk cho vai NPP, User Permission làm hàng rào chính, Workflow DocType, Web Form, Notification email |
| Không cài | HRMS, Payments, CRM, Website theme | — |

Site thiết lập: Company = NPP, tiền tệ VND, COA Việt Nam (TT200), múi giờ Asia/Ho_Chi_Minh, cài đặt bắt buộc ở mục 3.11 của bản bàn bạc.

## 6. Ràng buộc

- **Giữ nguyên hành vi nppsale** trừ 13 chỗ đã duyệt; mọi khác biệt mới phát hiện lúc build phải được ghi vào `00_ban_bac_chot.md` và hỏi anh, không tự quyết.
- **Kỹ thuật**: Frappe / ERPNext `version-16` (Python 3.14.x, Node ≥ 24, MariaDB ≥ 10.6 — từ bản 11.6.2 phải đặt `innodb_snapshot_isolation = OFF` hoặc đo lại phần đồng thời của PoC trên đúng bản ấy, xem `../poc/00_ket_qua_poc.md` mục 1); backend là Python whitelisted method (không Server / Client Script), method ghi là POST, fixtures export, fieldname ASCII, DocType tên `NPP …`; portal React (Vite) build sẵn commit vào repo, phục vụ qua www page `/nppsale` với `no_cache`; một hợp đồng mã lỗi; một bộ test so tập dòng từng người.
- **Hiệu năng**: Xuất hàng ≤ 1,5 s cho HĐ 10–20 dòng trên VPS Google Cloud cỡ 4 vCPU / 8 GB — **chưa đo trên VPS**, đo ở P2. P0 chỉ đo trên container phát triển 4 vCPU / 16 GB với dữ liệu mẫu: một người bấm thì riêng phần Xuất HĐ 15 dòng ~0,98 s, tính cả lập đơn TB 1,30 s (chậm nhất 1,78 s); năm người cùng bấm Xuất HĐ (HĐ 8 dòng) thì các lượt nối đuôi nhau (ở dãy số HĐ, hoặc ở câu khoá Bin khi trùng hàng), người thứ năm chờ ~3,4–4,4 s — nên ngưỡng 1,5 s phải ghi rõ là cho một người bấm, cho tới khi anh chọn cách cấp số ở blueprint 05; mỗi màn một lượt gọi.
- **Tên và nơi chứa**: app `nppsale` (độc lập với app `npp` đang chạy), mã nguồn ở repo `mrhuychien/npp`, nhánh phát triển `claude/elegant-hamilton-ak996q`; không đẩy `main` khi chưa được bảo; không PR khi chưa được bảo; không ghi tên / mã model vào repo.
- **Dữ liệu thật**: so số và cắt chuyển chạy trên bản sao dữ liệu thật của NPP, không trên dữ liệu đẹp. PoC P0 mới chạy trên dữ liệu mẫu do `nppsale/poc/setup.py` dựng (40 mặt hàng, 10 khách, 3 NCC), nên mọi số P0 và các ca lõi chặn phải chạy lại trên bản sao dữ liệu thật khi có công cụ nhập (bảng giai đoạn ở mục 9 bản bàn bạc đặt công cụ nhập ở P8, còn báo cáo PoC mục 4 hẹn đo trên dữ liệu thật ở P2 — hai mốc này em thống nhất lại khi anh duyệt lộ trình); mật khẩu MISA / khoá không đi qua chat.
- **Nhịp làm**: P0 (PoC) → P1 (sáu tệp blueprint, duyệt từng tệp) → P2…P8 theo mục 9 của bản bàn bạc; mỗi giai đoạn gửi bảng so số để anh duyệt.

---

*Anh duyệt tệp này ("duyệt 01") hoặc ghi chỗ cần sửa; em sang `02_doctype_blueprint.md`.*
