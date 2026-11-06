# Kết quả PoC P0 — ERPNext v16 chạy luật nppsale (đo 05/11/2026, soát và đo lại 06/11/2026)

Mục đích: trước khi viết blueprint và hứa lộ trình, **đo thật** các điểm ở mục 9 của bản bàn bạc trên một bench
ERPNext v16 dựng từ đầu, bằng mã Python đi đúng đường app sẽ đi (method gọi API lõi), không bấm tay trên Desk. Mọi con số
đọc từ sổ (`tabStock Ledger Entry`, `tabSerial and Batch Entry`, `tabRepost Item Valuation`, `tabGL Entry`…), không từ màn hình.

**Bản 06/11.** Một vòng soát độc lập (hai người soát, mỗi người đối chiếu từng con số với sổ PoC bằng câu chỉ đọc) tìm ra
bốn chỗ bản 05/11 **ghi sai hoặc đo sai** — LCV sinh 30 việc chứ không phải 5; giá vốn sau LCV ghi ngược chiều; phép so thuế
dùng sai kiểu làm tròn; lời giải thích bài đồng thời nói ngược cơ chế — và ba chỗ khẳng định khi **chưa đo** (dòng hai lô
thật, hàng không trùng thì chạy song song, đổi mã lô). Em đã đo lại / đo thêm tất cả; chỗ nào đổi so với bản 05/11 có dấu
*(đính chính 06/11)*. Bằng chứng thô — nguyên văn máy in ra và các câu đối chiếu sổ — ở `01_bang_chung.md`.

## 0. Kết luận một trang

| # | Điểm đo | Kết quả | Hệ quả cho thiết kế |
|---|---|---|---|
| 1 | Xuất hàng 15 dòng (13 dòng theo lô, 2 không lô), app tự gán lô FIFO bằng bundle | **TB 1,30 s** (1,16–1,78 s) / lượt gồm cả lập đơn, 10 lượt, 0 lỗi; riêng phần Xuất HĐ ~0,98 s | đạt, nhưng nặng hơn nppsale trên máy khoẻ nhiều lần (mục 2.(1)) |
| 1b | 5 phiên cùng bấm, bài cũ (đơn + HĐ một giao dịch, hàng trùng nhiều, lô gần hết) | không khoá: **1/5** thành công, 4 lỗi lô âm; khoá Bin: 5/5 nối đuôi | method `xuat_hang` **phải** khoá Bin — CFD-05 |
| 1c | Dòng cần **hai lô thật** (2 thùng, lô đầu còn 20 lon) *(đo 06/11)* | bundle: một dòng "2 thùng", sổ ghi đúng 20 + 28 lon; tách dòng: 0,833 + 1,167 thùng, sổ ghi **19,992 + 28,008 lon** | luôn dùng bundle, không bao giờ tách dòng |
| 1d | 5 phiên cùng Xuất HĐ của đơn đã chốt *(đo 06/11)* | hàng **rời nhau**: 5/5 nhưng **nối đuôi** ~0,7 s / HĐ (khoá dãy số HĐ); hàng trùng không khoá: 4/5, 1 **bế tắc** (deadlock); hàng trùng có khoá Bin: 5/5 nối đuôi | khoá Bin + thử lại khi bế tắc; nối đuôi do dãy số là giới hạn của lõi — cách cấp số anh chọn ở blueprint 05 |
| 2 | Thuế 0/5/8/10 % theo dòng + làm tròn, 100 HĐ 10–20 dòng có giảm dòng % *(đo lại 06/11)* | precision **0** + app gửi sẵn đơn giá sau giảm: **khớp từng đồng 100/100 HĐ (1.458 dòng)**; để lõi tự tính giảm % → 13 dòng lệch 1 đ; precision 2 → VAT có số lẻ ở 99/100 HĐ | `currency_precision = 0`; app tự tính đơn giá sau giảm theo luật nppsale; % giảm giữ ở trường riêng |
| 3 | Giảm đầu phiếu nhập NCC | dòng thuế **Actual + Deduct** giữ nguyên tiền hàng dòng, VAT và giá vốn lô; khoản giảm ghi Có vào một tài khoản lãi lỗ | chốt cách dòng trừ (CFD-11); anh chọn tài khoản |
| 4 | Landed Cost Voucher âm trên lô đã bán | nhận −30.000 đ, phiếu nhập giữ số; **30 việc** tính lại giá vốn (mỗi mặt hàng một việc) chạy 16,8 s; giá nhập lô SP001-L1 **8.109 → 8.105,52 đ** và HĐ đã xuất lô ấy tính lại theo đúng giá mới | sửa giá phiếu nhập đã bán = LCV — CFD-06 đúng; LCV dương chưa chạy |
| 5 | Tờ ghi có độc lập có kho, giá vốn hàng nhập lại | app đặt `incoming_rate` → sổ đúng; không đặt → lõi lấy bình quân lô ở kho nhận nếu lô còn ở đó, lô hết thì lấy **giá bán**; giá vốn sai **lan sang HĐ bán sau** lô ấy | app **luôn** tự điền `incoming_rate` — CFD-03 |
| 6 | Huỷ HĐ có chứng từ sau, app tự chạy tính lại | huỷ 1,25 s; sinh 15 việc tính lại (mỗi mặt hàng + kho một việc), chạy hết 4,2 s | bật tính lại song song + gọi ngay; màn "đang tính lại" đếm việc theo trạng thái — CFD-07 |
| 7 | Vỏ SPA `/nppsale/*`, `sw.js`, manifest qua `page_renderer` | vỏ không cache cho mọi đường dẫn con, có CSRF + người dùng; `sw.js` đúng `Content-Type`, `no-cache`, `Service-Worker-Allowed: /nppsale/` | renderer nhìn `request.path`; `sw.js` không để dưới `/assets`; header khung in kiểm lại trên VPS |
| 8 | HĐ hai dòng cùng mã cùng lô; đổi mã lô đã có sổ | cần `allow_multiple_items`; đổi tên lô: đường người dùng bị chặn, **method app ép `force=True` thì đổi trọn vẹn** *(đính chính 06/11)* | giữ được tính năng sửa mã lô của nppsale, qua method có kiểm vai |
| 9 | Nhập lại lô **đã hết hạn** | dòng ghi `batch_no` → `BatchExpiredError`; bundle nhập do app lập → nhận; tờ ghi có có kho → nhận | hàng trả quá date đi đường bundle; giữ bài này làm bài hồi quy khi nâng bản lõi |
| 10 | Tờ đầu kỳ giữ mã HĐ cũ | `insert(set_name="HD-0042")` → tên `HD-0042`, `is_opening = Yes`, nợ 1.250.000 | H3 giữ mã HĐ lịch sử được |
| 11 | Sửa HĐ = huỷ + tờ mới đuôi `-n` *(thêm 06/11)* | `…00101` → `…00101-1` → `…00101-2`, tờ cũ Đã huỷ; tờ mới **không mang lô cũ**, lõi tự chọn lô | CFD-01 đúng; method Sửa HĐ phải tự gán lô lại |

