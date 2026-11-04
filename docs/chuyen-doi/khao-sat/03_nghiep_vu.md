> Khảo sát tự động 04/11/2026 từ `src/lib/**`, `src/store/**`, `src/hooks/**`, `src/app/api/**` của `nppsale`. Bổ sung cho `CLAUDE.md` của nppsale (những luật đã chốt ở đó không chép lại). Tài liệu tham chiếu, không phải quyết định.

# Inventory nghiệp vụ npp.sale → ERPNext v16 (bổ sung ngoài CLAUDE.md)

Ghi chú chung:
- Tiền là VND, làm tròn về đồng (`Math.round`).
- Ngày tính theo giờ VN (UTC+7, `vnDateKey`).
- Logic thật nằm ở RPC SQL (`supabase/migrations/*.sql`); client chỉ tính trước để hiển thị.

Năm điểm đáng chú ý nhất cho việc chuyển sang ERPNext:
- **Không còn bước duyệt đơn.** Đơn đi Nháp → Phiếu tạm → Hoàn thành / Đã huỷ. Ngưỡng duyệt và hạn mức chỉ sinh câu cảnh báo.
- **Giá vốn theo từng lô, không bình quân.** Mỗi dòng phiếu nhập là một lô có giá vốn theo đơn vị cơ sở; bán lấy FIFO theo ngày nhập, chỉ kho bán; bán âm phụ thuộc `organizations.allow_oversell`.
- **Khuyến mãi và hoa hồng chỉ là cấu hình.** Không có chỗ nào áp khuyến mãi ở POS; không có gì ghi `commission_wallets`.
- **Lương vẫn tính theo đơn hàng** (`sales_orders.total`), trái luật doanh thu theo hoá đơn của CLAUDE.md — khoảng trống đã biết, không phải thứ để chép.
- **Logic máy chủ quan trọng ngang logic trình duyệt.** Phần lớn hành vi nằm ở RPC SQL (§20).

## 1. Bán hàng / POS / Đơn hàng

**Trạng thái đơn** (`sales_orders.status`, `src/lib/constants.ts:101`):

| Trạng thái | Nhãn | Ghi chú |
|---|---|---|
| `draft` | Nháp | |
| `submitted` | Phiếu tạm | |
| `completed` | Hoàn thành | |
| `cancelled` | Đã huỷ | |
| `partially_invoiced` | Hoàn thành | Di sản; hiện chung nhãn Hoàn thành |
| `closed` | Đã đóng | Di sản |

Chuyển trạng thái:
- Nháp ↔ Phiếu tạm khi lưu. `decideStatus` (`src/lib/sell/submit.ts:33`): lưu nháp → `draft`, còn lại luôn → `submitted`.
- Phiếu tạm → Hoàn thành qua `post_invoice`.
- Hoàn thành → Đã huỷ qua `cancel_invoice`.
- Đơn chưa xuất huỷ qua RPC `cancel_order`.

Không còn bước duyệt:
- `evaluateApproval` (`src/lib/approval.ts:96`) chỉ sinh câu cảnh báo, ghi vào `sales_orders.approval_reason`.
- Ngưỡng nằm ở `approval_rules`, mặc định: `auto_approve_max` = 20.000.000 · `manager_approve_max` = 50.000.000 · `customer_debt_max`, `customer_overdue_max`, `rep_portfolio_debt_max` = 0 (0 = tắt) · `enforce_credit_limit` = true.
- Các quy tắc cảnh báo: (1) `total ≥ auto` → "soát kỹ"; `total ≥ manager` → "chủ NPP nên xem". (2) Nợ khách > `customer_debt_max`. (3) Nợ quá hạn > `customer_overdue_max`. (4) Tổng nợ danh mục của NV > `rep_portfolio_debt_max`. (5) `nợ hiện tại + total > credit_limit` (khi `credit_limit > 0`). (6) Chiết khấu sâu: `pct = (gross − subtotal)/gross × 100`; ≥ 30% → manager, ≥ 50% → owner (hằng số trong code, `approval.ts:66`).
- Đọc ngữ cảnh lỗi → vẫn `submitted` kèm câu "NPP kiểm tay".

**Hạn mức tín dụng ở POS** (`components/pos/order-screen.tsx:911`): `vuotHanMuc = nợ + due − credit − credit_limit`; chỉ cảnh báo, không chặn; `credit_limit = 0` nghĩa là không đặt; chưa đọc được nợ thì im.

**Ai sửa / xoá đơn được:**
- Sửa (`src/lib/orders/edit-permission.ts`): cần `orders.update`; trạng thái không cuối (`TERMINAL_STATUSES` = partially_invoiced / completed / closed / cancelled); NVBH chỉ sửa đơn có `sales_user_id = mình` và ở `draft` / `submitted`; sửa đầy đủ dòng chỉ ở `draft` / `submitted`; trigger `guard_order_lines_locked` ném `ORDER_LOCKED`.
- Xoá (`src/lib/orders/delete.ts:23`): owner / manager: đơn `draft` hoặc `cancelled`; sales: đơn `draft` của mình.

**Lập đơn:**
- RPC `create_order_with_lines(client_request_id, order, lines, returns, return_lines)` (`src/lib/orders/create.ts:127`), idempotent theo `client_request_id`.
- Mã đơn `DH-0001`; số đệm ≥ 4 chữ số (`_so_chung_tu`, mig 237); lần sửa / lập lại thêm hậu tố `-n`.
- `payment_terms` mặc định `COD`.
- Dòng đơn (`src/lib/sell/create-order.ts:72`): `unit_price` = `netPriceOf` (giá sau giảm dòng, quy về đơn giá) · `line_discount` = `max(0, round(qty × (listPrice − price)))` (chỉ ghi nhớ, không trừ lần nữa) · `line_total` = `round(qty × unit_price)` · `conversion_factor` chụp lúc lập · `vat_rate` theo dòng.
- `subtotal` = sau giảm đơn, trước thuế. Hàng trả kèm đơn tạo `returns` với status `draft`.

**Giá bán** (`src/lib/sell/pricing.ts:25`, `unitPriceFor`), xét theo thứ tự: (1) `price_lists` theo (`unit_name`, `group_id` = nhóm khách); (2) `price_lists` chung (`group_id` null); (3) đơn vị cơ sở → `products.sell_price`; (4) đơn vị khác → giá cơ sở × `conversion`; (5) không có → 0 = "chưa có giá".
- `effective_from` / `effective_to` của `price_lists` KHÔNG được xét.
- Đổi đơn vị dòng bán thì tra lại bảng giá, không nhân hệ số (`src/lib/pos/units.ts:42`). Đổi đơn vị theo hệ số chỉ dùng cho giá vốn / dòng trả theo HĐ: `round(price / hsCũ × hsMới)`. Hệ số không tra được → 1.

**Sửa giá** (`src/lib/pricing.ts:3`, `src/lib/sell/cart.ts:303`): cột `users.allow_price_edit` và `price_edit_max_increase_pct`; sàn = giá bảng (`below_list`); trần = `round(list × (1 + pct/100))`; owner / accountant = `free`; mẫu quyền `sales_flex` = +10% (`src/lib/permission-templates.ts`).

