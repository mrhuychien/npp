# Kết quả PoC P0 — ERPNext v16 chạy luật nppsale (đo 05/11/2026, soát và đo lại 06/11 và 10/11/2026)

Mục đích: trước khi viết blueprint và hứa lộ trình, **đo thật** các điểm ở mục 9 của bản bàn bạc trên một bench
ERPNext v16 dựng từ đầu, bằng mã Python đi đúng đường app sẽ đi (method gọi API lõi), không bấm tay trên Desk. Mọi con số
do mã đo in ra (thời gian; phép so thuế — HĐ lập rồi rollback nên không còn trong sổ) hoặc đọc từ sổ (`tabStock Ledger Entry`, `tabSerial and Batch Entry`, `tabRepost Item Valuation`, `tabGL Entry`…), không từ màn hình.

**Bản 06/11.** Một vòng soát tự động bằng agent (không phải người thật) đối chiếu con số với sổ PoC bằng câu chỉ đọc. Lượt ấy chỉ hai
trong năm góc soát chạy xong — số liệu và sổ sách —, phần phản biện không chạy được vì hết lượt dùng; em tự kiểm lại từng phát hiện
trên sổ trước khi sửa. Hai góc ấy tìm ra bốn chỗ bản 05/11 **ghi sai hoặc đo sai** — LCV (phiếu chỉnh giá nhập của lô) sinh 30 việc
tính lại giá vốn chứ không phải 5; giá vốn sau LCV ghi ngược chiều; phép so thuế dùng sai kiểu làm tròn; lời giải thích bài đồng thời
nói ngược cơ chế — và ba chỗ khẳng định khi **chưa đo** (dòng hai lô thật, hàng không trùng thì chạy song song, đổi mã lô). Em đã đo
lại / đo thêm tất cả; chỗ đổi so với bản 05/11 có dấu *(đính chính 06/11)*.

**Bản 10/11.** Vòng soát lại đầy đủ trên bản 06/11: năm góc soát (số liệu, sổ sách, chuyên gia ERPNext, nhất quán + người đọc, mã đo)
ra 162 phát hiện, gộp thành 53 vấn đề; mỗi vấn đề hai agent phản biện khác góc nhìn, bất đồng thì agent thứ ba phân xử — giữ 51, bác 2.
Em áp các vấn đề ấy, trừ một chỗ chờ anh: mốc đo trên dữ liệu thật lệch giữa hai tài liệu (mục 4 dưới đây hẹn P2, bảng giai đoạn ở mục 9 bản bàn bạc đặt công cụ nhập ở P8) — anh chọn khi duyệt lộ trình, em mới ghi chú ở blueprint 01. Vì vấn đề nặng nhất là phép so thuế dùng sai luật giảm dòng của nppsale, em **đo lại phần thuế theo đúng luật**
(mục 2.(2)), đo thêm SL lẻ và dòng 0 đ. Bằng chứng thô — nguyên văn máy in ra và các câu đối chiếu sổ — ở `01_bang_chung.md`.

## 0. Kết luận một trang

| # | Điểm đo | Kết quả | Hệ quả cho thiết kế |
|---|---|---|---|
| 1 | Xuất hàng 15 dòng (13 dòng theo lô, 2 không lô), app tự gán lô FIFO bằng bundle | **TB 1,30 s** (1,16–1,78 s) / lượt gồm cả lập đơn, 10 lượt, 0 lỗi; riêng phần Xuất HĐ ~0,98 s | đạt, nhưng nặng hơn nppsale trên máy khoẻ nhiều lần (mục 2.(1)) |
| 1b | 5 phiên cùng bấm, bài cũ (đơn + HĐ một giao dịch, hàng trùng nhiều, lô gần hết) | không khoá: **1/5** thành công, 4 lỗi lô âm; khoá Bin: 5/5 nối đuôi | method `xuat_hang` **phải** khoá Bin (dòng ghi tồn của một mặt hàng tại một kho — khoá nó là bắt các lượt Xuất cùng mặt hàng xếp hàng) — CFD-05 |
| 1c | Dòng cần **hai lô thật** (2 thùng, lô đầu còn 20 lon) *(đo 06/11)* | bundle: một dòng "2 thùng", sổ ghi đúng 20 + 28 lon; tách dòng: 0,833 + 1,167 thùng, sổ ghi **19,992 + 28,008 lon** | luôn dùng bundle, không bao giờ tách dòng |
| 1d | 5 phiên cùng Xuất HĐ của đơn đã chốt *(đo 06/11)* | hàng **rời nhau**: 5/5 nhưng **nối đuôi** ~0,7 s / HĐ (khoá dãy số HĐ); hàng trùng không khoá: 4/5, 1 **bế tắc** (deadlock); hàng trùng có khoá Bin: 5/5 nối đuôi | khoá Bin (dòng tồn của một mặt hàng tại một kho) **trước khi dựng HĐ** — hàng trùng mà không khoá thì 3 HĐ lọt qua mang giờ ghi sổ sớm hơn HĐ đã ghi, sinh 24 việc tính lại giá vốn — + thử lại khi bế tắc (deadlock — hai phiên chờ khoá của nhau, MariaDB huỷ một); nối đuôi do dãy số HĐ (hàng `tabSeries` giữ số cuối của dãy, bị khoá tới khi ghi xong) là giới hạn của lõi — với anh: 5 người bấm Xuất hàng cùng giây thì người cuối chờ ~3,4–4,4 s; cách cấp số anh chọn ở blueprint 05 |
| 2 | Thuế 0/5/8/10 % theo dòng + làm tròn, giảm dòng %, so đúng luật nppsale *(đo lại 10/11)* | precision **0** (tiền làm tròn tới đồng) + app gửi đơn giá tính theo luật nppsale (% trên tiền dòng): tiền hàng / VAT / tổng **khớp từng đồng 100/100 HĐ SL nguyên (1.458 dòng)**; để lõi tự tính giảm % → 15 dòng thấp hơn 1 đ, 11 / 50 HĐ lệch tổng tới 25 đ; **SL lẻ** → 16–20 / 50 HĐ lệch tổng 1–2 đ — chỉ 3–10 HĐ lệch tiền hàng vì lõi làm tròn tiền từng dòng, còn lại phần lớn vì `post_invoice` làm tròn tổng một lần (HĐ SL lẻ của nppsale có tiền hàng + VAT ≠ tổng); VAT kiểu HĐĐT nppsale đang đẩy (làm tròn từng dòng) khác VAT sổ ở 13–31 / 50 HĐ từ hôm nay; bật `round_row_wise_tax` thì lõi từ chối 6 / 50 HĐ 10–20 dòng; dòng hàng đổi gửi đơn giá 0 kèm giá bảng → lõi tự đặt lại thành giá bảng; precision 2 → VAT có số lẻ | `currency_precision = 0`; app tự tính đơn giá theo luật nppsale, gửi kèm giá bảng; % giảm giữ ở trường riêng; dòng 0 đ gửi giá bảng kèm khoản giảm bằng giá bảng (`discount_amount`, không gửi %); tắt `auto_insert_price_list_rate_if_missing`; SL lẻ và `round_row_wise_tax`: anh chọn (câu 19) |
| 3 | Giảm đầu phiếu nhập NCC | dòng thuế **Actual + Deduct** giữ nguyên tiền hàng dòng, VAT và giá vốn lô; khoản giảm ghi Có vào một tài khoản lãi lỗ | chốt cách dòng trừ (CFD-11); anh chọn tài khoản |
| 4 | Landed Cost Voucher (LCV — phiếu chỉnh giá nhập của lô sau khi đã nhập; tờ phiếu nhập giữ nguyên số) âm trên lô đã bán | nhận −30.000 đ, phiếu nhập giữ số; **30 việc** tính lại giá vốn (mỗi mặt hàng một việc) chạy 16,8 s; giá nhập lô SP001-L1 **8.109 → 8.105,52 đ** và HĐ đã xuất lô ấy tính lại theo đúng giá mới | sửa giá phiếu nhập đã bán = LCV **+ debit note / bút toán giảm nợ NCC** (LCV không đụng công nợ NCC: Có NCC giữ 69.828.480, khoản −30.000 ghi Nợ vào tài khoản của LCV) — CFD-06 đúng; LCV dương chưa chạy |
| 5 | Tờ ghi có độc lập có kho, giá vốn hàng nhập lại | app đặt `incoming_rate` → sổ đúng; không đặt hoặc gửi 0 → lõi lấy bình quân lô ở kho nhận nếu lô còn ở đó; lô chưa có / đã hết ở kho nhận thì lõi gán thẳng `incoming_rate` = `rate` của dòng trả (`selling_controller.py:674–680`) — **giá bán theo đơn vị của dòng**, trong khi `incoming_rate` là giá mỗi đơn vị kho (`:696` phải nhân `conversion_factor` mới so được với `rate`): PoC chỉ thử dòng Lon nên thấy đúng "giá bán", dòng trả 1 thùng sẽ ghi giá vốn mỗi lon bằng giá cả thùng (theo mã, chưa đo); giá vốn sai **lan sang HĐ bán sau** lô ấy | app **luôn** tự điền `incoming_rate` theo đơn vị kho và không gửi 0; lưu lại tờ nháp mà đổi mặt hàng / kho / SL / lô thì lõi xoá giá app gửi ngay trong lượt lưu ấy rồi tự tính lại (`:630–631`) — method đặt giá lúc lập tờ và ghi sổ ngay, không sửa-lưu tờ nháp; giữ Selling Settings `set_zero_rate_for_expired_batch` = 0 (bật thì lõi ép giá vốn 0 cho dòng ghi lô hết hạn, `:610–619`) — CFD-03 |
| 6 | Huỷ HĐ (có chứng từ sau hay không — lõi luôn xếp việc khi huỷ chứng từ có sổ kho), app tự chạy tính lại | huỷ 1,25 s; sinh 15 việc tính lại (mỗi mặt hàng + kho một việc), chạy hết 4,2 s — chạy **tuần tự** bằng `repost_entries()` khi tính lại song song **tắt** và hàng đợi không còn việc cũ | bật tính lại song song + app gọi ngay `enqueue_parallel_reposting()` (chạy ở hàng `long`) — **không** gọi `repost_entries()`, vì bật song song thì hàm ấy thoát ngay không làm gì (`repost_item_valuation.py:834–835`); nhịp song song chưa đo; việc còn chờ không chặn huỷ / Sửa HĐ (điểm 11); màn "đang tính lại" đếm việc theo trạng thái — CFD-07 |
| 7 | Vỏ SPA `/nppsale/*`, `sw.js`, manifest qua `page_renderer` | vỏ không cache cho mọi đường dẫn con, có CSRF + người dùng; `sw.js` đúng `Content-Type`, `no-cache`, `Service-Worker-Allowed: /nppsale/` | renderer nhìn `request.path`; `sw.js` không để dưới `/assets`; header khung in kiểm lại trên VPS |
| 8 | HĐ hai dòng cùng mã cùng lô; đổi mã lô đã có sổ | cần `allow_multiple_items`; đổi tên lô: đường người dùng bị chặn, **method app ép `force=True` thì đổi được mọi cột Link trỏ tới lô** — thử trong một giao dịch rồi rollback (27 dòng gói lô + 1 dòng phiếu nhập sang mã mới); cột Data `Stock Ledger Entry.batch_no` của dòng sổ đảo đã huỷ thì không đổi, phần chạy sau commit chưa thử — xem 2.(8) *(đính chính 06/11)* | giữ được tính năng sửa mã lô của nppsale, qua method có kiểm vai |
| 9 | Nhập lại lô **đã hết hạn** | Material Receipt có dòng ghi `batch_no` (SL dương) → `BatchExpiredError`; bundle nhập do app lập → nhận; tờ ghi có có kho → nhận, **kể cả** khi dòng ghi thẳng `batch_no` lô hết hạn (`00026`: SL âm nên lõi không kiểm hạn — `stock_controller.py:387`, `:412`) | hàng trả quá date: tờ ghi có có kho lập thẳng; phiếu nhập kho (Stock Entry) của phiếu tự sinh mới phải đi đường bundle; giữ bài này làm bài hồi quy khi nâng bản lõi |
| 10 | Tờ đầu kỳ giữ mã HĐ cũ | `insert(set_name="HD-0042")` → tên `HD-0042`, `is_opening = Yes`, nợ 1.250.000 | H3 giữ mã HĐ lịch sử được |
| 11 | Sửa HĐ = huỷ + tờ mới đuôi `-n` *(thêm 06/11)* | `…00101` → `…00101-1` → `…00101-2`, tờ cũ Đã huỷ; tờ mới **không mang gói lô cũ** (huỷ đã xoá), lõi tự lập gói lô theo FIFO của lõi vì cờ `auto_create_serial_and_batch_bundle_for_outward` bật — ở bài đo ra **trùng đúng** lô app đã gán cho tờ gốc; tờ mới giữ giờ ghi sổ tờ cũ; mỗi lần huỷ sinh 8 việc tính lại giá vốn (sổ còn Queued) | CFD-01 đúng; method Sửa HĐ phải tự gán lô lại theo luật app (FIFO theo ngày nhập như `reissue_invoice` của nppsale — lõi xếp theo ngày tạo bản ghi lô), không để lõi tự chọn |

