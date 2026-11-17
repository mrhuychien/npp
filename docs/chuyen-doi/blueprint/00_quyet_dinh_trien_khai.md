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
| H28 — Địa chỉ API MISA trong cấu hình (vòng soát mã) | nhận mọi chuỗi: chủ / KT KHÔNG biết mật khẩu chỉ cần đổi địa chỉ rồi bấm "Thử kết nối" là máy chủ giải mã tài khoản + mật khẩu MISA đã lưu và gửi tới máy tuỳ ý (kèm dò mạng trong — câu lỗi mang 500 ký tự trả lời) | chỉ nhận `https://` tới máy chủ MISA (`testapp.meinvoice.vn`, `app.meinvoice.vn` — như hướng dẫn trên màn; thêm máy qua `site_config.json` `"npp_misa_may_chu"`); đường token / phát hành phải là `/…`; sai → 400 câu tiếng Việt (trước: 500 câu tiếng Anh của lõi); **đổi máy MISA mà không gõ lại tài khoản / mật khẩu ⇒ bản đã lưu bị xoá** (thử ↔ thật là hai tài khoản); không theo chuyển hướng (3xx gửi lại mật khẩu sang máy khác), trả lời quá 2 MB thì dừng đọc. **Anh xác nhận** địa chỉ API MISA thật đang dùng (`company_einvoice_config.api_base` trên sổ thật — bản tham chiếu không có dữ liệu): khác hai máy trên thì người quản trị máy chủ thêm vào `npp_misa_may_chu` trước khi cắt chuyển, không thì lưu cấu hình báo 400 |
| H29 — Bản nhớ token MISA (vòng soát mã) | khoá theo địa chỉ + MST + tài khoản: một tiến trình phục vụ MỌI NPP của bench (mỗi NPP một site) ⇒ NPP B nhập MST + tài khoản MISA của NPP A với mật khẩu bất kỳ là dùng được token của A ~29 phút; mật khẩu sai vẫn chạy bằng token cũ | khoá thêm site + mật khẩu (băm) |
| H30 — MISA trả 502 / 504 sau khi gửi (cổng trước MISA hết giờ — máy sau có thể đã ghi nháp) | lỗi rõ → "Lỗi" ⇒ mở khoá Huỷ / Sửa HĐ trong lúc MISA có thể đang giữ nháp | "chưa biết" như hết giờ: giữ "Chờ gửi", không gửi lại; Làm mới / vòng quét gỡ theo RefID (MISA không có sau 10 phút → "Lỗi"); 500 / 503 vẫn lỗi rõ |
| (vòng quét đêm — vòng soát mã) MISA trả LỖI cho một tờ (vd không tìm thấy RefID) | không ghi mốc "đã hỏi" ⇒ tờ ấy đứng đầu hàng mỗi đêm | vẫn ghi mốc "đã hỏi" để hàng đợi xoay vòng (lỗi đường truyền thì không); lượt đêm có hạn giờ (40 phút quét, 55 phút kéo snapshot) và dừng khi 5 tờ liền mất kết nối — luôn để lại một dòng nhật ký lượt, kể cả khi việc nền bị cắt |

## Q9. Kho / mua hàng / công nợ NCC (P4) — chỗ em tạm quyết, chờ anh chốt

Đặc tả P4 (đọc thẳng 51 hàm + trigger đang chạy của nppsale, đối chiếu blueprint 02; soát thiếu 16/11/2026) có 28 điểm bản ERPNext khác nppsale có
chủ ý / mâu thuẫn giữa blueprint, CLAUDE.md và mã (§7.2) và 41 điểm chờ chốt / cần đo (§7.3). Em dựng theo cột phải (= "đề xuất" của đặc tả).
**In đậm** = cần anh chốt trước khi dựng mốc ghi trong dòng; còn lại em làm theo đề xuất, đổi được một chỗ khi anh chốt khác. Mỗi mốc M0–M9 chỉ THÊM
dòng / ghi "đã dựng" vào bảng này.

**M0 (nền) đã dựng**: DocType `NPP Cong No NCC` (bản chiếu công nợ NCC từ sổ — `nppsale/su_kien/cong_no_ncc.py`, hook Purchase Invoice / Payment
Entry / Journal Entry), dồn trả trước NCC `don_tra_truoc_ncc` (method gọi tường minh), khám sổ NCC (`nppsale.kham_so.cong_no_ncc`, nhóm 20–22, chạy
cùng việc đêm 01:00), cài đặt site §2.11 + bộ kiểm cài đặt (`nppsale.thiet_lap.kho_mua.kiem_cai_dat`), luật thuần `nppsale/luat/kho_mua.py`, hàm kho dùng
chung `nppsale/rpc/goi_lo.py` (gói lô Inward / Outward — Xuất hàng và phiếu nhập lại `NL-` của P3 dùng chung), Custom Field `Purchase Invoice.npp_ghi_chu_no`,
DocPerm sàn đọc Purchase Invoice cho vai NPP; bài `test_luat_kho_mua` (thuần), `test_cong_no_ncc`, `test_do_kho_mua` (ghim hành vi lõi đã đo).

**M1 (phiếu nhập) đã dựng**: RPC `complete_purchase_invoice` / `cancel_purchase_invoice` (chưa có nhánh `DA_TRA_TIEN` — M3) / `khoi_phuc_phieu_nhap` / `luu_gia_nhap` + ghi giá nhập từ phiếu (`nppsale/rpc/phieu_nhap.py`); cổng `purchase_invoices` + `purchase_invoice_lines` (đọc + ghi phiếu tạm) và `payables` (đọc) — `nppsale/cong/bang/mua_hang.py`; quan hệ `purchase_price_lists → invoice:purchase_invoices` (🔧 §2.9); cổng sắp theo cột bảng lồng nhiều-một `.order('supplier(name)')` (đặc tả §4.1 — `/payables` bấm cột "Nhà cung cấp"; trước đây báo 42703) ở `nppsale/cong/sql.py`; Custom Field `Purchase Invoice.npp_kho_nhap`; TK giảm đầu phiếu nhập; bài so vàng `test_kho_mua_vang` (V01–V16: 28 kịch bản chạy khớp từng bước + ảnh chụp, 6 kịch bản chỉ nppsale bỏ; khác có chủ đích V05d / V08b / V12 — các dòng M1 dưới), `test_phieu_nhap` (18 bài: ghi thẳng phiếu tạm, câu đọc đúng của giao diện, dồn trả trước, hàng không lô, tiền dòng âm, khôi phục giữ nguyên đầu phiếu + dòng…), luật thuần thêm ở `test_luat_kho_mua`; thử phá: 27 đột biến luật thuần đều bắt; trên site 54 đột biến lượt trước (50 bắt, 4 lọt) + 24 lượt cuối đều bắt — gồm lại 4 cái từng lọt (đi theo chuỗi amend lúc chuẩn bị / lúc khoá, cửa vai của Huỷ, ngày giờ ghi sổ tờ khôi phục — nay có bài); còn một đột biến tương đương (`allow_zero_valuation_rate` của dòng 0 đ — dòng "Hàng tặng 0 đ" dưới).