**Giảm giá** (`src/lib/pos/discount.ts`): mỗi dòng `{value, unit: vnd|pct}`; `lineGross = round(qty × price)`; `discountAmount = clamp(round(pct ? g × v/100 : v), 0, g)`; đổi đơn vị nhập giữ nguyên số tiền (pct giữ 4 số lẻ); đang `%` mà đổi SL → tiền giảm chạy theo, đang `₫` → đứng yên; giảm cả đơn tính `%` trên tiền GỘP (trước giảm dòng), kẹp ≤ tiền sau giảm dòng. Trần theo người (`kiemGiamGia`): cần `allow_discount`; `discount_max_type` pct|vnd, `discount_max_value` (null = không giới hạn); áp riêng từng dòng (so tiền dòng) và cho đơn (so tiền gộp); pct: `floor(g × min(100, v)/100)`; khoản giảm có sẵn (`giamGoc`) không bị chặn nếu không tăng.

**Thuế** (`src/lib/pos/vat.ts`, `src/lib/pos/totals.ts`): VAT theo DÒNG; nút VAT cấp chứng từ chỉ đặt hàng loạt; bậc bấm vòng 0 → 5 → 8 → 10 → 0 (`VAT_RATES`); mặc định sản phẩm 0% (`DEFAULT_VAT_RATE`); dòng mới lấy theo thuế chung của giỏ nếu đang đồng nhất.

**Tổng chứng từ POS** (`posTotals`): `due = gross − lineDisc − docDisc + vat + other − returnCredit`; `vat = round(Σ (g − giảm dòng) × rate)`; giảm đơn không hạ nền thuế; `due` kẹp ≥ 0, phần âm thành "ghi có" (công nợ âm).

**Tổng ở /sell** (`cartTotals`, `src/lib/sell/cart.ts:248`): `grandTotal = max(0, round(subtotal + vat − returnCredit))`.

**Tổng hoá đơn** (`invoiceTotals`, `src/lib/orders/post-invoice.ts:98`): `subtotal = round(Σ qty × price − giảm)`; `vat = round(Σ line × rate)`; `total = round(subRaw − giảm + vatRaw)` — làm tròn ở tổng, không ở dòng. Giảm giá đơn suy ngược khi đọc (`src/lib/pos/invoice-discount.ts`): `giam = Σ(qty × price) − subtotal`; ≤ số dòng thì coi là sai số làm tròn, bằng 0.

**Gợi ý tiền mặt** (`cashSuggestions`): đúng số phải trả, rồi làm tròn lên theo bậc 10k / 50k / 100k / 500k / 1tr, tối đa 3 chip.

**Tồn khả dụng** (`src/lib/sell/committed.ts`): `available = tồn kho bán − committed`; `committed` từ RPC `committed_stock_by_product` (dòng của Phiếu tạm chưa xuất, đơn vị cơ sở, toàn NPP); không kẹp 0; chưa đọc được → committed = 0. Kiểm tồn khi soạn (`src/lib/orders/stock-check.ts`): quy về đơn vị cơ sở, cộng dồn các dòng cùng mặt hàng, hàng ĐỔI tính vào nhu cầu. Tồn hiển thị theo đơn vị đang chọn: `floor(base / conv)`.

**Hàng đổi trả kèm đơn / hoá đơn:** dòng trả (`return_lines.is_exchange = false`) trừ nợ; dòng ĐỔI ra khỏi kho, giá 0, không trừ tiền. Lúc xuất HĐ, dòng HĐ hàng đổi được dựng lại từ khối hàng đổi (`dongHangDoi`, `src/lib/pos/invoice-exchange.ts`): `unitPrice 0`, `vatRate 0`, `note "[Exchange]"`. Đổi quy cách dòng trả: `giá × hsMới / hsCũ`, làm tròn 2 số lẻ. `post_invoice` nhận `return_adds` / `return_edits` (`src/lib/orders/post-invoice.ts:374`).

**Giá dòng trả** (`src/lib/sell/returns.ts:150`): hạ giá luôn được (kể cả về 0); trần = giá tham chiếu × (1 + `price_edit_max_increase_pct`) — cùng thẩm quyền với giá bán.

**Lưu theo màn:** giỏ /sell ở `localStorage` khoá `npp.sell.cart.v1`. POS: tab ở `npp.pos.tabs.v1`, tối đa 8 tab, loại `SO` / `INV` / `RET` / `PUR` / `PRET` (`src/lib/pos/tabs.ts:17`); cài đặt ở `npp.pos.settings.v1` (`src/store/pos/settings.tsx`): cột hiển thị, đơn vị giảm mặc định `vnd`, `showLastPrice`, `suggestCash`, `mergeDuplicateLines`, `defaultCreditAll = true` (bán sỉ mặc định ghi nợ). Phiên đang làm dở (`workflow_sessions`, `src/lib/workflow/sessions.ts`): `entity_type` = `sales_order` / `stock_entry` / `delivery` / `driver_handover`; lưu `stage`, `last_url`, `form_draft`. Khoá sửa đồng thời (`entity_locks`): RPC `acquire_entity_lock` / `heartbeat_entity_lock` / `release_entity_lock`, nhịp 60 s (`src/hooks/use-entity-lock.ts:29`).

**Màn phụ:** Đặt lại đơn (`/sell/reorder/[id]`): chép dòng sang đơn MỚI theo bảng giá HÔM NAY; hàng ngừng bán thì bỏ và báo ra. Hàng hay lấy (`src/lib/orders/frequent-products.ts`): 90 ngày, ≤ 150 đơn, xếp theo SỐ ĐƠN có mặt hàng. Quét mã: chặn trùng cùng mã trong 1.500 ms (`SCAN_DEDUPE_MS`, `src/lib/sell/scan.ts`). Ngày giao: chip theo lịch VN. Đổi người đứng tên HĐ / phiếu trả: RPC `assign_doc_seller(p_kind, p_id, p_user)` (`src/lib/pos/save.ts:619`).

**Offline:** đơn lập lúc mất mạng xếp vào hàng chờ với `targetStatus` đã quyết sẵn (xem §15).

## 2. Hoá đơn bán

**Trạng thái** (`sales_invoices.status`): `posted` | `cancelled` — không có nháp. Mã `HD-0001`.