**Sáu điều lộ ra ngoài kế hoạch đáng chú ý nhất** (mục 3 ghi đủ mười ba điều, kể cả sổ kho không ghi lô ở dòng có gói lô và v16 không có hệ thống tài khoản Việt Nam): (a) **đồng thời là việc của app** — app chọn lô bằng câu đọc thường
(đọc theo ảnh chụp của giao dịch), lõi kiểm bằng câu đọc có khoá, nên không khoá thì lô âm hoặc bế tắc; (b) **số HĐ cấp trong
giao dịch và giữ khoá tới khi ghi xong**, nên mọi lượt Xuất hàng xếp hàng một, kể cả khi hàng khác nhau; (c) **tách dòng
làm lẻ số lon**; (d) **lõi tính giảm % trên đơn giá, nppsale tính trên tiền dòng** (SL × giá bảng) rồi chia lại SL — lệch 1 đ / đơn vị ở vài dòng, tuỳ SL, nên app phải tự tính đơn giá; (e) **dòng hàng đổi 0 đ bị lõi tự định giá lại thành dòng bán có tiền** (giá bảng, hoặc giá lõi tự tra khi thiếu giá bảng) nếu gửi sai cách; (f) Item Tax Template (mẫu thuế suất gắn cho từng dòng hàng) phải có **cả** tài khoản thuế đầu ra
và đầu vào — thiếu đầu vào thì phiếu nhập tính VAT sai mà không báo gì.

## 1. Môi trường

| | |
|---|---|
| frappe / erpnext | `version-16`: frappe **16.55.2**, erpnext **16.53.0** (bench 5.31.1) |
| Python / Node / MariaDB | 3.14.6 / 24.11.0 / 10.11.14 (mức cô lập REPEATABLE-READ, chờ khoá tối đa 50 s, `innodb_snapshot_isolation` = OFF — mặc định của bản này). Từ MariaDB 11.6.2 biến ấy mặc định **ON**, mà Frappe v16 nhận tới 11.8 (`frappe/database/mariadb/setup_db.py:102–116`). Khi bật, câu đọc có khoá hay câu UPDATE chạm dòng mà giao dịch khác đã đổi sau ảnh chụp sẽ bị từ chối bằng lỗi 1020 thay vì đọc số mới nhất; Frappe báo lỗi này thành `QueryDeadlockError` (`frappe/database/mariadb/database.py:27–29`), và chính Frappe ghi chú điều này ở `frappe/automation_engine/drainer.py:57–63`. Số của 1b / 1d khi ấy sẽ khác: ví dụ hàng dãy số `tabSeries` bị khoá sau ảnh chụp (`frappe/model/naming.py:412`) thì tiến trình tới sau hỏng thay vì nối đuôi (theo mã, chưa đo). VPS phải dùng bản trước 11.6.2 hoặc đặt `innodb_snapshot_isolation = OFF`; nếu không thì đo lại 1b / 1d trên đúng bản ấy |
| Máy | container 4 vCPU, 16 GB RAM (môi trường phát triển, không phải VPS) — số tuyệt đối sẽ khác trên GCloud; tỷ lệ và kết luận dự kiến giữ, riêng phần đồng thời phải đo lại với gunicorn nhiều worker và đúng bản MariaDB của VPS (mục 4) |
| Site | `poc.local`, công ty "NPP Thu" (VND, Việt Nam, Fiscal Year 2025 + 2026), 2 kho (`Kho ban - NPP`, `Kho can date - NPP`), 3 đơn vị (Lon 1 / Loc 6 / Thung 24), bảng giá "Gia chuan" + "Gia nhap" + "Gia nhom VIP", 40 mặt hàng (30 theo lô, 20 có hạn dùng, 10 không lô cho phép tồn âm), 10 khách, 3 NCC |
| Cài đặt theo mục 3.11 | Commercial Rounding, `currency_precision` 0 (đổi 2 để so rồi trả về), `round_row_wise_tax` 0 (mặc định), `enable_serial_and_batch_no_for_item`, `allow_multiple_items` bán + mua, `unlink_payment_on_cancellation_of_invoice`, `role_allowed_to_over_bill` / `over_deliver_receive`, `maintain_same_sales_rate` tắt, `is_cash_or_non_trade_discount` trên HĐ bán có giảm đơn, hạn mức tín dụng trống, `Item.taxes` trống + Item Tax Template `VAT 0/5/8/10% - NPP`. `default_amend_naming = Amend Counter` là mặc định của lõi (script không đặt; thử ở điểm 11). Các cài đặt khác quyết định kết quả ở dưới (đọc `tabSingles`): System Settings `float_precision` 3 (số lẻ của số lượng — gốc của 0,833 thùng ở 1c) và `enable_scheduler` 0 (việc tính lại giá vốn không tự chạy, phải gọi `repost_entries()` tay ở điểm 4, 6 — vì thế sổ còn 40 việc Queued từ 06/11); Stock Settings `valuation_method` FIFO + `do_not_use_batchwise_valuation` 0 (mọi lô `use_batchwise_valuation` = 1 → giá vốn lô = bình quân trong lô tại kho, điểm 4 / 5), `use_serial_batch_fields` 1, `pick_serial_and_batch_based_on` FIFO (= thứ tự `Batch.creation`, cũng là thứ tự `get_batch_qty` trả về), `auto_create_serial_and_batch_bundle_for_outward` 1 (nhờ nó lõi tự lập gói lô cho tờ amend ở điểm 11; tắt thì dòng xuất thiếu gói lô báo lỗi — theo mã, chưa thử); Accounts Settings `add_taxes_from_item_tax_template` 1; Stock Reposting Settings `item_based_reposting` 1 + `enable_parallel_reposting` 0 (việc tính lại theo mặt hàng + kho, chạy tuần tự — số "song song" chưa đo) |
| Mã | app khung `nppsale` (repo này): `nppsale/poc/setup.py` dựng toàn bộ site; `nppsale/poc/do.py` các phép đo; `nppsale/portal/tinh.py` + `nppsale/www/nppsale/` cho điểm 7 |

Tồn đầu: 3 phiếu nhập (mỗi mặt hàng theo lô một lô `SPxxx-L1..L3`, 240 lon / lô, ngày 06/10 · 13/10 · 20/10, giá nhập lệch 10 đ
giữa các lô) + 1 Material Receipt cho hàng không lô; giữa chừng nhập thêm lô `-L4` 600 lon để bài đồng thời không thiếu hàng.
Các phép đo ngày 06/11 lập thêm HĐ `ACC-SINV-2026-00043` trở đi (đọc sổ để soát số ngày 05/11 thì trừ các tờ ấy ra).

## 2. Số đo từng điểm

### (1) Xuất hàng — 10 lượt tuần tự, 15 dòng / lượt

