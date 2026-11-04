> Khảo sát tự động 04/11/2026 từ `supabase/migrations` 001–260 + `schema_full.sql` của `nppsale`. Tài liệu tham chiếu, không phải quyết định.


# Inventory dữ liệu + logic máy chủ (Supabase) — npp.sale → ERPNext v16

Nguồn: `supabase/migrations/001…260` (đè lên nhau theo số), `supabase/schema_full.sql` (gộp, 47.249 dòng), `src/types/index.ts`, `src/lib/db/*`, `/home/user/nppsale/CLAUDE.md` (luật nghiệp vụ chủ nhà chốt). Mọi bảng có `org_id` (multi-tenant) trừ các bảng con/khoá ghi chú riêng.

## A. TABLES (theo domain)

### A1. Tổ chức / người dùng / quyền
| Bảng | Mục đích | Cột nghiệp vụ chính |
|---|---|---|
| organizations | Tenant = 1 NPP | name, slug UQ, settings jsonb (address/phone/tax_code/email…), allow_oversell bool (086, cho bán/xuất âm mọi phiếu kho từ 222), completed_edit_days int (119) |
| users | Hồ sơ nhân viên (id = auth.users.id) | org_id, full_name, role CHECK(owner,manager,accountant,sales,warehouse,driver) — driver bị chặn gán mới bằng trigger (122); phone (định danh đăng nhập, email kỹ thuật `<sđt>@nppsale.local`, mig 104–106), is_active (khoá tài khoản → user_org_id() trả NULL), left_at/left_by (nghỉ việc, 223), allow_price_edit + price_edit_max_increase_pct (027), allow_discount + discount_max_type CHECK(pct,vnd) + discount_max_value (NULL = không trần) (185) |
| role_permissions | Ma trận quyền theo vai | (org_id, role, module, action) UQ; module dạng `a.b` (024/090), action CHECK(read,create,update,delete,approve,export), allowed |
| user_permission_overrides | Ghi đè quyền từng người | PK(user_id, permission_key), granted, org_id |
| user_suppliers | NVBH ↔ NCC (công ty) được làm | PK(user_id, supplier_id), org_id — giới hạn sản phẩm NVBH thấy |
| qr_login_tokens | Token đăng nhập QR (tách khỏi users, 088) | user_id PK, token, issued_at |
| entity_locks | Khoá bi quan khi mở sửa (046, cron nhả 053) | entity_type, entity_id UQ, locked_by, last_heartbeat_at |
| workflow_sessions | "Việc đang dở" (045) | entity_type CHECK(sales_order,stock_entry,delivery,driver_handover), stage, last_url, form_draft jsonb, closed_at |
| danh_muc_ban_phien | Số phiên (1 dòng, id=1) để máy NVBH biết danh mục đổi | phien/luc (sản phẩm·giá·đơn vị, 209), phien_khach/luc_khach (254) |

### A2. Khách hàng
| Bảng | Mục đích | Cột chính |
|---|---|---|
| customers | Điểm bán | store_name, owner_name, phone (UQ org_id+phone, chuẩn hoá), address/province/district/ward, channel (= mã tuyến `sales_routes.code`, CHECK cũ GT/MT/HORECA đã gỡ 073), group_id → customer_groups (= bảng giá nhóm), credit_limit, payment_terms (COD/NETxx), status CHECK(active,suspended,locked), gps_lat/lng, billing_name/tax_code/billing_address/billing_email/payment_method_label (HĐĐT, 011), created_by (032), photo_reminder_sent_at (103), route_reminder_sent_at (221), photo_approved_at/by (244), tim_kd (khoá tìm, trigger) |
| customer_groups | Nhóm khách (dùng làm nhóm giá) | name |
| customer_assignments | NV phụ trách khách | customer_id+user_id UQ, role CHECK(primary,secondary), status ('active'), assigned_at |
| sales_routes | Danh mục tuyến (018) | code UQ, name, sort_order, is_active |
| customer_photos | Ảnh điểm bán ≤3 ô (103) | slot 1..3, photo_url, taken_at, gps_lat/lng/accuracy, uploaded_by |
| customer_photo_requests | Yêu cầu đổi ảnh/vị trí sau khi đã duyệt (244) | kind CHECK(photo_add,photo_replace,photo_delete,pin_set,pin_clear), photo_id, slot, photo_url, pin_lat/lng, status CHECK(pending,approved,rejected,cancelled), requested_by/at, decided_by/at, decision_note |
| ban_giao_khach_log | Nhật ký bàn giao khách (246) | nguon CHECK(nv,chua_ai,tat_ca), tu_nv, den_nv, kieu CHECK(chung,chuyen), bo_loc jsonb, khach uuid[], ket_qua jsonb |

### A3. Sản phẩm / đơn vị / bảng giá
| Bảng | Mục đích | Cột chính |
|---|---|---|
| products | Mặt hàng | sku UQ(org), name, category, brand, barcode, base_unit (≠ rỗng, 176), vat_rate (TỈ LỆ 0..1; default 0 từ 110), shelf_life_days, status, cost_price, sell_price (= giá đơn vị cơ sở), min/max_stock, primary_supplier_id → suppliers (030; RLS NVBH), allow_price_edit + price_edit_max_type CHECK(percent,value) + price_edit_max (025/091 — giờ quyền sửa giá theo user), direct_sale, images jsonb, weight, track_serial, tim_kd |
| product_units | Đơn vị quy đổi | product_id+unit_name UQ, conversion integer (số đơn vị cơ sở trong 1 đơn vị) |
| price_lists | Bảng giá bán | product_id, group_id (NULL = bảng chung), unit_name, price (giá của ĐÚNG đơn vị đó), effective_from/to (không dùng trong tra giá) |
| purchase_price_lists | Bảng giá nhập (234) | UQ(product_id, unit_name), price, effective_date, source_invoice_id → purchase_invoices; tự cập nhật khi phiếu nhập hoàn thành |
| pricing_rules | Cài đặt 1 dòng/org | date_warehouse_threshold_days (028, ngày tự chuyển lô sang kho date); các cột sàn/trần giá cũ đã DROP (074) |

### A4. Đơn hàng (Sales Order)
| Bảng | Mục đích | Cột chính |
|---|---|---|
| sales_orders | Đơn đặt hàng | order_code UQ (DH-0001[-n]), order_seq, edit_no (130), customer_id, sales_user_id (người được gán; guard 153/155: chỉ NPP gán người khác), created_by (178), order_date (default vn_today 226), expected_delivery, **status CHECK chk_sales_orders_status_v2 (124): draft, submitted, partially_invoiced, completed, closed, cancelled** — từ 217 thực tế chỉ còn draft→submitted→completed/cancelled (partially_invoiced/closed đã gộp về completed); payment_terms, subtotal (SAU giảm đơn, trước thuế), discount (legacy), vat, total, notes, approval_reason (013), approved_by/at, submitted_at, completed_at/by, cancelled_at/by, cancel_reason (119), closed_at/by (124), current_workflow_stage (044, legacy), client_request_id (089, idempotent tạo đơn offline), updated_at (220), merged_into |
| sales_order_lines | Dòng đơn | product_id, unit_name (≠ rỗng → đơn vị cơ sở, 175), conversion_factor (039), quantity (>0), unit_price (giá SAU giảm dòng, ≥0), line_discount (ghi nhớ = SL×(giá bảng−giá áp), ≥0), line_total (= SL×unit_price), vat_rate (0..1, NULL=lấy theo SP, 183), invoiced_qty (124; theo đơn vị dòng đơn, quy đổi 179), note (029), batch_id (legacy) |
| giam_don_goc | Ảnh chụp khoản giảm cả đơn gốc khi sửa (226) | order_id PK, giam |
| merged_orders | Gộp đơn (legacy M1) | merged_order_id, source_order_id |
| order_status_history | Lịch sử trạng thái (008, trigger) | from_status, to_status, changed_by |
| order_activity_log | Nhật ký dòng / HĐ (052) | action CHECK(add_line,edit_line,remove_line,edit_after_complete,cancel_after_complete,invoice_posted,invoice_cancelled,order_closed), changes jsonb, actor_id |
| approval_rules | Ngưỡng cảnh báo/duyệt đơn (1/org, 013) | auto_approve_max, manager_approve_max, customer_debt_max, customer_overdue_max, rep_portfolio_debt_max, enforce_credit_limit |

### A5. Hoá đơn bán + dòng
| Bảng | Mục đích | Cột chính |
|---|---|---|
| sales_invoices | Hoá đơn bán = chứng từ THỰC XUẤT (124); nguồn doanh thu + công nợ | invoice_code (HD-0001, sửa → HD-0001-1), invoice_seq, reissue_no (128), order_id (UQ partial `uq_sales_invoices_mot_don_mot_hd` WHERE posted — 1 đơn 1 HĐ, 217), customer_id, sales_user_id, invoice_date (DATE giờ VN), **status CHECK(posted, cancelled)** (không có nháp), subtotal (sau giảm đơn, trước thuế), vat, total (làm tròn tổng), payment_terms, due_date, stock_entry_id (phiếu XK), replaced_from/replaced_by, posted_at/by (người tạo), cancelled_at/by, cancel_reason, soan_luc/soan_boi (đã soạn hàng, 224), updated_at (220), tim_kd |
| sales_invoice_lines | Dòng HĐ | order_line_id (NULL với hàng đổi/dòng thêm), product_id, unit_name, conversion_factor (CHỤP, máy chủ tra — 174/247), quantity, unit_price, line_discount (ghi nhớ), line_total = SL×unit_price, vat_rate (chụp), is_exchange (hàng đổi xuất đi, 0đ), sort_order, note. ⚠ không có created_at |
| invoices | Hoá đơn VAT/HĐĐT (M10 + MISA) — gắn `sales_invoice_id` (124) | invoice_number, customer_name/address/tax_code, subtotal/vat/total, status CHECK(draft,issued,cancelled), misa_status CHECK(pending,sent,waiting_code,signed,replaced,cancelled,amount_mismatch,error), misa_relation CHECK(new,replacement,adjustment,replaced,adjusted,unknown), misa_invoice_id/url, misa_ref_id, misa_inv_no, misa_inv_series, misa_inv_date, misa_invoice_code (mã CQT), misa_lookup_code, misa_org_ref_id, misa_no_locked, misa_published_at, misa_last_checked_at, misa_error/note |