**Xuất hàng:**
- RPC `post_invoice(p)` (`src/lib/orders/post-invoice.ts:374`). Tải trọng: `order_id`, `invoice_date`, `payment_terms`, `notes`, `lines[]` (`order_line_id`, `product_id`, `unit_name`, `conversion_factor`, `quantity`, `unit_price`, `line_discount`, `vat_rate`, `is_exchange`, `note`), `discount`, `return_adds`, `return_edits`. Trả về: `invoice_id`, `invoice_code`, `entry_id` (phiếu xuất kho), `receivable_id`, `short_qty`, `near_expiry_skipped`, `order_status`.
- Dòng SL 0 bị lọc ở client. Dòng cần xuất đọc qua `get_invoiceable_lines(p_order_id)` (GET): `ordered`, `invoiced`, `remaining`, `availableBase` (chỉ tồn kho bán).
- Đơn xuất được khi trạng thái thuộc `DON_CON_XUAT_DUOC` = `submitted` / `partially_invoiced`.
- Hạn nợ: `due_date = invoice_date + N`, N từ `_wf2b_payment_terms_days`, tức `NET(\d+)` của `payment_terms` (`COD` = 0). Danh sách điều khoản: `COD`, `NET7` / `15` / `30` / `45` / `60` (`src/lib/constants.ts:32`).
- Cảnh báo sau xuất (`invoiceWarnings`): thiếu `short_qty` đơn vị cơ sở mà vẫn xuất (khi `allow_oversell`); FIFO bỏ qua lô cận hạn hơn `near_expiry_skipped` lần.
- Mã lỗi (`explainInvoiceError`): `INSUFFICIENT_STOCK`, `ORDER_NOT_INVOICEABLE`, `NO_LINES`, `HAS_INVOICE`, `ORDER_LOCKED`, `INVOICE_NOT_POSTED`, `LOCKED_HAS_PAYMENT`, `LOCKED_EINVOICE`, `LOCKED_RETURN_DONE`, `REISSUE_RETURN_STOCKED`, `REISSUE_BREAKS_RETURN`, `RETURN_NEEDS_INVOICE`, `REASON_REQUIRED`, `FORBIDDEN_NOT_OWNER`, `USE_RPC`, `ORDER_CLOSE_REMOVED`.

**Giao thiếu:** vẫn chỉ một HĐ; phần thiếu bỏ, đơn → Hoàn thành.

**Sửa HĐ:** RPC `reissue_invoice(p_invoice_id, p)`: huỷ tờ cũ, lập tờ mới mã `-n`, chuyển MỌI phiếu thu của tờ cũ sang tờ mới; `discount` vắng mặt → giữ giảm giá đơn của tờ cũ; `tra_da_nhap` = `lam_lai` | `giu`; HĐ phải còn ≥ 1 dòng; bị khoá nếu đã phát hành HĐĐT (`reissueLock`, `src/lib/pos/invoice-edit.ts:50`).

**Huỷ HĐ:** RPC `cancel_invoice(p_invoice_id, p_reason)` — bắt buộc có lý do; hoàn kho về đúng lô đã lấy (`stock_line_consumptions`), xoá công nợ; đơn → `cancelled`; phiếu trả Nháp / Chờ xử lý → huỷ; trả về `import_entry_id`; bị chặn nếu đã có tiền thu (`LOCKED_HAS_PAYMENT`) hoặc đã phát hành HĐĐT.

**Vai được thao tác HĐ:** `src/lib/invoices/roles.ts`.

**In:** trang `/in/hoa-don/[id]`, `/in/don-hang/[id]`, `/in/tra-hang/[id]`, khổ A5. Thành phần trong `src/components/printing/`: `sales-invoice`, `return-slip`, `payment-receipt-tt200` (phiếu thu mẫu TT200), `payslip`, `delivery-slip`, `driver-list`. Đầu chứng từ lấy `organizations.name` + `settings.address` / `phone` / `tax_code` (`src/lib/org/header.ts`). Giờ trên tờ in ghim theo VN (`src/lib/printing/doc-stamp.ts`). Tiền bằng chữ: `src/lib/utils/number-to-vn-words.ts`.

**Excel:** danh sách (`src/lib/xuat-excel/cac-man.ts`): cột "Tổng tiền" HĐ = số còn lại sau hàng trả, kèm cột tiền gốc + hàng trả. Một phiếu "như mẫu in" (`src/lib/xuat-excel/mau-in.ts`, `mot-phieu.ts`): 8 loại chứng từ. Giá vốn chỉ xuất khi có quyền `inventory.cost`.

**HĐĐT MISA:**
- Bảng `invoices` (khác `sales_invoices`). `ensureEInvoiceRow` tạo theo `sales_invoice_id`, status `draft`; tiền lấy từ HĐ bán (`src/lib/einvoice/publish.ts`).
- Cấu hình `company_einvoice_config`: `api_base`, `tax_code`, `username_enc` / `password_enc` (mã hoá, `src/lib/crypto.ts`), `token_path`, `publish_path`, `seller_name`, `seller_address`, `sandbox`, `is_active`; tham số MISA: `misa_company_id`, `misa_org_unit_id`, `misa_template_id`, `misa_user_id`, `misa_inv_series`, `misa_inv_template_no`, `invoice_type`, `is_inherit_from_old_template`, `misa_is_invoice_with_code`; `test-connection` tự lấy các tham số MISA; quyền: owner / accountant.
- `POST /api/einvoice/publish {invoiceId, mode: as_sold|box, poNote}`: quyền owner / accountant / manager. Mapper (`src/lib/misa/mapper.ts`): `AmountOC = qty × giá BẢNG`, rồi trừ `DiscountAmount` — phải cộng ngược `line_discount/qty`. Ghi `einvoice_logs`.
- `misa_status`: `pending`, `sent`, `waiting_code`, `signed`, `replaced`, `cancelled`, `amount_mismatch`, `error` (`src/lib/misa/labels.ts`). Suy trạng thái (`deriveState`, `src/lib/misa/status.ts`): đã huỷ → `cancelled`; `EInvoiceStatus` 7 (bị thay thế) → `replaced`; số HĐ rỗng / `<…>` → `sent`; `PublishStatus` = 3 → `signed`, = 0 → `sent`; đơn vị dùng HĐ có mã và có `InvoiceCode` → `signed`; không chắc → giữ nguyên. Quan hệ `EInvoiceStatus`: 1 new, 3 replacement, 4 adjustment, 7 replaced, 8 adjusted (vẫn hiệu lực). Gặp `OrgRefID` của bản thay thế → đánh dấu tờ gốc `replaced` (`src/lib/misa/mark-replaced.ts`).
- `refresh-status`: một HĐ, người bấm. `sync`: cron, quét theo lô, Vercel giới hạn 60 s. `pull-snapshots?days=60`: kéo danh sách MISA vào `misa_invoice_snapshots`, trần 300 trang × 100.
- Đối soát 4 tầng (`src/lib/misa/reconcile.ts`): chắc chắn: `ref_id` → `transaction_id` → `inv_no` (ký hiệu + số); cần review: `inv_no_loose` (bỏ mẫu số), `tax_date_amount`. `match_status`: `matched`, `needs_review`, `amount_diff`, `misa_only`, `cancelled`, `replaced`. `reconcile-action` (`link` / `unlink` / `create`) đặt `match_method = 'manual'`; máy không ghi đè. Sổ đọc không hết thì không hạ cấp liên kết đã khớp.

## 3. Trả hàng (khách)

**Trạng thái:** `draft` (Nháp), `submitted` (Chờ xử lý — chỉ phiếu tự sinh), `completed` (Đã nhập kho), `cancelled`. Mã `PT-xxxx`.

**Ma trận hành động** (`hanhDongPhieuTra`, `src/lib/returns/loai-phieu.ts:47`):