Luồng như app sẽ làm: Sales Order (insert → submit) → `make_sales_invoice` → `update_stock = 1`, kho bán → app chọn lô FIFO
(`get_batch_qty`) và gắn **một Serial and Batch Bundle** (gói lô — bảng ghi "dòng này lấy lô nào bao nhiêu") cho mỗi dòng
(`SerialBatchCreation`, `do_not_submit`) → insert → submit. 15 dòng = 13 mặt hàng theo lô chọn ngẫu nhiên trong 30 + 2 mặt hàng
không lô trong 10; đơn vị trộn Lon / Loc / Thung, SL 1–3, thuế dòng 0 / 8 / 10 %; HĐ `ACC-SINV-2026-00013…00022`. Trong bảng: SO = đơn hàng (Sales Order), SI = hoá đơn (Sales Invoice); insert = lưu tờ, submit = ghi sổ (với HĐ là trừ kho, ghi nợ; với đơn là chốt đơn, giữ hàng trong `Bin`). Dòng "SI lập + gán lô + insert" tính từ sau khi chốt đơn nên gồm cả `make_sales_invoice`, bước app chọn lô và lập gói lô — khác "SI insert" ở 1d, chỉ đo riêng lệnh insert.

| | min | TB | max |
|---|---|---|---|
| Cả lượt (lập đơn + Xuất HĐ) | 1.156 ms | **1.300 ms** | 1.783 ms |
| SO insert / SO submit | | 173 / 150 ms | |
| SI lập + gán lô + insert / SI submit | | 405 / 573 ms | |

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

Năm tiến trình riêng (`bench execute`), mỗi tiến trình lập **đơn + HĐ trong cùng một giao dịch** ở lượt 1–2 (lượt 3 có khoá thì `xuat_hang_mot` commit đơn trước rồi mới khoá `Bin` và lập HĐ — `do.py:110–115`), 15 dòng như điểm 1, chọn
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

Vì sao lẻ: số lượng dòng giữ 3 số lẻ (`float_precision` = 3 — mặc định của Frappe, `setup.py` đặt lại 3; nâng số lẻ chỉ làm phần lẻ nhỏ đi chứ không hết, vì 20 / 24 không bao giờ tròn: 0,833333333 × 24 = 19,999999992) — 20 / 24 = 0,8333… lưu thành 0,833 thùng × 24 = 19,992 lon. Phần lẻ không nằm yên trong tờ ấy: năm lô SP002-L2, SP004-L3, SP006-L2, SP008-L2, SP010-L2 còn dư 0,008 lon, và hai HĐ làm nóng của bài 1d (`ACC-SINV-2026-00064`, `00065`) — đi đường bundle — đã phải gói "0,008 lon lô cũ + 1,992 lon lô sau" ở cả 5 dòng ấy, tức lẻ dính sang HĐ của người khác. Tồn lô lệch dần từng phần
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
| Hàng **trùng**, không khoá | **4/5**, 1 **bế tắc** — MariaDB 1213 "Deadlock found"; ngoài ra 3 / 4 HĐ ghi được (`00089`, `00090`, `00091`) mang giờ ghi sổ đặt lúc dựng HĐ — **trước** khi chờ — nên sớm hơn `00088` đã ghi trước (19:43:27,0032–,0038 so với ,0051): lõi coi là ghi lùi giờ và sinh **24** việc tính lại giá vốn (8 mặt hàng × 3), sổ PoC vẫn để Queued | 814 · 1.613 · 2.366 · 3.168 | lúc app lập gói lô: câu đọc có khoá số dư lô (`serial_batch_bundle.py:951`) quét **khoảng** trên chỉ mục kho + lô + giờ ghi sổ (EXPLAIN: `range`, `warehouse_batch_no_posting_datetime_index`), ở REPEATABLE READ khoá cả khe giữa các dòng; mỗi phiên lại chèn dòng gói lô / sổ kho mới vào đúng khoảng ấy → hai phiên chờ nhau, MariaDB huỷ một. Chưa chỉ đích danh được chu trình: tài khoản site không có quyền đọc `SHOW ENGINE INNODB STATUS` |
| Hàng trùng, khoá Bin | 5/5 | 873 · 1.781 · 2.646 · 3.475 · 4.444 | ở câu khoá Bin (1 → 863 → 1.772 → 2.636 → 3.464 ms) |

Ba kết luận:
- Một HĐ 8 dòng chiếm ~0,7–0,9 s. Năm người bấm cùng giây thì người thứ năm chờ ~3,4–4,4 s — **kể cả khi hàng khác nhau** *(đính chính
  06/11 — bản 05/11 viết "không trùng thì chạy song song" khi chưa đo)*. Công suất trên máy này cỡ 1,1–1,4 HĐ / giây.
- Không khoá Bin thì hàng trùng sẽ hoặc lô âm (1b — lô gần hết), hoặc bế tắc (đây — lô còn nhiều); ba HĐ lọt qua của kịch bản này còn bị lõi coi là ghi lùi giờ (giờ ghi sổ đặt lúc dựng HĐ, trước khi chờ) và sinh **24 việc tính lại giá vốn**, vẫn Queued trong sổ. Có khoá Bin thì HĐ dựng sau khi giành khoá, giờ ghi sổ tăng dần theo thứ tự ghi (`00097` → `00101`: 45,005 → 48,471), không sinh việc nào. Luật cho method `xuat_hang`:
  đọc danh sách mặt hàng của đơn **trước** → commit (chưa ghi gì) → câu **đầu tiên** sau commit: khoá `Bin` của **mọi** mặt hàng kho trên phiếu, cả hàng không lô, theo thứ tự tên. Bài PoC mới khoá hàng có lô (`do.py:113`; `hang_lo` trong `xuat_hd_dong_thoi`), trong khi lúc ghi sổ lõi cập nhật `Bin` từng dòng theo thứ tự dòng (`erpnext/stock/stock_ledger.py:205–223`) và đọc có khoá dòng sổ kho cuối của từng mặt hàng + kho (`:2263–2297`). Hai HĐ cùng dãy số thì khoá dãy số đã xếp hàng chúng từ lúc `insert`, nhưng ở bước ghi sổ SO trong `xuat_hang` (cập nhật `Bin` trước khi HĐ lấy số), ở phiếu xuất kho lẻ / phiếu nhập, hay khi dùng cách cấp số không khoá ở blueprint 05, hàng không lô vẫn có thể giành khoá chéo — theo mã, chưa đo. Giữa commit và khoá không được có câu đọc thường nào: đọc đơn, kiểm quyền, `get_cached_value` hụt cache, hay callback `after_commit` có đọc sổ (chạy khi giao dịch mới đã mở, `frappe/database/database.py:1204–1208`) đều lập ảnh chụp trước khoá. Vì vậy phải **dựng HĐ sau khi có khoá**: với `set_posting_time = 1` như PoC, giờ ghi sổ chốt lúc dựng HĐ; dựng trước khi chờ khoá thì HĐ ghi sau mang giờ sớm hơn HĐ đã ghi, lõi coi là ghi lùi và sinh việc tính lại (24 việc ở kịch bản hàng trùng không khoá trên). Sau đó mới đọc tồn lô → lập gói lô → insert / submit → commit. Luật này nằm trong method app, không đặt ở hook `doc_events` (lõi tắt commit trong hook — `frappe/model/document.py:1905–1917`, `frappe/database/database.py:1192–1194`); bắt
  `BatchNegativeStockError`, `QueryDeadlockError` (Frappe gộp cả lỗi 1213 lẫn 1020 "Record has changed since last read" vào đây — `frappe/database/mariadb/database.py:27–29`) và `QueryTimeoutError` (chờ khoá quá 50 s — `frappe/database/database.py:291–295`) thì rollback, dựng lại từ đầu và thử lại vài lần có giãn cách — không chỉ một lần: việc tính lại giá vốn chạy nền, chứng từ lập ở Desk và các câu khoá khoảng của lõi không theo thứ tự khoá của app, còn mặt hàng chưa có dòng `Bin` ở kho ấy (lần nhập đầu) thì câu khoá chỉ lấy được khoá khe — khoá Bin giảm chứ không loại hẳn bế tắc. Cùng luật cho **mọi** method ghi kho của app, cả chiều nhập (phiếu nhập NCC, tờ ghi có có kho, chuyển kho), và phiếu xuất kho lẻ, trả NCC, điều chỉnh
  kiểm kê, Sửa HĐ. Đây là cùng ý với `post_invoice` của nppsale khoá dòng đơn `FOR UPDATE`.
- Muốn bớt nối đuôi do dãy số: cấp số HĐ bằng SEQUENCE của MariaDB (bộ đếm số riêng của CSDL — cấp số không phải chờ ai; không khoá nhưng **lỗ số** khi ghi hỏng) hoặc tách bước cấp số
  ra một giao dịch ngắn riêng — cách này **cũng lỗ số** khi phần ghi HĐ sau đó hỏng, vì số đã cấp và đã commit thì không lấy lại được. SEQUENCE phải đi qua hook `autoname` của app (`frappe.db.get_next_sequence_val`) hoặc `insert(set_name=…)` — đặt tên trong `before_naming` không được vì lõi xoá tên ngay sau hook ấy (`frappe/model/naming.py:153`, `:158–159`); `autoname = autoincrement` cũng không dùng được vì khi ấy tên chứng từ thành số nguyên (`naming.py:161–163`). Khoá hiện dài vì tên được đặt ngay đầu `insert`, trước cả validate (`frappe/model/document.py:719` → `naming.py:412`), nên khoá giữ suốt insert + submit. Còn một cách **không lỗ số** mà khoá ngắn hơn: tên chứng từ là mã tạm, số HĐ thật là một trường riêng, cấp bằng `getseries` ở cuối bước ghi sổ (hook `on_submit` của app). Khi ấy khoá chỉ giữ tới lần commit ngay sau đó, đổi lại tên chứng từ khác số HĐ. Đổi chác "bớt chờ ↔ lỗ số HĐ ↔ tên khác số" này anh quyết ở blueprint 05 (tích hợp lõi); em chưa đo các cách ấy.

### (2) Thuế theo dòng + làm tròn *(đo lại 06/11, đo lại theo đúng luật nppsale 10/11)*

*Hai lần đính chính.* Bản 05/11 so bằng `round()` của Python (làm tròn nửa về số **chẵn**), mỗi HĐ 5 dòng, chỉ đếm lệch ≥ 1 đ — bốn
ca "lệch 1 đ" khi ấy đều do phép so, đã bỏ. Bản 06/11 sửa cách làm tròn nhưng lấy đơn giá sau giảm theo một bản rút gọn
round(giá bảng × (1 − %)), **không phải luật nppsale** (vòng soát lại tìm ra); ngày 10/11 em đo lại toàn bộ theo đúng luật dưới đây.
Số trong mục này là của lượt 10/11.

