# Quyết định triển khai — chung cho blueprint 02–06 và mã

Ngày 11/11/2026, anh đặt mục tiêu cho phiên làm việc: *"lần lượt làm và code đến khi xong"*. Em hiểu là: viết nốt blueprint
02–06 rồi dựng mã theo các giai đoạn P2 → P8 của bản bàn bạc (mục 9), không dừng chờ duyệt từng tệp như nhịp đã chốt ở câu 11.
Mọi tệp vẫn nằm trên nhánh để anh duyệt lại bất cứ lúc nào; chỗ nào em tự quyết thay anh được ghi ở đây.

## Q1. Tầng dữ liệu của giao diện: "cổng tương thích nppsale"

**Số đo mã nppsale** (thư mục `src/`, 11/11/2026): 936 lời gọi `.from("<bảng>")` trên 75 bảng; 313 lời ghi
(`insert / update / upsert / delete`); 328 select lồng bảng (`customer:customers(...)`); 72 bộ lọc `.or(...)`; 74 RPC khác tên;
3 chỗ Storage; 2 chỗ realtime.

**Quyết định**: giữ nguyên cách mã React gọi dữ liệu, thay phần dưới:

1. **Trình duyệt**: một lớp `createClient()` thay `@supabase/supabase-js`, cùng giao diện (`from / select / insert / update /
   upsert / delete / eq / neq / gt / gte / lt / lte / like / ilike / in / is / not / or / contains / order / range / limit /
   single / maybeSingle / abortSignal / count / head`, `rpc(name, params, { get })`, `storage.from()`, `channel()` tối thiểu,
   `auth.*` tối thiểu). Lớp này dựng yêu cầu và gọi **một** method của app, giữ luật hẹn giờ / thử lại / dịch lỗi của
   `fetchCoHetGio` và `errorMessage`.
2. **Máy chủ — cổng đọc / ghi** (`nppsale.cong.*`): một **sổ đăng ký bảng** (`nppsale/cong/bang/*.py`) khai cho từng bảng nppsale:
   nguồn (DocType, bảng con, hay câu SQL dựng sẵn), cột nppsale ↔ trường ERPNext, quan hệ để select lồng, **vế lọc RLS theo vai**
   (chép đúng chính sách RLS đang chạy của nppsale), và luật ghi (cho ghi thẳng cột nào, kiểm gì — hay chỉ qua RPC).
   Bảng nào nppsale cấm ghi thẳng từ trình duyệt (tiền, kho, trạng thái chứng từ — mig 214) thì cổng cũng cấm.
3. **Máy chủ — RPC** (`nppsale.rpc.<tên>`): 74 hàm Python **cùng tên, cùng tham số, cùng dạng trả về** như RPC Postgres của nppsale;
   bên trong gọi API lõi ERPNext (Sales Order, Sales Invoice, Payment Entry, Stock Entry…) theo luật đã đo ở PoC
   (khoá Bin, gói lô do app lập, tờ ghi có độc lập, đơn giá app gửi…). Mã lỗi giữ đúng chuỗi của nppsale.
4. **Hiệu năng**: số lượt gọi mỗi màn bằng nppsale hôm nay (mỗi `.from()` một lượt) — đã chạy được ở nppsale; màn nặng sẽ gộp
   thành method một lượt sau (nguyên tắc 1 của mục 3.2 bản bàn bạc vẫn là đích, làm sau khi đủ chức năng).

**Vì sao không viết lại từng màn**: 936 + 313 chỗ gọi, mỗi chỗ mang một luật nhỏ (lọc, select lồng, quyền) — viết lại tay là hàng
nghìn chỗ dễ lệch luật mà không ai soát hết; cổng tương thích gom luật về **một sổ đăng ký kiểm được bằng test** (so tập dòng từng
người như `scripts/sql/thu-260-rls-khach-tinh-mot-lan.sql`) và giữ nguyên các bài test / e2e đang có của nppsale.

## Q2. Sổ công nợ theo hoá đơn là DocType riêng, tính lại theo sự kiện

`NPP Cong No` = bảng `receivables` của nppsale: **mỗi hoá đơn đã ghi sổ một dòng**, dòng nợ đầu kỳ, dòng âm của phiếu trả tự lập
không gắn HĐ; cột `amount / paid / status / sales_user_id / giao_tu_nv`. Tính lại bằng một hàm (như `_wf2b_recompute_receivable`)
mỗi khi HĐ, tờ ghi có, Payment Entry, bút toán cấn trừ ghi sổ / huỷ. Sổ cái ERPNext vẫn là sổ thật; `NPP Cong No` là bản tính sẵn
để đọc nhanh, lọc RLS và giữ đúng luật nợ âm / nợ chuyển tay (mục 1 `CLAUDE.md`). Phía NCC tương tự: `NPP Cong No NCC`.