| Loại phiếu | Trạng thái | Hoàn thành | Huỷ | Sửa | Ghi chú |
|---|---|---|---|---|---|
| Tự sinh (`credit_with_invoice`) | submitted | Được | Không | Không | Sửa ở HĐ |
| Tự sinh | completed | — | Huỷ = về Chờ xử lý | Không | |
| Tự sinh | draft rỗng (0 dòng) | — | Huỷ hẳn | Không | |
| Theo đơn (draft, có `order_id`, chưa có `invoice_id`) | draft | Khoá | Khoá | Khoá | Sửa ở đơn |
| Tự lập | draft | Được | Được | Được | |
| Tự lập | completed | — | Được | Được | |

- Đường "Sửa" (`duongSuaPhieuTra`): tự sinh → `/sales-invoices/<id>/edit`; theo đơn → `/pos/don-hang/<id>`; tự lập → `/pos/tra-hang/<id>`.
- Hoàn thành: `complete_return(p_return_id, p_zone sale|date, p_ngay?)`: người duyệt PHẢI chọn kho nhận; `p_ngay` (ngày nhập kho) chỉ cho phiếu tự sinh; tạo phiếu nhập với `notes` = `Nhập lại từ phiếu trả <id>`; giá vốn theo lô.
- Huỷ: `cancel_return(p_return_id, p_reason)`; phiếu đảo mang đuôi "(đã đảo)". Lưu từ POS: `save_pos_return`. Lập phiếu: `create_return_with_lines`.
- Đổi ngày phiếu (`loiDoiNgayPhieuTra`): phiếu chưa huỷ, không sau hôm nay. Phiếu tự sinh: nợ / doanh số vẫn theo ngày HĐ.
- Quyền (`src/lib/sell/return-roles.ts`): sửa: owner / manager mọi phiếu, sales phiếu draft của mình; xoá: chỉ phiếu draft (owner / manager, hoặc sales của mình); hoàn thành / huỷ cần `returns.approve`: owner, manager, warehouse.
- Tổng phiếu trả (`returnTotals`, `src/lib/pos/return-totals.ts:56`): `goodsReturned = Σ` dòng trả; `fee` = phí trả hàng (₫ hoặc % trên tiền hàng trả); `dueToCustomer = max(0, goodsReturned − fee)`; hàng đổi không vào phép tính; `credit_note_amount` do trigger `trg_return_lines_sync_credit` cộng (bỏ dòng đổi).
- Lý do trả: `damaged`, `wrong_item`, `near_expiry`, `expired`, `refused`, hoặc chữ tự do.

## 4. Công nợ phải thu & phiếu thu

**Phiếu công nợ** (`receivables`): `amount`, `paid`, `due_date`, `status`, `invoice_id`, `return_id`, `opening_balance`, `sales_user_id`, `giao_tu_nv`; `status`: `open` / `partial` / `paid` / `overdue`, trigger quyết định (CLAUDE.md).

**Tuổi nợ** (`getAgingStatus`, `src/lib/utils.ts:142`; `src/lib/receivables/tuoi-no.ts`): `daysOverdue = hôm nay(VN) − due_date`; ≤ 0 hoặc không có hạn → `current`; 1–30 → `warning`; 31–60 → `overdue`; > 60 → `critical`; chỉ tính khoản `status <> 'paid'`. Hồ sơ khách dùng 3 ô: trong hạn / 1–30 / > 30 (`src/lib/customers/profile-stats.ts:43`).

**Báo cáo nợ:** RPC `receivables_summary`, `receivables_by_customer`, `receivables_by_rep`.

**Phiếu thu** (`cash_receipts`): trạng thái `pending` (Chờ xác nhận) → `received` (Đã nhận) → `voided` (Đã huỷ) (`src/lib/finance/cash-receipt-list.ts:25`). Lập: RPC `create_cash_receipt(p)` (`src/lib/finance/cash-receipt.ts`): `customer_id` (một phiếu một khách); `method`: `cash` / `transfer` / `ewallet` (`return_credit` / `credit_applied` chỉ do RPC tự ghi); `receipt_date`; `lines[{receivable_id, amount}]` — phân bổ do NGƯỜI chọn từng khoản; `credits[{return_id}]` (luồng cũ, nay không cấn ở phiếu thu); `use_credit`: rút số dư có, ghi bút toán hai vế; `client_key`: chống gửi trùng (mig 215, `src/hooks/use-khoa-gui.ts`). Thực thu: `cashToCollect = max(0, Σlines − Σcredits − use_credit)`. Mã lỗi: `CUSTOMER_REQUIRED`, `EMPTY_RECEIPT`, `CREDIT_EXCEEDS_SELECTED`, `BAD_RECEIVABLE_LINE` (thu vượt nợ), `BAD_CREDIT`, `CREDIT_BALANCE_TOO_LOW`, `RECEIPT_NOT_VOIDABLE`, `REASON_REQUIRED`.

**Ai làm gì:** thu tại điểm bán: NVBH (`/receivables/collect`, quyền `receivables.create`) lập phiếu `pending`, một khoản nợ mỗi lượt; thông báo `payment_received` gửi NV phụ trách khoản nợ nếu khác người thu. Xác nhận: chỉ owner / accountant, khi phiếu `pending` (`finance/cash-receipts/[id]/page.tsx:134`): ghi thẳng `payments.verified_at` / `verified_by`, rồi `cash_receipts.status = 'received'`, `received_by`, `received_at`. Huỷ: RPC `void_cash_receipt` + lý do; cần `receivables.update`, phiếu `pending` hoặc `received`; xoá `payments`, trừ lại `paid`.

**Bàn giao tiền:** không có luồng bàn giao tiền riêng. `src/lib/handover/confirm.ts` là bàn giao chuyến giao của tài xế (luồng cũ, `confirm_driver_handover`).

**Nợ đầu kỳ** (`src/lib/opening-balance/`): nhập / xuất Excel cho khách → `receivables` và cho NCC → `payables`, với `opening_balance = true`; khoá khớp chính: cột `id` (uuid), dự phòng SĐT / mã NCC; nhập lại cùng file = cập nhật (chỉ mục duy nhất mig 102); gán `sales_user_id` = NV phụ trách chính; ghi từng dòng, lỗi gom vào `failures` kèm số dòng Excel.

**Nhân viên nghỉ việc** (mig 223, `src/lib/users/nghi-viec.ts`): chưa có chứng từ → xoá hẳn; có chứng từ → `cho_nhan_vien_nghi`: đặt `left_at`, khoá; khách + công nợ chưa thu về NPP (`giao_cong_no_npp`). Trạng thái NV: `active` / `locked` (`is_active = false`) / `left`.

## 5. Mua hàng

**Phiếu nhập NCC** (`purchase_invoices`): trạng thái `draft` (Phiếu tạm) / `completed` / `cancelled`; mã `PN-0001`. Dòng (`src/lib/purchasing/receipt-form.ts`): `discount_mode` percent|vnd; `lineNet = max(0, qty × price − giảm)`; `vat = lineNet × vat% / 100`. Đầu phiếu: `discount` (₫); `vat_override` (gõ tay, thắng tổng thuế tự cộng); `total = max(0, subtotal + vat − discount)`; `warehouse_zone` sale|date người nhập chọn; `invoice_number`, `invoice_date`. Hoàn thành: RPC `complete_purchase_invoice` (mig 145): mỗi dòng sinh MỘT lô mới `batch_code = <mã phiếu>-NNN`; `unit_cost = (qty × price − line_discount) / (qty × conversion)` — giảm giá đầu phiếu KHÔNG phân bổ; `expires_at = hôm nay + shelf_life_days`, hoặc 2099-12-31 nếu không có hạn dùng; ghi nợ NCC (`payables`); trigger `trg_gia_nhap_tu_phieu` cập nhật bảng giá nhập. Sửa phiếu đã hoàn thành: `sua_phieu_nhap` (giữ lô, sửa nợ, tính lại giá vốn phần đã bán). Khôi phục phiếu đã huỷ: `khoi_phuc_phieu_nhap` (`src/lib/purchasing/khoi-phuc.ts`). Vai ghi: owner / manager / accountant / warehouse (`VAI_GHI_MUA_HANG`).