### A6. Trả hàng (khách)
| Bảng | Mục đích | Cột chính |
|---|---|---|
| returns | Phiếu trả hàng khách | return_code (PT-0001; TH- trước 237), return_seq (193), order_id, invoice_id (124), customer_id, requested_by (người tạo), sales_user_id (người gán, 160; gắn HĐ → luôn theo người của HĐ, 194), reason CHECK(damaged,wrong_item,near_expiry,expired,refused), **status CHECK(draft, submitted, completed, cancelled)** (119; "submitted" = Chờ xử lý, chỉ phiếu tự sinh), credit_with_invoice (133: TỰ SINH theo HĐ → công nợ trừ ngay lúc xuất HĐ), credit_note_amount (tiền trả = Σ line_total dòng không phải hàng đổi; trigger), applied_receipt_id (cấn ở phiếu thu kiểu cũ), destination_zone CHECK(sale,date), return_date (188), revenue_date (192: ngày trừ doanh số — tự sinh = ngày HĐ, tự lập = ngày hoàn thành), credited_at (097), completed_at/by, cancelled_at, cancel_reason, approved_by, photo_url, notes, updated_at |
| return_lines | Dòng trả | product_id, unit_name, quantity, unit_price (≥0, trần giá 230), line_total, vat_rate (0..1, 069), is_exchange (035: hàng đổi, không tính tiền), reason (159), note |

### A7. Công nợ phải thu + phiếu thu
| Bảng | Mục đích | Cột chính |
|---|---|---|
| receivables | SỔ CÔNG NỢ — 1 dòng/HĐ ghi sổ (UQ idx_receivables_invoice_unique), hoặc 1 dòng/phiếu trả tự lập không gắn HĐ (UQ return_id, 191), hoặc nợ đầu kỳ | invoice_id, order_id (legacy), return_id, customer_id, sales_user_id (người đứng tên nợ), amount (CÓ THỂ ÂM = dư có, 186), paid, due_date (= invoice_date + NETxx), **status CHECK(open, partial, paid, overdue)** do trigger quyết, opening_balance + note (102), ve_npp_luc (nợ về NPP khi NV nghỉ, 223), giao_tu_nv (dấu bàn giao, 246) |
| payments | Khoản thu gắn 1 receivable | receivable_id, collected_by, amount, method CHECK(cash,transfer,ewallet,return_credit,credit_applied), collected_at, verified_by/at |
| cash_receipts | Phiếu thu | receipt_code UQ(org) `PT-YYMMDD-NNNN` (ngẫu nhiên), receipt_date (ngày VN), source_type CHECK(delivery_settle,manual,standalone), source_id, collected_by, submitted_amount, expected_amount, **status CHECK(pending, received, voided)** (RPC lập thẳng 'received'), received_by/at, voided_at/by, void_reason, client_key (idempotent, 215), created_by, notes |
| cash_receipt_lines | Dòng phân bổ phiếu thu | receipt_id, receivable_id, invoice_id (tự điền từ receivable, 127), order_id, payment_id, return_id, amount, kind CHECK(payment, return_credit, credit_applied) |
| cash_collections | Đối soát tiền tài xế/ngày (009, legacy) | driver_id, work_date, total_collected/submitted, discrepancy (generated), status CHECK(pending,submitted,verified,discrepancy) |

### A8. Mua hàng
| Bảng | Mục đích | Cột chính |
|---|---|---|
| suppliers | NCC | code UQ(org), name, legal_name, business_type, representative, business_license_no/date, registered_address (232), tax_code, bank_account/name, payment_terms ('NET30'), credit_limit, rating, is_active, created_by, tim_kd. Xoá chỉ qua RPC; chặn xoá khi đã có chứng từ |
| purchase_orders / purchase_order_lines | Đơn mua PO (012) — legacy, không dùng trong luồng chính | po_code UQ, status CHECK(draft,confirmed,received,partial,cancelled), subtotal/vat/total; dòng: unit_price, vat_rate, line_discount, received_qty |
| purchase_invoices | **Phiếu nhập hàng NCC** (chứng từ chính, 065/142) | receipt_code PN-0001 (UQ org), invoice_number (số HĐ đầu vào NCC), invoice_date, supplier_id, po_id, **status CHECK(draft, completed, cancelled)**, subtotal, vat, vat_override (thuế gõ tay, 145), discount (đầu phiếu, trừ SAU thuế), total = subtotal + vat − discount, warehouse_zone CHECK(sale,date), stock_entry_id, payable_id, created_by, completed_at, cancelled_at/by, cancel_reason |
| purchase_invoice_lines | Dòng phiếu nhập | product_id, unit_name, quantity, unit_price, vat_rate, conversion_factor, line_discount (TRỪ THẬT), line_total = SL×giá − line_discount, sort_order |
| supplier_returns | Phiếu trả NCC (068/146) | return_code PTNCC-0001 (240; mã cũ ở return_code_cu), return_seq, supplier_id, return_date, reason, subtotal, vat, vat_override, discount, total, **status CHECK(draft, completed, cancelled)**, warehouse_zone CHECK(sale,date) default 'date', stock_entry_id, payable_credit_id (dòng payables ÂM), completed_at/by, cancel_reason |
| supplier_return_lines | Dòng trả NCC | unit_name, quantity, unit_price, vat_rate (TỈ LỆ từ 141), conversion_factor, line_discount, line_total, sort_order |
| payables | Công nợ NCC | supplier_id, stock_entry_id, invoice_number, amount (ÂM với trả NCC; 0 với dòng "trả trước"), paid, due_date, status CHECK(open,partial,paid,overdue), opening_balance (102) |
| payable_payments | Khoản trả NCC | payable_id, amount, method CHECK(cash,transfer,offset), paid_by/at, verified_by/at, supplier_payment_id (242) |
| supplier_payments | **Phiếu chi trả NCC** (242) | seq UQ(org), code PCNCC-0001, supplier_id, paid_date, amount (>0), method CHECK(cash,transfer), reference_code, **status CHECK(posted, cancelled)**, prepay_payable_id (dòng trả trước), cancelled_at/by, cancel_reason |

### A9. Kho
| Bảng | Mục đích | Cột chính |
|---|---|---|
| batches | **Sổ kho duy nhất** (lô/date), FIFO theo received_at (107) | product_id, batch_code, manufactured_at, expires_at, received_at, location, qty_initial / qty_on_hand (numeric, ĐƠN VỊ CƠ SỞ; có thể âm khi allow_oversell), unit_cost (giá vốn bình quân/đơn vị cơ sở, 016), warehouse_zone CHECK(sale,date) (tự sang 'date' khi gần hạn, 028), zone_moved_at/by, status ('available'…) |
| stock_entries | Phiếu kho | entry_code (XK-YYMMDD-HHMMSS bán; NK-… hoàn kho; PN… nhập hàng; IN-/ST-/WH-/XKL-/CKL-/NL- do app sinh), **type CHECK(import, export, transfer, stocktake)**, **status CHECK(draft, posted, cancelled)** (016), posted_at, supplier_id, ref_order_ids jsonb (017), warehouse_zone CHECK(sale,date) + dest_warehouse_zone (chuyển kho, 148), issue_reason (xuất lẻ: damaged/gift/transfer/other — free text, 144), created_by, notes |
| stock_entry_lines | Dòng phiếu kho / thẻ kho | product_id, batch_id, unit_name, quantity (numeric từ 228; kiểm kê = chênh lệch CÓ DẤU), qty_in_transaction_uom, transaction_uom, conversion_factor_snapshot, qty_in_base_uom NOT NULL (039), unit_cost (giá/đơn vị cơ sở) |
| stock_line_consumptions | Vết FIFO: dòng xuất lấy bao nhiêu từ lô nào (119) | line_id, batch_id, qty_in_base_uom, unit_cost — dùng hoàn kho đúng lô khi huỷ |
| luot_soan | Lượt soạn hàng (picking) (225) | ma (SH-dd/mm-NN), invoice_ids uuid[] (thứ tự = rổ A,B,C…), trang_thai CHECK(dang_soan, xong, huy), tien_do jsonb {nhat:{product_id: SL cơ sở}, chia:{"product|invoice": true}}, xong_luc/boi |
| swap_stock_movements | Hàng mang đi đổi (049, legacy giao hàng) | stock_entry_id, product_id, qty, conversion_factor, qty_in_base_uom, fifo_consumptions jsonb, qty_returned_in_base_uom |
| fifo_layers / fifo_consumptions | **ĐÃ DROP ở mig 107** | — |
| (kiểm kê) | Không có bảng riêng: stock_entries type='stocktake' draft → `post_stock_adjustment` / `reject_stock_adjustment`; hao hụt ghi `expenses` (source_type='stocktake') | |

### A10. Khuyến mãi
| promotions | CTKM (M9) — CRUD trên app, KHÔNG có RPC/áp giá tự động | type CHECK(trade_discount,buy_x_get_y,payment_discount,cumulative,display), rules jsonb, priority, target_groups uuid[], starts_at/ends_at, is_active |

### A11. Hoa hồng
| commission_policies | Chính sách hoa hồng | type CHECK(percentage,fixed,tiered), tiers jsonb, applies_to, effective_from/to |
| commission_wallets | Ví hoa hồng/NV/kỳ | user_id+period UQ, earned, paid, balance (generated), org_id |
(không có RPC; chỉ màn CRUD)