**M2 (trả NCC) đã dựng**: RPC `complete_supplier_return` / `cancel_supplier_return` / `khoi_phuc_phieu_tra_ncc` + RPC mới `sua_phieu_tra_ncc` (`nppsale/rpc/tra_ncc.py`: chọn lô hạn cũ trước theo kho của phiếu, gói lô Outward do app lập, khoá Bin → khoá PI theo chuỗi amend như M1, huỷ mở lại lô đã tắt, khôi phục = amend + gửi lại trong savepoint); luật thuần `nppsale/luat/tra_ncc.py` (câu lỗi nguyên văn, kiểm dòng, kết quả khôi phục); cổng `supplier_returns` + `supplier_return_lines` (đọc: mọi NV của NPP như RLS mig 068; ghi phiếu nháp: 4 vai) — `nppsale/cong/bang/tra_ncc.py`; lớp phủ portal: `lib/pos/save.ts` + `app/(dashboard)/purchase-returns/[id]/edit` gọi `sua_phieu_tra_ncc` (`lib/purchasing/sua-phieu-tra.ts`), `lib/purchasing/khoi-phuc.ts` + `lib/purchasing/doi-id.ts` + bốn trang bọc (`/pos/tra-ncc/[id]`, `/pos/tra-ncc/[id]/sua`, `/purchase-returns/[id]`, `/purchasing/receipts/[id]`) đưa màn sang tờ còn hiệu lực sau sửa / khôi phục (điền luôn chỗ M1 để ngỏ ở chi tiết phiếu nhập), `lib/pos/load.ts` (§7.3 điểm 41 — lô của phiếu gốc theo mã cắt đuôi amend). Bài: so vàng `test_kho_mua_vang` thêm V17–V28 + V87 (14 kịch bản chạy khớp từng bước + ảnh chụp: V17, V17b, V18, V19, V19b — kịch bản kiểm đặc tả, V20, V21, V22, V24, V25, V26, V27, V28, V87; V23a/b/c chỉ nppsale (dữ liệu cũ / ghi thẳng `status`) bỏ; khác có chủ đích V18 — tiền phiếu nháp như dòng M1 "Tiền phiếu tạm", V19 / V22 / V25 / V26 / V27 / V28 — các dòng M2 dưới; V22 dùng Material Issue dựng nền thay phiếu xuất lẻ tới khi M4 dựng), `test_tra_ncc` (12 bài trên site), `test_luat_tra_ncc` (6 bài thuần), `portal/tests/tra-ncc-sua.test.ts` (7 bài); thử phá: 16 đột biến luật thuần đều bắt; trên site 45 đột biến lượt đầu (42 bắt, 3 lọt) — thêm hai bài (khoá theo chuỗi amend lúc khoá, huỷ nháp rồi khôi phục về nháp) rồi chạy lại hai cái lọt + 3 đột biến mới: đều bắt; còn một đột biến tương đương (bỏ dòng chép lại `npp_hoan_thanh_boi` ở tờ amend — trường không `no_copy`, `copy_doc` đã giữ).

