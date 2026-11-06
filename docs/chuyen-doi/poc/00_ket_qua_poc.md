# Kết quả PoC P0 — ERPNext v16 chạy luật nppsale (đo ngày 05/11/2026)

Mục đích: trước khi viết blueprint và hứa lộ trình, **đo thật** mười điểm ở mục 9 của bản bàn bạc trên một bench
ERPNext v16 dựng từ đầu, bằng mã Python đi đúng đường app sẽ đi (whitelisted method gọi API lõi), không bấm tay trên
Desk. Mọi con số dưới đây đọc từ sổ (`tabStock Ledger Entry`, `tabSerial and Batch Entry`, `tabRepost Item Valuation`…),
không từ màn hình.

## 0. Kết luận một trang

| # | Điểm đo | Kết quả | Hệ quả cho thiết kế |
|---|---|---|---|
| 1 | Xuất hàng 15 dòng (13 dòng theo lô, 2 không lô), app tự gán lô FIFO bằng bundle | **TB 1,30 s** (1,16–1,78 s) / lượt, 10 lượt, 0 lỗi | đạt; nppsale trên Supabase Micro đang 1,29 s cho cùng việc (bảng khám 03/11) |
| 1b | 5 phiên cùng bấm Xuất hàng trên hàng trùng lô | **không khoá: 4/5 hỏng** `BatchNegativeStockError`; **khoá Bin FOR UPDATE: 5/5**, nối đuôi ~1 HĐ/giây | method `xuat_hang` **phải** khoá Bin từng mặt hàng (thứ tự tên) làm câu đầu giao dịch — CFD-05 |
| 2 | Thuế từng dòng 0/8/10 % + làm tròn, 50 HĐ so với công thức nppsale | precision **0**: tổng khớp 50/50, VAT lệch 1 đ ở 1/50; có giảm đơn 5 %: 0/30 lệch; precision 2: VAT 1/50, tổng 2/50 lệch 1 đ | chốt `currency_precision = 0` + Commercial Rounding; `Item.taxes` trống thì lõi tôn trọng template dòng |
| 3 | Giảm đầu phiếu nhập NCC | dòng thuế **Actual + Deduct** giữ nguyên tiền hàng dòng, VAT và giá vốn lô; `apply_discount_on` hạ cả ba | chốt cách dòng trừ — CFD-11 không cần dự phòng |
| 4 | Landed Cost Voucher âm trên lô đã bán | nhận −30.000 đ, phiếu nhập giữ số, 5 việc tính lại giá vốn chạy 16,8 s, HĐ đã xuất đổi giá vốn 8.105,52 → 8.118,15 | sửa giá phiếu nhập đã bán = LCV — CFD-06 đúng |
| 5 | Tờ ghi có độc lập có kho, giá vốn nhập lại | đặt `incoming_rate` → sổ ghi đúng; không đặt: lô còn ở kho nhận → bình quân lô tại kho ấy (9.628 đ); lô đã hết ở kho nhận → **giá bán** (11.150,7 đ) | app **luôn** tự điền `incoming_rate` = giá vốn lô đã xuất — CFD-03 |
| 6 | Huỷ HĐ có chứng từ sau, app tự chạy tính lại | huỷ 1,25 s; sinh **15 việc theo mặt hàng + kho** (không mang số HĐ), chạy hết 4,2 s | bật tính lại song song + gọi ngay; màn "đang tính lại" đếm việc Queued / In Progress — CFD-07 |
| 7 | Vỏ SPA `/nppsale/*`, `sw.js`, manifest qua `page_renderer` | vỏ no-cache cho mọi đường dẫn con, có CSRF + người dùng; `sw.js` đúng `Content-Type`, `no-cache`, `Service-Worker-Allowed: /nppsale/` | renderer phải nhìn `request.path`; `sw.js` không được nằm dưới `/assets` (cache 12 h dev / 1 năm nginx); `X-Frame-Options: SAMEORIGIN` do nginx của bench đặt — kiểm lại sau Cloudflare trên VPS |
| 8 | HĐ hai dòng cùng mã cùng lô; đổi mã lô đã có sổ | cần `allow_multiple_items` (tắt → lõi từ chối); **"Batch not allowed to be renamed"** | mã lô bất biến: đổi = lô mới + chuyển kho — CFD-10 |
| 9 | Nhập lại lô **đã hết hạn** | dòng ghi `batch_no` → `BatchExpiredError`; bundle Inward do app lập → nhận; tờ ghi có có kho với lô hết hạn → nhận | hàng trả quá date đi đường bundle — CFD-03 (c) đã chứng minh |
| 10 | Tờ đầu kỳ giữ mã HĐ cũ | `insert(set_name="HD-0042")` → tên `HD-0042`, `is_opening = Yes`, nợ 1.250.000 | H3 giữ mã HĐ lịch sử được |