Luật nppsale đem so — màn bán (`lineGross` / `discountAmount` trong `src/lib/pos/discount.ts`, `posLinesToCart` trong `save.ts`,
`toDraftCoGiam`, `netPriceOf`) và `post_invoice` (sau mig 183), làm tròn nửa **xa 0**:
- tiền dòng trước giảm g = round(SL × giá đang áp trên dòng); tiền giảm = round(g × % giảm) — **% tính trên tiền dòng**; giảm theo **đồng**
  là khoản cho **cả dòng**, kẹp trong [0, g] (`discountAmount`; POS cho chọn đồng làm đơn vị mặc định) — còn `discount_amount` của lõi là
  **mỗi đơn vị**;
- **đơn giá ghi sổ = round((g − tiền giảm) / SL)**, tính **lúc lập đơn**: POS (`posLinesToCart`) quy mọi dòng, `/sell` (`netPriceOf`) chỉ
  quy dòng có giảm. **Xuất hàng không tính lại**: màn hoá đơn nạp đơn giá của dòng đơn (`get_invoiceable_lines` → `seedForNew`) và `toDraft`
  giữ nguyên — kể cả xuất thiếu (SL HĐ khác SL đơn; `line_discount` chia theo tỉ lệ); chỉ dòng gõ giảm mới trên màn hoá đơn (`toDraftCoGiam`:
  g = SL HĐ × đơn giá đơn **đã giảm**) và dòng thêm tay (giá bảng) mới tính ở đó. Vì thế 0,5 lon × 15.343 của đơn lập ở POS lên HĐ là 15.344;
  HĐ giữ 15.343 chỉ khi đơn lập ở `/sell` hoặc dòng thêm tay trên HĐ (bảng dưới gọi là "luật màn hoá đơn"). App bê nguyên mã React nên đơn
  giá vẫn do chính các hàm ấy tính; method `xuat_hang` lấy nguyên `rate` của dòng SO, không tính lại từ % theo SL của HĐ; phép đo chạy cả
  hai luật ở ca SL lẻ;
- tiền dòng = SL × đơn giá, **không** làm tròn từng dòng; VAT = round(Σ tiền dòng × thuế suất);
  tổng = round(Σ tiền dòng − giảm đơn + Σ tiền dòng × thuế suất).

Mỗi lượt 50 HĐ, 10–20 dòng / HĐ chọn trong 40 mặt hàng, Lon / Loc / Thung, SL 1–20, thuế 0 / 5 / 8 / 10 %, ~30 % số dòng giảm 2–15 %;
lượt "SL lẻ" có thêm ~20 % số dòng SL 0,5 / 1,5 / 2,5 / 3,5. So **đúng từng đồng**, không ngưỡng; HĐ lập rồi rollback (`thue_lam_tron`).
Cùng `seed` thì cùng 50 HĐ, nên hàng "app gửi" và "lõi tự tính" dưới đây là cùng một bộ HĐ.

| precision | Đơn giá dòng đưa vào lõi | Giảm đơn | SL | HĐ / dòng (giảm % · SL lẻ) | Lệch đơn giá | Lệch tiền hàng | Lệch VAT | Lệch tổng đã làm tròn (lớn nhất) |
|---|---|---|---|---|---|---|---|---|
| **0** | **app gửi, theo luật nppsale** | — | nguyên | 50 / 738 (220 · 0) | 0 | 0 | 0 | **0** |
| **0** | **app gửi** | 5 % | nguyên | 50 / 720 (232 · 0) | 0 | 0 | 0 | **0** |
| 0 | lõi tự tính từ % | — | nguyên | 50 / 738 (220 · 0) | 15 dòng, đều thấp hơn 1 đ | 11 HĐ | 7 HĐ | 11 HĐ (25 đ) |
| 0 | app gửi — luật POS / luật màn hoá đơn | — | ~20 % lẻ | 50 / 716 (183 · 133) | 0 | 3 / 3 HĐ | 0 / 1 HĐ | 16 / 18 HĐ (2 đ) |
| 0 | app gửi — luật POS / luật màn hoá đơn | 5 % | ~20 % lẻ | 50 / 757 (238 · 147) | 0 | 9 / 10 HĐ | 2 / 2 HĐ | 18 / 20 HĐ (2 đ) |
| 2 | app gửi | — | nguyên | 50 / 738 | 0 | 0 | 50 HĐ — VAT có số lẻ | 0 |
| 2 | app gửi | 5 % | nguyên | 50 / 720 | 0 | 0 | 49 HĐ — VAT có số lẻ | 0 |
| 2 | lõi tự tính từ % | — | nguyên | 50 / 738 | 203 dòng (đơn giá có số lẻ) | 48 HĐ | 50 HĐ | 44 HĐ (23 đ) |
| 2 | app gửi — luật POS | — | ~20 % lẻ | 50 / 716 | 0 | 25 HĐ — tiền hàng lẻ ,5 (lõi giữ ,5 như tiền dòng nppsale, nhưng nppsale ghi tiền hàng đã làm tròn) | 49 HĐ — VAT có số lẻ | 0 |

Tên trường của lõi dùng dưới đây: `rate` = đơn giá dòng, `price_list_rate` = giá bảng, `discount_percentage` / `discount_amount` = % giảm / tiền giảm **mỗi đơn vị** của dòng, `margin_*` = phần bán cao hơn giá bảng; "Standard Selling" / "Standard Buying" = bảng giá bán / mua mặc định lõi tự tạo, không phải bảng giá của app.

- **App phải tự tính đơn giá theo luật nppsale và gửi `rate` cho mọi dòng.** Lõi tự tính từ % theo cách khác: % trên **đơn giá**,
  làm tròn tiền giảm rồi lấy giá trừ đi (`erpnext/controllers/taxes_and_totals.py:228–233`). Ví dụ SP011 thùng 275.668 đ giảm 12,5 %,
  SL 14: nppsale g = 3.859.352 đ, tiền giảm 482.419 đ, đơn giá = round(3.376.933 / 14 = 241.209,5) = **241.210**; lõi làm tròn tiền giảm
  mỗi thùng 34.458,5 → 34.459, đơn giá **241.209**. Lệch hay không còn tuỳ SL (cùng dòng ấy SL 1 hoặc 3 thì hai bên trùng nhau).
- **Lõi giữ đơn giá app gửi nhưng xoá `discount_percentage` về 0** ở dòng nào đơn giá app gửi khác cách lõi tự tính (15 / 220 dòng
  có giảm ở seed 1, 20 / 232 ở seed 2, 27 / 183 ở lượt SL lẻ — precision 0) và ghi `discount_amount` = giá bảng − đơn giá
  (`taxes_and_totals.py:254–256`) → % giảm để in và báo cáo app giữ ở trường riêng. Dòng đơn giá **cao hơn** giá bảng (NV bán trên bảng
  giá — chênh dương) đi nhánh khác: đo thật (`dong_dac_biet`) SP001 giá bảng 10.137 đ, gửi 11.137 → lõi giữ 11.137, ghi
  `margin_type = Amount`, margin 1.000, `discount_amount` 0 (`taxes_and_totals.py:245–252`). Vì vậy không báo cáo nào được lấy
  `discount_amount` / `margin_*` của lõi làm số giảm hay số chênh; chênh lệch giá của nhân viên vẫn so đơn giá trên HĐ với giá bảng hiện
  hành của đúng đơn vị dòng, như đã chốt ở bản bàn bạc.
- **Dòng 0 đ (hàng đổi xuất đi) — đo 10/11** (`dong_dac_biet`, SP001 giá bảng 10.137 đ, SL 2):

  | Gửi cho lõi | Lõi để lại | Thành tiền |
  |---|---|---|
  | `rate` 0 + `price_list_rate` 10.137 | `rate` = **10.137** (lõi coi là chưa có đơn giá) | **20.274 đ** ✘ |
  | `rate` 0, không gửi `price_list_rate` | lõi tự lấy giá từ bảng "Standard Selling": **10.054** | **20.108 đ** ✘ |
  | `rate` 0 + `price_list_rate` 10.137 + `discount_percentage` 100 | `rate` 0 | 0 ✔ |
  | `rate` 0 + `price_list_rate` 10.137 + `discount_amount` 10.137 | `rate` 0 | 0 ✔ |
  | `rate` 0 + `price_list_rate` 0 gửi rõ | `rate` 0 | 0 ✔ |

  Hai cách đầu biến dòng hàng đổi thành dòng bán có tiền mà không báo gì — sai doanh thu, VAT và công nợ. Luật: dòng 0 đ gửi giá bảng kèm
  khoản giảm bằng giá bảng (`discount_amount` = giá bảng — hàng thứ tư của bảng, ca `a5` ở C1c; cùng kiểu gửi giảm tuyệt đối "không gửi %" của dòng ánh xạ "Dòng HĐ" trong bản bàn bạc; giảm 100 % — hàng thứ ba, ca `a2` — cũng ra 0 nhưng là gửi %), vẫn giữ được giá bảng để in "trị giá hàng đổi".