## Q3. Câu 19 chưa trả lời — em tạm theo đề xuất

- (a) SL lẻ: tiền từng dòng làm tròn về đồng (cách của lõi). (c) VAT HĐĐT giữ như hôm nay (làm tròn từng dòng), sổ làm tròn một lần.
- Cả hai nằm trong `NPP Cai Dat` dưới dạng cờ để đổi được nếu anh chọn khác (đổi sang (e) là việc của module HĐĐT, không đổi sổ).

## Q4. Bố cục app

- App `nppsale`, các module: `NPP He Thong` (cài đặt, nhân viên, quyền, thông báo, khoá chứng từ, đo nạp, nhật ký),
  `NPP Khach Hang` (tuyến, phân công, lịch tuyến, ghé thăm, ảnh điểm bán, yêu cầu ảnh, bàn giao), `NPP Ban Hang` (phiếu trả, lượt
  soạn, công nợ, khuyến mãi, hoa hồng), `NPP Kho Mua` (kiểm kê, công nợ NCC, bảng giá nhập), `NPP Tien` (phiếu chi, danh mục chi phí),
  `NPP HDDT`, `NPP Nhan Su`, `NPP Luu Tru` (H3). Module cũ `NPP Sale` bỏ.
- Python: `nppsale/luat/` (luật thuần, không import frappe, có unit test), `nppsale/cong/` (cổng tương thích), `nppsale/rpc/`
  (74 RPC), `nppsale/api/` (method riêng của app: đăng nhập QR, đo nạp, lỗi trình duyệt, MISA…), `nppsale/su_kien/` (doc_events),
  `nppsale/lich/` (scheduler), `nppsale/portal/` (phục vụ portal), `nppsale/poc/` (giữ nguyên).
- Giao diện: `portal/` ở gốc repo (Vite + React Router), build ra `nppsale/public/portal/app/`. **Mã giao diện không chép vào
  repo này**: `portal/nguon.json` ghim một commit của repo nppsale, `scripts/lay-nguon.mjs` lấy `src/ public/ tests/` của commit
  ấy vào `portal/nguon/` (bỏ qua khi commit) lúc build. Repo npp chỉ giữ phần của bản Frappe: lớp thay `next/*` (`src/khung`),
  lớp phủ cùng đường dẫn với nppsale (`src/thay` — `@/x` tìm ở `src/thay/x` trước rồi mới tới `nguon/src/x`), cổng dữ liệu.
  Vì sao: (1) anh vẫn sửa giao diện ở nppsale trong lúc chuyển — đổi commit ghim là bản Frappe theo, không có hai bản lệch nhau;
  (2) không nhân đôi ~1.200 tệp mã giữa hai repo. Đến lúc tắt hẳn bản Next, có thể chép hẳn vào repo này (đổi một cấu hình).
  Máy chủ build cần quyền đọc repo nppsale (khoá triển khai do anh cấp trên máy chủ, không gửi qua chat).
- Cổng dữ liệu của portal nằm ở đường dẫn kiểu Supabase: `/rest/v1/<bảng>`, `/rest/v1/rpc/<hàm>` (renderer
  `nppsale.portal.rest`) — lớp mạng của nppsale nhận diện câu theo đường dẫn (hàm báo cáo `/rest/v1/rpc/bao_cao_*` chờ 45 giây,
  nhật ký đo nạp), giữ đường dẫn là giữ luật mà không sửa mã nppsale. Đọc = GET `?q=<JSON>` (máy chủ cần nginx
  `large_client_header_buffers 4 32k`); ghi = POST.
- Đường dẫn tuyệt đối trong mã nppsale (`window.open("/…")`, thẻ `<a href="/…">`) được thêm tiền tố `/nppsale` ở một chỗ
  (`src/khung/cua-so.ts`); lời gọi route `/api/<…>` cũ của Next đi qua `nppsale.api.tuyen.goi`; máy chủ có đường lùi
  `website_redirects` cho các đường dẫn cấp một của app.

## Q5. Nhịp làm

Mỗi giai đoạn: blueprint / mã → test (unit Python + bench run-tests trên site thử + vitest phía portal) → commit tiếng Việt →
push nhánh `claude/elegant-hamilton-ak996q`. Không đụng `main`, không tạo PR khi anh chưa bảo.

