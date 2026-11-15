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