| Câu | nppsale hôm nay | Bản ERPNext (tạm) |
|---|---|---|
| §7.2 #1 — Số phiếu nhập | cấp lúc **hoàn thành** = MAX + 1, không lỗ số (mig 142 / 237) | cấp lúc lập nháp `PN-.####` (câu 18 — đã chốt); nháp xoá để lỗ số; POS hiện mã lô dự kiến từ nháp. Dãy `PN-` / `PTNCC-` / `DKN-` / `NTN-` / `SGN-` đặt ở M0 (P8 đặt số bắt đầu sau MAX nppsale) |
| **§7.2 #2 — Sửa / khôi phục phiếu nhập, phiếu trả NCC** (trước M2) | sửa tại chỗ / khôi phục giữ số + giữ id (mig 235 / 241); CLAUDE.md (anh 13/10/2026): "Sửa phiếu trả NCC đã xuất giữ nguyên số phiếu" | huỷ + amend `-1` (CFD-01 "Duyệt tất cả"); giao diện thêm lớp phủ điều hướng theo id mới — **mâu thuẫn CLAUDE.md ↔ CFD-01 ở phiếu trả NCC, anh chốt lại** |
| **§7.2 #3 — Sửa phiếu nhập đã bán** (trước M7) | đổi được SL (≥ đã xuất), thêm / bỏ dòng, NCC, kho, số / ngày HĐ, giảm, VAT (mig 235 — anh 06/10/2026 "tao muốn sửa được") | chỉ sửa GIÁ (LCV `SGN-` + bút toán `DCN-`, CFD-06); đổi SL / lô / NCC / kho → lỗi — **hẹp hơn lời anh, anh xác nhận** (V67 / V68 / V70 ra khác) |
| §7.2 #4 — Xuất / huỷ vượt tồn | `allow_oversell` cho âm ở xuất lẻ, trả NCC, huỷ phiếu nhập (mig 222 / 238) | hàng theo lô không bao giờ âm (CFD-05 B); chỉ hàng không lô (`Item.allow_negative_stock` + `NPP Cai Dat.cho_ban_vuot_ton`); câu `HANG_DA_XUAT` cho hàng lô — §7.3 điểm 12 |
| §7.2 #5 — Nhập kho tay có NCC + tiền | `IN-` + dòng nợ, hai giá (đơn giá → nợ, giá vốn gõ riêng → lô) | thành phiếu nhập `PN-` (CFD-13, câu 17) — một `rate`; hai giá xử lý ở §7.3 điểm 3 |
| §7.2 #6 — Kiểm kê | `stock_entries stocktake`, áp lô tại chỗ, `expenses` | `NPP Kiem Ke` + `DCK-` Issue / Receipt + `NPP Phieu Chi` (CFD-09); thừa có bút toán (M6) |
| §7.2 #7 — Rà soát kho date | lật cờ vùng, không phiếu, không lịch | phiếu `CKL-` `chuyen_date_tu_dong` + việc đêm 01:00 (bàn bạc 3.9); huỷ PN có lô đã rà — §7.3 điểm 8 |
| §7.2 #8 — Nhận diện nguồn khi huỷ phiếu kho | khoá ngoại + **ghi chú** (sửa ghi chú là lách được — V54) | trường thật (`npp_loai`, `npp_phieu_tra`, `PI.npp_loai`…) — đóng lỗ, giữ nguyên câu lỗi |
| §7.2 #9 — Ghi thẳng phiếu nhập / trả NCC | RLS `FOR ALL` mọi cột kể cả `status`; xoá phiếu đã xuất được (K25) | chỉ phiếu nháp; đổi trạng thái → `USE_RPC` (BP §6.1; CLAUDE.md "trạng thái chứng từ chỉ đổi qua RPC") |
| §7.2 #10 — Huỷ phiếu nháp | giữ dòng `cancelled` + lý do | như §7.3 điểm 1 |
| §7.2 #11 — Tiền | không làm tròn (`13332.60`) | làm tròn đồng — chênh < 1 đ / phiếu (BP §7.2 điểm 3); Property Setter precision 4 cho `rate` / `net_rate` / `discount_amount` của dòng PI — **đã đặt M0** |
| §7.2 #12 — Ngày | `CURRENT_DATE` / `now()` UTC ở trigger kho date, rà soát, `HANG_GAN_HAN`, chi phí hao hụt, mặc định `return_date` (mig 140 ghi nhận, cố ý chưa sửa) | ngày VN mọi nơi; bài vàng chạy 07:00–23:59 VN |
| §7.2 #13 — Thẻ kho | gồm nháp, đổi vùng hồi tố, dòng âm ảo, cặp xuất + đảo | sổ kho lõi: chỉ chứng từ ghi sổ, không hồi tố, chứng từ huỷ biến mất — khác có chủ đích |
| §7.2 #14 — Phiếu kho của PN / PTNCC | bản ghi `stock_entries` riêng (`entry_code` = mã PN / `XK-…`), dòng một lô | = chính Purchase Invoice, dòng = dòng PI (cổng `stock_entries` gộp nguồn — M4) |
| §7.2 #15 — "Thử lại khi lô âm" (BP §4.4.0) | — | `_goi_co_khoa` chỉ thử lại deadlock / quá hạn khoá; sửa BP: có khoá Bin thì lô âm là dữ liệu sai — không thử lại, ghi log |
| §7.2 #16 — Ngày tương lai (CFD-12) | `chi_tra_ncc` có `NGAY_TUONG_LAI`; nhập kho tay lùi ngày được | lõi 16.53 không chặn ở Stock Entry / PI → method tự chặn ở `post_stock_import`, trả NCC, `DKN-` / `NTN-`: `NGAY_TUONG_LAI: Ngày chứng từ không được sau hôm nay.` |
| §7.2 #17 — `return_date` → `posting_date` (BP §5.9) | `return_date` không dùng cho kho / nợ (ghi lúc bấm) | như §7.3 điểm 11 |
| §7.2 #18 — Xoá khoản nợ của phiếu nhập qua cổng | hỏng 23503 khoá ngoại (cả PN lẫn PTNCC); chỉ nợ `IN-` / lập tay / đầu kỳ xoá được | chặn bằng đúng câu 23503 của nppsale (§7.3 điểm 38) |
| §7.2 #19 — `bill_date` không AOS | đổi ngày HĐ NCC trên phiếu đã bán được | nhánh sửa giá không đổi được ngày HĐ NCC — Property Setter riêng hoặc chấp nhận (M7) |
| §7.2 #20 — `DA_TRA_TIEN` | tính cả Bù trừ (`offset`) vào `paid` | gồm cả JE `bu_tru_ncc` (BP §6.4 chỉ kể PE Ghi trả) |
| §7.2 #21 — Bảng mã lỗi BP §6.4 | — | bổ sung 12 mã của phiếu nhập, bốn câu `FORBIDDEN` khác nhau, `KHONG_DU_QUYEN_GIA_NHAP` là P0001 — trước khi viết method (M1) |
| §7.2 #22 — Mã đang chạy lệch nppsale | — | `NCC_XOA_QUA_RPC` sai câu (`cong/bang/nha_cung_cap.py:33`); `purchase_price_lists` thiếu quan hệ `invoice:purchase_invoices` (PGRST200 → POS mất giá gợi ý); phiếu `NL-` ghi "Nhập lại từ phiếu trả …" vào `remarks` thay `npp_ghi_chu` — sửa ở M1 / M4 / M8 |
| §7.2 #23 — Gộp NCC | chuyển nợ đầu kỳ của NCC bị gộp thành nợ thường; `ON CONFLICT` phân công | thêm hai bước ấy vào `gop_nha_cung_cap` (M8) |
| §7.2 #24 — Trạng thái công nợ NCC | `sua_phieu_nhap` trả dư → `partial`; RPC thanh toán ghi đè `overdue` | như §7.3 điểm 13 — **đã dựng M0** |
| §7.2 #25 — Giá vốn kỳ báo cáo đọc cổng | mọi phiếu `export` ghi sổ: HĐ + **trả NCC** (giá lô) + xuất lẻ (dòng giá 0) | như §7.3 điểm 36 |
| §7.2 #26 — Lô sau khi mọi gói lô bị huỷ (huỷ PN) | dòng lô giữ `qty_initial`, giá, vùng, `status 'cancelled'` | cổng `batches` ra dòng "lô chưa phát sinh" (kho bán, `qty_initial 0`, giá `npp_gia_von_lo_rong` / 0) — §7.3 điểm 35 |
| §7.2 #27 — Sửa lô ở màn | sửa MỘT dòng lô (một vùng); `UPDATE OF expires_at` chạy cả khi hạn không đổi | một Batch cho cả hai kho (M5, V82) |
| §7.2 #28 — `v_stock_movements` hiển thị | đơn vị giao dịch của dòng ("+2 thùng (= +48)") | sổ kho lõi chỉ có đơn vị cơ sở — §7.3 điểm 39 |
| **§7.3 điểm 1 — Huỷ phiếu NHÁP** (PN, PTNCC, phiếu kho, kiểm kê) | giữ dòng `cancelled` + lý do; khôi phục về nháp được (mig 241) | giữ nháp + `npp_huy_luc / npp_huy_boi / npp_ly_do_huy` cho PN / PTNCC (cổng trả `cancelled`, mọi method coi như đã huỷ); Stock Entry nháp: xoá như BP (chỉ màn xuất lẻ dọn nháp hỏng) |
| **§7.3 điểm 2 — Sửa phiếu trả NCC đã xuất + điều hướng sau sửa / khôi phục** (trước M2) | POS / màn sửa: huỷ → ghi thẳng `draft` → dòng → gửi (bốn lời gọi, không cùng giao dịch) | RPC `sua_phieu_tra_ncc` MỘT giao dịch + lớp phủ `save.ts`, `purchase-returns/[id]/edit`, POS; sau sửa / khôi phục điều hướng theo `id` trả về |
| **§7.3 điểm 3 — `post_stock_import` nhánh phiếu nhập** (trước M4) | `IN-` mang hai giá: giá vốn lô và tiền nợ | dòng `rate` = giá vốn × hệ số + MỘT dòng thuế `Actual` / `Total` bù chênh tới tiền nợ (TK chờ §7.3 điểm 17); không ghi giá nhập (như nppsale); tên lô theo mã trình duyệt (`LOT-IN-…`) |
| §7.3 điểm 4 — Nhận diện tồn đầu kỳ ở `post_stock_import` | không có cờ | `entry_code` bắt đầu `DK-` → `ton_dau_ky`, `is_opening`; còn lại `nhap_kho` |
| §7.3 điểm 5 — Hạn trống khi nhập kho tay | `2099-12-31` | để trống (CFD-10 bỏ hạn giả; cổng trả `2099-12-31`); mặt hàng `has_expiry_date` mà trống — đo ở M4 |
| **§7.3 điểm 6 — Mã lô người gõ trùng** (trước M5) | nhận (mã lô không duy nhất) | chặn — câu mới `LO_TRUNG_MA: …` (BP §7.1 điểm 14) |
| **§7.3 điểm 7 — `sua_phieu_nhap` chi tiết** (trước M7) | sửa tại chỗ; ép kiểu sai → lỗi Postgres thô 22P02 | mã + câu "chỉ sửa giá" `PHIEU_DA_XUAT_CHI_SUA_GIA: …` (đề xuất); TK chênh giảm đầu phiếu / thuế ở `DCN-`; tên lô dòng mới nhánh A `<PN gốc>-<NNN>` theo MỌI Batch; ngày ghi sổ tờ amend = tờ gốc (repost); phân bổ lại tiền + trả dư nằm lại PE; ép kiểu sai → `BAD_PAYLOAD: dữ liệu phiếu sai kiểu.` |
| **§7.3 điểm 8 — Lô đã bị rà sang kho cận date chặn huỷ PN / `IN-`** (trước M5) | huỷ được (chỉ lật cờ vùng) | method huỷ trước các `CKL-` `chuyen_date_tu_dong` của đúng lô (khi lô không động gì khác) rồi mới huỷ — hoặc chấp nhận chặn |
| §7.3 điểm 9 — `DA_TRA_TIEN` gồm Bù trừ; lý do huỷ NULL | gồm `offset`; nhận NULL | gồm JE `bu_tru_ncc`; nhận NULL như nppsale (không thêm `REASON_REQUIRED`) |
| **§7.3 điểm 10 — Bù trừ (`offset`) + `method` NULL ở Ghi trả** (trước M3) | `offset` trừ thẳng `paid`; `method` NULL được | JE `CTN-` Debit Note; hết khoản giảm → `BU_TRU_KHONG_CON: NCC không còn khoản giảm để bù trừ.`; NULL / '' → tiền mặt (cổng trả `cash`) |
| **§7.3 điểm 11 — `return_date` ↔ ngày ghi sổ trả NCC** (trước M2) | kho / nợ ghi lúc bấm; `return_date` chỉ hiển thị | ghi sổ lúc bấm (như nppsale); `return_date` là trường hiển thị (`npp_ngay_tra` mới hoặc `bill_date`) |
| **§7.3 điểm 12 — Câu `HANG_DA_XUAT` với hàng theo lô** | khuyên "bật Cho phép bán vượt tồn…" | giữ mã, câu riêng: `HANG_DA_XUAT: Không huỷ được vì hàng của phiếu đã xuất bớt — %. Lập phiếu trả hàng NCC hoặc phiếu điều chỉnh kho.` |
| §7.3 điểm 13 — Trạng thái công nợ NCC | trả dư sau `sua_phieu_nhap` → `partial`; các RPC thanh toán ghi đè `overdue` | **đã dựng M0**: MỘT luật với phải thu (BP §4.3.0, `cong_no.trang_thai`): trả dư → `open` (dư có, trừ vào tổng NCC); dấu quá hạn tay giữ tới khi đủ; RPC thanh toán không xoá `npp_qua_han_tay` |
| §7.3 điểm 14 — Ghi chú công nợ NCC | `payables.notes` = chữ hệ thống ("Phiếu nhập hàng PN-…" / "Hoàn trả NCC — phiếu …" / "Nhập kho …" / "Trả trước NCC — phiếu chi …"), sửa riêng ở `/payables/[id]` | **đã dựng M0**: Custom Field `Purchase Invoice.npp_ghi_chu_no` (AOS) tách khỏi ghi chú phiếu; trống (NULL) → bản chiếu dùng chữ hệ thống như nppsale; người dùng xoá → rỗng; dòng trả trước = "Trả trước NCC — phiếu chi <PE>"; cổng dựng chuỗi "Phiếu chi …" cho dòng chi (M3). Lệch nhỏ: tờ amend (khôi phục) chép ghi chú cũ (nppsale lập dòng nợ mới mang chữ hệ thống); ghi chú dòng trả trước chưa sửa riêng được |
| **§7.3 điểm 15 — Kiểm kê chi tiết** (trước M6) | `shrink_value` một giá / dòng; thừa vào lô hạn xa nhất; giờ `ALREADY_POSTED` UTC; toast in mã trình duyệt | `shrink_value` theo luật nppsale (sổ kho đúng từng lô); kho nhận thừa = nơi lô có tồn lớn nhất, không đâu có → `npp_kho_tao`; `basic_rate` = giá lô hiện tại; khoá số tiền phiếu chi hao hụt; giờ VN; cổng trả `entry_code` = tên Frappe (toast lệch — chấp nhận) |
| §7.3 điểm 16 — DocType chưa có | — | `NPP Cong No NCC` **đã dựng M0**; `NPP Kiem Ke` (+ `Dong`), `NPP Danh Muc Chi Phi`, `NPP Phieu Chi` ở M6 |
| **§7.3 điểm 17 — Tài khoản kế toán app tự lập** (BP §7.1 điểm 16) | — | bảng TK mặc định theo TT200, kế toán duyệt một lần (đề xuất BP); M0 chỉ trỏ `tk_thue_dau_vao` = TK thuế GTGT đầu vào của mẫu "VAT n%"; TK giảm đầu phiếu nhập (M1), xuất lẻ / nhập không HĐ (M4), thừa kiểm kê (M6), trung gian sửa giá (M7), nợ lập tay (M3) lập ở mốc dùng; chênh giá trả NCC ↔ giá lô vào `Company.default_expense_account` của lõi (đo M0) |
| §7.3 điểm 18 — Gộp NCC | — | đổi `npp_loai` tờ `DKN-` (db_set sau ghi sổ), dồn trùng `NPP Nhan Vien Cong Ty`, dựng `da_chuyen` như §3.13 (M8) |
| §7.3 điểm 19 — Hệ số quy đổi dòng PN / PTNCC | tin hệ số trình duyệt gửi | **đã đo M0**: lõi GIỮ hệ số dòng (thùng ×20 dù danh mục ×24) và nhận đơn vị không khai trong `Item.uoms` — như nppsale, không cần gán lại (`test_do_kho_mua`) |
| §7.3 điểm 20 — Xoá lô đã có lịch sử | 23503 khoá ngoại thô | trả đúng câu 23503 của nppsale |
| §7.3 điểm 21 — Che giá vốn ở `bao_cao_ton_kho`, dòng phiếu kho, `v_stock_movements`, đơn giá dòng phiếu nhập | chỉ che ở giao diện | che theo `inventory.cost` như cổng `batches` |
| **§7.3 điểm 22 — `refresh_warehouse_zones` không kiểm vai** | NVBH gọi được | giữ như nppsale (chỉ chuyển lô theo luật — vô hại) |
| **§7.3 điểm 23 — Dòng SL ≤ 0, giá 0, giá / giảm âm ở phiếu nháp** (trước M1) | máy chủ không chặn (K12, V25) | cổng ghi nháp chặn bằng câu của `sua_phieu_nhap`: `SO_LUONG_KHONG_HOP_LE: Dòng % có số lượng không lớn hơn 0.` / `GIA_KHONG_HOP_LE: Dòng % có giá / giảm giá âm.` — **đo M0: lõi từ chối PI nháp có dòng SL 0** (phiếu nhập "Quantity … cannot be zero", tờ trả có kho "'0' qty Items are not allowed") nên buộc chặn ở cổng |
| §7.3 điểm 24 — `payables_summary(p_since)` chuỗi không múi giờ | hiểu UTC | hiểu giờ VN |
| §7.3 điểm 25 — `so_chung_tu_ncc` | thủ kho thấy `con_no` (definer); nhãn `supplier_payments` thô | giữ y nppsale |
| §7.3 điểm 26 — `INSUFFICIENT_STOCK \|` (trả NCC) in "còn" SAU khi trừ | gần như luôn `0.000000` | chép y nguyên (giao diện tách theo `\|`) |
| §7.3 điểm 27 — Chỗ nppsale không dồn trả trước | gộp NCC, `sua_phieu_nhap` tăng nợ, sửa số nợ đầu kỳ, Ghi trả | giữ y; riêng sửa số đầu kỳ (tờ `DKN-` amend là tờ mới ghi sổ) → GỌI dồn (nợ ròng không đổi). M0: `don_tra_truoc_ncc` do method gọi tường minh, KHÔNG gắn doc_events (thứ tự với phân bổ lại tiền của sửa / huỷ PN do method quyết) |
| **§7.3 điểm 28 — Cột `stock_entry_lines.created_at`** | không có (nút Excel một phiếu hỏng 42703) | không thêm (giữ hành vi) — hoặc thêm để nút Excel chạy |
| §7.3 điểm 29 — Nhãn đơn vị `MIN(unit_name)` trong `KHONG_DU_TON` | sai đơn vị với số cơ sở | chép y nguyên |
| §7.3 điểm 30 — `return_date` / ngày màn điện thoại theo ngày UTC | `toISOString` | cổng mặc định hôm nay VN; lớp phủ không cần |
| §7.3 điểm 31 — Hành vi lõi cần đo | — | **đã đo M0 (phần PI)**: PI nháp dòng SL 0 bị từ chối; huỷ tờ trả NCC vào lô `disabled` VẪN ĐƯỢC (hàng về lô đang tắt — method mở lại lô như mig 235); tờ trả NCC độc lập xuất theo GIÁ LÔ (`incoming_rate` của gói lô / `valuation_rate` SLE), chênh với giá trả vào `default_expense_account`, `PI Item.valuation_rate` = giá trả (cổng đọc sổ kho — S2). Chuyển kho giữ giá lô: đo ở M4 (V47) |
| §7.3 điểm 32 — Kịch bản vùng ① / ④ chưa chạy trên nppsale | — | chạy khi dựng `tools/vang_kho_mua.py`; sửa kỳ vọng nếu lệch |
| §7.3 điểm 33 — Dữ liệu cũ (phiếu `completed` thiếu `stock_entry_id` / `payable_id`, lô `cancelled` còn tồn, mã `XK-` trùng) | — | đếm trên sổ thật trước P8 |
| **§7.3 điểm 34 — `sua_phieu_nhap` đổi NCC khi phiếu đã có tiền trả** (trước M7) | giữ `paid` (cả tiền phiếu chi của NCC cũ) trên khoản nợ nay của NCC mới | chặn — gợi ý `NCC_DA_TRA_TIEN: Phiếu đã trả NCC % — không đổi nhà cung cấp được. Gỡ phiếu chi / Ghi trả trước.` (mã + câu chờ anh chốt) |
| §7.3 điểm 35 — Dòng cổng `batches` của Batch đã mất mọi gói lô | lô `cancelled` giữ số cũ | ghi `npp_kho_tao` + `npp_gia_von_lo_rong` lúc tạo Batch (PN, `IN-`); cân nhắc `disabled = 1` khi huỷ, bật lại khi khôi phục / amend |
| **§7.3 điểm 36 — `stock_entry_lines.unit_cost` của xuất lẻ / chuyển kho trên cổng** | dòng giữ 0 → giá vốn kỳ không tính xuất lẻ; trả NCC tính vào giá vốn | trả 0 như nppsale (giá vốn kỳ giữ số); giá trị thật ở sổ kho / GL cho P6 — kèm câu hỏi "trả NCC có nên tính vào giá vốn bán?" |
| §7.3 điểm 37 — Sửa lô: kiểm "lô đang có tồn" | theo dòng lô (một vùng) | theo cả Batch (mọi kho); vẫn ghi `npp_gia_von_lo_rong` |
| §7.3 điểm 38 — Câu khi xoá khoản nợ PN / PTNCC qua cổng | 23503 (`purchase_invoices_payable_id_fkey` / `supplier_returns_payable_credit_id_fkey`) | đúng câu 23503 của nppsale thay `NO_NCC_KHOA` |
| §7.3 điểm 39 — `v_stock_movements`: đơn vị giao dịch | có | nối SLE → dòng chứng từ qua `voucher_detail_no` |
| §7.3 điểm 40 — RPC luồng cũ chưa đăng ký (`confirm_driver_handover`) | còn hàm | đăng ký, ném `LEGACY_FLOW_REMOVED: chức năng đã gỡ` |
| §7.3 điểm 41 — POS trả NCC tìm lô của phiếu gốc bằng `LIKE '<mã PN>-%'` khi gốc là tờ amend | — | lớp phủ `loadReceiptLinesForReturn` cắt đuôi amend trước `LIKE` |
| M0 — Tờ PI lập ngoài app (Desk, không `npp_loai`) | không có | vẫn có dòng công nợ NCC (loại theo tiền tố tên rồi `is_return` / `is_opening`) để Σ dòng của NCC bằng sổ cái; khoá một-dòng-đầu-kỳ (`khoa_cho`) chỉ cho tờ app `npp_loai = dau_ky` |
| M0 — Thứ tự dồn trả trước khi hai phiếu chi cùng "lúc chi" | hoà theo uuid dòng tiền (ngẫu nhiên) | hoà theo số phiếu `PCNCC-` |
| M0 — Khám sổ công nợ NCC | `scripts/sql/kham-so-that.sql` dòng 66 / 70 / 78 / 81 / 82 | nhóm 20 (Σ dòng ≠ sổ cái theo NCC — bắt cả tiền ngoài nhóm như Ghi trả còn chưa phân bổ), 21 (dòng chiếu cũ), 22 (thiếu / mồ côi); phần còn lại của §8.1 (dòng `payable_payments`, tồn lô ↔ Bin, phiếu chi) dựng ở M9 |
| M1 — Kho của phiếu (`warehouse_zone`) | cột `warehouse_zone` của phiếu | Custom Field mới `Purchase Invoice.npp_kho_nhap` (Link Warehouse, RO) — lõi XOÁ `set_warehouse` khi các dòng khác kho (`reset_default_field_value`, `purchase_invoice.py:311`; dòng hạn ngắn vào kho cận date dù đầu phiếu chọn kho bán); cổng đọc trường này trước `set_warehouse`. Blueprint §5.9 đã thêm dòng |
| **M1 — TK giảm đầu phiếu nhập** (§7.3 điểm 17, CFD-11) | không ghi sổ | tạm lập "Chiet khau mua hang duoc huong" dưới Indirect Income (711 — thu nhập khác), `NPP Cai Dat.tk_giam_dau_phieu_nhap` trỏ vào; bộ kiểm cài đặt báo khi trống — **anh / kế toán chốt 711 hay 632** |
| M1 — Nguồn giá nhập (`source_invoice_id`) | cột riêng (khoá ngoại tới phiếu) | `Item Price.reference` = tên tờ PI, ghi SAU khi lưu (lõi `ItemPrice.before_save` đè `reference = customer or supplier`, `item_price.py:135–136`); lưu lại tay trên Desk là mất nguồn (chỉ để xem) |
| M1 — Đơn vị tính trùng chữ khác dấu | `unit_name` chữ tự do từng dòng ("thùng" ≠ "Thung") | UOM của Frappe là bản ghi, khoá `name` theo collation `utf8mb4_unicode_ci`: "thùng" và "Thung" là MỘT đơn vị, tên lưu theo bản ghi có trước (dòng phiếu, bảng giá nhập theo bản ghi ấy); bài vàng so đơn vị không phân biệt dấu / hoa thường; P8 gộp đơn vị trùng chữ trước khi chuyển |
| **M1 — Mã lô trùng lúc hoàn thành** (BP §7.1 điểm 14) | `batch_code` không duy nhất — lô thứ hai cùng mã | Batch `<PN>-NNN` đã có (vd lô gõ tay ở nhập kho) → `LO_TRUNG_MA: Mã lô <mã> đã có trong sổ — đổi mã lô ấy rồi hoàn thành lại phiếu.` (mã + câu mới — **anh chốt cùng §7.3 điểm 6**) |
| M1 — Lô sau huỷ phiếu nhập (§7.3 điểm 35) | lô `status 'cancelled'` khi tồn ≤ 0, giữ `qty_initial` / giá / vùng | Batch lập kèm `npp_kho_tao` (kho dòng) + `npp_gia_von_lo_rong` (giá vốn lô); huỷ làm lô hết hàng → `disabled = 1`, khôi phục bật lại; cổng `batches`: Batch tắt → `status 'cancelled'` (trước đây `'disabled'`); `qty_initial` của lô chưa phát sinh = 0 (§7.2 #26 — bài vàng ghi khác có chủ đích) |
| M1 — Gọi RPC trên tờ cũ của chuỗi amend | một id cho mọi lần khôi phục / sửa; danh sách phiếu nhập một dòng | complete / cancel / khôi phục nhận tên BẤT KỲ tờ nào của chuỗi và làm trên tờ CUỐI (trang cũ của `PN-0001` bấm Huỷ là huỷ `PN-0001-1`); khôi phục trả `id` = tờ còn hiệu lực. Cổng `purchase_invoices` đọc mọi tờ (đặc tả §4.2 "mọi docstatus") nên sau khôi phục danh sách / trang NCC hiện HAI dòng: `PN-0001` Đã huỷ + `PN-0001-1` Hoàn thành (báo cáo NCC, công nợ, trả NCC chỉ lấy tờ Hoàn thành — số không đổi); bấm Khôi phục ở tờ cũ báo "không còn ở trạng thái Đã huỷ" |
| M1 — Người lập / lúc lập phiếu sau khôi phục | giữ `created_by` / `created_at` | cổng `created_by` / `created_at` lấy của tờ GỐC chuỗi amend; owner thật của tờ amend (sổ lõi) = người bấm khôi phục |
| M1 — Nợ 0 đ (V05d: giảm đầu phiếu nuốt hết tiền) | dòng nợ `open` amount 0 | dòng `paid` (BP §4.3.0 — một luật với phải thu); lõi kẹp dòng Deduct còn tiền hàng + thuế (grand_total 0) |
| M1 — Ghi thẳng phiếu tạm qua cổng (BP §6.1) | RLS `FOR ALL` bốn vai, mọi cột kể cả `status` | đổi `status`, ghi cột của RPC (`receipt_code`, `completed_at`, `stock_entry_id`, `payable_id`, `cancelled_*`), đụng phiếu đã hoàn thành (trừ `notes`) / đã huỷ, ghi dòng của phiếu không còn tạm → `USE_RPC: dùng nút Hoàn thành / Huỷ phiếu / Khôi phục / Lưu sửa` (câu đề xuất); xoá chỉ tờ chưa ghi sổ; dòng SL ≤ 0 / giá / giảm âm → câu của `sua_phieu_nhap` ngay lúc lưu (V08b báo ở bước lập, không ở bước Hoàn thành); NVBH sửa / xoá → 0 dòng |
| M1 — Tiền dòng âm (giảm dòng lớn hơn SL × đơn giá) | máy chủ nhận: lô giá vốn âm, tiền hàng phiếu trừ dòng âm (`sua_phieu_nhap` "không kiểm giảm dòng > tiền hàng"); màn máy tính chỉ kẹp số HIỆN ra ("KHÔNG ĐỂ ÂM" — `lineNetOf`) mà vẫn gửi nguyên số giảm gõ (POS kẹp thật) | lõi ERPNext không ghi sổ được dòng `rate` âm (câu tiếng Anh "rate must be a positive number…", Buying Settings `allow_negative_rates_for_items` tắt — bật là đổi cả site) → chặn bằng `GIA_KHONG_HOP_LE: Dòng % có giảm giá lớn hơn tiền hàng.` (mã của `sua_phieu_nhap`, câu mới) ngay lúc lưu nháp ở cổng, và lúc Hoàn thành (nháp lọt ngoài cổng — sau mọi lỗi SL); giảm BẰNG tiền hàng (dòng 0 đ) vẫn được — anh chốt câu |
| M1 — Tiền phiếu tạm | số trình duyệt gửi (chỉ để xem, Hoàn thành tính lại) | lõi tính lại mỗi lần lưu nháp (cùng công thức §2.4, bảng thuế dựng lại) — danh sách phiếu tạm hiện đúng tiền |
| **M1 — §7.3 điểm 21 phần `purchase_invoice_lines.unit_price`** | chỉ che ở giao diện | CHƯA che theo `inventory.cost` (lệch đề xuất): POS / màn sửa nạp lại phiếu tạm từ cổng — đơn giá NULL là lưu đè giá 0 (mất giá phiếu); bốn vai mua hàng mặc định đều xem được giá vốn — **anh chốt cùng việc gác màn nhập hàng** |
| M1 — Hai lượt cùng Hoàn thành (V02c) | đọc không khoá — có thể nhập kho hai lần (suy từ mã) | khoá Bin (câu đầu) → khoá PI `FOR UPDATE` trước mọi câu đọc; lượt sau thấy docstatus 1, trả tên. Bài kiểm thứ tự câu khoá + gọi lại (không chạy hai tiến trình thật — nháp chưa commit thì tiến trình kia không thấy) |
| M1 — Ghi chú phiếu kho của phiếu nhập | "Nhập kho từ phiếu nhập hàng <mã>" (phiếu kho riêng) | phiếu kho = chính PI → ghi chú = ghi chú phiếu (`npp_ghi_chu` — §10.1 của đặc tả) |
| M1 — `DA_TRA_TIEN` khi huỷ phiếu nhập | chặn khi đã Ghi trả / bù trừ thẳng vào phiếu | chưa có ở M1 (cần phiếu `GTN-` / `CTN-` của M3) — huỷ phiếu đã trả bằng phiếu chi `PCNCC-` thì lõi gỡ phân bổ, method dồn sang khoản khác (mig 242) — có bài |
| M1 — Huỷ phiếu nhập có hàng KHÔNG lô (câu 14 B) | — (mọi hàng nppsale theo lô: so từng lô) | so `Bin` của kho với Σ SL nhập của MỌI dòng cùng (mặt hàng, kho) — một mục `HANG_DA_XUAT` cho mặt hàng (so từng dòng thì hai dòng cùng hàng mỗi dòng "đủ" mà cả phiếu thiếu, huỷ đẩy Bin âm, lõi báo NegativeStockError tiếng Anh); được âm khi mặt hàng `allow_negative_stock` + NPP `cho_ban_vuot_ton` (V12b) |
| M1 — Hàng tặng 0 đ trên phiếu nhập | lô giá 0 | dòng tiền 0 → `allow_zero_valuation_rate = 1` (lõi không thay giá dự phòng khi định giá bình quân); tờ khôi phục chép lại cờ (trường no_copy của lõi). Với cài đặt hiện tại (hàng theo lô định giá theo lô, hàng không lô FIFO) cờ không đổi số nào — giữ phòng khi đổi cách định giá |
| M1 — Hạn thanh toán của lõi trên phiếu nhập | `payables.due_date` NULL (nợ phiếu nhập không có hạn) | `due_date` + lịch thanh toán của lõi tính lại MỖI lần lưu phiếu tạm và lúc hoàn thành (= max(ngày HĐ NCC, ngày ghi sổ), hoặc theo điều khoản của NCC); hạn của app là `npp_han_thanh_toan` (trống như nppsale). Giữ lịch cũ thì sửa ngày HĐ NCC của phiếu tạm sang sau hạn cũ bị lõi từ chối "Due Date cannot be before Supplier Invoice Date" |
| **M2 — Sửa phiếu trả NCC đã xuất** (§7.2 #2, §7.3 điểm 2) | POS / màn sửa: `cancel_supplier_return` → ghi thẳng `status 'draft'` → ghi lại dòng → `complete_supplier_return` (POS "Lưu nháp" dừng sau bước 2) — giữ số + id; không cùng giao dịch: gửi hỏng là phiếu kẹt Nháp, hàng đã về kho, nợ đã xoá (K11) | RPC mới `sua_phieu_tra_ncc(p_return_id, p_reason, p_head, p_lines, p_chi_luu_nhap)` — MỘT giao dịch: phiếu đã xuất → thân huỷ (lý do `p_reason`, trống → "Sửa phiếu — lập lại"; POS gửi "Sửa phiếu từ POS — lập lại" — chuỗi nppsale) + amend `PTNCC-0001-1` theo đầu / dòng mới + thân gửi; gửi hỏng → lùi hết, tờ cũ vẫn Đã xuất; `p_chi_luu_nhap` → dừng ở tờ amend Nháp (tờ cũ Đã huỷ, hàng về kho — như nppsale). Phiếu nháp → sửa tại chỗ; phiếu đã huỷ → `PHIEU_DA_HUY: Phiếu trả NCC này đã huỷ — không sửa được. Khôi phục phiếu ở màn chi tiết trước, hoặc lập phiếu mới.` (mã mới, câu của giao diện nppsale); cửa vai như hai RPC nó gộp. Trả `{id, trang_thai}` — lớp phủ đưa màn sang `id` mới. **Số phiếu đổi đuôi `-1` — vẫn chờ anh chốt cùng §7.2 #2 (CLAUDE.md "giữ nguyên số phiếu")** |
| M2 — Ngày trả `return_date` (§7.3 điểm 11, §7.2 #17) | chỉ hiển thị; kho / nợ ghi lúc bấm Gửi | như đề xuất: `return_date` nằm ở `bill_date` của tờ (không thêm trường), mặc định hôm nay VN, sửa được khi còn nháp; ngày giờ ghi sổ = lúc bấm Gửi. Blueprint 02 §5.9 + bảng cổng sửa theo (trước ghi `return_date` = `posting_date`) |
| **M2 — Dòng tiền 0 trên phiếu trả NCC** (§3.7 bước 7 ❓, §7.3 điểm 23) | nhận (giá 0, hoặc giảm dòng = tiền hàng): lô xuất theo giá lô, nợ không có phần dòng ấy | lõi đè `rate ≤ 0` của tờ trả độc lập bằng giá vốn (`buying_controller.py:43–45, 224–242`, cả lúc lưu nháp) → nợ sai; chặn ngay lúc lưu dòng (và lúc Gửi): `GIA_KHONG_HOP_LE: Dòng % có tiền hàng bằng 0 — phiếu trả NCC phải có tiền trả lớn hơn 0.` (mã cũ, câu mới) — **anh chốt chặn hay chấp nhận** |
| M2 — Chi phí trả hàng (`discount` của phiếu trả) + thuế gõ tay | trừ vào khoản NCC phải trả lại: nợ = −max(0, tiền hàng + thuế − giảm) | bảng thuế đảo dấu (§2.4): thuế gõ tay = một dòng `Actual` −max(0, x) thay các dòng VAT; giảm = dòng `Actual` "Add" +min(giảm, \|tiền + thuế\|), mô tả "Chi phí trả hàng", vào `tk_giam_dau_phieu_nhap` (TK tạm 711 của M1 — **anh / kế toán chốt cùng dòng M1**); cổng `vat` không tính dòng ấy. Nợ khớp nppsale tới đồng (§7.2 #11) |
| M2 — Đơn vị trong câu `INSUFFICIENT_STOCK \|` | đơn vị cơ sở của sản phẩm (chữ tự do); trống → "đv cơ sở" | tên bản ghi UOM `Item.stock_uom` — chữ của bản ghi có trước (vd "Hop" thay "hộp", như dòng M1 "Đơn vị tính trùng chữ khác dấu"); bài vàng so đơn vị trong câu không phân biệt dấu / hoa thường |
| M2 — Trả NCC hàng KHÔNG lô vượt tồn (V19b — kịch bản kiểm đặc tả) | `allow_oversell` → ghi dòng không lô, tồn âm | Bin trừ phần đã lấy trong lượt; âm được chỉ khi `Item.allow_negative_stock` + `NPP Cai Dat.cho_ban_vuot_ton` (cờ tắt → `INSUFFICIENT_STOCK`), giá xuất do lõi định (giá vốn hiện có của kho); hàng theo lô luôn `INSUFFICIENT_STOCK` (CFD-05 B — V19 khác có chủ đích) |
| M2 — Giờ ghi sổ tờ trả | `now()` | `posting_time` kèm micro giây (`HH:MM:SS.ffffff`): cắt về giây thì tờ trả lập cùng giây với chứng từ nhập ngay trước nó bị lõi xếp TRƯỚC chứng từ ấy (hàng không lô báo "Valuation Rate … is required" — đo ở V19b) |
| M2 — `DA_CAN_TRU` khi huỷ phiếu trả | `payables.paid ≠ 0` trên dòng nợ âm (chỉ dữ liệu cũ) | phần đã phân bổ của tờ trên sổ thanh toán (Payment Ledger — `gia_tri_pi`) ≠ 0 → cùng câu, số in như `paid` thô; M2 chưa có lối phân bổ khoản giảm (Bù trừ `CTN-` — M3) nên bài giả lập số |
| M2 — Huỷ phiếu trả khi lô đã tắt (V20) | cộng trả về lô; lô đã đóng thì mở lại (mig 235) | bật lại Batch `disabled` của các gói lô còn hiệu lực trên tờ rồi mới huỷ (lõi vẫn huỷ được vào lô tắt — đo M0 — nhưng cổng `batches` coi lô tắt là `cancelled`); huỷ xong xếp repost như phiếu nhập |
| M2 — Khôi phục phiếu trả đã gửi rồi huỷ (V21 / V22) | về Nháp giữ id; gửi lại hỏng → Nháp + `ly_do`, phiếu còn trỏ phiếu kho cũ, `completed_*` giữ | amend `PTNCC-0001-1` nháp → gửi lại trong savepoint; hỏng nghiệp vụ (P0001) → tờ amend ở Nháp + `ly_do`, lỗi khác ném ra lùi cả lượt; tờ amend nháp giữ `npp_hoan_thanh_*` (cổng `completed_at` / `completed_by` như nppsale) nhưng `stock_entry_id` NULL (tờ mới chưa có phiếu kho — CFD-01) |
| M2 — Dãy số `PTNCC-` khi xoá nháp (V27) | xoá nháp mang số cuối → số ấy được cấp lại (trigger mig 240 lấy MAX + 1) | như nppsale: lõi lùi dãy số khi xoá tờ mang số CUỐI (`delete_doc` → `revert_series_if_last`, `frappe/model/delete_doc.py:253`) — ghi chú ⚠K "lỗ số" của đặc tả sai; xoá nháp không phải số cuối thì lỗ số (cũng đúng với `PN-` — §7.2 #1). `return_code` / `return_seq` gửi qua cổng bị bỏ qua (giao diện không gửi; chỉ V27 gửi) |
| M2 — Ghi thẳng phiếu trả qua cổng (V25 / V28, BP §6.1) | RLS `FOR ALL` mọi cột kể cả `status`; sửa dòng / về nháp / xoá phiếu đã xuất được (K25) | như phiếu nhập M1: chỉ phiếu nháp; đổi `status`, ghi cột của RPC (`stock_entry_id`, `payable_credit_id`, `completed_*`, `cancel_reason`), đụng phiếu đã xuất (trừ `notes`) / đã huỷ, ghi dòng của phiếu không còn nháp → `USE_RPC: dùng nút Gửi phiếu / Huỷ phiếu / Khôi phục` (câu đề xuất); xoá chỉ tờ nháp; NV bán hàng chỉ đọc (RLS mig 068) |
| M2 — Gọi RPC trên tờ cũ / danh sách sau sửa, khôi phục | một id; danh sách một dòng | như M1: bốn RPC nhận tên BẤT KỲ tờ nào của chuỗi amend, làm trên tờ cuối; danh sách / trang NCC hiện hai dòng (tờ cũ Đã huỷ + tờ mới); `created_by` / `created_at` lấy của tờ gốc chuỗi |
| M2 — Phiếu kho + nợ của phiếu trả | phiếu kho `XK-` riêng ghi chú "Xuất kho trả NCC — phiếu <mã> (kho: <vùng>)"; dòng `payables` âm, `invoice_number` = mã phiếu, ghi chú "Hoàn trả NCC — phiếu <mã>" | phiếu kho = chính tờ PI (ghi chú = `npp_ghi_chu` của phiếu, như M1); dòng `NPP Cong No NCC` âm theo `grand_total` (`so_hd_ncc` = `bill_no` hoặc tên tờ, cùng ghi chú); tổng 0 (chi phí trả hàng nuốt hết — V26 R3) → `paid` (BP §4.3.0, như dòng M1 "Nợ 0 đ"); không dồn trả trước vào dòng âm |