**Bảng giá nhập** (`purchase_price_lists`, mig 234; `src/lib/purchasing/bang-gia-nhap.ts`): một giá cho mỗi (mặt hàng, đơn vị); giá gợi ý theo thứ tự: giá đúng đơn vị → giá cơ sở × hệ số → quy từ đơn vị khác → `cost_price` × hệ số → 0; sửa tay qua RPC `luu_gia_nhap`.

**Gợi ý đặt hàng** (`src/lib/purchasing/reorder.ts`): `cần đặt = max(0, Σ(quantity − invoiced_qty) × conversion − tồn)` trên đơn `submitted` / `partially_invoiced`; gom theo `products.primary_supplier_id` ("Chưa gán NCC"); KHÔNG dùng `min_stock`.

**Trả NCC** (`supplier_returns`): mã (cũ) `TH-YYMMDD-HHMMSS`, nay `PTNCC-0001`; trạng thái draft → (gửi) → cancelled. `complete_supplier_return`: xuất kho FIFO theo hạn, giảm nợ NCC bằng dòng `payables` âm. `cancel_supplier_return`. Sửa phiếu đã gửi = huỷ rồi gửi lại, giữ số phiếu (`src/lib/pos/save.ts:587`). `khoi_phuc_phieu_tra_ncc`: gửi lại; kho thiếu → dừng ở Nháp kèm lý do.

**Công nợ NCC:** `payables` (`amount`, `paid`, `status`), `payables_by_supplier`. Màn hiện: Tổng nợ gộp − Hàng trả lại − Đã thanh toán = Còn lại (`src/lib/payables/theo-ncc.ts`). Loại dòng nợ: `phieu-nhap`, `tra-ncc`, `dau-ky`, `lap-tay`, `tra-truoc`.

**Trả tiền NCC:** trả một khoản: `record_payable_payment`. Phiếu chi NCC: `chi_tra_ncc(supplier, amount, paid_date ≤ hôm nay, method cash|transfer, reference)` (mig 242, `src/lib/payables/phieu-chi-ncc.ts`): máy chủ phân bổ vào khoản cũ nhất (nợ đầu kỳ trước, rồi theo ngày); phần dư thành tiền trả trước, tự trừ vào phiếu nhập sau; huỷ: `huy_phieu_chi_ncc`; vai: owner / accountant; không phải chi phí, không vào lãi lỗ.

**Đơn mua** (`purchase_orders`): `draft` / `confirmed` / `received` / `partial` / `cancelled` — chỉ còn tra cứu.

## 6. Kho

**Lô** (`batches`): `qty_initial`, `qty_on_hand` (đơn vị cơ sở), `unit_cost` (mỗi đơn vị cơ sở), `expires_at`, `warehouse_zone` sale|date, `status`. Tự chuyển sang `date` khi `expires_at ≤ hôm nay + date_warehouse_threshold_days` (mặc định 30, cột `pricing_rules`; trigger `batches_auto_zone`, mig 028); không tự quay về `sale`; chuyển vùng: `refresh_warehouse_zones` hoặc phiếu chuyển kho `post_stock_transfer`.

**Giá vốn:** theo LÔ thực tế (mỗi phiếu nhập một lô), không có bình quân gia quyền. COGS mỗi lần xuất = Σ lấy × `unit_cost` của lô, lưu trong `stock_line_consumptions`.

**Chọn lô khi bán:** FIFO theo `received_at`, `created_at`, `id`, chỉ vùng `sale` (mig 138); không phải FEFO; đếm `near_expiry_skipped` khi bỏ qua lô hạn gần hơn; trả NCC thì xuất theo hạn cũ trước.

**Bán âm:** `organizations.allow_oversell` (cờ ở `/settings/org`). Tắt → `INSUFFICIENT_STOCK`, kèm câu báo nếu hàng đang nằm ở kho date. Bật → ghi sổ và trả `short_qty`.

**Phiếu kho** (`stock_entries.type`): `import` / `export` / `transfer` / `stocktake`; trạng thái `draft` / `posted` / `cancelled`. Nhập: `post_stock_import` — một giao dịch, gồm cả tồn đầu kỳ với `posted_at` lùi ngày. Xuất lẻ có vùng: `post_stock_issue` — trừ đúng vùng, không có giá, giá trị = giá vốn FIFO; quét trùng mặt hàng → "Đã có trên phiếu". Xuất cũ: `post_stock_export`. Chuyển kho: `post_stock_transfer`. Huỷ: `cancel_stock_entry` (hoàn kho cùng giao dịch). Duyệt phiếu nháp (`src/lib/inventory/approve-entry.ts`): nhập nháp không ghi sổ được.

**Kiểm kê:** lập ở `/inventory/stocktake`; dòng lưu chênh có dấu (đơn vị cơ sở; + thừa, − hụt). Chờ duyệt (draft) → `post_stock_adjustment(p_entry_id)` (mig 123): hụt trừ lô theo FEFO; giá trị hụt ghi `expenses` (trả `shrink_value`, `expense_id`); thừa phải có giá vốn (`coThuaChuaGiaVon`); dòng 0 bỏ qua. Từ chối: `reject_stock_adjustment`. Chênh = `actual − system`; giá trị = chênh × giá vốn lô (`src/lib/inventory/kiem-ke-mobile.ts`).

**Soạn hàng** (`/inventory/soan-hang`, mig 225, `src/lib/orders/luot-soan.ts`): chọn HĐ đã ghi sổ, tối đa 26 HĐ (rổ A–Z); nhặt tổng theo kệ (`shelf_location`) hoặc NCC, rồi chia vào rổ; RPC `tao_luot_soan`, `cap_nhat_luot_soan`, `hoan_tat_luot_soan`, `huy_luot_soan`, `danh_dau_soan_hang`; không trừ kho; thiếu hàng ghi "báo để sửa HĐ"; vai: owner / manager / warehouse / accountant.

**Thẻ kho:** `/inventory/stock-card/[productId]` (`src/lib/inventory/the-kho.ts`): chuyển kho không đổi tồn tổng; lịch sử theo kho: view `v_stock_movements` (chuyển kho: − kho nguồn, + kho đích); tồn sau cộng dồn từ giao dịch đầu tiên.

**Tồn kho hiện tại:** RPC `ton_kho_trang` (gộp vùng, phân trang); giá trị = Σ `qty_on_hand × unit_cost`. Tổng giá trị: `stock_value_summary`. **Tra soát** (`/inventory/audit`): toàn bộ mã hàng × tồn × giá trị từ `batches`.