## Q6. Phiếu trả (P3c) — chỗ em tạm quyết, chờ anh chốt

Đặc tả phiếu trả (đọc thẳng hàm + trigger đang chạy của nppsale) liệt kê 14 câu cần anh chốt (Q1–Q14 của đặc tả). Để không dừng, em dựng theo
cách dưới. Bài vàng `nppsale/tests/test_phieu_tra_vang.py` so 150 tình huống với CHÍNH hàm Postgres của nppsale (`tools/vang_phieu_tra.py`);
chỗ khác nppsale ghi ở `LECH_PT` / `SUA_MONG` trong bài, đổi được một chỗ khi anh chốt khác.

| Câu | nppsale hôm nay | Bản ERPNext (tạm) |
|---|---|---|
| Q1 — ngày ghi kho phiếu tự lập | ghi kho **lúc bấm** Hoàn thành (mig 188), doanh số theo ngày phiếu | giữ như nppsale: tờ ghi có có kho ghi sổ lúc bấm; doanh số theo `ngay_tru_doanh_so` (12:00 ngày phiếu) |
| Q2 — làm tròn tờ ghi có | tiền trả = Σ làm tròn từng dòng, đơn giá 2 số lẻ | lõi làm tròn khác (vd 3 × 3.333,5 ra 10.002 thay 10.001) → bù đúng phần lệch bằng giảm giá **sau thuế** (tài khoản giảm giá đơn) để tờ = đúng số nppsale từng đồng |
| Q3 — không tìm được giá vốn nhập lại | nhập giá vốn 0 | lõi sẽ lấy giá bán làm giá vốn → **chặn** `RETURN_NO_COST` (nhập giá vốn mặc định của mặt hàng rồi hoàn thành lại); trước đó thử HĐ → đơn → lô mới nhất → giá vốn mặc định → giá nhập |
| Q4 — lô nhập lại mới | `RESTOCK-<mã phiếu nhập>` | `RESTOCK-<PT>-<mặt hàng>` (lõi đặt tên lô theo mã — hai mặt hàng không trùng); hạn = hạn xa nhất của mặt hàng → hôm nay + hạn dùng → hôm nay + 365 |
| Q5 — huỷ khi hàng nhập lại đã bán tiếp | cho lô âm | lõi chặn lô âm → báo `RETURN_STOCK_USED` |
| Q6 — dòng nợ âm khi phiếu độc lập bị huỷ | để lại dòng 0 đ | bản chiếu thuần xoá dòng (tổng nợ như nhau); phần dư có đã dùng ở phiếu thu dựng ở P3d |
| Q7 — sửa tay ô "Credit Note" của phiếu nháp | nhận, giữ tới lần đổi dòng kế | giữ như nppsale |
| Q8a — SL trả âm | nhận → tiền trả âm làm nợ **tăng** (ngược ý mig 227) | **chặn** như CHECK đơn giá / thuế: `23514 … "return_lines_quantity_khong_am"` (SL 0 vẫn nhận; RPC vốn bỏ dòng SL ≤ 0) — lõi cũng không nhận dòng SL dương trên tờ ghi có |
| Q8c — đơn vị lạ | nhận chữ tự do | nhận, tự tạo UOM (như dòng đơn) |
| Q8d, e, g, h | thuế 100 %, phiếu nháp cờ tự sinh, ngày tương lai, POS sửa phiếu theo đơn | giữ như nppsale |
| Q9 — lý do huỷ phiếu trả | không bắt | giữ như nppsale |
| Q10 — đổi ngày phiếu tự lập đã hoàn thành | chỉ dời mốc ghi có / ngày trừ doanh số | giữ như nppsale (không lập lại tờ ghi có) |
| Q11 — phiếu rỗng hoàn thành | lập phiếu nhập rỗng, `entry_id` có | hoàn thành không chứng từ kho, `entry_id` rỗng |
| Q12 — tài khoản chênh lệch phiếu nhập lại `NL-` | — | mặc định của lõi (Stock Adjustment) — chưa thêm ô `tk_*` |
| Q13 — hệ số quy đổi | tra danh mục lúc hoàn thành | chụp lúc lập chứng từ (tờ ghi có / phiếu nhập) — cùng thời điểm |
| Q14 — lập lại tờ ghi có khi tiền phiếu tự sinh đổi | — | huỷ tờ cũ, amend `HDT-x-n` |
| Q15 — tự gắn HĐ khi hoàn thành phiếu theo đơn | không kiểm khách (phiếu khách khác gắn được HĐ, trừ nợ khách HĐ) | chặn `INVOICE_CUSTOMER_MISMATCH` (luật "khách phiếu = khách HĐ" mig 212) |
| Q8i — ghi thẳng phiếu Nháp kèm cột "chỉ RPC" | nhận (kể cả `applied_receipt_id` → phiếu không bao giờ trừ nợ) | nhận như nppsale các cột khác (giờ hoàn thành / huỷ…, kho nhận); riêng `applied_receipt_id` báo `PHIEU_TRA_KHOA: cột này chỉ đổi qua RPC` (cột không port) |
| Q8j — người lập ghi dòng của phiếu đã sang tên NV khác | được; xoá hết dòng thì tiền phiếu GIỮ số cũ (hoàn thành phiếu rỗng ra dư có) | ghi dòng được như nppsale; tiền phiếu luôn tính lại (xoá hết dòng → 0) |