**Năm điều lộ ra ngoài kế hoạch** (chi tiết ở mục 3): (a) **đồng thời là việc của app** — app chọn lô bằng câu đọc thường
(đọc theo ảnh chụp của giao dịch), lõi kiểm bằng câu đọc có khoá, nên không khoá thì lô âm hoặc bế tắc; (b) **số HĐ cấp trong
giao dịch và giữ khoá tới khi ghi xong**, nên mọi lượt Xuất hàng xếp hàng một, kể cả khi hàng khác nhau; (c) **tách dòng
làm lẻ số lon**; (d) **lõi làm tròn giảm % dòng khác nppsale**; (e) Item Tax Template phải có **cả** tài khoản thuế đầu ra
và đầu vào — thiếu đầu vào thì phiếu nhập tính VAT sai mà không báo gì.

## 1. Môi trường

| | |
|---|---|
| frappe / erpnext | `version-16`: frappe **16.55.2**, erpnext **16.53.0** (bench 5.31.1) |
| Python / Node / MariaDB | 3.14.6 / 24.11.0 / 10.11.14 (mức cô lập REPEATABLE-READ, chờ khoá tối đa 50 s) |
| Máy | container 4 vCPU, 16 GB RAM (môi trường phát triển, không phải VPS) — số tuyệt đối sẽ khác trên GCloud, **tỷ lệ và kết luận thì không** |
| Site | `poc.local`, công ty "NPP Thu" (VND, Việt Nam, Fiscal Year 2025 + 2026), 2 kho (`Kho ban - NPP`, `Kho can date - NPP`), 3 đơn vị (Lon 1 / Loc 6 / Thung 24), bảng giá "Gia chuan" + "Gia nhap" + "Gia nhom VIP", 40 mặt hàng (30 theo lô, 20 có hạn dùng, 10 không lô cho phép tồn âm), 10 khách, 3 NCC |
| Cài đặt theo mục 3.11 | Commercial Rounding, `currency_precision` 0 (đổi 2 để so rồi trả về), `round_row_wise_tax` 0 (mặc định), `enable_serial_and_batch_no_for_item`, `allow_multiple_items` bán + mua, `unlink_payment_on_cancellation_of_invoice`, `role_allowed_to_over_bill` / `over_deliver_receive`, `maintain_same_sales_rate` tắt, `is_cash_or_non_trade_discount` trên HĐ bán có giảm đơn, hạn mức tín dụng trống, `Item.taxes` trống + Item Tax Template `VAT 0/5/8/10% - NPP`. `default_amend_naming = Amend Counter` là mặc định của lõi (script không đặt; thử ở điểm 11) |
| Mã | app khung `nppsale` (repo này): `nppsale/poc/setup.py` dựng toàn bộ site; `nppsale/poc/do.py` các phép đo; `nppsale/portal/tinh.py` + `nppsale/www/nppsale/` cho điểm 7 |

Tồn đầu: 3 phiếu nhập (mỗi mặt hàng theo lô một lô `SPxxx-L1..L3`, 240 lon / lô, ngày 06/10 · 13/10 · 20/10, giá nhập lệch 10 đ
giữa các lô) + 1 Material Receipt cho hàng không lô; giữa chừng nhập thêm lô `-L4` 600 lon để bài đồng thời không thiếu hàng.
Các phép đo ngày 06/11 lập thêm HĐ `ACC-SINV-2026-00043` trở đi (đọc sổ để soát số ngày 05/11 thì trừ các tờ ấy ra).

## 2. Số đo từng điểm

### (1) Xuất hàng — 10 lượt tuần tự, 15 dòng / lượt