## 7. Khách hàng

**Trường** (`src/types/index.ts:200`): định danh: `store_name`, `owner_name`, `phone` (UNIQUE `org_id` + `phone`, đã chuẩn hoá); địa chỉ: `address`, `province`, `district`, `ward` (danh mục phường Hải Phòng `src/lib/constants/wards-hai-phong.ts`); `channel`: lưu MÃ TUYẾN `sales_routes.code`, không phải GT / MT; thương mại: `group_id` (→ bảng giá), `credit_limit`, `payment_terms`, `status` (`active` / `suspended` / `locked`; POS không thấy chặn theo status); vị trí / ảnh: `gps_lat`, `gps_lng`, `photo_approved_at`, `route_reminder_sent_at`; xuất HĐ: `billing_name`, `tax_code`, `billing_address`, `billing_email`, `payment_method_label`.

**Phân công** (`customer_assignments`: `user_id`, `role` primary|secondary, `status`): NVBH tạo khách → tự nhận qua `claim_customer_for_me` (chỉ vai sales; đã có primary thì làm secondary); owner / manager tạo khách → không tự gán; gán NV làm chính → `giao_cong_no_npp` chuyển nợ NPP đang giữ.

**Tuyến:** `sales_routes` (`code`, `name`, `description`, `is_active`, `sort_order`); gõ ngắn không dấu ≤ 12 ký tự → hiểu là mã tuyến (`src/lib/customers/tuyen.ts`).

**Lịch đi tuyến (PJP):** `pjp_routes` (`sales_user_id`, `day_of_week` 0–6, `customer_id`, `visit_order`, `is_active`) — lịch tuần lặp, không có tuần chẵn / lẻ.

**Ghé thăm** (`visit_logs`): `visit_date`, `check_in_at`, `check_in_lat` / `lng`, `result` (`order_placed` / `no_order` / `closed` / `not_visited`), `notes`; không chụp ảnh khi đi tuyến; khoảng cách Haversine tới GPS khách: > 100 m cảnh báo, > 500 m hỏi xác nhận (bỏ qua khi `not_visited`); thông báo `visit_logged` gửi NV chính nếu khác người ghé.

**Ảnh điểm bán** (`src/lib/customers/photos.ts`): tối đa 3 ảnh / khách; bucket `customer-photos`; vai quản ảnh: owner / manager / sales; tự ghim GPS khi accuracy ≤ 100 m và khách chưa có toạ độ; cảnh báo khi xa > 300 m; "cùng chỗ" là ≤ 1 m; nhắc lại ảnh mỗi 7 ngày; duyệt ảnh / vị trí: mig 244 (CLAUDE.md).

**Nhắc việc** (cron): `route-reminders`: khách `channel` rỗng → báo NV chính, không có thì owner / manager; hạ nhiệt 3 ngày (`NHAC_TUYEN_SAU_NGAY`). `photo-reminders`: thứ Hai giờ VN, loại `customer_photo_missing`.

**Hồ sơ khách — việc cần làm** (`customerTodos`): `photos`, `tax_code`, `gps`, `overdue`, `no_assignee`. **Nhập Excel:** chỉ bắt buộc "Tên cửa hàng" (`src/lib/customers/import-parse.ts`).

## 8. Sản phẩm

**Trường** (`src/types/index.ts:248`): `sku`, `name`, `barcode` (trùng chỉ cảnh báo), `base_unit`, `vat_rate` (tỉ lệ), `shelf_life_days`; `status` active|inactive; `cost_price`, `sell_price` (cơ sở), `min_stock`, `max_stock`; `shelf_location`, `weight`, `weight_unit`, `direct_sale`, `track_serial`, `images[]`, `warranty_info`, `description`; `brand`, `primary_supplier_id`; `category`: đã bỏ, thay bằng nhóm theo NCC.

**Đơn vị:** `product_units` (`unit_name`, `conversion` → cơ sở). **Bảng giá:** `price_lists` (`product_id`, `group_id`, `unit_name`, `price`, `effective_from` / `to`).

**Nhập Excel** (`src/lib/products/import-parse.ts`): nhận tiêu đề kiểu KiotViet ("Đơn vị quy đổi", "Hệ số quy đổi", "Mã ĐVT cơ bản"); có cột "Tồn kho", "Giá vốn" → dựng phiếu nhập tồn đầu kỳ (`src/lib/products/opening-stock-plan.ts`).

**Ẩn giá vốn** (`cost_price`, `unit_cost`, lãi gộp): sau quyền `inventory.cost`.

## 9. Khuyến mãi

Bảng `promotions` (`type`, `rules` jsonb, `priority`, `target_groups[]`, `starts_at`, `ends_at`, `is_active`). Các loại (`src/app/(dashboard)/promotions/new/page.tsx:83`): `trade_discount` `{discount_percent}` · `payment_discount` `{discount_percent}` · `cumulative` `{threshold, bonus}` · `buy_x_get_y` `{buy_qty, get_qty}` (cùng loại) · `display` `{description}`. KHÔNG được áp dụng ở POS / đơn / hoá đơn — không có tham chiếu trong `lib/pos`, `lib/sell`. Chỉ là danh mục.

## 10. Hoa hồng

`commission_policies` (`type` percentage|fixed|tiered, `tiers` jsonb, `applies_to` mặc định `all`, hiệu lực từ / đến); `tiers` theo loại: percentage `[{rate}]` (0–1), fixed `[{amount}]`, tiered `[{min, max, rate}]`. `commission_wallets` (`period`, `earned`, `paid`, `balance`) chỉ đọc: không migration hay RPC nào ghi → chưa có engine tính / chi.

## 11. Nhân sự / lương

**Chấm công** (`hr_attendance`): lưới tay của quản lý, upsert theo `(user_id, work_date)`, không GPS; `status`: `present` / `absent` / `half_day` / `leave` / `holiday`; ngày công = present + holiday + 0,5 × half_day.

**Cấu hình** (`hr_salary_config`): `base_salary`, `gas_allowance`, `phone_allowance`, `working_days_per_month` (26); `kpi_target_revenue` (A), `target_tiers` jsonb `[{min_percent, bonus, label}]`; `over_target_percent`, `under_60_percent`, `bypass_attendance_roles` (mặc định sales).

**Tính lương:** RPC `compute_payroll_run` (mig 096): chỉ user `role = 'sales'` đang hoạt động; `revenue = max(0, Σ sales_orders.total (is_revenue_status, theo order_date) − payroll_returns_for)` — vẫn theo ĐƠN; lương CB không prorate theo ngày công; KPI: ưu tiên `salary_kpi_tiers` riêng người / tháng (bậc cao nhất có `min_revenue ≤ revenue`, kiểu percent|fixed); không có thì theo A: `%A < 60` → lương = `revenue × under_60%`, không phụ cấp, không KPI; 60 ≤ `%A` < 70 → không KPI; còn lại: KPI = Σ bonus các bậc `min_percent ≤ %A` (cộng dồn), > 100% cộng thêm `(revenue − A) × over%`. Thưởng số đơn (`salary_order_count_bonus_configs`): `min_order_count`, `min_order_value`, `bonus_per_order`, `period` week|month (tuần xét riêng từng tuần). Thưởng hoạt động: `monthly_activity_bonuses`. BHXH = `round(prorated × 10,5%)`. `net = prorated + allowances + kpi + order_count + activity + overtime + manual_adjustment − deductions − social_insurance` (trigger `trg_tinh_luong_thuc_nhan`, mig 173).