### A12. Nhân sự / chấm công / lương
| Bảng | Mục đích | Cột chính |
|---|---|---|
| hr_salary_config | Cấu hình lương org | base_salary, gas_allowance, phone_allowance, working_days_per_month, target_tiers jsonb (% mục tiêu → thưởng), kpi_target_revenue (mức doanh số chung A, 061), over_target_percent, under_70_rule, under_60_percent, bypass_attendance_roles jsonb |
| hr_monthly_bonus | Thưởng tháng theo doanh số | period UQ(org), tiers jsonb, per_unit_bonuses, order_milestone_tiers, kpi_metrics jsonb (031) |
| hr_attendance | Chấm công | user_id+work_date UQ, status CHECK(present,absent,half_day,leave,holiday), check_in/out |
| hr_payroll | Bảng lương legacy (007) | period, revenue/target/bonus cols, total_salary, breakdown jsonb, status CHECK(draft,confirmed,paid) |
| salary_kpi_tiers | Bậc KPI theo NV/tháng (043) | month, min_revenue, bonus_type CHECK(percent,fixed), bonus_value |
| salary_order_count_bonus_configs | Thưởng theo số đơn (043) | period CHECK(week,month), min_order_count, min_order_value, bonus_per_order |
| monthly_activity_bonuses | Thưởng hoạt động tay (043) | user_id+month UQ, amount |
| payroll_runs | Kỳ lương (050) | month UQ(org), **status CHECK(draft, locked)**, computed_at, locked_at/by |
| payroll_run_items | Dòng lương/NV | base_salary, standard/actual_workdays, prorated_base, allowances (064), kpi_bonus, order_count_bonus, activity_bonus, overtime, deductions, social_insurance, manual_adjustment, net_salary (trigger tính lại, 173), computed_breakdown jsonb |

### A13. Giao hàng (DEPRECATED — chủ nhà bỏ chuyến giao 24/09/2026; vai driver khoá 122)
deliveries (status CHECK(pending,in_transit,completed,cancelled), driver/warehouse confirm, settled_at/amount, goods_handover_*, source_stock_entry_id), delivery_lines (status CHECK(pending,delivered,partial,failed), pod_photo_url, payment_method, amount_collected), driver_handovers (status CHECK(draft,confirmed)), driver_handover_failed_orders (failure_reason CHECK(customer_refused,customer_absent,wrong_address,other)), driver_handover_items (source_type CHECK(failed_order,customer_return,unused_swap_stock), destination_zone, unit_cost), swap_stock_movements, cash_collections.

### A14. Tuyến / PJP / viếng thăm
| pjp_routes | Lịch đi tuyến | sales_user_id, day_of_week 0..6, customer_id, visit_order; UQ(user,dow,customer) |
| visit_logs | Check-in | visit_date, check_in/out_at, lat/lng, check_in_address, photo_url, result CHECK(order_placed,no_order,closed,not_visited), order_id |
| sales_routes | (xem A2) | |

### A15. Ảnh điểm bán + yêu cầu duyệt → customer_photos, customer_photo_requests, customers.photo_approved_* (A2). Storage buckets: customer-photos, visit-photos, pod-photos.

### A16. Bàn giao khách → ban_giao_khach_log, receivables.giao_tu_nv, customer_assignments.

### A17. Hoá đơn điện tử (MISA)
| company_einvoice_config | Cấu hình MISA 1/org | provider 'misa', api_base, tax_code, seller_name/address, misa_company_id, misa_org_unit_id, misa_template_id, misa_user_id, misa_app_id, misa_inv_series, misa_inv_template_no, sign_type, invoice_type, is_inherit_from_old_template, misa_is_invoice_with_code, token_path, publish_path (/v3sainvoice), username_enc/password_enc, sandbox |
| einvoice_logs | Log đẩy | invoice_id, order_id, request/response_payload, status CHECK(success,failed,pending), misa_lookup_code, misa_inv_no |
| misa_invoice_snapshots | Kéo HĐ từ MISA để đối soát (100) | ref_id, inv_series/no/date, transaction_id, invoice_code, buyer_*, total/before_vat/vat, publish_status, einvoice_status, relation, invoice_id, match_method CHECK(ref_id,transaction_id,inv_no,inv_no_loose,tax_date_amount…), match_status CHECK(matched,amount_diff,misa_only,cancelled,replaced,needs_review), inv_no_norm/inv_series_norm |
Logic MISA nằm ở API route Next (`src/app/api/einvoice/{publish,sync,refresh-status,pull-snapshots,reconcile-action}`), không phải RPC.

### A18. Thông báo
| notifications | Chuông/người | user_id, type CHECK(order_pending_approval, order_approved, order_cancelled, order_completed, order_edited, invoice_cancelled, return_completed, payment_received, receivable_overdue, visit_logged, customer_photo_missing, customer_route_missing, customer_photo_review, info) (244), title, body, link_url, is_read, metadata |

### A19. Phê duyệt → approval_rules (A4), customer_photo_requests (A2); duyệt kiểm kê = stock_entries draft→posted.

### A20. Nợ đầu kỳ → receivables.opening_balance (+note, không invoice_id), payables.opening_balance (102). Xoá chỉ khi chưa thu (policy 102).

### A21. Chi phí
| expense_categories | Danh mục chi phí | code UQ, bucket CHECK(cogs,operating,hr,financial,tax,other) |
| expenses | Phiếu chi chi phí | expense_date, amount ≥0, category_id, reference_code, source_type/source_id (vd 'stocktake'), is_paid, paid_at, payment_method CHECK(cash,transfer,ewallet) |

### A22. Cấu hình / cài đặt / số chứng từ
organizations.settings, pricing_rules, approval_rules, company_einvoice_config, role_permissions, danh_muc_ban_phien, reports_config (report_type, config jsonb). Không có bảng sequence riêng: số chạy = MAX(seq)+1 với advisory lock (§E).