Luồng như app sẽ làm: Sales Order (insert → submit) → `make_sales_invoice` → `update_stock = 1`, kho bán → app chọn lô FIFO
(`get_batch_qty`) và gắn **một Serial and Batch Bundle** (gói lô — bảng ghi "dòng này lấy lô nào bao nhiêu") cho mỗi dòng
(`SerialBatchCreation`, `do_not_submit`) → insert → submit. 15 dòng = 13 mặt hàng theo lô chọn ngẫu nhiên trong 30 + 2 mặt hàng
không lô trong 10; đơn vị trộn Lon / Loc / Thung, SL 1–3, thuế dòng 0 / 8 / 10 %; HĐ `ACC-SINV-2026-00013…00022`.

| | min | TB | max |
|---|---|---|---|
| Cả lượt (lập đơn + Xuất HĐ) | 1.156 ms | **1.300 ms** | 1.783 ms |
| SO insert / SO submit | | 173 / 150 ms | |
| SI insert / SI submit | | 405 / 573 ms | |

Ở thực tế đơn đã có sẵn nên người bấm Xuất hàng chỉ chờ phần SI: **~0,98 s** cho HĐ 15 dòng trên máy này. Để hình dung: nppsale
hôm nay mất 1,29 s cho `post_invoice` trên Supabase Micro đang quá tải, nhưng chỉ 19 ms trên sổ thử khoẻ (bảng khám 03/11) — hai
máy khác nhau nên không so trực tiếp được. ERPNext làm nhiều việc hơn trong một lượt (sổ cái, gói lô, định giá, cập nhật đơn):
trên chính máy 4 vCPU / 16 GB khá rảnh này vẫn ~1 s cho HĐ 15 dòng, tức là cỡ ấy, không phải vài chục mili-giây như nppsale trên
sổ khoẻ. Số trên VPS đo lại ở P2.

Lượt 10 lần đầu tiên (bằng cách tách dòng, xem 1c) dính một lỗi lô âm (SP016-L1 −6) không tái hiện được khi chạy riêng. Lượt ấy
chạy tuần tự trong một tiến trình nên **không** phải do đồng thời *(đính chính 06/11 — bản 05/11 đoán là cùng gốc với 1b)*;
−6 = 42 − 48 gợi ý lõi soát cả 48 lon vào lô đầu khi dòng bị tách — gốc chưa rõ. Cách tách dòng còn hỏng ở điểm 1c nên đã bỏ
hẳn; đường bundle 10/10 sạch.

### (1b) Đồng thời — bài cũ 05/11

Năm tiến trình riêng (`bench execute`), mỗi tiến trình lập **đơn + HĐ trong cùng một giao dịch**, 15 dòng như điểm 1, chọn
ngẫu nhiên nên các lượt trùng nhiều mặt hàng; lúc ấy lô đầu của nhiều mặt hàng đã gần hết. Lượt 2 và 3 cho mỗi tiến trình chạy
một lượt làm nóng trước rồi chờ cùng một mốc giờ.

| Lượt | Kết quả | Thời gian từng tiến trình (ms) |
|---|---|---|
| 1 — lạnh, không khoá | **1/5** thành công; 4 lỗi `BatchNegativeStockError` (SP021-L1 −12, SP011-L1 −12, SP001-L1 −1, SP004-L1 −2) | lượt thành công 1.872 |
| 2 — đã làm nóng, không khoá | **1/5** thành công; 4 lỗi (SP025-L1 −33, SP019-L1 −37, SP003-L1 −1, SP008-L1 −12). Lượt làm nóng (không đồng bộ) cũng hỏng **4/5** *(đính chính 06/11 — bản 05/11 ghi 3/5)* | lượt thành công 1.222 |
| 3 — đã làm nóng, khoá `Bin` từng mặt hàng (`SELECT … FOR UPDATE`, theo thứ tự tên) làm **câu đầu** giao dịch Xuất HĐ | **5/5**, xong cách nhau ~1 s | 1.400 · 2.519 · 3.538 · 4.591 · 5.550 (gồm cả lập đơn và chờ khoá) |

Vì sao hỏng *(đính chính 06/11 — bản 05/11 viết ngược cơ chế)*: app **chọn lô** bằng `get_batch_qty` — câu đọc thường, đọc theo
**ảnh chụp** của giao dịch (MariaDB REPEATABLE READ lập ảnh chụp ở câu đọc thường đầu tiên) — nên năm tiến trình cùng thấy số dư cũ
và cùng chọn một lô. Còn lõi **kiểm** số dư lô bằng câu đọc **có khoá** (`.for_update()` trong
`BatchNoValuation.get_batch_stock_before_date`, `erpnext/stock/serial_batch_bundle.py:951`) nên thấy số mới nhất và báo âm.
Khoá `Bin` trước mọi câu đọc thường: tiến trình sau chờ tới khi tiến trình trước ghi xong mới đọc lần đầu, nên ảnh chụp của nó đã
có số mới.

Thời gian chờ ở lượt 3 lộ ra ở **SO insert** (0,2 s ở tiến trình tới trước → 0,5 / 1,6 / 2,7 / 3,7 s ở bốn tiến trình sau — hàng
dãy số `SAL-ORD-` bị tiến trình trước giữ) và **SO submit** (0,18 s → 0,9–1,0 s — `Bin.reserved_qty`); câu khoá Bin chỉ 1–3 ms.
Bài này trộn lập đơn với Xuất HĐ nên đo lại riêng phần Xuất HĐ ở 1d.

### (1c) Dòng cần hai lô thật — bundle so với tách dòng *(đo 06/11)*