Khác biệt kỹ thuật không đổi số: nppsale đảo nhập kho bằng phiếu xuất "Đảo phiếu trả" + ghi chú "(đã đảo)", bản ERPNext huỷ chứng từ (docstatus 2);
giá vốn lô nền sau khi nhập lại do lõi định giá theo lô (nppsale giữ giá lô).

## Q7. Phiếu thu / tiền thu / nợ đầu kỳ (P3d) — chỗ em tạm quyết, chờ anh chốt

Đặc tả phiếu thu (đọc thẳng `create_cash_receipt` / `void_cash_receipt` / trigger công nợ đang chạy của nppsale) có 17 câu cần chốt (Q1–Q17 của
đặc tả). Em dựng theo cách dưới; bảng thêm dần theo từng phần P3d.

| Câu | nppsale hôm nay | Bản ERPNext (tạm) |
|---|---|---|
| Q4 — quản lý ở NPP MỚI lập / huỷ phiếu thu | hàm gieo quyền (`_gieo_quyen_mac_dinh`) không gieo `manager receivables.create/update`; mig 215 chỉ vá NPP có sẵn lúc chạy và ghi rõ thiếu là "KHÔNG cố ý" | gieo thêm hai dòng ấy (`DONG_VAI_GIEO_SAN`) — đúng ý anh 28/09/2026; NPP chuyển sang mang theo dòng quyền đang có |
| Q1 — tiền đã thu vượt tờ mới sau Sửa HĐ giảm tiền | phần vượt nằm ngay trên dòng HĐ (`paid > amount`, dư có) | **phương án B** (đổi từ A, chờ anh chốt): phần vượt chuyển vào CHÍNH HĐ mới bằng bút toán `chuyen_tien_thua` (Credit Note, số `CTR-`: Nợ Payment Entry / Có HĐ) → dòng HĐ đã thu > phải thu = dư có, khớp TỪNG DÒNG như nppsale; Sửa tiếp thì bút toán gộp lại vào phần của phiếu rồi lập theo tờ mới; huỷ phiếu huỷ bút toán trước. Bỏ A vì A (dòng `tien_thua` riêng mang nhãn HĐ) phải giả "dòng nppsale" ở 5 chỗ (nhãn / đơn / hạn / ngày lập / người giữ) và không làm được phiếu thu nhiều HĐ; dòng `tien_thua` chỉ còn là lưới an toàn khi sổ có Payment Entry treo tiền ngoài app (CFD-04 "Tiền thừa chưa phân bổ") |
| Q2 — sửa SỐ nợ đầu kỳ đã thu | cho (phần chênh thành dư có) | khoá `CONG_NO_KHOA` (CFD-01: huỷ + lập lại tờ `DK-` không mang được tiền đã thu); chưa thu thì sửa = huỷ + `DK-…-n`, giữ id dòng công nợ + ngày lập gốc |
| Q5 — hai người cùng rút một dư có | cả hai qua, phiếu sau ghi tiền mặt không ai đưa | khoá khách + mọi dòng công nợ của khách TRƯỚC khi tính; người sau nhận `CREDIT_BALANCE_TOO_LOW` |
| Q7 — nợ đầu kỳ 0 / âm / số lẻ | nhận | `BAD_AMOUNT: nợ đầu kỳ phải là số đồng chẵn lớn hơn 0` (thêm và sửa) |
| Q8 — xoá nợ đầu kỳ từng có phiếu thu (đã huỷ) | lỗi 23503 (khoá ngoại dòng phiếu thu) | giữ như nppsale |
| Q14 — `method` lạ (kể cả `credit_applied` / `return_credit`) khi có tiền thật | chỉ nổ CHECK ở dòng `payment` | từ chối mọi giá trị ngoài cash / transfer / ewallet bằng đúng lỗi `23514` |
| Q16 — dòng công nợ mất chứng từ nguồn mà còn dòng phiếu thu sống trỏ tới | không xảy ra (dòng phiếu trả giữ `amount 0`) | giữ dòng (số 0) cho dòng phiếu trả / tiền thừa — `payments` / báo cáo công nợ không mất khoản thu |
| Q19 — cấn phiếu trả ở phiếu thu (`credits`, nhánh cũ trước mig 191) | chỉ phiếu 0đ còn lọt điều kiện (tick ở thẻ cấn trừ), ghi `applied_receipt_id` | lệch có chủ ý: chỉ giữ phần kiểm (`BAD_CREDIT`); phiếu 0đ lọt thì không ghi gì (`applied_receipt_id` không port) |
| Q18 — dấu xác nhận (`xac_nhan_*`) trên dòng của phiếu bị huỷ | `payments` bị xoá khi huỷ → mất luôn người / lúc xác nhận | (a): huỷ phiếu xoá dấu xác nhận trên dòng (dòng giữ như `cash_receipt_lines`) — `so_chung_tu_nhan_vien` đếm `payments.collected_by / verified_by` chỉ trên phiếu chưa huỷ, khớp nppsale |
| Ghi thẳng `receivables`: đổi người giữ / hạn / ghi chú của dòng HĐ, phiếu trả | chủ / kế toán đổi được (trigger không chặn) | `CONG_NO_KHOA` (blueprint §6.1 — không màn nào gửi; người giữ đổi qua bàn giao / giao nợ) |
| Mã phiếu thu | `PT-YYMMDD-NNNN` 4 số ngẫu nhiên | `PTH-YYMMDD-####` chạy liên tục (câu 13); Payment Entry mang đúng số phiếu |
| Q3 — nguồn dư có mất / đổi sau khi đã bị rút (sửa / huỷ phiếu trả nguồn, Sửa HĐ được đắp) | nợ "tự tăng lại" trên CHÍNH dòng nguồn (dòng phiếu trả `amount 0, paid −take`), số payments không đổi | bút toán cấn trừ `CTR-` huỷ trước rồi lập lại `CTR-…-n` GIỮ số từng vế, chỉ trỏ sang chứng từ còn hiệu lực cùng dòng (tờ ghi có mới của cùng phiếu / HĐ mới); phiếu trả độc lập bị huỷ → vế Nợ giữ tờ ghi có ĐÃ HUỶ của phiếu (lõi không kiểm docstatus với bút toán Credit Note) → dòng phiếu trả còn nợ đúng số đã rút như nppsale |
| Q9 — Huỷ / Sửa tờ nợ đầu kỳ `DK-` qua RPC Huỷ HĐ | không phải `sales_invoices` → `INVOICE_NOT_FOUND` | như nppsale (lọc `is_opening`) |