**Hai điều lòi ra ngoài kế hoạch mà bản bàn bạc chưa có**: (a) lõi kiểm lô âm trong ảnh chụp của giao dịch nên **đồng thời**
là việc của app, không phải của lõi; (b) Item Tax Template phải có **cả hai** tài khoản thuế đầu ra và đầu vào — thiếu đầu vào
thì phiếu nhập tính VAT = 0 mà không báo gì.

## 1. Môi trường

| | |
|---|---|
| frappe / erpnext | `version-16`: frappe **16.55.2**, erpnext **16.53.0** (bench 5.31.1) |
| Python / Node / MariaDB | 3.14.6 / 24.11.0 / 10.11.14 |
| Máy | container 4 vCPU, 16 GB RAM (môi trường phát triển, không phải VPS) — số tuyệt đối sẽ khác trên GCloud, **tỷ lệ và kết luận thì không** |
| Site | `poc.local`, công ty "NPP Thu" (VND, Việt Nam, Fiscal Year 2025 + 2026), 2 kho (`Kho ban - NPP`, `Kho can date - NPP`), 3 đơn vị (Lon 1 / Loc 6 / Thung 24), bảng giá "Gia chuan" + "Gia nhap", 40 mặt hàng (30 theo lô, 20 có hạn dùng, 10 không lô cho phép tồn âm), 10 khách, 3 NCC |
| Cài đặt theo mục 3.11 | Commercial Rounding, `currency_precision` 0 (đổi 2 để so), `enable_serial_and_batch_no_for_item`, `allow_multiple_items` bán + mua, `Amend Counter`, `unlink_payment_on_cancellation_of_invoice`, `role_allowed_to_over_bill` / `over_deliver_receive`, `maintain_same_sales_rate` tắt, `is_cash_or_non_trade_discount` trên HĐ bán, hạn mức tín dụng trống, `Item.taxes` trống + Item Tax Template `VAT 0/5/8/10% - NPP` |
| Mã | app khung `nppsale` (repo này): `nppsale/poc/setup.py` dựng toàn bộ site; `nppsale/poc/do.py` mười điểm đo; `nppsale/portal/tinh.py` + `nppsale/www/nppsale/` cho điểm 7 |

Tồn đầu: 3 phiếu nhập (mỗi mặt hàng theo lô một lô `SPxxx-L1..L3`, 240 lon / lô, ngày lùi 30 / 23 / 16 ngày, giá nhập lệch 10 đ
giữa các lô) + 1 Material Receipt cho hàng không lô; giữa chừng nhập thêm lô `-L4` 600 lon để bài đồng thời không thiếu hàng.

## 2. Số đo từng điểm

### (1) Xuất hàng — 10 lượt tuần tự, 15 dòng / lượt

Luồng đúng như app sẽ làm: Sales Order (insert → submit) → `make_sales_invoice` → `update_stock = 1`, kho bán → app chọn lô FIFO
(`get_batch_qty`) và gắn **một Serial and Batch Bundle nhiều lô** cho mỗi dòng (`SerialBatchCreation`, `do_not_submit`) → insert →
submit. Đơn vị trộn Lon / Loc / Thung, thuế dòng trộn 0 / 8 / 10 %.

| | min | TB | max |
|---|---|---|---|
| Cả lượt | 1.156 ms | **1.300 ms** | 1.783 ms |
| SO insert / SO submit | | 173 / 150 ms | |
| SI insert / SI submit | | 405 / 573 ms | |