Mỗi lượt một mặt hàng riêng: bán bớt trước (không tính giờ) cho lô FIFO đầu còn 20 lon, rồi lập đơn + HĐ một dòng **2 thùng = 48 lon**.
5 lượt mỗi cách, xen kẽ (`hai_lo_do`).

| Cách | Dòng trên HĐ | Sổ kho ghi | Thời gian (đơn + HĐ một dòng) |
|---|---|---|---|
| **Bundle** (một dòng, gói hai lô) — SP001 / 003 / 005 / 007 / 009 | 1 dòng "2 Thung", 48 lon | **20 lon lô L2 + 28 lon lô L3** — đúng | 364 · 391 · 398 · 413 ms (lượt đầu 1.094 ms, tiến trình còn lạnh) |
| **Tách dòng** (mỗi lô một dòng, ghi `batch_no`) — SP002 / 004 / 006 / 008 / 010 | 0,833 Thung + 1,167 Thung | **19,992 lon + 28,008 lon** | 393 · 396 · 447 · 460 · 464 ms |

Vì sao lẻ: số lượng dòng chỉ giữ 3 số lẻ — 20 / 24 = 0,8333… lưu thành 0,833 thùng × 24 = 19,992 lon. Tồn lô lệch dần từng phần
nghìn lon và tờ in ghi "0,833 thùng". Thời gian hai cách ngang nhau. *(Đính chính 06/11: bản 05/11 ghi "bundle hai lô 848 ms" — lượt
ấy chạy sau lượt tách dòng nên lô đầu đã hết, thực tế chỉ lấy một lô; gói nhiều lô có thật ở 28 dòng của 16 HĐ sau, `ACC-SINV-2026-00014…00042`,
ví dụ `00014` SP024-L1 −59 + SP024-L2 −13.)* Kết luận: **luôn bundle**.

### (1d) Đồng thời — chỉ đo phần Xuất HĐ của đơn đã chốt *(đo 06/11)*

Đúng cảnh thật: NVBH đã lên đơn, thủ kho / kế toán bấm Xuất hàng. Mỗi tiến trình làm nóng (một đơn + HĐ, không tính), chốt một đơn
8 dòng (6 theo lô + 2 không lô, 2 lon / dòng) **trước** mốc giờ, tới mốc mới Xuất HĐ (`xuat_hd_dong_thoi`). Năm tiến trình bắt đầu
trong cùng 5 ms. Bốn kịch bản:

| Kịch bản | Thành công | Thời gian phần Xuất HĐ, theo thứ tự xong (ms) | Chờ ở đâu |
|---|---|---|---|
| Hàng **rời nhau**, không khoá | 5/5 | 828 · 1.424 · 2.075 · 2.794 · 3.518 | ở SI insert (163 → 791 → 1.356 → 2.036 → 2.666 ms): hàng dãy số HĐ `tabSeries` bị khoá từ lúc đặt tên tới khi ghi xong (`frappe/model/naming.py:412`) |
| Hàng rời nhau, khoá Bin | 5/5 | 798 · 1.377 · 2.013 · 2.671 · 3.351 | như trên (câu khoá Bin 0–2 ms) |
| Hàng **trùng**, không khoá | **4/5**, 1 **bế tắc** — MariaDB 1213 "Deadlock found" | 814 · 1.613 · 2.366 · 3.168 | lúc app lập gói lô: lõi đọc có khoá số dư lô (`serial_batch_bundle.py:951`), hai tiến trình khoá chéo nhau, MariaDB huỷ một |
| Hàng trùng, khoá Bin | 5/5 | 873 · 1.781 · 2.646 · 3.475 · 4.444 | ở câu khoá Bin (1 → 863 → 1.772 → 2.636 → 3.464 ms) |

Ba kết luận:
- Một HĐ 8 dòng chiếm ~0,7–0,9 s. Năm người bấm cùng giây thì người thứ năm chờ ~3,4–4,4 s — **kể cả khi hàng khác nhau** *(đính chính
  06/11 — bản 05/11 viết "không trùng thì chạy song song" khi chưa đo)*. Công suất trên máy này cỡ 1,1–1,4 HĐ / giây.
- Không khoá Bin thì hàng trùng sẽ hoặc lô âm (1b — lô gần hết), hoặc bế tắc (đây — lô còn nhiều). Luật cho method `xuat_hang`:
  commit (chưa ghi gì) → khoá `Bin` theo thứ tự tên mặt hàng → đọc tồn lô → lập gói lô → insert / submit → commit; bắt
  `BatchNegativeStockError` **và** `QueryDeadlockError` thì thử lại một lần. Cùng luật cho phiếu xuất kho lẻ, trả NCC, điều chỉnh
  kiểm kê, Sửa HĐ. Đây là cùng ý với `post_invoice` của nppsale khoá dòng đơn `FOR UPDATE`.
- Muốn bớt nối đuôi do dãy số: cấp số HĐ bằng SEQUENCE của MariaDB (không khoá nhưng **lỗ số** khi ghi hỏng) hoặc tách bước cấp số
  ra một giao dịch ngắn riêng. Đổi chác này anh quyết ở blueprint 05 (tích hợp lõi); em chưa đo hai cách ấy.

### (2) Thuế theo dòng + làm tròn *(đo lại 06/11)*

*Đính chính:* bản 05/11 so bằng `round()` của Python — làm tròn nửa về số **chẵn** — trong khi nppsale làm tròn nửa **xa 0**
(`round(numeric)` của Postgres trong `post_invoice`; lõi đặt Commercial Rounding cũng thế), mỗi HĐ chỉ 5 dòng và chỉ đếm lệch ≥ 1 đ.
Bốn ca "lệch 1 đ" của bản ấy đều là số tận cùng ,5 bị **phép so** làm tròn sai, không phải lõi. Kết quả bản ấy bỏ; đo lại như dưới.