- **Lõi tự ghi giá vào bảng giá.** `Stock Settings.auto_insert_price_list_rate_if_missing` đang **bật** — mặc định của DocType là tắt
  (`erpnext/stock/doctype/stock_settings/stock_settings.json:158–160`); `setup_complete` mà `setup.py` gọi chạy `install_defaults` →
  `update_stock_settings`, bật nó cùng `update_price_list_based_on = Rate` (`erpnext/setup/setup_wizard/operations/install_fixtures.py:511`, `:536–546`).
  Mỗi lần lưu, lõi tra giá cho **mọi** dòng (`accounts_controller.py:1305`); bảng giá của chứng từ chưa có giá mặt hàng ấy thì lõi ghi **đơn
  giá của dòng ÷ hệ số** vào chính bảng ấy (`get_item_details.py:1204–1207`, `:1249–1342`) — **kể cả khi dòng đã gửi `price_list_rate`**:
  `SAL-ORD-2026-00001` gửi SP023 Lốc 78.406 kèm giá bảng 78.406 → lõi ghi SP023 Lon 13.067,67 (= 78.406 / 6) vào "Standard Selling". Sổ PoC
  có 40 giá như thế ở "Standard Selling", 30 ở "Standard Buying"; ca thứ hai ở bảng trên lấy SP001 Lon **10.054 = giá Lốc 60.322 / 6**, không
  phải giá bảng Lon 10.137. Chứng từ PoC đều mang "Standard Selling" (104 HĐ, 85 đơn) dù nhóm khách Thuong / VIP có bảng giá mặc định
  "Gia chuan" / "Gia nhom VIP": Selling Settings ghi `selling_price_list` thành mặc định chung (`selling_settings.py:85–93`), `new_doc` điền
  sẵn (`frappe/model/create_new.py:88`), còn thông tin khách chỉ lấp chỗ trống (`selling_controller.py:184`). Luật: tắt cài đặt này (3.11) —
  đặt bảng giá và gửi `price_list_rate` **không** ngăn được lõi ghi (vẫn bật mà method đặt bảng giá nhóm chưa có mặt hàng thì đơn giá sau giảm
  vào thẳng bảng giá nhóm); method luôn tự đặt `selling_price_list` / `buying_price_list` đúng bảng giá của app, không trông vào bảng giá mặc
  định của nhóm khách, và gửi `price_list_rate` cho mọi dòng; Selling / Buying Settings đổi bảng giá mặc định sang bảng của app.
- **SL lẻ (1,5 thùng)**: ở precision 0 lõi làm tròn **tiền từng dòng** về đồng (`taxes_and_totals.py:280`) và tổng luôn = tiền hàng + VAT;
  `post_invoice` giữ phần ,5 trong tiền dòng (1,5 × 241.209 = 361.813,5), làm tròn riêng tiền hàng và VAT, còn tổng làm tròn **một lần** trên
  số chưa làm tròn — nên HĐ SL lẻ của nppsale có thể có tiền hàng + VAT ≠ tổng (`…00105` ở C1b: 8.037.711 + 326.206 = 8.363.917, tổng
  nppsale 8.363.916; lõi 8.363.917). Đo (C1b, C1d): **16–20 / 50 HĐ có dòng SL lẻ lệch tổng 1–2 đ** tuỳ luật đơn giá; chỉ 3–10 HĐ lệch tiền
  hàng, còn **8–14 HĐ mỗi lượt lệch tổng dù tiền hàng và VAT đều khớp** (13 / 14 / 8 / 9) — phần này do cách `post_invoice` làm tròn tổng,
  không cài đặt nào của lõi bỏ được. Precision 2 thì tổng khớp nhưng tiền hàng (25 / 50 HĐ lẻ ,5), VAT và tổng chưa làm tròn có số lẻ. Quy
  dòng SL lẻ về đơn vị cơ sở **không** giúp — đo trong lõi (`sl_le_ve_lon`): 1,5 thùng → 36 lon thì đơn giá lon 241.209 / 24 = 10.050,375 bị
  lõi làm tròn về 10.050 (36 × 10.050 = 361.800, lệch 13,5 đ một dòng) → **45 và 43 / 50 HĐ lệch tổng, tới 40 và 56 đ**; dòng lon còn so với
  giá bảng lon nên chênh lệch giá NV đổi, dòng 0,5 lon thì không quy được. Em đề xuất giữ precision 0 và **chấp nhận tiền từng dòng làm tròn
  về đồng** — đúng như bộ đẩy MISA của nppsale đang làm (`src/lib/misa/mapper.ts:108–110`). **Anh chọn** (mục 10 bản bàn bạc, câu 19).
- **VAT trên HĐĐT — lệch có sẵn từ hôm nay** *(đo 10/11, C1d)*: bộ đẩy MISA của nppsale làm tròn tiền **và VAT từng dòng** rồi cộng
  (`mapper.ts:108–110`; nơi gọi đã cộng ngược khoản giảm vào đơn giá nên không trừ giảm hai lần), còn `post_invoice` làm tròn VAT một lần ở
  tổng. Phép đo tính thêm "VAT kiểu HĐĐT" cho chính các HĐ ấy và bật thử `round_row_wise_tax` (cài đặt làm tròn VAT từng dòng của lõi):

  | `round_row_wise_tax` | HĐ thử | Lõi từ chối | VAT lõi ≠ VAT sổ nppsale | VAT lõi ≠ VAT kiểu HĐĐT | VAT sổ nppsale ≠ VAT kiểu HĐĐT |
  |---|---|---|---|---|---|
  | 0 (mặc định) | 50 HĐ 10–20 dòng | 0 | 0 | 31 | 31 |
  | 0 | 50 HĐ 3–6 dòng | 0 | 0 | 13 | 13 |
  | 0 | 50 HĐ có SL lẻ | 0 | 1 | 27 | 28 |
  | **1** | 50 HĐ 10–20 dòng | **6** | 25 / 44 lập được | 0 / 44 | 25 / 44 |
  | 1 | 50 HĐ 3–6 dòng | 0 | 13 | 0 | 13 |
  | 1 | 50 HĐ có SL lẻ | **3** | 25 / 47 | 0 / 47 | 25 / 47 |

  Nghĩa là: (1) **hôm nay** VAT trên HĐĐT của nppsale đã khác VAT trong sổ ở 13–31 / 50 HĐ thử, tới 2 đ — lệch có sẵn, không do chuyển
  đổi; (2) bật `round_row_wise_tax` thì VAT của lõi khớp HĐĐT ở mọi HĐ lập được, nhưng **lõi từ chối 6 / 50 HĐ 10–20 dòng** ("Item Wise Tax
  Details do not match with Taxes and Charges": lõi chỉ cho tổng VAT chi tiết từng dòng lệch dòng thuế tối đa 1 đ ở tiền không có số lẻ,
  `taxes_and_totals.py:650–700`, kèm ghi chú `TODO: fix rounding difference issues`) → **không dùng được** nếu không vá lõi; (3) muốn HĐĐT
  khớp sổ thì module HĐĐT của app phải chia VAT của HĐ xuống các dòng sao cho cộng lại đúng VAT sổ (vài dòng lệch 1–2 đ so với làm tròn từng
  dòng) — chưa đo, cần kế toán xác nhận MISA nhận cách ấy. Anh chọn ở câu 19.
- **precision 2**: VAT ghi số lẻ (821.591,24 thay vì 821.591), tổng chưa làm tròn cũng lẻ — không khớp nppsale và MISA (VAT nguyên đồng).
- **Chốt**: `currency_precision = 0` + Commercial Rounding + `round_row_wise_tax = 0` (mặc định — làm tròn VAT một lần ở tổng như
  `post_invoice`; bật 1 thì lõi từ chối HĐ nhiều dòng; HĐĐT có khớp sổ hay không anh chọn ở câu 19) + app gửi đơn giá theo luật nppsale (HĐ lập từ đơn giữ nguyên đơn giá dòng SO) và giá bảng cho mọi dòng + % giảm ở trường riêng + dòng 0 đ gửi giá bảng kèm khoản giảm bằng giá bảng (`discount_amount`, không gửi %) + tắt
  `auto_insert_price_list_rate_if_missing`. `Item.taxes` để trống thì lõi tôn trọng template thuế của từng dòng (VAT khớp từng đồng ở mọi
  HĐ SL nguyên trộn bốn mức thuế).

### (3) Giảm đầu phiếu nhập NCC — CFD-11

Phiếu nhập 3 dòng × 10 lon (SP001 20.000 đ / lon, SP002 21.000, SP003 22.000), VAT mua 8 %, giảm đầu phiếu 50.000 đ.

| Cách | Tiền hàng dòng SP001 / SP002 / SP003 | Σ thuế (gồm dòng trừ) | Tổng phải trả | Giá vốn lô SP001 / SP002 / SP003 |
|---|---|---|---|---|
| **Dòng thuế `Actual` + `Deduct` 50.000** (`ACC-PINV-2026-00006`) | 200.000 / 210.000 / 220.000 (giữ) | 400 (= 50.400 − 50.000) | 630.400 | 20.000 / 21.000 / 22.000 (giữ) |
| `apply_discount_on = Grand Total` của lõi (`ACC-PINV-2026-00007`) | 185.303 / 194.568 / 203.833 | 46.696 | 630.400 | 18.530 / 19.457 / 20.383 |

Tổng phải trả như nhau; cách dòng trừ giữ tiền hàng, VAT và giá vốn lô đúng luật mig 145 của nppsale. **Chốt cách dòng trừ.** Hệ quả cho báo cáo: dòng trừ nằm trong bảng thuế nên `total_taxes_and_charges` của `00006` chỉ còn **400** (50.400 − 50.000) — VAT đầu vào (tờ khai, đối chiếu với HĐ của NCC) phải cộng theo tài khoản `Thue GTGT dau vao` (dòng thuế / sổ cái — mỗi dòng thuế một bút toán, `purchase_invoice.py:1588–1610`), không đọc tổng thuế của phiếu.
Sổ cái của `00006`: Nợ Kho 630.000, Nợ Thuế GTGT đầu vào 50.400 / Có NCC 630.400, **Có tài khoản của dòng trừ 50.000** — khoản giảm
vào thẳng lãi lỗ, không hạ giá trị kho. PoC tạm dùng tài khoản "Miscellaneous Expenses"; tài khoản thật (ví dụ thu nhập khác 711
hay ghi giảm giá vốn 632) anh chốt cùng hệ thống tài khoản TT200.
(`ACC-PINV-2026-00004` / `00005` là lượt đầu khi template thuế chưa có tài khoản đầu vào — VAT sai, xem mục 3. Hai lượt dùng chung tên
lô `SP00x-GD-…` nên tra Batch sẽ thấy giá pha trộn; đọc theo từng phiếu.)

### (4) Landed Cost Voucher âm trên lô đã bán — CFD-06

LCV `MAT-LCV-2026-00001` −30.000 đ phân bổ theo tiền cho 30 dòng của `ACC-PINV-2026-00001` (−836 tới −1.164 đ / dòng): lõi **nhận**,
phiếu nhập giữ nguyên số. Lõi sinh **30** việc Repost Item Valuation (tính lại giá vốn) — mỗi mặt hàng của phiếu một việc; `repost_entries()`
chạy hết **16,8 s**, ~0,56 s / việc (mỗi việc quét lại sổ từ ngày phiếu nhập 06/10 — vì sao dài gấp đôi việc huỷ HĐ thì chưa đo, xem (6)) *(đính chính 06/11 — bản 05/11 ghi 5 việc vì hàm
đo chỉ liệt kê `limit=5`)*.