Dòng cần hai lô (2 thùng = 48 lon, lô đầu còn 42): bundle hai lô trên **một dòng** 848 ms; tách thành hai dòng ghi `batch_no`
942 ms, và dòng tách mang số lượng lẻ (1,75 thùng + 0,25 thùng) — chọn **bundle**, tờ in giữ đúng "2 thùng".

Lượt đầu chạy 10 lần bằng cách tách dòng từng dính một lỗi `BatchNegativeStockError` (SP016-L1 −6) không tái hiện được khi chạy
riêng; chuyển sang bundle thì 10/10 sạch. Với kết quả điểm 1b bên dưới, nhiều khả năng là cùng một gốc: lõi kiểm số dư lô trên
**ảnh chụp** của giao dịch.

### (1b) Đồng thời — 5 tiến trình cùng Xuất hàng một lúc

Mỗi tiến trình là một `bench execute` riêng (nạp mã xong, chạy **một lượt làm nóng** rồi chờ tới cùng một mốc giờ mới chạy lượt đo),
mỗi lượt 15 dòng chọn ngẫu nhiên trong 30 mặt hàng theo lô nên các lượt trùng nhau nhiều mặt hàng.

| Cách | Kết quả | Thời gian từng lượt (ms) |
|---|---|---|
| Không khoá (lõi tự lo) | **1/5 thành công**; 4 lỗi `BatchNegativeStockError` (SP025-L1 −33, SP019-L1 −37, SP003-L1 −1, SP008-L1 −12). Ngay lượt làm nóng không đồng bộ cũng hỏng 3/5 | lượt thành công 1.222 |
| Khoá `Bin` từng mặt hàng (`SELECT … FOR UPDATE`, thứ tự tên) làm **câu đầu** của giao dịch Xuất hàng | **5/5 thành công**, kết thúc cách nhau đúng ~1 s | 1.400 · 2.519 · 3.538 · 4.591 · 5.550 (tính cả chờ khoá) |

Vì sao hỏng: MariaDB mặc định REPEATABLE READ — ảnh chụp dữ liệu lập ở câu đọc đầu tiên của giao dịch; năm tiến trình cùng đọc
số dư lô như nhau, cùng chọn một lô, tiến trình ghi sau không thấy lô đã bị tiến trình trước lấy, tới lúc lõi kiểm số dư thì âm.
Khoá `Bin` **trước** mọi câu đọc khác thì ảnh chụp chỉ được lập sau khi giành được khoá → đọc được tồn mới nhất. Lưu ý thời gian
chờ khoá lộ ra ở **SO insert / SO submit** (0,5–3,7 s — hàng `tabSeries` và `Bin.reserved_qty` của SO submit cũng xếp sau khoá),
còn câu khoá chỉ 1–3 ms. Thực tế đơn đã chốt ở lượt trước nên lượt Xuất hàng chỉ còn phần SI (~1 s / HĐ khi trùng mặt hàng; không trùng
thì chạy song song). Đây là cùng ý với `post_invoice` của nppsale khoá dòng đơn `FOR UPDATE`.

Luật cho method `xuat_hang` (vào blueprint 05 tích hợp lõi): `frappe.db.commit()` (chưa ghi gì) → khoá `Bin` theo thứ tự tên mặt hàng →
đọc tồn lô → gán bundle → insert / submit SI → commit; thêm một lượt thử lại khi vẫn dính `BatchNegativeStockError` (phòng request đã lỡ
đọc gì đó trước khi khoá). Cùng luật cho phiếu xuất kho lẻ, trả NCC, phiếu điều chỉnh kiểm kê.

### (2) Thuế theo dòng + làm tròn — so với công thức nppsale trên 50 HĐ

Công thức nppsale: `round(Σ net × thuế_dòng)` cho VAT, tổng = `round(net − giảm_đơn + VAT_thô)`. Mỗi HĐ 50 dòng ngẫu nhiên, mỗi dòng
thuế 0 / 8 / 10 % riêng, lõi đặt Commercial Rounding, HĐ được lập rồi **rollback** (không để lại sổ).