Công thức nppsale (`post_invoice` sau mig 183): đơn giá dòng = round(giá bảng × (1 − % giảm dòng)) (POS làm tròn đơn giá sau giảm
về đồng); tiền dòng = SL × đơn giá; **VAT = round(Σ tiền dòng × thuế suất)**; **tổng = round(Σ tiền dòng − giảm đơn + Σ tiền dòng ×
thuế suất)**. So **đúng từng đồng**, không ngưỡng. Mỗi lượt 50 HĐ, 10–20 dòng / HĐ chọn trong 40 mặt hàng, Lon / Loc / Thung, SL 1–20,
thuế 0 / 5 / 8 / 10 %, ~30 % số dòng có giảm 2–15 %; HĐ lập rồi rollback (`thue_lam_tron`).

| precision | Giảm dòng đưa vào lõi thế nào | Giảm đơn | HĐ / dòng (có giảm) | Lệch đơn giá dòng | Lệch tiền hàng | Lệch VAT | Lệch tổng (làm tròn / chưa làm tròn) |
|---|---|---|---|---|---|---|---|
| **0** | **app gửi sẵn đơn giá sau giảm** | — | 50 / 738 (220) | 0 | 0 | 0 | 0 / 0 |
| **0** | **app gửi sẵn** | 5 % | 50 / 720 (232) | 0 | 0 | 0 | 0 / 0 |
| 0 | lõi tự tính từ % | — | 50 / 738 (220) | 13 dòng (thấp hơn 1 đ) | 12 HĐ | 8 HĐ | 12 / 12 HĐ |
| 2 | app gửi sẵn | — | 50 / 738 | 0 | 0 | 50 HĐ — VAT có số lẻ | 0 / 50 |
| 2 | app gửi sẵn | 5 % | 50 / 720 | 0 | 0 | 49 HĐ — VAT có số lẻ | 0 / 49 |
| 2 | lõi tự tính từ % | — | 50 / 738 | 203 dòng (đơn giá lẻ) | 48 HĐ | 50 HĐ | 43 / 50 HĐ |

- **Giảm % dòng — lõi làm tròn khác nppsale.** Lõi tính tiền giảm = giá × %, làm tròn **tiền giảm** rồi lấy giá trừ đi
  (`erpnext/controllers/taxes_and_totals.py:228–233`); nppsale làm tròn **đơn giá sau giảm**. Ca tiền giảm tận cùng ,5 thì lệch 1 đ mỗi
  đơn vị: SP011 thùng 275.668 đ giảm 12,5 % → tiền giảm 34.458,5 → lõi 34.459, đơn giá 241.209; nppsale 241.209,5 → **241.210**. Vì
  vậy app tự tính đơn giá theo luật nppsale và gửi `rate`. Lõi giữ đơn giá app gửi nhưng ở đúng những dòng lệch ấy **xoá
  `discount_percentage` về 0** và ghi `discount_amount` = giá bảng − đơn giá (`taxes_and_totals.py:241–255`; 13 / 220 dòng ở precision 0)
  → % giảm để in và báo cáo app giữ ở trường riêng.
- **precision 2**: VAT ghi số lẻ (821.591,24 thay vì 821.591), tổng chưa làm tròn cũng lẻ, chỉ tổng đã làm tròn về đồng — không khớp
  nppsale và MISA (VAT nguyên đồng).
- **Chốt**: `currency_precision = 0` + Commercial Rounding + `round_row_wise_tax = 0` (mặc định — làm tròn VAT một lần ở tổng như
  nppsale) + app gửi đơn giá sau giảm. `Item.taxes` để trống thì lõi tôn trọng template thuế của từng dòng (VAT khớp từng đồng ở cả 100
  HĐ trộn bốn mức thuế).

### (3) Giảm đầu phiếu nhập NCC — CFD-11

Phiếu nhập 3 dòng × 10 lon (SP001 20.000 đ / lon, SP002 21.000, SP003 22.000), VAT mua 8 %, giảm đầu phiếu 50.000 đ.

| Cách | Tiền hàng dòng SP001 / SP002 / SP003 | Σ thuế (gồm dòng trừ) | Tổng phải trả | Giá vốn lô SP001 / SP002 / SP003 |
|---|---|---|---|---|
| **Dòng thuế `Actual` + `Deduct` 50.000** (`ACC-PINV-2026-00006`) | 200.000 / 210.000 / 220.000 (giữ) | 400 (= 50.400 − 50.000) | 630.400 | 20.000 / 21.000 / 22.000 (giữ) |
| `apply_discount_on = Grand Total` của lõi (`ACC-PINV-2026-00007`) | 185.303 / 194.568 / 203.833 | 46.696 | 630.400 | 18.530 / 19.457 / 20.383 |