**Kỳ lương:** `payroll_runs` (`month`, `draft` → `locked` qua `lock_payroll_run`); quyền tính / khoá: owner / manager / accountant. **Lương của tôi:** RPC `my_payslips()` (mig 201, `src/lib/hr/phieu-luong-cua-toi.ts`).

**Thư viện thưởng ở client** (`src/lib/bonus.ts`, theo dòng đã giao, đơn vị khớp), dùng cho xem trước: thưởng mỗi đơn vị (đầu thùng); mốc số đơn: lấy bậc cao nhất; KPI: `new_customers`, `visit_coverage`, `aov`, `return_rate`, `above_list_pct`.

## 12. Thông báo

Chỉ trong app (bảng `notifications`; chuông). Không có push / Zalo / email. Loại (`src/types/index.ts:466`): `order_*` (cũ), `return_completed`, `payment_received`, `receivable_overdue`, `visit_logged`, `customer_photo_missing`, `customer_route_missing`, `customer_photo_review`, `info`. Nguồn đang chạy: `payment_received` (màn thu tiền → NV phụ trách khoản nợ); `visit_logged` (ghé thăm → NV chính); nhắc ảnh / tuyến (cron → NV chính hoặc owner / manager); duyệt ảnh (RPC mig 244); bàn giao khách (RPC mig 246); một số loại từ mig 120.

## 13. Người dùng & quyền

**Vai:** `owner`, `manager`, `accountant`, `sales`, `warehouse` (`driver` đã ngưng, mig 122).

**Mô-đun × hành động** (`DEFAULT_PERMISSION_MAP`, `src/lib/permissions.ts:89`): mô-đun `orders`, `customers`, `inventory`, `products`, `commissions`, `receivables`, `deliveries`, `promotions`, `invoices`, `returns`, `reports`, `settings`; hành động `read`, `create`, `update`, `delete`, `approve`, `export`. Điểm chính: sales: orders R/C/U, customers R/C/U, receivables R, returns R, reports R, promotions R, commissions R; warehouse: inventory R/C/U/E, returns R/U/Approve; manager: receivables R/C/U/E; accountant: invoices R/C/U/E, receivables R/C/U/E.

**Ô tính năng** (`src/lib/permissions-features.ts`): BO = owner / manager / accountant; BOW = BO + warehouse. Không khai `defaultRoles` → theo mô-đun cha: `orders`, `customers`, `customers.visits`, `promotions`, `commissions`, `returns`, `inventory`, `products`, `receivables`, `receivables.by_customer`, `invoices`, `hr`, `reports.sales`, `settings`, `settings.users`, `settings.permissions`, `settings.org`, `settings.approval_rules`. Ô riêng (`defaultRoles`):

| Ô | Mặc định |
|---|---|
| `customers.handover` | owner, manager |
| `purchasing.invoices` | BO |
| `purchasing.returns` | BOW |
| `suppliers` | BO |
| `payables` | BO (manager chỉ R/E) |
| `inventory.cost` | BOW |
| `receivables.by_rep` | BO |
| `finance.cash_receipts` | BO |
| `finance.opening_balances` | BO |
| `finance.expenses` | BO |
| `einvoice.config` | BO |
| `analytics.business` / `.products` / `.customers` / `.performance` | BO |
| `reports.dashboard`, `reports.end_of_day`, `reports.orders`, `reports.products`, `reports.customers`, `reports.inventory` | BOW |
| `reports.suppliers`, `reports.employees`, `reports.channels`, `reports.finance` | BO |

**Ghi đè:** theo NPP: `role_permissions`; theo người: `user_permission_overrides` (`<key>.<action>` = bool).

**Cờ quyền trên user:** `allow_price_edit`, `price_edit_max_increase_pct`, `allow_discount`, `discount_max_type`, `discount_max_value`, `is_active`, `left_at`. Mẫu tạo user: `sales_basic`, `sales_flex` (+10%), `warehouse`, `accountant`.

**Tạo user** (`POST /api/admin/users`, owner): email tổng hợp từ SĐT; đăng nhập bằng SĐT + mật khẩu (`lookup_email_by_identifier`); đồng thời cấp token QR.

**Đăng nhập QR:** token `randomBytes(32)` base64url trong `qr_login_tokens` (một token / user, chỉ service_role đọc); không hết hạn; xoay lại (POST) / thu hồi (DELETE) là QR cũ hết hiệu lực. `GET /qr-login?t=` (`src/app/qr-login/route.ts`): kiểm token + `users.is_active` → `generateLink` magiclink → `verifyOtp` phía máy chủ → chuyển `/orders`. Quản lý QR chỉ owner.

**Tài khoản bị khoá** (`is_active = false`): chặn khi nạp hồ sơ (`apDungHoSo`).

## 14. Tổ chức / cài đặt

`organizations`: `name`, `slug`, `allow_oversell`, `settings` jsonb (`address`, `phone`, `tax_code`, `setup_completed_at`). Không có logo / ngân hàng / cấu hình làm tròn. Wizard `/setup`: welcome → org → warehouse (`pricing_rules.date_warehouse_threshold_days`) → salary (`hr_salary_config`) → done. Bảo trì: env `MAINTENANCE_MODE` (`1` / `true` / `on`); cookie vượt `npp_maintenance_bypass`; luôn mở `/maintenance`, `/debug` (`src/lib/maintenance.ts`). Sao lưu: GitHub Actions dump DB → mã hoá age → Google Drive lúc 02:00 VN; không gồm Storage; `/backup` chỉ là trang thông tin (`src/lib/backup/public-info.ts`). Ngưỡng cảnh báo đơn: `/settings/approval-rules` (§1).

## 15. Offline / PWA

`public/sw.js` (`CACHE_VERSION` `npp-v2`): cache-first `/_next/static`; trang: network-first với navigation preload, offline trả bản đã cache; không cache `/api`, `/login`, `/qr-login`, Supabase. IndexedDB `nppsale-offline` / store `kv`: `order-outbox` (đơn chờ gửi `{id = clientRequestId, payload, status pending|error, attempts}`), `order-ref-data` (danh mục hàng / giá / khách, có khoá phiên `danh_muc_ban_phien`). `syncOutbox` (`src/lib/offline/sync.ts`): online + đã đăng nhập → `createOrderRecords`, idempotent; lỗi mạng giữ lại thử sau; lỗi dữ liệu đánh dấu `error` cho người xử lý. Chỉ ĐƠN HÀNG lập được offline; HĐ / phiếu thu / kho thì không. Không có màn mời cài app (`beforeinstallprompt`).

## 16. Báo cáo & phân tích (định nghĩa ngoài CLAUDE.md)

**Cuối ngày** (`/reports/end-of-day`): đơn trong ngày, HĐ ghi sổ, phiếu trả trừ doanh số trong ngày; giá vốn theo phiếu xuất của từng HĐ, `cash_receipts`, `expenses`; lọc theo khách / NV / người tạo / hình thức thanh toán; phiếu trả qua cùng bộ lọc.