| `currency_precision` | Giảm đơn | Lệch VAT | Lệch tổng | Mẫu |
|---|---|---|---|---|
| 0 | không | **1 / 50** (1 đ) | **0 / 50** | VAT lõi 7.307 / nppsale 7.306, tổng 390.156 cả hai |
| 0 | 5 % (`is_cash_or_non_trade_discount`) | 0 / 30 | 0 / 30 | |
| 2 | không | 1 / 50 | **2 / 50** (1 đ) | tổng 353.033 / 353.032; 231.155 / 231.154 |

Đổi thuế suất **một dòng** (template dòng khác mặc định của mặt hàng): lõi tôn trọng template của dòng khi `Item.taxes` để trống —
đúng giả định ở 3.11. Chốt: **precision 0**; trong giai đoạn chạy song song so tổng từng HĐ, lệch 1 đ VAT (≈ 2 % số HĐ) chấp nhận được
vì tổng HĐ (số công nợ, số đẩy MISA) khớp 100 %.

### (3) Giảm đầu phiếu nhập NCC — CFD-11

Phiếu nhập 3 dòng 200.000 / 210.000 / 220.000, VAT mua 8 %, giảm đầu phiếu 50.000.

| Cách | Tiền hàng dòng | Σ thuế (gồm dòng trừ) | Tổng phải trả | Giá vốn lô |
|---|---|---|---|---|
| **Dòng thuế `Actual` + `Deduct` 50.000** | 200.000 / 210.000 / 220.000 (giữ) | 400 (= 50.400 − 50.000) | 630.400 | 22.000 / 21.000 / 20.000 (giữ) |
| `apply_discount_on = Grand Total` của lõi | 185.303 / 194.568 / 203.833 | 46.696 | 630.400 | 20.383 / 19.457 / 18.530 |

Tổng phải trả như nhau; cách dòng trừ giữ tiền hàng, VAT và giá vốn lô đúng luật mig 145 của nppsale. **Chốt cách dòng trừ.**

### (4) Landed Cost Voucher âm trên lô đã bán — CFD-06

LCV −30.000 đ phân bổ cho phiếu nhập `ACC-PINV-2026-00001` (30 dòng, lô đã xuất ở nhiều HĐ): lõi **nhận**, phiếu nhập giữ nguyên số,
sinh 5 việc Repost Item Valuation (theo mặt hàng + kho) — `repost_entries()` chạy hết **16,8 s**; sổ lô `SP001-L1`: nhập 8.105,52 đ,
HĐ đã xuất sau đó định giá 8.118,15 đ (giá trị nhập giảm, giá vốn đơn vị của phần còn lại và phần đã bán được tính lại).

### (5) Tờ ghi có độc lập có kho — giá vốn hàng nhập lại (luật mig 127) — CFD-03

Tờ ghi có `is_return = 1`, **không** `return_against`, `update_stock = 1`, 5 lon lô `SP001-L1` (giá vốn gốc 8.105,52 đ, giá bán dòng trả
11.150,7 đ):

| Ca | Kho nhận | `incoming_rate` app đặt | Sổ ghi giá vốn |
|---|---|---|---|
| trả về kho cận date | Kho can date | 8.105,52 | **8.105,52** ✔ |
| trả về kho cận date, không đặt | Kho can date (lô đang còn tồn ở đó) | — | 9.628,11 (bình quân lô **tại kho nhận**) |
| lô đã bán hết ở kho bán, trả về kho bán, không đặt | Kho ban | — | **11.150,7 = giá bán** ✘ |

Nợ của tờ: −55.755 đ (dư có) ở cả ba ca — đúng luật công nợ âm. Kết luận: app **luôn** điền `incoming_rate` cho từng dòng nhập lại,
lấy từ `Serial and Batch Entry.incoming_rate` của bundle xuất trên HĐ gốc (SLE có bundle **không** ghi `batch_no` — tra qua bundle).

### (6) Huỷ HĐ có chứng từ sau — nhịp tính lại giá vốn — CFD-07

Huỷ `ACC-SINV-2026-00001` (15 dòng, HĐ đầu tiên nên mọi HĐ sau đều là chứng từ sau): `cancel()` **1.248 ms**; lõi sinh **15** Repost
Item Valuation `based_on = Item and Warehouse` (mỗi mặt hàng + kho một việc, `voucher_no` trống — đếm theo số HĐ sẽ không thấy);
`repost_entries()` gọi ngay: **4.192 ms**, 15/15 Completed. Cùng cơ chế cho LCV ở điểm 4 (5 việc, 16,8 s vì mỗi việc quét nhiều HĐ hơn).