Tổng phải trả như nhau; cách dòng trừ giữ tiền hàng, VAT và giá vốn lô đúng luật mig 145 của nppsale. **Chốt cách dòng trừ.**
Sổ cái của `00006`: Nợ Kho 630.000, Nợ Thuế GTGT đầu vào 50.400 / Có NCC 630.400, **Có tài khoản của dòng trừ 50.000** — khoản giảm
vào thẳng lãi lỗ, không hạ giá trị kho. PoC tạm dùng tài khoản "Miscellaneous Expenses"; tài khoản thật (ví dụ thu nhập khác 711
hay ghi giảm giá vốn 632) anh chốt cùng hệ thống tài khoản TT200.
(`ACC-PINV-2026-00004` / `00005` là lượt đầu khi template thuế chưa có tài khoản đầu vào — VAT sai, xem mục 3. Hai lượt dùng chung tên
lô `SP00x-GD-…` nên tra Batch sẽ thấy giá pha trộn; đọc theo từng phiếu.)

### (4) Landed Cost Voucher âm trên lô đã bán — CFD-06

LCV `MAT-LCV-2026-00001` −30.000 đ phân bổ theo tiền cho 30 dòng của `ACC-PINV-2026-00001` (−836 tới −1.164 đ / dòng): lõi **nhận**,
phiếu nhập giữ nguyên số. Lõi sinh **30** việc Repost Item Valuation (tính lại giá vốn) — mỗi mặt hàng của phiếu một việc; `repost_entries()`
chạy hết **16,8 s**, ~0,56 s / việc vì mỗi việc quét lại sổ từ ngày phiếu nhập 06/10 *(đính chính 06/11 — bản 05/11 ghi 5 việc vì hàm
đo chỉ liệt kê `limit=5`)*.

Sổ lô SP001-L1: dòng phiếu nhập 8.109 đ, LCV phân −836 đ / 240 lon → giá nhập **8.105,52 đ**; các HĐ đã xuất lô ấy (`00003` −18 lon,
`00007` −72, `00009` −12, `00013` −1, …) được tính lại theo đúng 8.105,52 (`Serial and Batch Entry.incoming_rate`). LCV âm làm giá vốn
phần đã bán **giảm** đúng như mong đợi. *(Đính chính 06/11: con số 8.118,15 bản 05/11 gọi là "giá vốn HĐ" là cột `valuation_rate` của
sổ kho = bình quân di động **của mặt hàng tại kho**, gộp cả L1 / L2 / L3 — không phải giá vốn lô.)* Báo cáo giá vốn / lãi gộp theo lô
phải đọc qua gói lô, không đọc cột ấy. Chỉ chạy LCV âm; LCV dương cùng đường mã, đo bổ sung ở P2.

### (5) Tờ ghi có độc lập có kho — giá vốn hàng nhập lại (luật mig 127) — CFD-03

Tờ ghi có `is_return = 1`, **không** `return_against`, `update_stock = 1`, 5 lon lô `SP001-L1` (giá vốn lô 8.105,52 đ, giá bán dòng
trả 11.150,7 đ). Sổ có **bốn** tờ, theo thứ tự lập:

| Tờ | Kho nhận | `incoming_rate` app gửi | Sổ ghi giá vốn |
|---|---|---|---|
| `ACC-SINV-2026-00024` | Kho cận date (lô chưa từng có ở đó) | 0 — app tra giá vốn qua `SLE.batch_no` (luôn trống với dòng có gói lô) nên ra 0 | **11.150,7 = giá bán** ✘ |
| `ACC-SINV-2026-00025` | Kho cận date | 8.105,52 | **8.105,52** ✔ |
| `ACC-SINV-2026-00027` | Kho cận date (lô đang còn 10 lon ở đó) | không gửi | 9.628,11 = bình quân lô **tại kho nhận** = (5 × 11.150,7 của `00024` + 5 × 8.105,52 của `00025`) / 10 ✘ |
| `ACC-SINV-2026-00029` | Kho bán (lô đã bán hết ở đó) | không gửi | **11.150,7 = giá bán** ✘ |

Nợ của cả bốn tờ: −55.755 đ (dư có) — đúng luật công nợ âm. Ca `00029` còn để lại hệ quả về sau: hai HĐ bán tiếp lô ấy (`00030`
−3 lon, `00033` −2 lon) bị tính giá vốn **11.150,7** — giá vốn sai **lan sang lãi gộp của HĐ sau**, không chỉ nằm ở tờ trả. Kết
luận: app **luôn** gửi `incoming_rate` cho từng dòng nhập lại = giá vốn lô đã xuất, đọc từ `Serial and Batch Entry.incoming_rate`
của gói lô trên HĐ gốc.

### (6) Huỷ HĐ có chứng từ sau — nhịp tính lại giá vốn — CFD-07

Huỷ `ACC-SINV-2026-00001` (15 dòng, HĐ đầu tiên nên mọi HĐ sau đều là chứng từ sau): `cancel()` **1.248 ms**; lõi sinh **15** việc tính
lại `based_on = Item and Warehouse` — một việc mỗi mặt hàng + kho của HĐ, `voucher_no` trống (lọc theo số HĐ sẽ không thấy; bản 05/11
lọc như thế nên in danh sách rỗng — số 15 đếm theo giờ tạo trong sổ). Gọi `repost_entries()` ngay: **4,2 s**, 15/15 Completed. So với LCV
(30 việc, 16,8 s): gấp đôi số việc, và mỗi việc dài gấp đôi (~0,56 s so với ~0,28 s) vì quét lại sổ từ 06/10 thay vì từ giờ HĐ.

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
`SAMEORIGIN` — đúng yêu cầu khung in của POS, nhưng Cloudflare / nginx thật trên VPS phải kiểm lại (P2).

### (8) Hai dòng cùng mã cùng lô; đổi mã lô