## Q8. Hoá đơn điện tử MISA (P3d) — chỗ em tạm quyết, chờ anh chốt

Đặc tả HĐĐT (đọc thẳng `src/lib/misa/*`, 7 route `/api/einvoice/*`, bốn bảng + `cancel_invoice` đang chạy của nppsale; số vàng chạy từ chính mã TS)
có 27 câu (H1–H27, §0.3 của đặc tả + vòng soát thiếu 2); vòng soát mã ba góc (16/11/2026) thêm H28–H30 và mở rộng H2 / H5 / H14 / H25 (cuối bảng).
Em dựng theo cột phải; mỗi chỗ khác nppsale có kịch bản vàng khai lệch, đổi được một chỗ khi anh chốt khác. **Bốn câu cần anh chốt** (em đang giữ như
nppsale): **H10, H11, H12, H16** (in đậm). **Đã dựng H1–H30** — bốn DocType + khoá Huỷ / Sửa HĐ (`nppsale/rpc/xuat_hang.py::_khoa_hddt`), bốn bảng cổng
(`nppsale/cong/bang/hddt.py`), lớp gọi MISA (`nppsale/api/misa_mang.py`), route `/api/einvoice/*` (`nppsale/api/misa.py`), lịch quét + kéo
snapshot (`nppsale/lich/misa.py`), khám sổ HĐĐT (`nppsale.kham_so.hddt`); bài `test_luat_hddt`, `test_misa_mang`, `test_hddt_khoa`, `test_cong_hddt`,
`test_hddt`, `test_lich_misa`. Còn chờ P8: nhánh dữ liệu chuyển sang (`hoa_don_ban_ls` / `don_hang_ls`, bảng lưu trữ — KV-29a) chưa có bảng để thử.