### (7) Vỏ SPA, `sw.js`, manifest — phục vụ ngoài Desk

Đã dựng thật trong app khung: `website_route_rules` `/nppsale/<path:app_path>` → `www/nppsale` (`no_cache = 1`); `page_renderer`
`nppsale.portal.tinh.TepTinhPortal` cho `sw.js` + manifest; chạy `bench serve` và `curl`:

| URL | Mã | Header đáng chú ý |
|---|---|---|
| `/nppsale/`, `/nppsale/pos/orders`, `/nppsale/sell/new`, `/nppsale/khong-co-that/abc` | 200, cùng một vỏ HTML | `Cache-Control: no-store,no-cache,must-revalidate,max-age=0`; đăng nhập rồi thì `<meta name="csrf_token">` + người dùng có giá trị |
| `/nppsale/sw.js` | 200 | `Content-Type: application/javascript`, `Cache-Control: no-cache, must-revalidate`, `Service-Worker-Allowed: /nppsale/`, `X-Content-Type-Options: nosniff` |
| `/nppsale/manifest.webmanifest` | 200 | `application/manifest+json`, `no-cache` |
| `/assets/nppsale/portal/sw.js` (để so) | 200 | `Cache-Control: max-age=43200, public` (dev server); nginx của bench đặt `max-age=31536000` cho `/assets` → **không** để `sw.js` ở đó |

Hai điều rút ra: (a) route rule viết lại endpoint thành `nppsale` **trước** khi tới renderer (`self.path == "nppsale"` với mọi đường
dẫn con) → renderer phải nhìn `frappe.local.request.path`; (b) Frappe không tự đặt `X-Frame-Options`; mẫu nginx của bench thêm
`SAMEORIGIN` — đúng yêu cầu khung in của POS, nhưng Cloudflare / nginx thật trên VPS phải kiểm lại (đo ở P2).

### (8) Hai dòng cùng mã cùng lô; đổi mã lô

- `allow_multiple_items = 1`: HĐ hai dòng `SP002` cùng lô ghi được; tắt → *"Item SP002 entered multiple times. Please enable Allow Item
  to Be Added Multiple Times in a Transaction"*.
- Đổi tên Batch đã có sổ: lõi từ chối thẳng — **"Batch not allowed to be renamed"** (Batch khai `allow_rename = 0`). Luật mới: mã lô bất
  biến; muốn đổi = lập lô mới + Stock Entry chuyển kho giữa hai lô (giá vốn giữ), hoặc chỉ cho sửa mã khi lô chưa có chứng từ nào.

### (9) Nhập lại lô đã hết hạn

Lô `SP001-HETHAN` hết hạn 10 ngày trước:

| Cách | Kết quả |
|---|---|
| Material Receipt, dòng ghi `batch_no` | `BatchExpiredError: The batch SP001-HETHAN has already expired` |
| Material Receipt, dòng gắn **bundle Inward do app lập** (không `batch_no` ở dòng) | **nhận** (`MAT-STE-2026-00002`) |
| Tờ ghi có có kho (`is_return`, `update_stock`) với lô hết hạn | **nhận** (`ACC-SINV-2026-00026`) |

Hàng trả quá date của NPP đi được đường bundle / tờ ghi có — không cần lô phụ `HT-…`.

### (10) Tờ đầu kỳ giữ mã HĐ cũ

`Sales Invoice.insert(set_name="HD-0042")` với `is_opening = Yes`, tiền 1.250.000: tên **`HD-0042`**, nợ 1.250.000 — nợ đầu kỳ theo từng HĐ lịch
sử (H3) giữ nguyên mã HĐ nppsale. Lưu ý dãy số thật của app phải không bao giờ sinh trùng mã lịch sử (dãy `HD-` bắt đầu sau số lớn nhất đã nhập).

## 3. Phát hiện ngoài kế hoạch

1. **Item Tax Template phải có cả tài khoản thuế đầu vào**: template chỉ có "Thuế GTGT đầu ra" → Purchase Invoice tính VAT = 0 không báo gì
   (phát hiện ở điểm 3; `va_thue_mua()` vá bằng cách thêm dòng tài khoản đầu vào). Vào 3.11.