- `allow_multiple_items = 1`: HĐ hai dòng `SP002` (1 thùng + 3 lon) cùng lô ghi được (`ACC-SINV-2026-00023`); tắt → *"Item SP002 entered
  multiple times. Please enable Allow Item to Be Added Multiple Times in a Transaction"*.
- Đổi tên lô *(đính chính 06/11)*: đường thường (`rename_doc` không ép) bị chặn — **"Batch not allowed to be renamed"** vì DocType Batch
  không khai `allow_rename`. Nhưng lõi chỉ chặn khi **không** `force` / `ignore_permissions` (`frappe/model/rename_doc.py:385`): method
  của app gọi `rename_doc("Batch", cũ, mới, force=True)` thì đổi được — lô `SP003-L3` có 27 dòng gói lô + 1 dòng phiếu nhập đổi theo
  trong 0,43 s; dò **10.371 cột chữ** của mọi bảng không còn chỗ nào giữ mã cũ (thử trong giao dịch rồi rollback). Bản 05/11 kết luận
  "mã lô bất biến" là sai. Hướng mới: giữ tính năng sửa mã lô của nppsale qua method có kiểm vai, ép `force`, xoá cache sau khi đổi.
  Rủi ro còn lại: lõi cố ý không cho đổi tên lô ở Desk, nên đây là đường đi vòng — giữ bài thử này làm bài hồi quy khi nâng bản lõi.

### (9) Nhập lại lô đã hết hạn

Lô `SP001-HETHAN` hết hạn 26/10 (10 ngày trước ngày đo):

| Cách | Kết quả |
|---|---|
| Material Receipt, dòng ghi `batch_no` | `BatchExpiredError: The batch SP001-HETHAN has already expired` |
| Material Receipt, dòng gắn **gói lô nhập do app lập** (không `batch_no` ở dòng) | **nhận** (`MAT-STE-2026-00002`, +5 @ 10.000) |
| Tờ ghi có có kho (`is_return`, `update_stock`) với lô hết hạn | **nhận** (`ACC-SINV-2026-00026`, +2 @ 9.000) |

Lõi chỉ kiểm hạn khi dòng mang `batch_no` (`erpnext/controllers/stock_controller.py:387`) và với gói lô **xuất**
(`validate_outward_bundle_batches`, `:411`); gói lô nhập không bị kiểm. Đây là khoảng trống của lõi chứ không phải tính năng được
hứa — bản sau có thể chặn nốt, nên ghim phiên bản và giữ bài này làm bài hồi quy trước mỗi lần nâng bản; đường dự phòng là nhập vào
lô mới `HT-<lô cũ>`.

### (10) Tờ đầu kỳ giữ mã HĐ cũ

`Sales Invoice.insert(set_name="HD-0042")` với `is_opening = Yes`, tiền 1.250.000: tên **`HD-0042`**, nợ 1.250.000 — nợ đầu kỳ theo từng HĐ
lịch sử (H3) giữ nguyên mã HĐ nppsale. Dãy số thật của app phải không bao giờ sinh trùng mã lịch sử (dãy `HD-` bắt đầu sau số lớn nhất đã
nhập).

### (11) Sửa HĐ đã ghi sổ = huỷ + tờ mới đuôi `-n` — CFD-01 *(thêm 06/11)*

`sua_hd_amend`: huỷ `ACC-SINV-2026-00101` rồi lập tờ amend (`copy_doc` + `amended_from`), làm hai lần liền → **`ACC-SINV-2026-00101-1`**
(2,6 s) rồi **`ACC-SINV-2026-00101-2`** (1,1 s); tờ cũ docstatus 2 (Đã huỷ), tờ mới trỏ `amended_from` về tờ trước. Tờ amend **không mang
gói lô cũ** (trường ấy không chép sang); lõi tự lập gói lô lúc ghi sổ theo luật chọn lô của lõi (ở đây SP001-L3, SP004-L4… chứ không phải
lô app từng gán). Vì vậy method Sửa HĐ phải tự gán lô lại theo luật app trước khi ghi sổ tờ mới.

## 3. Phát hiện ngoài kế hoạch

1. **Đồng thời là việc của app** (1b, 1d): lõi chỉ kiểm lô âm bằng câu đọc có khoá lúc lập gói lô và lúc ghi sổ; bước chọn lô của app
   đọc theo ảnh chụp cũ. Không khoá `Bin` trước thì hàng trùng sẽ lô âm hoặc bế tắc (MariaDB 1213).
2. **Số HĐ khoá suốt giao dịch** (1d): `getseries` giữ khoá hàng `tabSeries` của dãy tới khi commit, nên mọi lượt Xuất hàng xếp hàng một,
   kể cả hàng khác nhau. Đo lại với gunicorn nhiều worker trên VPS; cách cấp số chọn ở blueprint 05.
3. **Tách dòng làm lẻ số lon** (1c): 0,833 thùng = 19,992 lon. Luôn dùng gói lô một dòng.
4. **Giảm % dòng: lõi làm tròn tiền giảm, nppsale làm tròn đơn giá** (2) → app gửi đơn giá; lõi xoá `discount_percentage` ở dòng lệch →
   app giữ % ở trường riêng.
5. **Item Tax Template phải có cả tài khoản thuế đầu vào**: template chỉ có "Thuế GTGT đầu ra" thì phiếu nhập NCC tính VAT sai mà không báo
   gì (lượt đầu của điểm 3). `setup.py` đã sửa ngày 06/11 để tạo đủ hai tài khoản. Vào 3.11.