### A23. Nhật ký / audit
order_status_history, order_activity_log, einvoice_logs, ban_giao_khach_log, stock_entry_lines (thẻ kho), stock_line_consumptions; các cột *_by/*_at/cancel_reason trên chứng từ.

### A24. Offline / khác
sales_orders.client_request_id (idempotent offline), cash_receipts.client_key, workflow_sessions, entity_locks, qr_login_tokens, danh_muc_ban_phien (cache danh mục máy NVBH), cột tim_kd (khoá tìm không dấu) trên products/customers/suppliers (177/203) + batches, stock_entries, payables, cash_receipts, invoices, returns, sales_orders, sales_invoices, users (249, trigger trg_zzzz_tim_kd).

---

## B. RPC FUNCTIONS
Quy ước: mọi RPC ghi là SECURITY DEFINER, một giao dịch, kiểm `org_id = user_org_id()` (ORG_MISMATCH) + `user_has_permission(auth.uid(),'module.action')` (FORBIDDEN). Đặt cờ `set_config('npp.via_rpc','on')` để qua trigger khoá ghi thẳng. Lỗi dạng `RAISE 'MÃ_HOA: câu tiếng Việt'` ERRCODE P0001. Hàm có `(mig X)` = vá chuỗi thân hàm đang chạy.

### B1. Đơn hàng / hoá đơn bán
| RPC | Mục đích | Đọc/ghi | Luật chính |
|---|---|---|---|
| create_order_with_lines(p jsonb) → (order_id, order_code, already_existed) [169, vá 183] INVOKER | Tạo đơn + dòng + phiếu trả kèm (draft) 1 giao dịch | sales_orders, sales_order_lines, returns, return_lines | Idempotent theo client_request_id; mã DH do trigger; thuế dòng lưu vat_rate; trigger 226/229 kiểm SL>0, giá ≥0, quyền giảm giá/trần giá |
| cancel_order(order, reason) [125] | Huỷ đơn CHƯA xuất | sales_orders | chỉ draft/submitted, không có HĐ ghi sổ |
| close_order [217] | Đã bỏ → ORDER_CLOSE_REMOVED | | |
| get_invoiceable_lines(order) [183, vá 212] | Dữ liệu màn Xuất hàng: dòng đơn còn lại + hàng đổi của phiếu trả kèm | read | available_base chỉ kho 'sale'; trả list_price, vat_rate của dòng đơn; gọi GET |
| **post_invoice(p jsonb)** → (invoice_id, invoice_code, entry_id, receivable_id, short_qty, near_expiry_skipped, order_status) [125; vá 128,131,133,152,174,180,183,189,213,214,215,227,247] | Xuất hàng = lập + ghi sổ HĐ | FOR UPDATE sales_orders; `_wf2_export_order` (phiếu XK + FIFO `post_stock_export` kho sale); sales_invoices/lines; `_wf2b_recompute_receivable`; returns; order_activity_log; notifications | quyền orders.approve; đơn phải 'submitted' (hoặc đang lập lại); ≥1 dòng SL>0; hệ số quy đổi máy chủ tra (`_chuan_he_so_dong_hoa_don`: đơn vị cơ sở=1 → product_units → giữ số gửi; khi Sửa HĐ giữ hệ số tờ cũ qua cờ `npp.he_so_tu_hd`); thuế: payload 0..1 nếu hợp lệ, không thì products.vat_rate; line_total=SL×unit_price; subtotal=round(Σline − discount kẹp [0,tiền hàng]); vat=round(Σline×vat); total=round(sub_raw+vat_raw); invoice_date mặc định vn_today(); số HĐ `_wf2b_next_invoice_seq` (advisory lock) → `_inv_code`; phiếu trả draft của đơn → 'submitted' + credit_with_invoice=true + gắn invoice_id; return_adds/return_edits áp ngay; đơn → completed (217); không chặn xuất vượt số đặt; INSUFFICIENT_STOCK nếu không allow_oversell; UQ 1 đơn 1 HĐ |
| **cancel_invoice(invoice, reason)** → (import_entry_id, order_status) [125; vá 131,135,184,217] | Huỷ HĐ | stock_entries 'import' NK-…, `_wf2_restock` hoàn ĐÚNG lô theo stock_line_consumptions (lô lấy sau trả trước), xoá receivables, returns, sales_invoices, sales_orders | chỉ 'posted'; bắt buộc lý do; khoá: LOCKED_HAS_PAYMENT (có paid / phiếu thu chưa huỷ — trừ khi gọi từ reissue, mig 184), LOCKED_EINVOICE (invoices issued / misa_inv_no / misa_status signed,replaced), LOCKED_RETURN_DONE; (217) đơn → 'cancelled' + phiếu trả draft/submitted → 'cancelled' trừ khi cờ `npp.reissue_chuyen_thu`='on' |
| **reissue_invoice(invoice, p)** [125; viết lại 149–158; vá 182,184,210,213,215,227,246,247] | "Sửa HĐ" = huỷ + lập lại 1 giao dịch | cancel_invoice + post_invoice; replaced_from/by | giữ số gốc HD-0042-n (reissue_no+1); giữ sales_user_id tờ cũ (182); chuyển phiếu thu/payments sang tờ mới (184); mặc định invoice_date + discount từ tờ cũ nếu payload thiếu (213); phiếu trả tự sinh đã nhập kho: tham số chọn 'lam_lai' (huỷ phiếu nhập, phiếu về Chờ xử lý — 216) hoặc giữ; chép dấu giao_tu_nv (246); giữ hệ số tờ cũ (247); `_apply_return_edits/_apply_return_adds` sửa/thêm hàng trả trên HĐ (giá do máy chủ tính) |
| assign_doc_seller(kind,id,user) [178/194; vá 182] | NPP gán người được gán cho đơn/HĐ/phiếu trả | sales_user_id trên chứng từ + receivables + phiếu trả theo HĐ | chỉ NPP |
| committed_stock_by_product(p_exclude_order) [136/137] DEFINER | Hàng đã đặt (đơn submitted) chưa rời kho, theo đơn vị cơ sở | read | dùng chặn đặt vượt tồn − đã đặt |
| ton_ban_theo_hang() [257] INVOKER jsonb | Tồn kho bán theo mặt hàng (POS) 1 câu | batches | GET |
| danh_dau_soan_hang(ids, da) [224] | Đánh dấu HĐ đã soạn | sales_invoices.soan_luc/boi | |
| tao_luot_soan / cap_nhat_luot_soan / hoan_tat_luot_soan / huy_luot_soan [225] | Lượt soạn hàng (nhặt tổng → chia rổ) | luot_soan, sales_invoices.soan_* | cập nhật gộp khoá jsonb; hoàn tất không trừ kho |

Helper nội bộ của nhóm này: `_wf2_export_order`, `_wf2_restock` (157), `_wf2_notify`, `_wf2b_sync_order_status` (217: có HĐ posted → completed, không → submitted), `_wf2b_payment_terms_days` (NETxx → ngày), `_wf2b_next_invoice_seq`, `_inv_code`, `_chuan_he_so_dong_hoa_don`, `_da_xuat_cua_dong_don`, `_giam_gia_don`, `_thue_hop_le`, `_huy_don_theo_hoa_don`, `_mac_dinh_lap_lai`, `_nho_don_dong_lap_lai`/`_tra_don_dong_lap_lai`, `_tra_da_nhap_truoc/sau_lap_lai`, `_apply_return_edits/_adds`, `_pending_return_for`, `_wf2_recompute_receivable` (cầu cũ theo order). Đã DROP: complete_order, edit_completed_order, _wf2_assert_order_unlocked (124), _wf2b_next_invoice_code (128).

### B2. Trả hàng khách
| RPC | Mục đích | Luật |
|---|---|---|
| create_return_with_lines(p_head, p_lines) [171] INVOKER | Lập phiếu trả tự lập (đầu + dòng) 1 giao dịch | RLS + trigger đánh số / tính credit |
| save_pos_return(p) [190/191; vá 227] | Lưu phiếu trả từ POS (tạo/sửa) | chặn sửa phiếu tự sinh (RETURN_FOLLOWS_INVOICE); NVBH chỉ sửa nháp của mình; đã hoàn thành → phải Ghi nhận lại |
| complete_return(id, zone) [127/158/191/200] & complete_return(id, zone, ngay) [211] | Hoàn thành = nhập kho (phiếu import, zone sale/date) + (tự lập) trừ nợ | tự lập gắn HĐ → `_wf2b_recompute_receivable`; không gắn → `_cong_no_phieu_tra` (dòng công nợ ÂM); gắn đơn chưa HĐ → bắt buộc đơn có đúng 1 HĐ posted (200); bản 3 tham số chỉ cho phiếu tự sinh, ngày ∈ [ngày HĐ, hôm nay]; tự lập đi thẳng draft→completed |
| cancel_return(id, reason) [191; vá 190,213,227] | Huỷ phiếu trả | tự sinh + Chờ xử lý → chặn; tự sinh đã nhập → đảo kho, về 'submitted', nợ giữ; tự lập → đảo kho, 'cancelled', tính lại nợ (luôn cho, kể cả đã thu); khoá LOCKED_CREDIT_APPLIED nếu đã cấn ở phiếu thu cũ |
| Triggers liên quan | `_danh_so_phieu_tra` (PT-), `_khoa_phieu_tra_tu_sinh` (chặn ghi thẳng phiếu tự sinh), `_phieu_tra_theo_nguoi_hoa_don`, `_phieu_tra_doi_nguoi_cong_no`, `_phieu_tra_dung_khach_hoa_don`, `_phieu_tra_hoan_thanh_gan_hd`, `_phieu_tra_doi_can_tru`, `_ngay_tru_doanh_so` (revenue_date), `sync_return_credited_at`, `sync_return_credit_note_amount` (credit = Σ line_total dòng không đổi), `_chot_gia_tran_dong_tra` (trần giá trả), `guard_return_sales_user` | |

### B3. Công nợ phải thu
- **`_wf2b_recompute_receivable(invoice_id)`** [125→186→194→200, vá 227]: credits = Σ credit_note_amount của returns gắn HĐ thoả (credit_with_invoice AND status IN(submitted,completed)) OR (NOT credit_with_invoice AND status='completed'), AND applied_receipt_id IS NULL. amount = total − credits (CÓ THỂ ÂM). Cập nhật cả sales_user_id + customer_id theo HĐ. Không đụng `paid`. Tạo mới chỉ khi HĐ 'posted'; due_date = invoice_date + NET days.
- **`_cong_no_phieu_tra(return_id)`** [191]: phiếu tự lập không gắn HĐ/đơn → 1 dòng receivables amount = −credit (UQ return_id); huỷ/sửa đổi theo; RETURN_CREDIT_USED khi đổi khách mà dư có đã dùng.
- **Trigger `trg_cong_no_am_trang_thai` → `_cong_no_am_trang_thai()`** [186→191→212] BEFORE INSERT/UPDATE receivables: amount<0 → 'paid' nếu |paid−amount|<0,01, ngược lại 'open'; |paid−amount|<0,01 → 'paid'; paid>amount (trả dư) → 'open'; giữ 'overdue'; paid>0 → 'partial'; else 'open'.
- `_cong_no_giu_ve_npp` [223/246] trigger giữ người đứng tên nợ (ve_npp_luc / giao_tu_nv).
- `_khoa_ghi_thang_cong_no` / `_khoa_ghi_thang_thu_tien` / `_khoa_ghi_thang_phieu_thu` [214]: chặn trình duyệt ghi thẳng tiền (chỉ nợ đầu kỳ chưa thu, xác nhận phiếu thu, phiếu trả nháp còn ghi thẳng được).
- Aggregates (INVOKER, RLS): receivables_summary [195], receivables_by_rep [195], receivables_by_customer [199] — Σ(amount−paid) trên status<>'paid', KHÔNG kẹp 0; aging theo vn_today().
- giao_cong_no_npp(customer, user) [223]: NPP giao lại nợ của 1 khách cho NV mới. cho_nhan_vien_nghi(user) [223]: khoá, gỡ phân công + tuyến, nợ chưa thu về NPP, thu hồi QR. so_chung_tu_nhan_vien(user) [223]: đếm chứng từ chặn xoá.

### B4. Phiếu thu
| create_cash_receipt(p) [120; vá 191,212,215,227] | p={customer_id, receipt_date, method, notes, lines:[{receivable_id, amount}], use_credit, client_key} | quyền receivables.create; khoá FOR UPDATE từng receivable, không thu vượt (amount−paid)+0,01 (BAD_RECEIVABLE_LINE); use_credit rút dư có (dòng âm) ≤ số dư (CREDIT_BALANCE_TOO_LOW) và ≤ phần phải trả; mã PT-YYMMDD-NNNN (thử 5 lần); status 'received', source 'standalone'; phân bổ hạn cũ trước; tạo payments + cash_receipt_lines(kind payment/credit_applied); cộng receivables.paid; idempotent client_key (215); (191) bỏ cấn phiếu trả |
| void_cash_receipt(id, reason) [120/191; vá 212,227] | Huỷ phiếu thu | quyền receivables.update; status pending/received; lý do bắt buộc; gỡ payments, trả paid về (dòng âm trả đúng, không kẹp) |
| cash_received_total(from,to) [093] | Tổng thu kỳ | read |

### B5. Mua hàng / NCC
| RPC | Mục đích | Luật |
|---|---|---|
| complete_purchase_invoice(id) [065/142/145] | Hoàn thành phiếu nhập: tạo stock_entries import + batches (zone phiếu) + payables; cấp mã PN | tiền tính lại ở máy chủ: line = SL×giá − line_discount; vat = vat_override ?? Σline×vat_rate; total = subtotal+vat−discount; unit_cost lô = tiền/đơn vị cơ sở; trigger `_trg_gia_nhap_tu_phieu` cập nhật purchase_price_lists |
| cancel_purchase_invoice(id, reason) [142; vá 238,242] | Huỷ phiếu nhập: trừ sạch lô, xoá công nợ | HANG_DA_XUAT nếu lô đã xuất (trừ khi allow_oversell, 238); DA_TRA_TIEN nếu trả thẳng; phần phiếu chi đã trừ trả về trả trước |
| sua_phieu_nhap(id, head, lines) [235/236] | Sửa phiếu nhập đã hoàn thành (kể cả đã bán) tại chỗ, giữ mã | điều chỉnh lô/giá vốn/công nợ |
| khoi_phuc_phieu_nhap(id) / khoi_phuc_phieu_tra_ncc(id) [241] | Khôi phục phiếu đã huỷ về trạng thái trước huỷ | |
| next_purchase_receipt_code(org) [142/237] internal | PN-#### (advisory lock) | |
| complete_supplier_return(id) [068…228] | Xuất kho FIFO đúng zone + payables ÂM (payable_credit_id) | tiền tính ở máy chủ (146); cho âm nếu allow_oversell (222) |
| cancel_supplier_return(id, reason) [143/147/235; vá 222] | Đảo: cộng lại lô (cộng theo lô, 147), xoá dòng nợ âm | DA_CAN_TRU nếu đã cấn |
| record_payable_payment(payable, amount, method, notes) [167] | Ghi trả 1 dòng nợ NCC (FOR UPDATE, cộng dồn máy chủ) | không vượt còn nợ |
| chi_tra_ncc(supplier, amount, date, method, notes, ref) [242] | Phiếu chi PCNCC: tự trừ khoản nợ cũ nhất (đầu kỳ trước), dư → dòng trả trước (amount 0, paid=dư) | quyền Chủ/Kế toán; không chạm dòng âm phiếu trả NCC; trigger `_trg_tra_truoc_vao_no_moi` dồn trả trước vào nợ mới |
| huy_phieu_chi_ncc(id, reason) [242] | Gỡ phân bổ, status cancelled | |
| payables_summary / payables_by_supplier [231/239] INVOKER | Tổng/theo NCC, không kẹp âm; total_returned | |
| luu_gia_nhap(p_dong) [234] | Ghi bảng giá nhập tay | |
| gop_nha_cung_cap(tu, vao) [232], xoa_nha_cung_cap(id, xoa_hang) [233], so_chung_tu_ncc(id) [232] | Gộp / xoá NCC (chỉ owner; hỏi xoá kèm hàng; hàng có chứng từ → ngừng bán) | trigger `_ncc_chan_xoa`, `_ncc_xoa_qua_rpc` |

### B6. Kho
| RPC | Mục đích | Luật |
|---|---|---|
| post_stock_import(p) [168/219] → (entry_id, entry_code, payable_id, lines_written) | Nhập kho / tồn đầu kỳ 1 giao dịch (+ công nợ NCC tuỳ chọn) | warehouse_zone sale/date (219) |
| post_stock_export(entry_id) [107/119/138] → (posted, total_cost, short_qty, near_expiry_skipped) | Ghi sổ phiếu xuất: FIFO theo batches.received_at, CHỈ kho 'sale' (138), ghi stock_line_consumptions, unit_cost dòng = bình quân lô lấy | chống trừ 2 lần; INSUFFICIENT_STOCK nếu không allow_oversell |
| post_stock_issue(entry_id) [144; vá 222,228] | Phiếu xuất lẻ (hỏng/biếu/khác) FIFO trong 1 zone | KHONG_DU_TON trừ khi allow_oversell |
| post_stock_transfer(entry_id) [148] | Chuyển kho sale↔date giữ lô/hạn/giá vốn | |
| post_stock_adjustment(entry_id) [123] → (batches_touched, shrink/surplus qty/value, expense_id) | Duyệt kiểm kê: dòng quantity = chênh có dấu (đơn vị cơ sở); hao hụt → expenses | quyền inventory.approve (owner/manager, không warehouse) |
| reject_stock_adjustment(entry_id, reason) [170] | Từ chối kiểm kê nháp | |
| cancel_stock_entry(entry_id, reason) [139; vá 227] | Huỷ phiếu kho, đảo tồn theo vết lô | chặn phiếu của chứng từ đã đảo (HĐ huỷ…) |
| refresh_warehouse_zones(org) [028/166] | Chuyển lô gần hạn sang 'date' | |
| stock_value_summary() [093], ton_kho_trang(p_tim, p_con_ton, p_sap, offset, limit) [255] INVOKER | Tồn theo mặt hàng + total_count + sum_* | |
| bao_cao_ton_kho(tu, den) [204] | Dòng thô báo cáo kho | |
| Trigger khoá | `_trg_khoa_ghi_thang_lo/_phieu_kho/_dong_kho` [170] chặn trình duyệt ghi batches/stock_entries/lines; `batches_auto_zone` [028] | |

### B7. Khách hàng / ảnh / bàn giao
| search_customer_dupes(p_q) [082→205→245] DEFINER | Tìm khách đã có CHỈ khớp đúng SĐT (toàn org) | trả primary_user_name, has_my_assignment |
| claim_customer_for_me(customer) [083] | NVBH tự nhận khách (customer_assignments) | chỉ vai sales |
| ban_giao_khach(p_den_nv, p_kieu 'chung'|'chuyen', p_nguon 'nv'|'chua_ai'|'tat_ca', p_tu_nv, p_tuyen[], p_ncc[], mốc, xem trước…) [246] | Làm chung / chuyển hẳn khách; chuyển hẳn: nợ chưa thu sang NV nhận (giao_tu_nv), doanh số không đổi; chép lịch tuyến | quyền customers.handover (owner/manager) |
| hang_khach_da_lay(p_nv, p_khach[], p_tu, p_tuyen[]) [246] | SL đơn vị cơ sở khách đã lấy = HĐ posted − hàng trả (revenue_date), bỏ hàng đổi, không tiền | NVBH chỉ khách mình + NCC mình |
| khach_thieu_anh(tab, offset, limit) / khach_cho_duyet_anh(offset, limit) [253] INVOKER | Danh sách điểm bán thiếu ảnh / chờ duyệt, phân trang + total_count | |
| xin_doi_anh_diem_ban(customer, photo_action, photo_id, slot, url, taken_at, gps…, pin…) [244] | NV xin thay/thêm/xoá ảnh, dời/xoá vị trí khi đã duyệt | tạo customer_photo_requests pending |
| duyet_yeu_cau_anh_diem_ban(ids[], dong_y, ghi_chu) [244] | Duyệt/từ chối yêu cầu → áp vào customer_photos/customers | quyền customers.approve |
| duyet_anh_diem_ban(customer, duyet) [244] | Khoá/mở bộ ảnh + vị trí (photo_approved_at) | |
| huy_yeu_cau_anh_diem_ban(id) [244] | NV huỷ yêu cầu của mình | |
| Trigger | `_trg_khoa_anh_diem_ban`, `_trg_khoa_vi_tri_diem_ban`, `_trg_bao_anh_dau_cho_duyet` | |

### B8. Báo cáo / dashboard / finance (INVOKER, RLS; gọi GET)
- dashboard_summary(period_start) [093→126→192]: doanh thu = Σ sales_invoices.total posted theo invoice_date − hàng trả theo revenue_date; số đơn; nợ mở; số quá hạn. dashboard_channel_revenue, dashboard_top_customers [192].
- finance_pnl(from,to) [093…228]: revenue (thuần), cogs = Σ qty_in_base_uom × unit_cost (187) − giá vốn hàng trả đã nhập, các nhóm expense. finance_cash_flow [228], finance_balance_sheet(as_of) [243] (cash, AR, inventory, AP ròng theo NCC, unpaid_expenses, supplier_prepayments).
- bao_cao_so_ban(tu, den) jsonb [204→218→228→256, SET jit=off]: dòng thô HĐ/dòng HĐ/phiếu xuất/phiếu trả/dòng trả/giá vốn một lượt; bao_cao_cong_no(p_tu_thu, p_tu_90) [204]; bao_cao_ton_kho [204].
- is_revenue_invoice_status(status) [124] = posted; is_revenue_status [126].
- my_sales_target() [196] (kpi_target_revenue), my_payslips() [201] (dòng lương của chính mình, kỳ locked).

### B9. Lương
| compute_payroll_run(run_id) [050…096] → int | Tính dòng lương: doanh số THUẦN theo HĐ − trả (payroll_returns_for), bậc KPI cộng dồn theo % mức A, phụ cấp (không có khi <60%), thưởng số đơn, hoạt động; chỉ role sales (066) | quyền owner/manager/accountant; run chưa locked |
| lock_payroll_run(run_id) [050/094] | Khoá kỳ → status locked | trigger enforce_payroll_lock chặn sửa |
| payroll_returns_for(user, org, start, end) [192], payroll_unbilled_returns(month) [097] | Trừ hàng trả vào doanh số lương | |
| Trigger `_trg_tinh_luong_thuc_nhan` [173] | net_salary = prorated_base + allowances + kpi_bonus + order_count_bonus + activity_bonus + overtime + manual_adjustment − deductions − social_insurance | |

### B10. Khuyến mãi / hoa hồng
Không có RPC (CRUD bảng thẳng qua RLS owner/manager).

### B11. E-invoice
Không có RPC SQL; API route Next ghi `invoices.misa_*`, `einvoice_logs`, `misa_invoice_snapshots`. cancel_invoice đọc trạng thái MISA để khoá.

### B12. Quyền / hệ thống / tìm kiếm
user_org_id(), user_role() [122, trả NULL khi is_active=false], user_has_permission(uid, perm) [166], customer_org_id(cid), user_assigned_customer_ids(), user_is_assigned_to_customer(cid), user_sells_to_customer(cid) [154], khach_toi_da_ban() [260], `_gieo_quyen_mac_dinh(org)` + trigger `_trg_gieo_quyen_npp_moi`, `_rls_tinh_mot_lan(_ap)` [250], lookup_email_by_identifier(phone) [106], normalize_phone [104], acquire/heartbeat/release_entity_lock, release_stale_entity_locks [046], confirm_driver_handover [047…107, legacy], khoa_tim / khoa_tim_ds / khong_dau [205/258] + trigger `_trg_tim_kd` (tim_kd), vn_today() [140/259], `_hom_nay_vn`, `_la_trinh_duyet` (phân biệt phiên trình duyệt cho trigger khoá ghi), `_tang_phien_danh_muc_ban` / `_tang_phien_khach_ban`.

### B13. Bản đồ vá chuỗi (thân cuối = bản CREATE cuối + các migration vá)
post_invoice: 180,183,213,214,215,227,247 · reissue_invoice: 182,184,210,213,215,227,246,247 · cancel_invoice: 184,217 · create_cash_receipt: 191,212,215,227 · void_cash_receipt: 212,227 · cancel_return: 190,191,213,227 · complete_return: 191 · _wf2b_recompute_receivable: 186,200,227 · get_invoiceable_lines: 183,212 · create_order_with_lines: 183 · cancel_purchase_invoice: 238,242 · cancel_supplier_return: 222,235 · complete_supplier_return: 222 · post_stock_issue: 222 · post_stock_import: 219 · cancel_stock_entry: 227 · finance_pnl: 187,192,228 · finance_cash_flow: 228 · bao_cao_so_ban: 218,228 · dashboard_summary: 192 · receivables_by_customer: 199 · receivables_by_rep: 195 · payables_summary: 231 · payroll_returns_for: 192 · assign_doc_seller: 182 · check_order_status_transition / close_order: 217 · guard_order_lines_locked: 172 · sync_return_credited_at: 188 · _apply_return_adds: 183,227 · _apply_return_edits: 181,183 · _pending_return_for: 189 · _tra_da_nhap_sau_lap_lai: 213,216 · _khoa_ghi_thang_phieu_tra: 227 · _chot_gia_dong_don: 229 · sua_phieu_nhap: 236 · save_pos_return: 227. Cách lấy bản thật: chạy `pg_get_functiondef` trên DB đang chạy.

---

## C. TRIGGERS & VIEWS

### Triggers (bảng — tên — thời điểm — hàm — mục đích)
- **sales_orders**: trg_sales_orders_assign_code (BI, cấp DH-seq) · trg_sales_orders_bump_edit (BU, sửa → DH-xxxx-n) · trg_check_order_status (BU status, kiểm chuyển trạng thái, USE_RPC nếu không qua RPC) · trg_log_order_status (AU → order_status_history) · trg_orders_guard_sales_user (BI/BU sales_user_id, chỉ NPP gán người khác) · trg_don_nguoi_tao (created_by = auth.uid) · trg_don_moi_moc_gui / trg_don_moi_lich_su (đơn gửi thẳng: submitted_at + lịch sử) · trg_quyen_giam_don (AI/AU subtotal, constraint deferred: quyền giảm giá cả đơn) · trg_sales_orders_before_delete (dọn phiếu trả chưa hoàn thành, chặn nếu có phiếu hoàn thành) · trg_zzz_sua_luc (updated_at) · [đã bỏ: trg_sync_workflow_stage]
- **sales_order_lines**: trg_guard_order_lines_locked (chặn sửa dòng đơn đã xuất/huỷ) · trg_quyen_gia_dong_don (`_chot_gia_dong_don`: SL>0, giá≥0, quyền giảm dòng + trần giá) · trg_khoa_ghi_thang_da_xuat (không ghi thẳng invoiced_qty) · trg_don_vi_rong_la_co_so · trg_log_sales_order_line (order_activity_log) · trg_zzz_sua_luc
- **sales_invoices**: trg_sync_invoiced_qty_status (AU status → cập nhật invoiced_qty dòng đơn) · trg_hoa_don_doi_nguoi (đổi người → nợ + phiếu trả theo) · trg_hoa_don_ngay_tru_hang_tra (đổi ngày/trạng thái → revenue_date phiếu tự sinh) · trg_zzz_sua_luc · trg_zzzz_tim_kd
- **sales_invoice_lines**: trg_sync_invoiced_qty (cộng invoiced_qty quy đổi) · trg_don_vi_rong_la_co_so · trg_zzz_sua_luc
- **returns**: trg_danh_so_phieu_tra (PT-) · trg_khoa_phieu_tra_tu_sinh · trg_khoa_ghi_thang_phieu_tra · trg_phieu_tra_theo_nguoi_hoa_don · trg_phieu_tra_doi_nguoi_cong_no · trg_phieu_tra_dung_khach_hoa_don · trg_phieu_tra_hoan_thanh_gan_hd · trg_phieu_tra_doi_can_tru · trg_returns_credited_at · trg_zz_returns_revenue_date · trg_returns_guard_sales_user · trg_zzz_sua_luc · trg_zzzz_tim_kd · [đã bỏ: trg_auto_restock_return (120)]
- **return_lines**: trg_sync_return_credit (credit_note_amount) · trg_gia_tran_dong_tra · trg_khoa_dong_tra_tu_sinh · trg_khoa_ghi_thang_dong_tra · trg_don_vi_rong_la_co_so · trg_zzz_sua_luc · [đã bỏ: trg_return_lines_sync_credit (055), trg_return_lines_cap (158)]
- **receivables**: trg_cong_no_am_trang_thai · trg_cong_no_giu_ve_npp · trg_khoa_ghi_thang_cong_no
- **payments / cash_receipts / cash_receipt_lines**: trg_khoa_ghi_thang_payments / _phieu_thu / _dong_phieu_thu · trg_fill_crl_invoice_id
- **payables / payable_payments**: trg_khoa_ghi_thang_no_ncc / _chi_ncc (227) · trg_tra_truoc_vao_no_moi (242)
- **purchase_invoices**: trg_gia_nhap_tu_phieu (→ purchase_price_lists)
- **supplier_returns**: trg_danh_so_tra_ncc (PTNCC-)
- **suppliers**: trg_ncc_chan_xoa · trg_ncc_xoa_qua_rpc · trg_ncc_nguoi_tao · trg_tim_kd
- **batches**: trg_batches_auto_zone_ins/upd (gần hạn → date) · trg_khoa_ghi_thang_lo · trg_zzzz_tim_kd
- **stock_entries / stock_entry_lines**: trg_khoa_ghi_thang_phieu_kho / _dong_kho · trg_zzzz_tim_kd
- **customers**: trg_tim_kd · trg_khoa_vi_tri_diem_ban · trg_phien_khach_ban (STMT)
- **customer_photos**: trg_khoa_anh_diem_ban · trg_bao_anh_dau_cho_duyet
- **products / price_lists / product_units**: trg_phien_danh_muc_ban (STMT) · products trg_tim_kd
- **customer_groups / customer_assignments / user_permission_overrides / role_permissions**: trg_phien_khach_ban (STMT)
- **users**: trg_block_driver_role · trg_zzzz_tim_kd
- **organizations**: trg_gieo_quyen_npp_moi (seed role_permissions)
- **payroll_run_items**: trg_enforce_payroll_lock · trg_tinh_luong_thuc_nhan
- Touch triggers: approval_rules, expenses, pricing_rules, role_permissions, sales_routes, workflow_sessions.
- tim_kd (249): trg_zzzz_tim_kd trên batches, stock_entries, payables, cash_receipts, invoices, returns, sales_orders, sales_invoices, users (luôn chạy sau trigger đặt mã).

### Views
- **v_hoa_don_con_lai** [257, security_invoker]: `sales_invoices.*` + `con_lai` = tiền HĐ − hàng trả đã trừ (luật creditCounted; truy vấn con theo từng tờ).
- **v_stock_balance_by_zone** [107]: tồn + giá trị theo sản phẩm × zone, đọc batches.
- **v_stock_movements** [228]: thẻ kho (dòng phiếu kho + đầu phiếu + số dư lũy kế; chuyển kho tách 2 dòng).
- **v_uom_audit** [228]: dòng phiếu kho nghi sai quy đổi.
- Đã DROP: v_sales_order_line_picked (119).

---

## D. RLS / PHÂN QUYỀN
- **Hàm nền**: `user_org_id()` / `user_role()` (SECURITY DEFINER, đọc users theo auth.uid(), NULL nếu is_active=false → mọi policy chặn). Policy viết `(SELECT user_org_id())` để tính 1 lần/câu (250/260).
- **Vai (users.role)**: owner, manager, accountant, sales, warehouse, driver (driver ngưng dùng, 122). TS: `Role` trong src/types.
- **role_permissions** (org, role, module, action): module = mô-đun hoặc khoá tính năng `a.b` (orders, customers, customers.visits, customers.handover, customers.approve, customer.view_all, promotions, commissions, returns, purchasing.invoices, purchasing.returns, suppliers, payables, inventory, inventory.cost, products, receivables(.by_customer/.by_rep), finance.cash_receipts/opening_balances/expenses, invoices, einvoice.config, hr, analytics.*, reports.*, settings(.users/.permissions/.org/.approval_rules)); action ∈ read, create, update, delete, approve, export.
- **user_has_permission(uid, 'module.action')**: override (user_permission_overrides, cùng org) > owner luôn true > role_permissions (tách ở dấu chấm CUỐI) > false. Seed mặc định `_gieo_quyen_mac_dinh`: manager orders.approve/update, returns.approve, inventory.approve; sales orders.update, receivables.create; accountant receivables.create/update. App có `defaultRoles` cho ô riêng không thừa hưởng mô-đun cha (`src/lib/permissions.ts`, `permissions-features.ts`).
- **Bảng scope theo org**: tất cả bảng có org_id (policy `org_id = user_org_id()`); bảng con (lines, consumptions…) qua EXISTS bảng cha.
- **NVBH (sales) bị giới hạn**:
  - customers: owner/manager/accountant hoặc `customer.view_all`, hoặc có customer_assignments active của mình, hoặc created_by = mình, hoặc `id IN khach_toi_da_ban()` (khách có đơn đứng tên mình) [154/260].
  - sales_orders: nháp chỉ người đứng tên thấy (kể cả chủ NPP, 161); NVBH thấy đơn sales_user_id = mình hoặc khách mình phụ trách.
  - sales_invoices: sales_user_id = mình hoặc đơn của mình (124).
  - receivables: sales_user_id = mình (002).
  - returns: mình lập, đứng tên mình, hoặc gắn HĐ/đơn của mình (198); sửa/xoá nháp của mình (165).
  - products: chỉ hàng có primary_supplier_id ∈ user_suppliers của mình (hoặc NULL) (081).
  - payments/cash_receipts: của mình (092/034); invoices (HĐĐT): đơn của mình (084).
  - HR (hr_salary_config, hr_monthly_bonus, hr_attendance, payroll_*): không đọc (197/173); dùng my_sales_target, my_payslips.
  - Từ 202: NVBH mặc định chỉ có mô-đun Bán hàng + công nợ / báo cáo bán / phiếu lương của mình; xem trả hàng (208).
- **Ghi**: tiền/tồn/trạng thái chỉ qua RPC; trigger `_khoa_ghi_thang_*` chặn vai authenticated ghi thẳng (`_la_trinh_duyet`). Hàm SECURITY DEFINER nội bộ REVOKE khỏi PUBLIC/anon/authenticated (166/207).
- **Kho/phiếu kho**: ghi chỉ owner/warehouse + RPC; duyệt kiểm kê owner/manager. Công nợ NCC / phiếu nhập: owner/manager/accountant.

---

## E. ĐÁNH SỐ CHỨNG TỪ
Không dùng sequence Postgres. Mẫu chung: `seq = MAX(seq)+1` trong org, khoá `pg_advisory_xact_lock(hashtext(...))`. `_so_chung_tu(n)` = lpad tối thiểu 4 chữ số, không cắt khi > 9999 (237).
| Chứng từ | Định dạng | Cơ chế |
|---|---|---|
| Đơn hàng | DH-0001; sửa lần n → DH-0001-n | sales_orders.order_seq + edit_no; trigger BI/BU (130); `_next_order_seq`, `_order_code` |
| Hoá đơn bán | HD-0001; sửa lần n → HD-0001-n | invoice_seq + reissue_no; `_wf2b_next_invoice_seq`, `_inv_code` (128/151) |
| Phiếu trả khách | PT-0001 (trước 237: TH-0001) | return_seq; trigger `_danh_so_phieu_tra` (193), `_ma_phieu_tra` |
| Phiếu nhập hàng NCC | PN-0001 | `next_purchase_receipt_code` lúc hoàn thành (142/237) |
| Phiếu trả NCC | PTNCC-0001 (đánh lại cả phiếu cũ; mã cũ ở return_code_cu) | return_seq; trigger `_danh_so_tra_ncc` (240) |
| Phiếu chi trả NCC | PCNCC-0001 | supplier_payments.seq (242) |
| Phiếu thu | PT-YYMMDD-NNNN (4 số ngẫu nhiên, thử lại 5 lần khi trùng UQ) | create_cash_receipt (120). ⚠ cùng tiền tố PT- với phiếu trả khách |
| Phiếu xuất bán | XK-YYMMDD-HHMMSS | `_wf2_export_order` |
| Phiếu nhập hoàn kho (huỷ HĐ / trả hàng) | NK-YYMMDD-HHMMSS | cancel_invoice / complete_return |
| Phiếu kho do app sinh | IN-YYYYMMDD-NNNN (nhập kho), ST-…/WH-… (kiểm kê), XKL-/CKL-<base36> (xuất lẻ/chuyển kho), NL-… (nhập lại hàng trả cũ), RESTOCK-… (mã lô) | client-side, không unique toàn cục |
| Lượt soạn | SH-dd/mm-NN | tao_luot_soan (225) |
| Hoá đơn điện tử | Số do MISA cấp (misa_inv_series + misa_inv_no, mã CQT misa_invoice_code) | API MISA |

---

## F. QUY ƯỚC TIỀN / ĐƠN VỊ
- **Làm tròn**: tiền VND làm tròn về đồng. Đơn giá sau giảm dòng làm tròn ở đơn giá (`netPriceOf`). Hoá đơn: subtotal=round(Σline−giảm đơn), vat=round(Σ line×vat_rate), total=round(sub_raw+vat_raw) — làm tròn ở TỔNG, không ở dòng. `chotTienChungTu` (src/lib/analytics/hang-ban-nhan-vien.ts): báo cáo cấp nhân viên lấy TIỀN CHỨNG TỪ (sales_invoices.total − credit_note_amount, gồm VAT, sau giảm đơn, đã làm tròn) thay vì cộng dòng; cột "Thuế + làm tròn" = tiền chứng từ − Σ line_total + giảm đơn.
- **Thuế**: `vat_rate` là TỈ LỆ 0..1 ở mọi bảng (products default 0 từ mig 110; supplier_return_lines đổi từ % sang tỉ lệ ở 141). Bán: thuế tính trên giá dòng (sau giảm dòng), TRƯỚC giảm đơn; chụp vào sales_invoice_lines.vat_rate; sales_order_lines.vat_rate NULL = theo SP. Mua: vat = vat_override ?? Σ(line×vat_rate).
- **Giảm giá bán**: (1) dòng — `unit_price` đã là giá sau giảm; `line_discount` chỉ GHI NHỚ = SL×(giá bảng − giá áp) hoặc khoản giảm; line_total = SL×unit_price (không trừ lần 2). Giảm thật được kiểm = MAX(line_discount, SL×(giá bảng−đơn giá)). (2) cả đơn — không có cột riêng: giảm = Σ SL×unit_price − subtotal (`giamCuaChungTu` / `_giam_don_hien_tai`); `%` tính trên tiền gộp, kẹp [0, tiền hàng]. Quyền: users.allow_discount + discount_max_type ('pct'|'vnd') + discount_max_value (NULL = không trần); owner/accountant toàn quyền. Trần giá: giá ≤ giá bảng × (1 + users.price_edit_max_increase_pct) nếu allow_price_edit; NVBH không quyền → trần = giá bảng; sàn = giá bảng (229/230; trả hàng tham chiếu giá đã bán trên HĐ).
- **Giảm giá mua**: line_discount TRỪ THẬT; discount đầu phiếu trừ SAU thuế.
- **Đơn vị / quy đổi**: products.base_unit + product_units(unit_name, conversion = số đơn vị cơ sở). Dòng chụp hệ số: sales_order_lines.conversion_factor, sales_invoice_lines.conversion_factor (máy chủ tra, Sửa HĐ giữ hệ số tờ cũ), purchase_invoice_lines/supplier_return_lines.conversion_factor, stock_entry_lines.conversion_factor_snapshot + qty_in_transaction_uom + transaction_uom + qty_in_base_uom (NOT NULL). return_lines KHÔNG có hệ số (tra product_units). invoiced_qty theo đơn vị dòng đơn (quy đổi, 179). Báo cáo cộng SL quy về đơn vị cơ sở (`soLuongCoSo`, `heSoQuyDoi` — ưu tiên hệ số chụp).
- **unit_cost**: giá vốn mỗi ĐƠN VỊ CƠ SỞ (batches.unit_cost bình quân nhập; stock_entry_lines.unit_cost; stock_line_consumptions.unit_cost). COGS = qty_in_base_uom × unit_cost (187). Tồn/lô theo đơn vị cơ sở (numeric từ 107).
- **Bảng giá bán** (`_gia_bang_don_vi` = `unitPriceFor`, 4 bậc): (1) price_lists theo nhóm khách (group_id = customers.group_id) + đúng unit_name; (2) price_lists chung (group_id NULL); (3) đơn vị cơ sở → products.sell_price; (4) đơn vị quy đổi → giá cơ sở × conversion. Trùng → giá thấp nhất. 0 = chưa có giá. effective_from/to không dùng. Giá nhập: purchase_price_lists (1 giá/(SP, đơn vị)).
- **Kho bán**: chỉ zone 'sale' được bán (138); 'date' = cận hạn.
- **Ngày**: invoice_date / receipt_date / order_date theo giờ VN (`vn_today()`); doanh thu theo invoice_date; hàng trả trừ theo returns.revenue_date.
- **Doanh thu / công nợ**: doanh thu = Σ sales_invoices.total posted; thuần = − credit_note_amount (hàng đổi không tính). Nợ = Σ(amount − paid) trên status <> 'paid', không kẹp 0. Hạn mức = nợ hiện có + đơn này so với credit_limit.

---

## G. PHỤ LỤC — DANH SÁCH MIGRATION (changelog)
001_schema · 002_rls_policies · 003_seed · 004_fix_rls_permissions · 005_fix_customers_recursion · 006_suppliers · 007_hr_module · 008_fix_security_audit · 009_business_flow_p1 · 010_supplier_payables · 011_misa_invoice · 012_purchase_orders · 013_approval_rules · 014_visit_photos · 015_notifications · 016_inventory_costs_expenses · 017_stock_entries_order_link · 018_sales_routes · 019_delivery_settlement · 020_cash_receipts · 021_pricing_rules · 022_role_permissions · 023_products_extras · 024_permissions_features · 025_products_price_edit · 026_salary_bypass_attendance · 027_user_price_edit · 028_warehouse_zones · 029_line_notes · 030_products_supplier · 031_hr_bonus_extensions · 032_customers_created_by · 033_per_user_data_filtering · 034_per_user_data_filtering_part2 · 035_return_exchange · 036_rls_repair · 037_fix_rls_recursion · 038_delivery_goods_handover · 039_uom_conversion_fix · 040_fifo_layers · 041_user_permission_overrides · 042_customer_row_level · 043_payroll_per_user_bonuses · 044_workflow_stage · 045_workflow_sessions · 046_entity_locks · 047_driver_handovers · 048_stock_balance_views · 049_swap_stock · 050_payroll · 051_handover_swap_link · 052_order_activity_log · 053_entity_locks_cron · 054_user_has_permission_fix · 055_return_credit_excludes_exchange · 056_deliveries_source_stock_entry · 057_handover_batch_code_fix · 058_user_has_permission_split_last_dot · 059_allow_delivering_to_cancelled · 060_payroll_skip_attendance · 061_hr_salary_kpi_target_revenue · 062_payroll_kpi_cumulative · 063_payroll_low_perf_rules_vs_target · 064_payroll_allowances_and_breakdown · 065_purchase_invoice_simplified · 066_payroll_sales_only · 067_payroll_no_allowance_when_under_60 · 068_supplier_returns · 069_return_lines_vat · 070_supplier_return_stock_line_uom · 071_supplier_return_better_stock_error · 072_einvoice_misa · 073_drop_customers_channel_check · 074_drop_pricing_price_columns · 075_einvoice_misa_paths · 076_einvoice_misa_appid_signtype · 077_einvoice_webapi_v2 · 078_einvoice_v3sainvoice · 079_einvoice_misa_with_code · 080_user_suppliers · 081_products_supplier_scope · 082_search_customer_dupes · 083_claim_customer_for_me · 084_invoices_sales_scope · 085_login_by_username_phone · 086_allow_oversell · 087_qr_login · 088_qr_token_isolation · 089_order_client_request_id · 090_fix_role_permissions_module_check · 091_backfill_missing_objects · 092_rls_hardening · 093_aggregate_functions · 094_payroll_revenue_and_manual_edits · 095_payroll_net_revenue · 096_payroll_net_revenue_fixes · 097_returns_credited_at · 098_stock_value_zero_fallback · 099_einvoice_refid_split · 100_misa_invoice_snapshots · 101_pod_photos_bucket · 102_opening_balances · 103_customer_photos · 104_login_by_phone · 105_drop_username_login · 106_owner_login_by_phone · 107_fifo_one_ledger · 108_default_vat_8 · 109_set_all_products_vat_8 · 110_default_vat_0 · 111_set_all_products_vat_0 · 112_backfill_customer_creator · 113_delete_cancelled_orders · 114_fix_activity_log_on_order_delete · 115_sales_edit_after_approval · 116_grant_sales_order_update · 117_sales_delete_own_draft · 118_delete_order_cleans_returns · 119_workflow_v2 · 120_workflow_v2_rpcs · 121_credit_balance_aggregates · 122_retire_driver_role · 123_post_stock_adjustment · 124_wf2b_sales_invoices · 125_wf2b_invoice_rpcs · 126_wf2b_revenue_from_invoices · 127_wf2b_returns_and_receipts · 128_invoice_code_no_date · 129_order_delete_sweeps_returns · 130_order_code_no_date · 131_cancel_invoice_keeps_returns · 132_backfill_missing_receivables · 133_return_credit_rides_invoice · 134_return_cap_per_customer · 135_cancel_invoice_returns_to_draft · 136_committed_stock · 137_committed_stock_stable_order · 138_sale_zone_only · 139_cancel_stock_entry · 140_vn_today · 141_supplier_return_vat_ratio · 142_purchase_receipt · 143_cancel_supplier_return · 144_stock_issue · 145_purchase_receipt_vat_override · 146_supplier_return_same_shape · 147_cancel_supplier_return_sum_by_batch · 148_stock_transfer · 149_reissue_updates_returns · 150_reissue_ambiguous_invoice_id · 151_reissue_keeps_invoice_seq · 152_invoice_adds_return_lines · 153_order_sales_user_guard · 154_sales_sees_customer_of_own_order · 155_guard_sales_user_on_update · 156_restock_any_zone · 157_restock_no_phantom · 158_return_any_product · 159_return_line_reason · 160_return_sales_user · 161_giu_don_nhap_kin · 162_huy_hoa_don_roi_sua_don_duoc · 163_khoa_chinh_sach_theo_npp · 164_doi_soat_tien_da_thu_ma_cong_no_chua_tru · 165_nvbh_sua_xoa_phieu_tra_nhap_cua_minh · 166_va_lo_quyen_rpc_va_cheo_npp · 167_tra_tien_ncc_mot_giao_dich · 168_nhap_kho_mot_giao_dich · 169_tao_don_mot_giao_dich · 170_khoa_ghi_thang_so_kho · 171_lap_phieu_tra_mot_giao_dich · 172_khoa_dong_don_da_huy · 173_bang_luong_ke_toan_va_luong_thuc_nhan · 174_hoa_don_tu_tra_he_so · 175_don_vi_rong_la_don_vi_co_so · 176_don_vi_co_so_khong_rong · 177_tim_khong_dau · 178_nguoi_tao_nguoi_duoc_gan · 179_da_xuat_quy_doi_don_vi · 180_xuat_hang_sua_hang_tra · 181_sua_hang_tra_doi_quy_cach · 182_nguoi_duoc_gan_theo_hoa_don · 183_hoa_don_be_du_truong_tu_don · 184_lap_lai_hoa_don_chuyen_phieu_thu · 185_quyen_giam_gia_nhan_vien · 186_cong_no_am · 187_gia_von_lai_lo_don_vi_co_so · 188_ngay_tra_hang · 189_hang_tra_luc_xuat_hoa_don · 190_luu_phieu_tra_pos · 191_luat_phieu_tra_tu_sinh_va_tu_lap · 192_doanh_so_thuan_tru_hang_tra · 193_ma_phieu_tra_th · 194_nguoi_dung_ten_cong_no_khop_doanh_so · 195_cong_no_theo_nv_bo_kep_0 · 196_muc_tieu_doanh_so_nvbh · 197_khoa_nhan_su_voi_nvbh · 198_nvbh_doc_phieu_tra_cua_minh · 199_cong_no_theo_khach_bo_kep_0 · 200_phieu_tra_hoan_thanh_gan_hd · 201_phieu_luong_cua_toi · 202_nvbh_chi_con_ban_hang · 203_tim_khach_theo_dia_chi · 204_bao_cao_mot_luot · 205_tim_kiem_chung · 206_dem_theo_nhom · 207_don_canh_bao_bao_mat · 208_nvbh_xem_tra_hang · 209_phien_danh_muc_ban · 210_sua_hoa_don_co_phieu_tra_da_nhap · 211_ngay_nhap_kho_phieu_tra_tu_sinh · 212_sua_sai_tien_cong_no_phieu_thu · 213_sua_hd_giu_ngay_giam_gia_phieu_tu_lap · 214_khoa_ghi_thang_tien_phieu_tra · 215_diem_chot_don_dong_phieu_thu_trung_quyen · 216_sua_hd_phieu_tra_ve_cho_xu_ly · 217_huy_hd_huy_don_mot_don_mot_hd · 218_chenh_lech_gia_luc_ban · 219_nhap_kho_chon_kho_nhan · 220_gio_sua_cuoi_chung_tu · 221_nhac_khach_chua_tuyen · 222_xuat_am_moi_phieu_kho · 223_nhan_vien_nghi_viec · 224_danh_dau_da_soan_hang · 225_luot_soan_hang · 226_sua_loi_ban_hang · 227_sua_loi_hoa_don_tra_hang_cong_no · 228_sua_loi_kho_bao_cao · 229_chan_gia_tran_may_chu · 230_chan_gia_tran_phieu_tra · 231_cong_no_ncc_khong_kep_am · 232_nha_cung_cap_chi_tiet_xoa_gop · 233_xoa_ncc_kem_mat_hang · 234_bang_gia_nhap · 235_sua_phieu_nhap_da_ban · 236_sua_phieu_nhap_safeupdate · 237_ma_phieu_tra_pt · 238_huy_phieu_nhap_ton_am · 239_cong_no_ncc_hang_tra_lai · 240_ma_tra_ncc_ptncc · 241_khoi_phuc_phieu_ncc · 242_phieu_chi_tra_ncc · 243_can_doi_tra_truoc_ncc · 244_duyet_anh_diem_ban · 245_tim_khach_trung_dung_so · 246_ban_giao_khach · 247_sua_hd_giu_he_so_to_cu · 248_ban_giao_khach_tra_quyen · 249_luu_khoa_tim_chung_tu · 250_soat_quyen_tinh_mot_lan · 251_tat_jit_cho_app · 252_tat_jit_vai_dang_nhap · 253_khach_thieu_anh_rpc · 254_phien_khach_ban · 255_ton_kho_trang · 256_bao_cao_doc_nhanh · 257_tong_danh_sach_may_chu · 258_ham_phu_plpgsql · 259_ham_phu_plpgsql_dot2 · 260_rls_khach_tinh_mot_lan

## Ghi chú cho mapping ERPNext
- Vòng đời: Sales Order (draft/submitted → completed/cancelled) → Sales Invoice có update_stock (posted = submitted docstatus 1, cancelled = 2; sửa = cancel+amend giữ số "-n").
- Phiếu trả tự sinh (`credit_with_invoice`) ≈ Credit Note trừ ngay vào HĐ, còn bước nhập kho treo ở "Chờ xử lý". Phiếu tự lập ≈ Sales Return độc lập: nhập kho và ghi nợ âm cùng lúc.
- `receivables` ≈ Payment Ledger. Công nợ được phép âm (dư có). Phiếu thu ≈ Payment Entry phân bổ theo hạn cũ trước.
- `batches` + zone sale/date ≈ Batch + 2 Warehouse. Kiểm kê ≈ Stock Reconciliation. Xuất lẻ ≈ Material Issue. Chuyển kho ≈ Material Transfer. FIFO ≈ valuation FIFO.
- `purchase_invoices` ≈ Purchase Invoice có update_stock. `supplier_returns` ≈ Debit Note. `supplier_payments` ≈ Payment Entry trả NCC (advance khi trả dư).
- Bảng giá ≈ Price List theo nhóm khách + UOM. Quyền giảm/sửa giá theo từng user cần custom field trên User/Employee.
- Đơn giá trên dòng bán đã là giá sau giảm. `line_discount` chỉ để ghi nhớ, không trừ lần hai.