2. **Đồng thời là việc của app** (điểm 1b) — lõi chỉ kiểm, không khoá lúc chọn lô.
3. **SLE của dòng có bundle không ghi `batch_no`** (null) — mọi câu "giá vốn theo lô", "tồn theo lô" phải nối qua `Serial and Batch Bundle`
   / `Serial and Batch Entry` (hoặc dùng `get_batch_qty`), không lọc `SLE.batch_no`.
4. **Repost theo mặt hàng + kho, không theo chứng từ** (điểm 6): màn "đang tính lại giá vốn (N)" đếm theo trạng thái, không theo số HĐ.
5. **Không có hệ thống tài khoản Việt Nam trong v16** (`erpnext/accounts/doctype/account/chart_of_accounts/verified/` không có `vn_*`) →
   app ship mẫu TT200 và truyền `chart_of_accounts` khi tạo công ty (anh đã đồng ý câu 9). PoC tạm dùng "Standard".
6. `session_expiry` của System Settings nhận dạng `hh:mm` (`720:00` = 30 ngày), không nhận `30d`.
7. `Item Barcode.barcode_type` đặt EAN là lõi kiểm checksum — mã nội bộ của NPP để trống `barcode_type`.
8. `bench execute --kwargs` nhận **Python literal** (`True` / `False`), không nhận JSON `true` / `false` (chỉ ảnh hưởng script đo).
9. Tên thư mục app: bench đặt theo `pyproject.toml` (`nppsale`) nhưng khi cài từ repo nên gọi
   `bench get-app nppsale https://github.com/mrhuychien/npp` để thư mục là `apps/nppsale` (repo tên `npp`).

## 4. Những gì chỉ đo được trên VPS (P2, GCloud)

- Header thật qua nginx của bench / Cloudflare: `X-Frame-Options` cho khung in, cache HTML của vỏ SPA, `sw.js`, nén.
- socket.io (cổng 9000) qua proxy; gunicorn nhiều worker (số đo đồng thời ở đây là tiến trình `bench execute`, nặng hơn worker nóng).
- Thời gian với **dữ liệu thật** của anh (1.835 mặt hàng, 598 khách, ~2.700 HĐ) sau khi có công cụ nhập H3.
- Sao lưu `bench backup --with-files` + đẩy Drive theo lịch.

## 5. Chạy lại

```bash
bench --site <site> execute nppsale.poc.setup.run --kwargs "{'currency_precision': '0'}"
bench --site <site> execute nppsale.poc.do.nhap_ton
bench --site <site> execute nppsale.poc.do.xuat_hang_nhieu --kwargs "{'lan': 10, 'so_dong': 15}"
bench --site <site> execute nppsale.poc.do.thue_lam_tron --kwargs "{'n': 50, 'giam_don_pct': 0}"
bench --site <site> execute nppsale.poc.do.giam_dau_phieu_nhap
bench --site <site> execute nppsale.poc.do.lcv_sua_gia
bench --site <site> execute nppsale.poc.do.ghi_co_doc_lap2 --kwargs "{'dat_incoming_rate': False}"
bench --site <site> execute nppsale.poc.do.repost_khi_huy
bench --site <site> execute nppsale.poc.do.hai_dong_cung_lo
bench --site <site> execute nppsale.poc.do.doi_ma_lo
bench --site <site> execute nppsale.poc.do.nhap_lai_lo_het_han2
bench --site <site> execute nppsale.poc.do.dau_ky_giu_ma
```

Bài đồng thời: 5 cửa sổ cùng gọi `nppsale.poc.do.xuat_hang_dong_thoi --kwargs "{'cho_den': <epoch + 75>, 'khach': k, 'khoa': True}"`.
Điểm 7: `bench --site <site> serve --port 8000` rồi `curl -D - http://127.0.0.1:8000/nppsale/sw.js`.

Mã PoC nằm trong app để P2 dùng lại làm bộ dựng site thử và bộ đo hồi quy; **không** cài lên site thật (`setup.run` tạo công ty, kho,
mặt hàng mẫu).