| Câu | nppsale hôm nay | Bản ERPNext (tạm) |
|---|---|---|
| H1 — HĐĐT lập từ danh sách Đơn hàng / màn "Tạo HĐĐT" có chọn đơn | lập theo ĐƠN: người mua + tiền của đơn (giao thiếu vẫn khai cả đơn), không gắn HĐ bán ⇒ không khoá Sửa / Huỷ HĐ; quản lý bấm Phát hành ở HĐ chưa có dòng HĐĐT thì hỏng (quyền dữ liệu chỉ cho chủ / KT ghi) | gắn HĐ ghi sổ của đơn, người mua + ba số tiền lấy từ HĐ; đơn chưa xuất → "Đơn chưa có hóa đơn bán nào — xuất hàng trước rồi mới phát hành hoá đơn điện tử."; đơn nhiều HĐ → từ chối, phát hành từng HĐ; quản lý lập được dòng gắn HĐ (blueprint §7.1 điểm 19) |
| H2 — Huỷ / Sửa HĐ khi HĐĐT **đang chờ MISA** trả kết quả | không khoá (chỉ khoá khi đã phát hành / có số / signed / replaced) ⇒ có thể ra HĐĐT nháp trên MISA cho HĐ đã huỷ | khoá thêm: có RefID ∧ trạng thái MISA pending / sent / waiting_code / **amount_mismatch** → `LOCKED_EINVOICE: HĐĐT đang chờ MISA — bấm Làm mới trạng thái trước` (blueprint §7.1 điểm 20; amount_mismatch chưa số thêm ở vòng soát — nháp lệch tiền của mọi HĐ có giảm giá đơn, chủ "Huỷ" HĐĐT nội bộ không huỷ gì bên MISA) |
| H3 — Đẩy lại tờ đã có RefID (lần trước lỗi rõ / hết giờ) | RefID mới mỗi lần đẩy (RefID chỉ ghi khi MISA nhận) | dùng lại RefID và **hỏi MISA trước** (`GET ?refID=`): MISA đã có → không gửi lại, cập nhật như Làm mới; chưa có → gửi cùng RefID |
| H3b — Màn chi tiết HĐĐT rẽ nhánh theo RefID | RefID chỉ có khi đã tới MISA | cổng trả RefID rỗng khi trạng thái MISA trống / lỗi (tờ chưa chắc tới MISA) ⇒ màn vẫn hiện "Đẩy lại lên MISA" như cũ, không sửa giao diện; mất link "Mở MISA" của tờ lỗi ở danh sách |
| H4 — Bấm Phát hành khi tờ đang "Chờ gửi" | 409 "Hoá đơn đang được xử lý…" | giữ đúng 409 + câu ấy (blueprint cũ ghi trả kết quả cũ) |
| H5 — Làm mới / vòng quét gặp tờ đang chờ mà MISA chưa có; hoặc MISA đã có tờ đang chờ / lỗi | 404, không ghi gì | chuyển "Lỗi" **chỉ khi** đã gửi quá 10 phút (MISA có thể chưa ghi xong); MISA đã có ⇒ coi như đẩy thành công (tờ "đã phát hành nội bộ", xoá lỗi, trạng thái MISA ít nhất "Đã gửi MISA" khi bản ghi không đủ để kết luận — trước đó kẹt "Chờ gửi" / "Lỗi"); bản ghi MISA rỗng (`{}` / `[]`) cho tờ đang chờ / lỗi coi như MISA KHÔNG có (không "xác nhận" tờ MISA chưa nhận; đẩy lại thì gửi tiếp cùng RefID) |
| H6 — Phát hành dòng HĐĐT trỏ HĐ bán **đã huỷ** | cho (phát hành thật cho lần bán đã huỷ) | chặn 400 "Hóa đơn {mã} không còn hiệu lực — không phát hành hoá đơn điện tử được."; tờ huỷ nội bộ vẫn đẩy được |
| H7 — Ghi chú đối chiếu (`misa_note`) khi có ghi chú mới | thay cả ô (mất ghi chú "MẤT RefID" / ghi chú người) | chỉ thêm dòng chưa có (không phình mỗi đêm) |
| H8 — MISA trả bản ghi chưa có số cho tờ sổ đã có số | hạ "Đã phát hành" → "Đã gửi MISA" | giữ trạng thái + ghi chú "… giữ nguyên trạng thái, cần kiểm tra tay." |
| H9 — Dựng HĐĐT từ đối soát khi MISA còn `<Chưa cấp số>` | ghi chuỗi giữ chỗ vào ô số | để trống số (trạng thái "Đã gửi MISA") |
| **H10 — Giảm giá cả đơn không lên HĐĐT** | không gửi ⇒ MISA khai cao hơn sổ đúng khoản giảm; tờ thành "Lệch với MISA" | **giữ như nppsale — anh chốt**: giữ, hay đưa giảm giá đơn lên HĐĐT (dòng chiết khấu / chiết khấu tổng của MISA — chưa đo MISA nhận dạng nào) |
| **H11 — Hàng đổi (đơn giá 0) lên HĐĐT như một dòng hàng 0 đ** | có | **giữ như nppsale — anh chốt**: giữ / bỏ dòng hàng đổi khỏi HĐĐT / đánh dấu hàng khuyến mại |
| **H12 — HĐĐT đã huỷ trên MISA (còn số) vẫn khoá Huỷ / Sửa HĐ bán mãi** | có | **giữ như nppsale (đã dựng) — anh chốt**: giữ khoá, hay mở khoá khi MISA báo đã huỷ |
| H13 — Ghi kết quả hỏng ở Làm mới / Thử kết nối | chỉ ghi log máy chủ, vẫn báo thành công | báo lỗi (không toast "thành công" mà sổ không đổi) |
| H14 — Cửa sổ 60 ngày của vòng quét đêm | theo ngày phát hành nội bộ — tờ chưa có ngày ấy không bao giờ được quét | theo ngày muộn hơn của (phát hành nội bộ, lần gửi MISA gần nhất); vòng khớp snapshot đêm dùng CÙNG mốc (+ ngày HĐĐT MISA) để chọn phần sổ — nppsale chỉ ngày phát hành nội bộ nên tờ "Khoá HĐ" cũ mới đẩy / tờ huỷ nội bộ rồi phát hành thành "HĐ phát hành ngoài app" mỗi đêm |
| H15 — Token MISA hỏng trong vòng quét | lấy token lại cho TỪNG tờ (tới 400 lượt / đêm — nguy cơ MISA khoá tài khoản) | lấy token một lần đầu lượt; hỏng ⇒ bỏ lượt, một dòng lỗi |
| **H16 — Kế toán không thấy nút "Phát hành HĐ điện tử" ở màn HĐ bán** | như vậy (nút gác quyền `orders.approve` — mặc định chủ / quản lý) dù máy chủ + quyền dữ liệu cho kế toán phát hành | **giữ như nppsale — anh chốt**: cho kế toán thấy nút (gieo `orders.approve` cho KT, hoặc sửa màn) |
| H17 — Số gõ tay khác số MISA cấp | không nói gì | thêm ghi chú "sổ ghi X, MISA cấp Y", không đổi trạng thái; ⚠ màn "Tạo HĐĐT" tự sinh số `INV-YYYYMMDD-xxxx` ⇒ mọi tờ lập tay sẽ mang ghi chú này khi có số — anh cho bỏ qua số đúng khuôn ấy không |
| H18 — Tên hàng đẩy lên MISA | tên hàng hiện hành lúc đẩy | giữ: tên mặt hàng (Item) lúc đẩy |
| H19 — Thứ tự dòng hàng gửi MISA | thứ tự cơ sở dữ liệu trả (không sắp) | theo thứ tự dòng của HĐ |
| H20 — Phát hành đọc được mã tra cứu ⇒ "Đã phát hành" | có, nhưng với dạng phản hồi tài liệu mô tả thì không bao giờ đọc được (luôn "Đã gửi MISA") | chép nguyên bộ đọc; đo phản hồi thật khi anh cho phép dùng tài khoản thử |
| H21 — Hai cột chuẩn hoá của ảnh chụp MISA | cột tính sẵn của Postgres (`'000'` giữ `'000'`) | đúng hàm khớp số / ký hiệu (`'000'` → `'0'`) — app không đọc hai cột này — **đã dựng** |
| H22 — Kéo về: số MISA khác số đang có trên tờ | ghi đè im lặng | vẫn ghi số MISA + ghi chú "Số HĐĐT đổi từ … sang … theo MISA — cần kiểm tra." |
| H23 — Phát hành tờ **mất RefID** (có số, không RefID — dữ liệu mig 099) | đẩy nháp thứ hai lên MISA cho tờ đã có số | có số ⇒ trả kết quả cũ, không đẩy; xử lý tay qua Desk (gán RefID tìm lại / xoá dấu MISA rồi phát hành lại) |
| H24 — Sửa người mua / tiền của tờ bị MISA từ chối (vd MST người mua sai) | sửa được (RefID chưa ghi khi lỗi) | RefID nay ghi TRƯỚC khi gửi ⇒ luật sửa = "nháp ∧ trạng thái MISA trống hoặc Lỗi" (không còn "chưa có RefID"); xoá dòng nháp đã gửi MISA báo "Chỉ xoá được hoá đơn điện tử nháp chưa gửi MISA." |
| H25 — Câu lỗi lấy token mang 300 ký tự thân trả về của MISA | có (MISA đổi tên khoá là token lọt vào câu lỗi, nhật ký) | giữ câu, che giá trị mọi khoá có chữ `token` + chuỗi dạng JWT + giá trị dạng token của `Data` / `jwt` / `*key` (API tích hợp MISA trả `{"Success":true,"Data":"<token>"}`), cả nhánh MISA trả mã lỗi |
| H26 — MISA trả ngày không có thật (`2026-02-30`) | Postgres từ chối cả câu ghi — sổ không đổi gì, lỗi bị nuốt | bỏ ngày + ghi chú "… không phải ngày có thật — bỏ qua, cần kiểm tra tay."; ảnh chụp để trống ngày |
| H27 — Thử gửi lại khi lỗi có chữ token / expired / unauthorized (cả lỗi 400 / 500) | gửi lại nguyên tờ cùng RefID | hỏi MISA trước lần gửi thứ hai; MISA đã có ⇒ không gửi lại |
| H28 — Địa chỉ API MISA trong cấu hình (vòng soát mã) | nhận mọi chuỗi: chủ / KT KHÔNG biết mật khẩu chỉ cần đổi địa chỉ rồi bấm "Thử kết nối" là máy chủ giải mã tài khoản + mật khẩu MISA đã lưu và gửi tới máy tuỳ ý (kèm dò mạng trong — câu lỗi mang 500 ký tự trả lời) | chỉ nhận `https://` tới máy chủ MISA (`testapp.meinvoice.vn`, `app.meinvoice.vn` — như hướng dẫn trên màn; thêm máy qua `site_config.json` `"npp_misa_may_chu"`); đường token / phát hành phải là `/…`; sai → 400 câu tiếng Việt (trước: 500 câu tiếng Anh của lõi); **đổi máy MISA mà không gõ lại tài khoản / mật khẩu ⇒ bản đã lưu bị xoá** (thử ↔ thật là hai tài khoản); không theo chuyển hướng (3xx gửi lại mật khẩu sang máy khác), trả lời quá 2 MB thì dừng đọc |
| H29 — Bản nhớ token MISA (vòng soát mã) | khoá theo địa chỉ + MST + tài khoản: một tiến trình phục vụ MỌI NPP của bench (mỗi NPP một site) ⇒ NPP B nhập MST + tài khoản MISA của NPP A với mật khẩu bất kỳ là dùng được token của A ~29 phút; mật khẩu sai vẫn chạy bằng token cũ | khoá thêm site + mật khẩu (băm) |
| H30 — MISA trả 502 / 504 sau khi gửi (cổng trước MISA hết giờ — máy sau có thể đã ghi nháp) | lỗi rõ → "Lỗi" ⇒ mở khoá Huỷ / Sửa HĐ trong lúc MISA có thể đang giữ nháp | "chưa biết" như hết giờ: giữ "Chờ gửi", không gửi lại; Làm mới / vòng quét gỡ theo RefID (MISA không có sau 10 phút → "Lỗi"); 500 / 503 vẫn lỗi rõ |
| (vòng quét đêm — vòng soát mã) MISA trả LỖI cho một tờ (vd không tìm thấy RefID) | không ghi mốc "đã hỏi" ⇒ tờ ấy đứng đầu hàng mỗi đêm | vẫn ghi mốc "đã hỏi" để hàng đợi xoay vòng (lỗi đường truyền thì không); lượt đêm có hạn giờ (40 phút quét, 55 phút kéo snapshot) và dừng khi 5 tờ liền mất kết nối — luôn để lại một dòng nhật ký lượt, kể cả khi việc nền bị cắt |