6. **Sổ kho của dòng có gói lô không ghi `batch_no`** (null) — mọi câu "giá vốn theo lô", "tồn theo lô" phải nối qua `Serial and Batch
   Bundle` / `Serial and Batch Entry` (hoặc dùng `get_batch_qty`), không lọc `SLE.batch_no`. Cột `valuation_rate` của sổ kho là bình quân
   mặt hàng tại kho, không phải giá vốn lô (điểm 4).
7. **Giá vốn hàng trả sai thì lan sang HĐ sau** (điểm 5) — lý do app phải tự điền `incoming_rate` cho mọi dòng nhập lại.
8. **Tính lại giá vốn theo mặt hàng + kho, không theo chứng từ** (6): màn "đang tính lại giá vốn (N)" đếm theo trạng thái việc, không theo
   số HĐ.
9. **Tờ amend không mang lô cũ** (11): Sửa HĐ phải gán lô lại.
10. **Không có hệ thống tài khoản Việt Nam trong v16** (không có `vn_*` trong `chart_of_accounts/verified` lẫn `unverified`) → app ship mẫu
    TT200 và truyền `chart_of_accounts` khi tạo công ty (anh đã đồng ý câu 9). PoC tạm dùng "Standard".
11. Nhỏ: `session_expiry` nhận dạng `hh:mm` (`720:00` = 30 ngày); `Item Barcode.barcode_type` đặt EAN là lõi kiểm số kiểm tra — mã nội bộ
    để trống loại mã; `bench execute --kwargs` nhận literal Python (`True` / `False`), không nhận JSON `true` / `false`; khi cài app từ repo
    gọi `bench get-app nppsale https://github.com/mrhuychien/npp` để thư mục là `apps/nppsale` (repo tên `npp`).

## 4. Những gì chỉ đo được trên VPS (P2, GCloud)

- Header thật qua nginx của bench / Cloudflare: `X-Frame-Options` cho khung in, cache HTML của vỏ SPA, `sw.js`, nén.
- socket.io (cổng 9000) qua proxy; gunicorn nhiều worker — số đo đồng thời ở đây là tiến trình `bench execute`, nặng hơn worker nóng.
- Thời gian với **dữ liệu thật** của anh (1.835 mặt hàng, 598 khách, ~2.700 HĐ) sau khi có công cụ nhập H3.
- Sao lưu `bench backup --with-files` + đẩy Drive theo lịch.

## 5. Chạy lại

```bash
bench --site <site> execute nppsale.poc.setup.run --kwargs "{'currency_precision': '0'}"
bench --site <site> execute nppsale.poc.do.nhap_ton
bench --site <site> execute nppsale.poc.do.xuat_hang_nhieu --kwargs "{'lan': 10, 'so_dong': 15}"
bench --site <site> execute nppsale.poc.do.hai_lo_do --kwargs "{'lan': 5}"
bench --site <site> execute nppsale.poc.do.thue_lam_tron --kwargs "{'n': 50, 'giam_don_pct': 0, 'cach_giam_dong': 'app', 'seed': 1}"
bench --site <site> execute nppsale.poc.do.thue_lam_tron --kwargs "{'n': 50, 'giam_don_pct': 0, 'cach_giam_dong': 'loi', 'seed': 1}"
bench --site <site> execute nppsale.poc.do.thue_lam_tron --kwargs "{'n': 50, 'giam_don_pct': 5, 'cach_giam_dong': 'app', 'seed': 2}"
bench --site <site> execute nppsale.poc.do.dat_precision --kwargs "{'p': '2'}"
bench --site <site> execute nppsale.poc.do.dat_precision --kwargs "{'p': '0'}"
bench --site <site> execute nppsale.poc.do.giam_dau_phieu_nhap
bench --site <site> execute nppsale.poc.do.lcv_sua_gia
bench --site <site> execute nppsale.poc.do.lcv_kiem_lai
bench --site <site> execute nppsale.poc.do.ghi_co_doc_lap2 --kwargs "{'dat_incoming_rate': False}"
bench --site <site> execute nppsale.poc.do.repost_khi_huy
bench --site <site> execute nppsale.poc.do.hai_dong_cung_lo
bench --site <site> execute nppsale.poc.do.doi_ma_lo_ep
bench --site <site> execute nppsale.poc.do.doi_ma_lo_ep_do_sot
bench --site <site> execute nppsale.poc.do.nhap_lai_lo_het_han2
bench --site <site> execute nppsale.poc.do.dau_ky_giu_ma
bench --site <site> execute nppsale.poc.do.sua_hd_amend
```

Lượt precision 2: chạy `dat_precision` với `'2'`, gọi lại ba lượt `thue_lam_tron` (cùng `seed`), rồi trả về `'0'`.
Bài đồng thời 1d: năm cửa sổ cùng gọi `nppsale.poc.do.xuat_hd_dong_thoi --kwargs "{'cho_den': <epoch + 75>, 'k': k, 'chung': False, 'khoa': True}"`
với k = 1…5 (đổi `chung` / `khoa` cho bốn kịch bản); bài cũ 1b: `xuat_hang_dong_thoi`. Điểm 7: `bench --site <site> serve --port 8000` rồi
`curl -D - http://127.0.0.1:8000/nppsale/sw.js`.

Mã PoC nằm trong app để P2 dùng lại làm bộ dựng site thử và bộ đo hồi quy; **không** cài lên site thật (`setup.run` tạo công ty, kho,
mặt hàng mẫu).