Sổ lô SP001-L1: dòng phiếu nhập 8.109 đ, LCV phân −836 đ / 240 lon → giá nhập **8.105,52 đ**; các HĐ đã xuất lô ấy (`00003` −18 lon,
`00007` −72, `00009` −12, `00013` −1, …) được tính lại theo đúng 8.105,52 (`Serial and Batch Entry.incoming_rate`). LCV âm làm giá vốn
phần đã bán **giảm** đúng như mong đợi. *(Đính chính 06/11: con số 8.118,15 bản 05/11 gọi là "giá vốn HĐ" là cột `valuation_rate` của
sổ kho = giá trị tồn ÷ số tồn **của cả mặt hàng tại kho**, gộp cả L1 / L2 / L3 (5.698.945 ÷ 702 lon ngay sau `00003`) — không phải giá vốn lô; sổ PoC định giá FIFO theo lô (`valuation_method` = FIFO, lô `use_batchwise_valuation` = 1), không phải bình quân di động.)* Báo cáo giá vốn / lãi gộp theo lô
phải đọc qua gói lô, không đọc cột ấy. Chỉ chạy LCV âm; LCV dương cùng đường mã, đo bổ sung ở P2. **Sổ cái**: LCV chỉ sửa giá trị kho, **không đụng công nợ NCC** — sau LCV, bút toán của `ACC-PINV-2026-00001` là Có NCC 69.828.480 (giữ nguyên), Nợ Kho 69.798.480 (−30.000) và **Nợ 30.000 vào tài khoản của LCV** (PoC dùng Miscellaneous Expenses, tức chi phí *tăng* 30.000). Vì vậy method sửa giá phải lập kèm debit note / bút toán Nợ NCC / Có đúng tài khoản ấy (CFD-06 đã ghi), và tài khoản của LCV nên là tài khoản trung gian chứ không phải tài khoản chi phí; thiếu bút toán kèm thì nợ NCC vẫn theo giá cũ và lãi lỗ lệch đúng khoản giảm.

### (5) Tờ ghi có độc lập có kho — giá vốn hàng nhập lại (luật mig 127) — CFD-03

Tờ ghi có `is_return = 1`, **không** `return_against`, `update_stock = 1`, 5 lon lô `SP001-L1` (giá vốn lô 8.105,52 đ, giá bán dòng
trả app gửi 11.150,7 đ = 10.137 × 1,1 — dòng HĐ làm tròn thành 11.151 đ ở precision 0 nên nợ mỗi tờ = 5 × 11.151 = 55.755 đ, còn chỗ lõi rơi về giá bán thì chép nguyên số 11.150,7 chưa làm tròn). Sổ có **bốn** tờ, theo thứ tự lập:

| Tờ | Kho nhận | `incoming_rate` app gửi | Sổ ghi giá vốn |
|---|---|---|---|
| `ACC-SINV-2026-00024` | Kho cận date (lô chưa từng có ở đó) | 0 — app tra giá vốn qua `SLE.batch_no` (luôn trống với dòng có gói lô) nên ra 0 | **11.150,7 = giá bán** ✘ |
| `ACC-SINV-2026-00025` | Kho cận date | 8.105,52 | **8.105,52** ✔ |
| `ACC-SINV-2026-00027` | Kho cận date (lô đang còn 10 lon ở đó) | không gửi | 9.628,11 = bình quân lô **tại kho nhận** = (5 × 11.150,7 của `00024` + 5 × 8.105,52 của `00025`) / 10 ✘ |
| `ACC-SINV-2026-00029` | Kho bán (lô đã bán hết ở đó) | không gửi | **11.150,7 = giá bán** ✘ |

Nợ của **mỗi** tờ: −55.755 đ (5 lon × 11.151 đ; bốn tờ cộng −223.020 đ, dư có) — đúng luật công nợ âm. Ca `00029` còn để lại hệ quả về sau: hai HĐ bán tiếp lô ấy (`00030`
−3 lon, `00033` −2 lon) bị tính giá vốn **11.150,7** — giá vốn sai **lan sang lãi gộp của HĐ sau**, không chỉ nằm ở tờ trả. Kết
luận: app **luôn** gửi `incoming_rate` cho từng dòng nhập lại theo đúng chuỗi của nppsale (mig 127, giữ ở mig 158): có HĐ gốc → giá vốn lô đã xuất trên HĐ ấy; phiếu không gắn HĐ → theo đơn, rồi giá lô mới nhất cùng mặt hàng (PoC mới thử đặt bằng giá nhập của lô — `gia_von_lo`); nhánh cuối của nppsale là 0, mà gửi 0 cho lõi là rơi về giá bán — app phải chặn hoặc chọn giá khác, anh quyết. Nhánh đầu đọc từ `Serial and Batch Entry.incoming_rate`
của gói lô trên HĐ gốc.

### (6) Huỷ HĐ có chứng từ sau — nhịp tính lại giá vốn — CFD-07

Huỷ `ACC-SINV-2026-00001` (15 dòng, HĐ đầu tiên nên mọi HĐ sau đều là chứng từ sau — nhưng có chứng từ sau hay không cũng vậy: huỷ chứng từ đã có sổ kho là lõi **luôn** xếp việc tính lại, `erpnext/controllers/stock_controller.py:2115–2123` đặt `force = True` khi `docstatus = 2`; ở điểm 11, huỷ `…00101` — tờ mới nhất của 8 mặt hàng ấy, không có chứng từ nào sau — và huỷ `…00101-1` mỗi lần cũng sinh 8 việc, 16 việc này vẫn Queued trong sổ): `cancel()` **1.248 ms**; lõi sinh **15** việc tính
lại `based_on = Item and Warehouse` — một việc mỗi mặt hàng + kho của HĐ, `voucher_no` trống (lọc theo số HĐ sẽ không thấy; bản 05/11
lọc như thế nên in danh sách rỗng — số 15 đếm theo giờ tạo trong sổ). Gọi `repost_entries()` ngay: **4,2 s**, 15/15 Completed. So với LCV
(30 việc, 16,8 s): gấp đôi số việc, và mỗi việc dài gấp đôi (~0,56 s so với ~0,28 s). Vì sao dài gấp đôi thì em chưa đo tách: việc của LCV tính lại từ ngày phiếu nhập 06/10, việc huỷ HĐ tính từ giờ HĐ, nhưng số dòng sổ kho mỗi việc phải đi qua chỉ hơn ~1,4 lần (TB 14,2 dòng / việc LCV so với 10,4 dòng / việc huỷ HĐ), chưa đủ giải thích gấp đôi.

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
  multiple times. Please enable Allow Item to Be Added Multiple Times in a Transaction"*. Bài này chỉ dùng mặt hàng **theo lô** (`hai_dong_cung_lo` lấy `_items(True)[1]`) nên chưa lộ một hệ quả: tờ ghi sổ kho có hai dòng cùng mặt hàng + kho mà **bất kỳ** dòng xuất nào của tờ định giá theo hàng đợi FIFO (hàng không lô — sổ PoC: SP031 `stock_queue` = `[[1136.0, 11397.0]]`, hàng theo lô là `[]`) thì lõi xếp việc tính lại giá vốn cho **mọi** mặt hàng + kho của tờ ngay lúc ghi sổ (`repost_required_for_queue`, `erpnext/controllers/stock_controller.py:2520–2546`, gọi ở `:2123`; `create_item_wise_repost_entries`, `:2769–2799`). HĐ "1 thùng + 3 lon" kèm một dòng hàng không lô sẽ sinh một việc mỗi mặt hàng ở mỗi lần Xuất hàng (theo mã, chưa đo); phải đo và chọn cách xử lý trước khi chốt `allow_multiple_items`.
- Đổi tên lô *(đính chính 06/11)*: đường thường (`rename_doc` không ép) bị chặn — **"Batch not allowed to be renamed"** vì DocType Batch
  không khai `allow_rename`. Nhưng lõi chỉ chặn khi **không** `force` / `ignore_permissions` (`frappe/model/rename_doc.py:385`): method
  của app gọi `rename_doc("Batch", cũ, mới, force=True)` thì đổi được — lô `SP003-L3` có 27 dòng gói lô + 1 dòng phiếu nhập đổi theo
  trong 0,43 s; dò **10.371 cột chữ** của mọi bảng không còn chỗ nào giữ mã cũ (thử trong giao dịch rồi rollback — chưa lần đổi nào được commit, nên phần lõi chạy sau commit — việc nền dựng lại chỉ mục tìm kiếm, báo đổi tên cho màn đang mở, `rename_doc.py:211–230` — chưa quan sát; câu dò bỏ qua mọi giá trị có chứa mã mới, mà `SP003-L3-DOI` chứa nguyên mã cũ, nên giá trị giữ cả hai sẽ lọt; và chỉ dò trên sổ PoC). Bản 05/11 kết luận
  "mã lô bất biến" là sai. Hướng mới: giữ tính năng sửa mã lô của nppsale qua method có kiểm vai, ép `force` (lõi tự xoá cache khi đổi — xem dưới).
  Rủi ro còn lại: lõi cố ý không cho đổi tên lô ở Desk, nên đây là đường đi vòng — giữ bài thử này làm bài hồi quy khi nâng bản lõi. Hai giới hạn nữa: (1) `rename_doc` chỉ sửa cột **Link** trỏ tới Batch và trường đặt tên `batch_id` (`frappe/model/rename_doc.py:174–176`, `:326–331`, `:475`); `Stock Ledger Entry.batch_no` là cột **Data** nên giữ mã cũ — mà lõi có ghi mã lô vào cột này ở một số dòng sổ kho đảo (sổ PoC có 43 dòng, đều `is_cancelled = 1`: dòng đảo khi LCV đăng lại `ACC-PINV-2026-00001` và khi huỷ `ACC-SINV-2026-00001`, ví dụ `SP001-L1`; dòng huỷ của Sửa HĐ `ACC-SINV-2026-00101` thì không có); lô `SP003-L3` được thử không có dòng nào như thế nên phép dò không thấy — số dư không lệch (dòng đã huỷ không tính) nhưng tra sổ kho theo mã lô sẽ còn mã cũ; (2) mỗi lần đổi, `rename_doc` gọi `frappe.clear_cache()` (`rename_doc.py:211–212`) — xoá **mọi** khoá Redis của site trừ vài khoá giữ lại, kể cả bộ nhớ phiên (`frappe/cache_manager.py:311–317`), nên lượt bấm kế tiếp của mọi người phải đọc lại từ sổ — và xếp việc dựng lại tìm kiếm toàn cục cho Batch (`erpnext/hooks.py:729`): app không cần tự xoá cache, có thể truyền `rebuild_search=False` (portal không dùng tìm kiếm toàn cục) và chỉ đổi lúc vắng. `force=True` chỉ bỏ chặn `allow_rename`, vẫn kiểm quyền ghi Batch (`rename_doc.py:377`).