**Kênh** (`/reports/channels`): doanh thu HĐ − trả, nhóm theo `customers.channel` khớp `sales_routes` (không kênh = "Bán trực tiếp").

**Nhà cung cấp:** `purchase_invoices` + `payables` + phiếu nhập đã ghi sổ + dòng đơn mua; nợ NCC theo `tongNoNcc`.

**Đặt hàng** (`/reports/orders`): số hoạt động theo `order_date` (không phải doanh thu); "Đã xuất" = tiền dòng × `invoiced_qty` / `qty`; "Chưa xuất" chỉ của Phiếu tạm.

**Tồn kho:** lô cận date: `getExpiryStatus` (≤ 30 ngày = danger; ≤ shelf_life/3 = warning); "bán chậm": < 5 đơn vị cơ sở bán trong kỳ, mặc định 90 ngày.

**Tài chính:** `finance_pnl`: doanh thu HĐ − `credit_note_amount`; COGS = phiếu xuất (bỏ phiếu của HĐ huỷ / "Đảo phiếu trả") − giá vốn phiếu nhập lại từ phiếu trả; chi phí theo `expense_categories.bucket`: `cogs` / `operating` / `hr` / `financial` / `tax` / `other`. `finance_cash_flow`: thu = `payments` (bỏ `return_credit` / `credit_applied`); chi = `payable_payments` + `expenses` đã trả. `finance_balance_sheet` (mig 243): tiền = thu − trả NCC − chi; phải thu = Σ(amount − paid); tồn kho = Σ qty × unit_cost; phải trả = Σ max(nợ ròng NCC, 0); trả trước NCC = Σ max(−nợ ròng, 0). `cash_received_total`.

**Hiệu quả công nợ** (`/analytics/performance/receivables`): tổng nợ / quá hạn theo NV, khách, hạn mức. **Phân tích khách:** `customers/overview` (tổng khách, khách mới, khách active không mua); `customers/categories` (doanh thu thuần theo nhóm / kênh / tỉnh). **Phân tích hàng:** `products/stock` (giá trị tồn theo lô); `products/categories` (theo NCC / thương hiệu). **Kinh doanh:** `business/overview` (kỳ này so kỳ trước, top nhóm / kênh / NV / mặt hàng); `business/cost-profit` (lãi gộp thuần − chi phí).

**Báo cáo tổng hợp** (`/bao-cao/*`, `src/lib/bao-cao/`): dòng bán = dòng HĐ phân bổ tỉ lệ để Σ = `sales_invoices.total`; dòng trả âm; giá vốn bán = SL cơ sở × giá vốn bình quân phiếu xuất trong kỳ; công nợ tại ngày X = `amount − paid + Σ` khoản thu sau X (phiếu phát sinh ≤ X); kho XNT: tồn cuối = tồn hiện tại − biến động sau kỳ, nhóm Nhập / Trả về / Xuất bán / Xuất khác; tốc độ bán: 90 ngày; kỳ: "Tháng này" = tháng lịch, so với cùng số ngày kỳ trước.

**Tổng quan:** `dashboard_summary` / `dashboard_top_customers` / `dashboard_channel_revenue`; trang chủ NVBH: `my_sales_target`.

## 17. Cron

Một cron Vercel `0 18 * * *` UTC (01:00 VN) → `/api/cron/daily`, xác thực `CRON_SECRET` (so sánh an toàn thời gian). Thứ tự: (1) `einvoice-sync`; (2) `customer-photo-reminders` (chỉ thứ Hai VN); (3) `customer-route-reminders`; (4) `einvoice-pull-snapshots`. Mỗi việc độc lập; một việc hỏng không chặn việc khác.

## 18. Chuyến giao (đã bỏ)

Bảng `deliveries` (`pending` / `in_transit` / `delivered` / `partial` / `failed`), `delivery_lines` (POD ảnh / chữ ký, `cod_cash` / `cod_transfer` / `credit` / `partial`), `driver_handovers` (+ `failed_orders`, `items`, `confirm_driver_handover`). Màn `/deliveries`, `/inventory/stock-out`, `/inventory/entries/[id]`, thu tiền theo phiếu xuất, `/inventory/pending`: chỉ đọc, nút ghi bị khoá (`LEGACY_FLOW_WRITES_LOCKED`, `src/lib/nav/legacy-flow.ts`). Vai `driver` bị trigger chặn gán mới. Bỏ khỏi bảng quyền.

## 19. Nhật ký / dòng thời gian

`order_activity_log` (mig 052): trigger ghi `add_line` / `edit_line` / `remove_line` + diff jsonb + `actor_id`; hiện ở chi tiết đơn (100 dòng). `order_status_history`: `from_status` / `to_status` / `changed_by`. `einvoice_logs`: mọi lần gọi MISA. Liên kết chứng từ: `sales_invoices.replaced_by`, `cancel_reason`; `cash_receipts.received_by` / `received_at`; `payments.verified_by`; `customer_photo_requests`. Không có audit log chung; "Hoạt động gần đây" của khách ghép từ `visit_logs` + đơn + thu tiền (`mergeActivity`).

## 20. RPC chính cần tái hiện

- Bán / HĐ: `create_order_with_lines`, `cancel_order`, `get_invoiceable_lines`, `post_invoice`, `reissue_invoice`, `cancel_invoice`.
- Trả hàng: `create_return_with_lines`, `save_pos_return`, `complete_return`, `cancel_return`.
- Thu tiền: `create_cash_receipt`, `void_cash_receipt`.
- Mua / NCC: `complete_purchase_invoice`, `sua_phieu_nhap`, `khoi_phuc_phieu_nhap`, `complete_supplier_return`, `cancel_supplier_return`, `khoi_phuc_phieu_tra_ncc`, `record_payable_payment`, `chi_tra_ncc`, `huy_phieu_chi_ncc`, `luu_gia_nhap`.
- Kho: `post_stock_import`, `post_stock_export`, `post_stock_issue`, `post_stock_transfer`, `post_stock_adjustment`, `reject_stock_adjustment`, `cancel_stock_entry`, `refresh_warehouse_zones`, `committed_stock_by_product`, `ton_kho_trang`, `ton_ban_theo_hang`.
- Soạn hàng: `tao_luot_soan`, `cap_nhat_luot_soan`, `hoan_tat_luot_soan`, `huy_luot_soan`.
- Lương: `compute_payroll_run`, `lock_payroll_run`, `my_payslips`.
- Khách / nhân viên: `ban_giao_khach`, `hang_khach_da_lay`, `claim_customer_for_me`, `search_customer_dupes`, `giao_cong_no_npp`, `cho_nhan_vien_nghi`, `assign_doc_seller`.
- Ảnh điểm bán: `xin_doi_anh_diem_ban`, `duyet_yeu_cau_anh_diem_ban`, `duyet_anh_diem_ban`, `huy_yeu_cau_anh_diem_ban`.
- Báo cáo: `finance_pnl`, `finance_cash_flow`, `finance_balance_sheet`, `bao_cao_so_ban`.