### (9) Nhập lại lô đã hết hạn

Lô `SP001-HETHAN` hết hạn 26/10 (10 ngày trước ngày đo):

| Cách | Kết quả |
|---|---|
| Material Receipt, dòng ghi `batch_no` | `BatchExpiredError: The batch SP001-HETHAN has already expired` |
| Material Receipt, dòng gắn **gói lô nhập do app lập** (không `batch_no` ở dòng) | **nhận** (`MAT-STE-2026-00002`, +5 @ 10.000) |
| Tờ ghi có có kho (`is_return`, `update_stock`) với lô hết hạn | **nhận** (`ACC-SINV-2026-00026`, +2 @ 9.000) |

Lõi chỉ kiểm hạn khi dòng mang `batch_no` **và có số lượng dương** (`erpnext/controllers/stock_controller.py:387`: `flt(d.qty) > 0.0 and d.get("batch_no")` — vì thế tờ ghi có `00026` **có** ghi `batch_no` = `SP001-HETHAN` ở dòng mà vẫn được nhận, do SL −2: nó qua nhờ SL âm chứ không nhờ gói lô) và với gói lô **xuất** của chứng từ không phải trả hàng
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
gói lô cũ** — không phải vì `no_copy` (`frappe.copy_doc` mặc định chép cả trường `no_copy`) mà vì huỷ HĐ đã xoá `serial_and_batch_bundle` **và** `batch_no` trên mọi dòng của tờ cũ (`erpnext/controllers/stock_controller.py:1216–1237`). Lõi tự lập gói lô mới lúc ghi sổ chỉ vì cờ `auto_create_serial_and_batch_bundle_for_outward` = 1 (mặc định, `setup.py` cũng bật), theo FIFO của lõi, tức thứ tự **ngày tạo bản ghi lô** (`Batch.creation`). Ở đây lõi ra SP001-L3, SP002-L3, SP003-L3, SP004-L4, SP005-L3, SP006-L3 — **trùng đúng** các lô app đã gán cho `…00101` (mỗi dòng −2), vì app PoC chọn lô bằng `get_batch_qty`, mà hàm này xếp lô theo cùng cài đặt ấy; bài này chưa cho thấy ca lõi chọn khác app. Tờ amend còn **giữ giờ ghi sổ của tờ cũ** (`sales_invoice.py:1279–1280`: `-2` lập lúc 19:47:26 mà mang giờ 19:44:48). Lõi sẽ chọn khác khi luật app khác FIFO của lõi — nppsale xếp theo ngày nhập `received_at` (`post_stock_export`, mig 138), và Sửa HĐ của nppsale là `cancel_invoice` hoàn đúng lô rồi `post_invoice` chạy lại FIFO ấy — hoặc khi tờ khác lấy mất lô trong lúc sửa (chưa đo). Nên dù lô trùng, gói lô của tờ mới vẫn do lõi tự chọn (trùng là nhờ cùng thứ tự, không phải lõi giữ lô app từng gán). Vì vậy method Sửa HĐ phải tự gán lô lại theo luật app trước khi ghi sổ tờ mới. Mỗi lần huỷ còn sinh **8 việc tính lại giá vốn** (mỗi mặt hàng + kho của tờ một việc) dù `…00101` là chứng từ cuối của tám mặt hàng ấy — lõi ép tính lại ở mọi lần huỷ chứng từ có sổ kho (`erpnext/controllers/stock_controller.py:2115–2123`). Hai lần sửa để lại 16 việc, vẫn Queued trong sổ PoC (bài không gọi chạy, site tắt lịch chạy nền), nên 2,6 s / 1,1 s ở trên **chưa gồm** phần tính lại. Lần sửa thứ hai vẫn huỷ được tờ `-1` ngay khi 8 việc của lần trước còn chờ — lõi không chặn.

## 3. Phát hiện ngoài kế hoạch

1. **Đồng thời là việc của app** (1b, 1d): lõi đọc có khoá số dư lô ngay lúc lập gói lô, nhưng lúc ấy chưa trừ số của chính phiếu nên chưa chặn được lô âm. Kiểm âm thật chỉ diễn ra lúc ghi sổ (`serial_and_batch_bundle.py:770–775`: số của phiếu chỉ được trừ khi `docstatus == 1`), vì thế cả 8 lỗi lô âm của 1b đều nổ ở bước submit (có `si_insert`, không có `si_submit`); bước chọn lô của app
   đọc theo ảnh chụp cũ. Không khoá `Bin` trước thì hàng trùng sẽ lô âm hoặc bế tắc (MariaDB 1213).
2. **Số HĐ khoá suốt giao dịch** (1d): `getseries` giữ khoá hàng `tabSeries` của dãy tới khi commit, nên mọi lượt Xuất hàng xếp hàng một,
   kể cả hàng khác nhau. Đo lại với gunicorn nhiều worker trên VPS; cách cấp số chọn ở blueprint 05.
3. **Tách dòng làm lẻ số lon** (1c): 0,833 thùng = 19,992 lon. Luôn dùng gói lô một dòng.
4. **Giảm % dòng: lõi tính % trên đơn giá, nppsale tính trên tiền dòng rồi chia lại SL** (2) → app tự tính đơn giá theo luật nppsale (`posLinesToCart` / `toDraftCoGiam` / `netPriceOf`) và gửi `rate` + giá bảng cho mọi dòng; lõi xoá `discount_percentage` ở dòng lệch → app giữ % ở trường riêng. HĐ lập từ đơn giữ nguyên đơn giá dòng SO (nppsale không tính lại lúc Xuất hàng, kể cả xuất thiếu). SL lẻ: lõi làm tròn tiền từng dòng, `post_invoice` thì không và làm tròn tổng một lần — lệch tổng 1–2 đ ở 16–20 / 50 HĐ của lượt SL lẻ (các HĐ còn lại khớp), phần lớn do cách làm tròn tổng của nppsale; VAT HĐĐT nppsale làm tròn từng dòng (anh chọn, câu 19).
5. **Item Tax Template phải có cả tài khoản thuế đầu vào**: template chỉ có "Thuế GTGT đầu ra" thì phiếu nhập NCC tính VAT sai mà không báo
   gì (lượt đầu của điểm 3; cả ba phiếu nhập tồn đầu `ACC-PINV-2026-00001…00003` — 90 dòng mang template VAT 8 % — cũng ghi VAT = 0, nên đọc sổ PoC sẽ thấy tồn đầu không có thuế đầu vào; phiếu nhập lô L4 `00008` lập sau khi vá thì đúng 8 %). `setup.py` đã sửa ngày 06/11 để tạo đủ hai tài khoản. Vào 3.11.
6. **Sổ kho của dòng có gói lô không ghi `batch_no`** (null — trừ một số dòng đảo đã huỷ `is_cancelled = 1`: sổ PoC có 43 dòng mang mã lô, và `rename_doc` không sửa cột Data này) — mọi câu "giá vốn theo lô", "tồn theo lô" phải nối qua `Serial and Batch
   Bundle` / `Serial and Batch Entry` (hoặc dùng `get_batch_qty`), không lọc `SLE.batch_no`. Cột `valuation_rate` của sổ kho là bình quân
   mặt hàng tại kho, không phải giá vốn lô (điểm 4).
7. **Giá vốn hàng trả sai thì lan sang HĐ sau** (điểm 5) — lý do app phải tự điền `incoming_rate` cho mọi dòng nhập lại.
8. **Tính lại giá vốn theo mặt hàng + kho, không theo chứng từ** (6): màn "đang tính lại giá vốn (N)" đếm theo trạng thái việc, không theo
   số HĐ.
9. **Tờ amend không mang gói lô cũ** (11): huỷ đã xoá gói lô trên dòng tờ cũ, lõi tự lập gói lô mới theo FIFO của nó (`Batch.creation`) vì cờ tự lập gói lô xuất đang bật. Ở bài đo lô ra trùng đúng lô tờ gốc vì app PoC cũng chọn bằng `get_batch_qty` cùng thứ tự; ca lô bị đổi chưa đo. Sửa HĐ muốn giữ đúng luật lô của nppsale (ngày nhập) thì app phải tự gán lô lại.
10. **Không có hệ thống tài khoản Việt Nam trong v16** (không có `vn_*` trong `chart_of_accounts/verified` lẫn `unverified`) → app ship mẫu
    TT200 và truyền `chart_of_accounts` khi tạo công ty (anh đã đồng ý câu 9). PoC tạm dùng "Standard".
11. Nhỏ: `session_expiry` nhận dạng `hh:mm` (`720:00` = 30 ngày); `Item Barcode.barcode_type` đặt EAN là lõi kiểm số kiểm tra — mã nội bộ
    để trống loại mã; `bench execute --kwargs` nhận literal Python (`True` / `False`), không nhận JSON `true` / `false`; khi cài app từ repo
    gọi `bench get-app https://github.com/mrhuychien/npp`: bench 5.31 bỏ qua tham số tên đặt trước URL ("Dummy argument for backward compatibility") và tự đổi thư mục theo `name = "nppsale"` trong `pyproject.toml`; PoC chép thẳng app vào `apps/nppsale`, chưa chạy `get-app` từ GitHub — kiểm ở P2.

12. **Dòng 0 đ bị lõi định giá lại** (2): gửi đơn giá 0 kèm giá bảng thì lõi tự đặt đơn giá = giá bảng gửi kèm (10.137); thiếu giá bảng thì lõi tự lấy giá trong bảng giá của chứng từ — ở PoC là "Standard Selling" do chính lõi tự sinh (10.054 = giá Lốc ÷ 6, không phải giá bảng 10.137 của app — điều 13) — dòng hàng đổi thành dòng bán có tiền, không báo gì. Dòng 0 đ gửi giá bảng kèm khoản giảm bằng giá bảng (`discount_amount` = giá bảng, không gửi %; giảm 100 % cũng ra 0).
13. **Lõi tự ghi giá vào bảng giá** (2): `auto_insert_price_list_rate_if_missing` do trình cài đặt bật — bảng giá của chứng từ chưa có giá mặt hàng thì lõi ghi đơn giá dòng ÷ hệ số vào bảng ấy, **kể cả khi dòng đã gửi giá bảng** (sổ PoC: 40 + 30 giá ở "Standard Selling" / "Standard Buying"), rồi dùng lại khi dòng thiếu giá; chứng từ do method lập mang bảng giá mặc định của Selling Settings, không theo bảng giá mặc định của nhóm khách. Tắt ở 3.11; method luôn tự đặt bảng giá của app.

## 4. Những gì chưa đo (dời P2)

Đo được ngay trên bench thử này nhưng em chưa đo: LCV **dương** (điểm 4 chỉ chạy LCV âm); thời gian Xuất hàng HĐ 20 dòng (điểm 1 mới đo 15 dòng); hai cách cấp số HĐ bớt nối đuôi và cách số HĐ là trường riêng (1d); SL lẻ ngoài nửa đơn vị (0,25 / 0,3 thùng… — ô số lượng POS cho gõ số lẻ bất kỳ, bài 10/11 chỉ thử 0,5 / 1,5 / 2,5 / 3,5); chia VAT của HĐ xuống dòng cho HĐĐT khớp sổ (câu 19); giảm theo **đồng** (khoản cho cả dòng — `discountAmount` đơn vị "vnd") và giảm gõ thêm trên màn hoá đơn (`toDraftCoGiam`, tính trên đơn giá đơn đã giảm) — điểm 2 mới đo giảm %; HĐ lập từ đơn **xuất thiếu** (`xuat_hang` phải giữ đơn giá dòng SO, không tính lại theo SL HĐ); thuế + làm tròn của tờ ghi có so với `credit_note_amount` của nppsale (phiếu trả làm tròn từng dòng gồm cả VAT — `round(SL × giá × (1 + thuế))`, mig 152 / 183 — và đơn giá 2 số lẻ khi đổi quy cách, mig 181; điểm 2 mới đo HĐ bán); thuế và dòng 0 đ trên đúng đường `xuat_hang` (`update_stock = 1`, có gói lô — `thue_lam_tron` và `dong_dac_biet` đo với `update_stock = 0`); tính lại giá vốn **song song** (điểm 6 khuyên bật, nhưng sổ PoC vẫn để `enable_parallel_reposting = 0` — 15 việc chạy lần lượt); tắt `auto_create_serial_and_batch_bundle_for_outward` rồi chạy lại Sửa HĐ (điểm 11); HĐ hai dòng cùng mặt hàng kèm dòng hàng không lô (điểm 8).

Chỉ đo được trên VPS (GCloud):

- Header thật qua nginx của bench / Cloudflare: `X-Frame-Options` cho khung in, cache HTML của vỏ SPA, `sw.js`, nén. Thêm: mẫu nginx của bench có `rewrite ^(.+)/$ $1 permanent;` trong `location /`, nên `/nppsale/` bị chuyển 301 sang `/nppsale` — trang ấy nằm **ngoài** phạm vi service worker `/nppsale/` (phạm vi so khớp tiền tố chuỗi) mà manifest (`start_url`, `scope`) và `index.html` đang khai; PoC chạy `bench serve` không qua nginx nên chưa thấy — chọn lại `start_url` / `scope` (hoặc bỏ rewrite ấy ở nginx của VPS) và kiểm ở P2.
- socket.io (cổng 9000) qua proxy; gunicorn nhiều worker — số đo đồng thời ở đây là tiến trình `bench execute`, nặng hơn worker nóng; đo lại 1b / 1d trên đúng bản MariaDB của VPS (mục 1 — `innodb_snapshot_isolation`).
- Thời gian với **dữ liệu thật** của anh (1.835 mặt hàng, 598 khách, ~2.700 HĐ) sau khi có công cụ nhập H3.
- Sao lưu `bench backup --with-files` + đẩy Drive theo lịch.

## 5. Chạy lại

```bash
bench --site <site> execute nppsale.poc.setup.run --kwargs "{'currency_precision': '0'}"
bench --site <site> execute nppsale.poc.do.nhap_ton
bench --site <site> execute nppsale.poc.do.nhap_ton --kwargs "{'so_lo': 1, 'sl_moi_lo': 600, 'ngay_lui': 0, 'lo_bat_dau': 4}"   # lô -L4 600 lon — 05/11 nhập giữa chừng (sau lượt 1b đầu, trước hai lượt 1b có làm nóng); 1c, 1d chạy khi đã có lô này
bench --site <site> execute nppsale.poc.do.xuat_hang_nhieu --kwargs "{'lan': 10, 'so_dong': 15}"
bench --site <site> execute nppsale.poc.do.hai_lo_do --kwargs "{'lan': 5}"
bench --site <site> execute nppsale.poc.do.thue_lam_tron --kwargs "{'n': 50, 'giam_don_pct': 0, 'cach_giam_dong': 'app', 'seed': 1}"
bench --site <site> execute nppsale.poc.do.thue_lam_tron --kwargs "{'n': 50, 'giam_don_pct': 0, 'cach_giam_dong': 'loi', 'seed': 1}"
bench --site <site> execute nppsale.poc.do.thue_lam_tron --kwargs "{'n': 50, 'giam_don_pct': 5, 'cach_giam_dong': 'app', 'seed': 2}"
bench --site <site> execute nppsale.poc.do.thue_lam_tron --kwargs "{'n': 50, 'giam_don_pct': 0, 'cach_giam_dong': 'app', 'seed': 3, 'ty_le_sl_le': 0.2}"
bench --site <site> execute nppsale.poc.do.thue_lam_tron --kwargs "{'n': 50, 'giam_don_pct': 5, 'cach_giam_dong': 'app', 'seed': 4, 'ty_le_sl_le': 0.2}"
bench --site <site> execute nppsale.poc.do.thue_lam_tron --kwargs "{'n': 50, 'giam_don_pct': 0, 'cach_giam_dong': 'app', 'seed': 3, 'ty_le_sl_le': 0.2, 'luat_dong': 'hoa_don'}"
bench --site <site> execute nppsale.poc.do.thue_lam_tron --kwargs "{'n': 50, 'giam_don_pct': 5, 'cach_giam_dong': 'app', 'seed': 4, 'ty_le_sl_le': 0.2, 'luat_dong': 'hoa_don'}"
bench --site <site> execute nppsale.poc.do.dong_dac_biet
bench --site <site> execute nppsale.poc.do.thue_lam_tron --kwargs "{'n': 50, 'dong_min': 3, 'dong_max': 6, 'giam_don_pct': 0, 'cach_giam_dong': 'app', 'seed': 5}"
bench --site <site> execute nppsale.poc.do.thue_lam_tron --kwargs "{'n': 50, 'giam_don_pct': 0, 'cach_giam_dong': 'app', 'seed': 3, 'ty_le_sl_le': 0.2, 'luat_dong': 'hoa_don', 'sl_le_ve_lon': True}"
bench --site <site> execute nppsale.poc.do.dat_round_row_wise_tax --kwargs "{'v': 1}"   # chạy lại các lượt trên rồi trả về {'v': 0}
bench --site <site> execute nppsale.poc.do.dat_precision --kwargs "{'p': '2'}"
bench --site <site> execute nppsale.poc.do.dat_precision --kwargs "{'p': '0'}"
bench --site <site> execute nppsale.poc.do.giam_dau_phieu_nhap
bench --site <site> execute nppsale.poc.do.lcv_sua_gia
bench --site <site> execute nppsale.poc.do.lcv_kiem_lai
bench --site <site> execute nppsale.poc.do.ghi_co_doc_lap
bench --site <site> execute nppsale.poc.do.ghi_co_doc_lap2
bench --site <site> execute nppsale.poc.do.ghi_co_doc_lap2 --kwargs "{'dat_incoming_rate': False}"
bench --site <site> execute nppsale.poc.do.ghi_co_doc_lap2 --kwargs "{'kho': 'Kho ban - NPP', 'dat_incoming_rate': False, 'ban_het': True}"
bench --site <site> execute nppsale.poc.do.repost_khi_huy
bench --site <site> execute nppsale.poc.do.hai_dong_cung_lo
bench --site <site> execute nppsale.poc.do.doi_ma_lo_ep
bench --site <site> execute nppsale.poc.do.doi_ma_lo_ep_do_sot
bench --site <site> execute nppsale.poc.do.nhap_lai_lo_het_han2
bench --site <site> execute nppsale.poc.do.dau_ky_giu_ma
bench --site <site> execute nppsale.poc.do.sua_hd_amend
```

Lượt precision 2: chạy `dat_precision` với `'2'`, gọi lại các lượt `thue_lam_tron` (cùng `seed`; bảng 2.(2) có bốn lượt precision 2), rồi trả về `'0'`.
Bài đồng thời 1d: năm cửa sổ cùng gọi `nppsale.poc.do.xuat_hd_dong_thoi --kwargs "{'cho_den': <epoch + 75>, 'k': k, 'chung': False, 'khoa': True}"`
với k = 1…5 (đổi `chung` / `khoa` cho bốn kịch bản); bài cũ 1b: `xuat_hang_dong_thoi`. Điểm 7: `bench --site <site> serve --port 8000` rồi
`curl -D - http://127.0.0.1:8000/nppsale/sw.js`.

Mã PoC nằm trong app để P2 dùng lại làm bộ dựng site thử và bộ đo hồi quy; **không** chạy trên site thật. Mã đi theo app nên cài app là site thật cũng có mã này, nhưng không có hàm nào whitelisted nên chỉ gọi được từ dòng lệnh máy chủ (`bench execute`); đừng chạy `setup.run` ở đó (nó tạo công ty, kho,
mặt hàng mẫu).
