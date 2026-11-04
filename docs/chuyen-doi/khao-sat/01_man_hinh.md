> Khảo sát tự động 04/11/2026 từ mã nguồn `nppsale` (nhánh `claude/elegant-hamilton-ak996q`, HEAD 58158b1). Đây là tài liệu tham chiếu, không phải quyết định.


# Inventory màn hình — npp.sale (Next.js 14 + Supabase) → tham chiếu dựng lại SPA portal trên ERPNext

## Quy ước

**Vai trò** (`src/types/index.ts`, nhãn trong `src/lib/constants.ts` `ROLE_LABELS`):

| Mã | Tên |
|---|---|
| owner | Chủ NPP |
| manager | Quản lý bán hàng |
| accountant | Kế toán |
| sales | NV Bán hàng (NVBH) |
| warehouse | NV Kho |
| driver | Tài xế (ngưng dùng — đã khoá, mig 122) |

- **BO** (`BACK_OFFICE`) = owner + manager + accountant.
- **BO+K** = BO + warehouse.
- Quyền mặc định nằm ở `DEFAULT_PERMISSION_MAP` (`src/lib/permissions.ts`). Ô quyền chi tiết nằm ở `FEATURES` (`src/lib/permissions-features.ts`).
- Ô có `defaultRoles` là **ô riêng**: không thừa hưởng quyền của mô-đun cha (`laORieng`).

**Gác cửa trang**
- Mỗi trang gọi `useRoleGuard("<module>")`. Hook này gọi `duocVaoTrang(role, pathname, module)` trong `src/lib/nav/nav-permission.ts`.
- Thứ tự kiểm:
  1. `LEGACY_V2_HREFS` → chặn.
  2. Có trong `NAV_PERMISSION` → `canEnterHref`.
  3. Có trong `CUA_VAO` → kiểm theo dòng đó.
  4. Đường dẫn động → kiểm như mục cha (`NAV_TIEN_TO`).
  5. Còn lại → kiểm theo mô-đun.
- Quyền riêng từng người (`user_permission_overrides`) được xét trước quyền vai trò.

**Thiết bị** (cột "Máy")
- **Cả hai (tách)**: trang dùng `useKhoMay()` để dựng hai cây component riêng cho máy tính và điện thoại.
- **Cả hai (DocList)**: trang dùng `DocListLayout`. Máy tính hiện `DocTable`, điện thoại hiện `DocCardList` + `DocListMobileHead` (đầu trang xanh).
- **ĐT→POS**: trang cho điện thoại. Máy tính rộng ≥1024px bị `PosDesktopRedirect` (phía trình duyệt) hoặc middleware 307 (`dichPosMayChu` + cookie `npp_kho`) chuyển sang màn `/pos/...`.
- **MT**: dựng cho máy tính, vẫn co giãn được.
- Breakpoint giao diện là `lg` = 1024px. `POS_MIN_WIDTH` = 1024, nhưng thông báo của POS shell ghi "1280px trở lên".

---

## 1. Bảng route theo module

### 1.1 Bán hàng / POS (máy tính) — `src/app/pos/**`
Layout `pos/layout.tsx` bọc theo thứ tự: `PosSettingsProvider` › `NapHoSo` › `PosRefDataProvider` › `PosTabsProvider` › `PosProductSearchProvider` › `PosShell`. Không có menu dashboard. POS **không** gọi `useRoleGuard`; quyền dựa vào middleware đăng nhập, RLS và `hasPermission` ở từng nút.

| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /pos | Mở chứng từ mới | BO, kho | MT | Trang gốc POS khi chưa có tab nào | 4 nút mở tab: Đơn đặt hàng (SO), Phiếu trả hàng (RET), Phiếu nhập hàng (PUR), Phiếu trả NCC (PRET) | store `usePosTabs` | Không được trả 404 khi đóng tab cuối. Hoá đơn không lập trực tiếp mà đi từ "Xuất hàng & lập HĐ" |
| /pos/don-hang/[id] (`moi` = mới, `?customerId=`) | Đơn đặt hàng (MÀN 1) | owner/manager/sales trên máy tính | MT | Lập đơn hoặc xem tiếp đơn | Thêm SP (F2/F3), chọn khách (F4), hàng đổi (F7), hàng trả (F8), Lưu nháp (F6), Gửi đơn (F9), Xuất hàng & lập HĐ, In (`inTaiCho` → `/in/don-hang`), gán NV bán (`SellerPicker`) | `OrderScreen`: `sales_orders`, `sales_invoices`, `returns`; RPC `create_order_with_lines`, `assign_doc_seller`; danh mục `loadSellRefData` (products, price lists, units, customers, `danh_muc_ban_phien`, `ton_ban_theo_hang`), `loadLastPrices` | Dòng mới lên đầu (`themLenDau`). Khối hàng đổi trả có trần `max-h-[42vh]`. Bấm thẻ khách mở `KhachPosModal` |
| /pos/don-hang/[id]/sua | Sửa đơn hàng (MÀN 1b) | như trên | MT | Sửa đơn đã lưu | như trên, kèm `DeltaPreviewStrip` | `OrderScreen mode="sua"` | Đích của `/sell/edit/<id>` trên máy tính. Có khoá thực thể |
| /pos/hoa-don/moi?order=<id> | Xuất hàng (lập HĐ từ đơn) | owner, manager, accountant, warehouse | MT | Lập hoá đơn bán từ đơn | Sửa SL giao, hàng đổi/trả (F7/F8), Xuất hàng (F9) → tự in `/in/hoa-don/<id>?auto=1` qua `inTaiCho` | `InvoiceScreen`: RPC `get_invoiceable_lines` (gọi GET), `post_invoice`; đọc `sales_orders`, `sales_invoices`, `returns`, `invoices`, `cash_receipt_lines` | Một đơn chỉ một HĐ (mig 217). Khi chưa biết kết quả ghi thì `kiemLaiSauLoiXuat` hỏi lại sổ. Có `beforeunload` khi đang ghi |
| /pos/hoa-don/[id] (`?daXuat=1`) | Hóa đơn bán — xem (MÀN 2) | như trên | MT | Xem HĐ, 3 bậc công nợ | In, Trả hàng (→ `/pos/tra-hang/moi?invoice=`), Phát hành HĐĐT (→ màn web), Sửa HĐ, gán NV | `sales_invoices`, `sales_invoice_lines`, `returns`, `cash_receipt_lines`; `RelatedDocs` | `?daXuat=1` hiện dải nhắc In. Phép trừ hàng trả đi qua `invoice-credit.ts` |
| /pos/hoa-don/[id]/sua | Sửa hoá đơn | như trên | MT | Lập lại HĐ (`reissue_invoice`) | Lưu (F9), hỏi "Cần huỷ phiếu nhập trước?" | RPC `reissue_invoice`, `get_invoiceable_lines` | Giữ hệ số quy đổi của tờ cũ (mig 247) |
| /pos/tra-hang/[id] (`moi?invoice=`/`?customerId=`) | Phiếu trả hàng (MÀN 3) | BO, kho, sales | MT | Khách trả / đổi hàng | Chọn HĐ gốc (`SourceInvoiceModal`), Thêm hàng, Lưu nháp, Hoàn thành, In → `/in/tra-hang` | RPC `save_pos_return`, `create_return_with_lines`, `complete_return`/`cancel_return`; `returns`, `sales_invoices` | Phiếu tự sinh khác phiếu tự lập (`hanhDongPhieuTra`) |
| /pos/tra-hang/[id]/sua | Sửa phiếu trả đã nhập kho (MÀN 8) | như trên | MT | Sửa phiếu đã ghi nhận | Lưu | `ReturnScreen mode="sua"` | Có huy hiệu "ĐÃ NHẬP KHO" |
| /pos/nhap-hang/[id] (`moi?ncc=`) | Phiếu nhập hàng (MÀN 9) | owner, manager, accountant, warehouse (`duocGhiMuaHang`) | MT | Nhập hàng từ NCC | Thêm SP, chọn NCC (F4), Lưu nháp/Lưu tạm, Hoàn thành (cộng kho + công nợ NCC) | `PurchaseScreen`: `purchase_invoices`, `purchase_invoice_lines`, `suppliers`; RPC `complete_purchase_invoice`, `sua_phieu_nhap` | Nhãn và nút theo **trạng thái thật** (`manPhieuNcc`). Không tải sổ khách |
| /pos/nhap-hang/[id]/sua | Sửa phiếu nhập (MÀN 10) | như trên | MT | Sửa phiếu nhập | như trên | như trên | |
| /pos/tra-ncc/[id] (`moi?ncc=`) | Phiếu trả NCC (MÀN 11) | BO+K | MT | Trả hàng cho NCC | Lưu nháp, Xuất kho | `SupplierReturnScreen`: `supplier_returns`; RPC `complete_supplier_return`, `cancel_supplier_return` | Ở phiếu đã xuất, "lưu nháp" nghĩa là huỷ phiếu |
| /pos/tra-ncc/[id]/sua | Sửa phiếu trả NCC (MÀN 12) | như trên | MT | Sửa phiếu đã xuất (giữ số phiếu) | Lưu | như trên | |

### 1.2 Bán hàng trên điện thoại — `/sell/**`
Layout `sell/layout.tsx` gồm: `SellDataProvider`, `SellCartProvider`, `CommittedStockProvider`, `SellPrefetch`, `DonDoModal` (hỏi đơn dở dang). Quyền: `orders` + action `create`.

| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /sell (`?customerId=`) | Bán hàng — Thêm hàng | sales, owner, manager | ĐT→POS | Chọn hàng vào giỏ | Tìm SP, `ProductCard` +/−, Tạo SP nhanh, Tải lại danh mục, sang giỏ | `useSellData` → `loadSellRefData` (products, price lists, units, `ton_ban_theo_hang`, cache IndexedDB) | Luồng tác vụ: ẩn thanh nav dưới. Máy tính đi `/pos/don-hang/moi` |
| /sell/customer | Chọn khách hàng | như trên | ĐT | Chọn hoặc tạo khách cho đơn | Tìm, `TaoNhanhKhach` (lọc trùng SĐT) | customers (RLS), `search_customer_dupes`, `claim_customer_for_me` | |
| /sell/cart | Đơn hàng (giỏ) | như trên | ĐT | Soạn đơn, sửa dòng | `LineEditSheet`, xoá dòng, Lưu tạm, Đặt hàng | `create_order_with_lines`; `approval_rules`, `receivables` (kiểm hạn mức) | Có thanh đáy riêng (`BottomBar`). Có số thứ tự dòng |
| /sell/terms | Điều khoản & giao hàng | như trên | ĐT | Ngày giao, ghi chú, thanh toán | Xong · về đơn hàng | giỏ (context) | |
| /sell/returns | Hàng trả / đổi | như trên | ĐT | Thêm hàng trả/đổi kèm đơn | `ReturnLineSheet`, `ReturnPriceInput` | giỏ | |
| /sell/scan | Quét mã vạch | như trên | ĐT | Quét mã thêm vào giỏ | `BarcodeScanner` | `findByCode` | |
| /sell/done | Đã gửi đơn | như trên | ĐT | Xác nhận đơn đã gửi | Xem danh sách đơn | — | |
| /sell/drafts | Đơn nháp | như trên | ĐT | Danh sách đơn nháp | Sửa đơn (`diHoacMoPos`), Xoá | `sales_orders`, `sales_order_lines` | |
| /sell/edit/[id] | Sửa đơn (điện thoại) | sales (đơn của mình), BO | ĐT→POS | Nạp đơn vào giỏ để sửa | Giữ giỏ / Thay giỏ | `sales_orders`, `sales_order_lines`, `returns` | Máy tính đi `/pos/don-hang/<id>/sua` |
| /sell/reorder/[id] | Đặt lại đơn | như trên | ĐT | Chép đơn cũ vào giỏ | Giữ / Thay giỏ | `sales_orders`, `sales_order_lines` | |

### 1.3 Đơn hàng
| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /orders | Đơn hàng (Quản lý đơn hàng) | mọi vai có `orders` (NVBH chỉ đơn của mình) | Cả hai (tách) | Danh sách đơn | Tạo đơn (`diHoacMoPos`/tab mới), Duyệt, Xuất hàng / Xuất đủ, Huỷ (`cancel_order`), chọn hàng loạt, lọc tuyến (`RouteFilter`), Xuất Excel, phát hành HĐĐT, ngăn xem nhanh `OrderDrawer` | `sales_orders` (`total.sum()` ở máy chủ), `sales_order_lines`, `invoices`, `receivables`, `sales_routes`, `users`; RPC `cancel_order`, `post_invoice`; `/api/einvoice/publish` | Máy tính: `DesktopOrderTable` + `OrderDrawer`. Điện thoại: `MobileOrdersScreen` (20 dòng/lượt). Có `loading.tsx` |
| /orders/[id] | Chi tiết đơn | như trên | Cả hai (tách: `MobileOrderDetail`) | Xem/sửa đơn, tiến trình, lịch sử | Duyệt đơn, Sửa đơn (POS tab mới), Xuất hàng, Huỷ đơn, Xoá vĩnh viễn, Đặt lại đơn này, In, Xuất Excel phiếu, sửa dòng tại chỗ | `sales_orders`, `sales_order_lines`, `order_status_history`, `order_activity_log`, `invoices`, `sales_invoices`, `returns`, `receivables`, `stock_entries`, `delivery_lines`; RPC `cancel_order`; khoá thực thể (`acquire/heartbeat/release_entity_lock`) | Tệp 3.093 dòng. Dùng `detail-chrome`, `customer-quick-view` |
| /orders/[id]/print | In đơn đặt hàng | như trên | MT/In | Mẫu in "ĐƠN ĐẶT HÀNG" | `PrintButton`, `?auto=1` tự in, `useLeaveAfterPrint` | `sales_orders`, `sales_order_lines`, `returns` | Chung mẫu `SalesInvoice`. POS dùng lại qua `/in/don-hang/[id]` |
| /orders/new | — | | | Chuyển hướng → `/sell?customerId=` | | | redirect |

### 1.4 Hoá đơn bán (sales_invoices)
| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /sales-invoices | Hóa đơn bán | quyền `orders` (NVBH chỉ HĐ của mình) | Cả hai (tách) | Danh sách HĐ, tiền **còn lại** sau hàng trả | Lọc nhanh, lọc tuyến, Sửa HĐ, Huỷ, Xuất Excel, ngăn `InvoiceDrawer` | `sales_invoices`, `v_hoa_don_con_lai` (`con_lai.sum()`), `sales_routes`, `users` | Máy tính: `DesktopInvoiceTable`. Điện thoại: `MobileOrdersScreen` |
| /sales-invoices/[id] | Chi tiết hóa đơn bán | như trên | Cả hai | Xem HĐ, cộng tiền, chứng từ liên quan | Sửa hóa đơn, Huỷ hóa đơn (`cancel_invoice` → đơn Đã huỷ), Phát hành HĐ điện tử, In, Xuất Excel phiếu | `sales_invoices`, `sales_invoice_lines`, `returns`, `invoices` | `RelatedDocs`, `InvoiceMoneySummary` |
| /sales-invoices/[id]/print | In hóa đơn bán | như trên | MT/In | Mẫu KiotViet, in cả hàng đổi/trả | Print, `?auto=1` | `sales_invoices`, `sales_invoice_lines`, `returns` | Dùng lại ở `/in/hoa-don/[id]` (POS, `inTaiCho`) |
| /sales-invoices/new?order= | Xuất hàng (điện thoại) | owner, manager, accountant, warehouse | ĐT→POS | Lập HĐ từ đơn | Xuất hàng, In hoá đơn | `InvoiceEditor`; `sales_orders`; `post_invoice` | Máy tính → `/pos/hoa-don/moi?order=` |
| /sales-invoices/[id]/edit | Sửa hóa đơn (điện thoại) | như trên | ĐT→POS | `reissue_invoice` | Lưu | `sales_invoices`, `sales_invoice_lines` | Máy tính → `/pos/hoa-don/<id>/sua` |

### 1.5 Hoá đơn điện tử (MISA) — `/invoices`
| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /invoices | Hóa đơn điện tử | owner, accountant (`invoices`) | Cả hai (DocList) | Danh sách HĐĐT | Tạo HĐ, Đối soát MISA | `invoices`, `company_einvoice_config` | |
| /invoices/[id] | Chi tiết HĐĐT | như trên | MT | Phát hành / làm mới trạng thái | Phát hành, Làm mới trạng thái, Khoá HĐ, Huỷ HĐ, Lưu, Xoá vĩnh viễn | `invoices`, `company_einvoice_config`; `/api/einvoice/publish`, `/api/einvoice/refresh-status` | |
| /invoices/[id]/print | In hóa đơn bán (HĐĐT) | như trên | In | In | PrintButton | `invoices`, `sales_orders`, `sales_order_lines`, `sales_invoice_lines` | |
| /invoices/new | Tạo hóa đơn mới | quyền `invoices.create` | MT | Lập HĐĐT từ đơn | Tạo, Huỷ | `invoices`, `sales_orders` | |
| /invoices/reconcile | Đối soát hoá đơn MISA | `invoices.update` | MT | Khớp HĐ MISA với sổ | Kéo snapshot, Nối tay, Dựng HĐ trong sổ | `misa_invoice_snapshots`; `/api/einvoice/reconcile-action`, `pull-snapshots` | |

### 1.6 Trả hàng (khách)
| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /returns | Trả hàng (Quản lý trả hàng / "Trả hàng của tôi" với NVBH) | owner, manager, warehouse, accountant (xem), sales (xem của mình) | Cả hai (tách) | Danh sách phiếu trả, tab Chờ xử lý | Lập phiếu, Hoàn thành/Huỷ nhập kho, Xuất Excel, `ReturnDrawer`/`MobileReturnSheet` | `returns`, `users`; đếm nhóm `reason,count()` | Phiếu tự sinh: "sửa từ hóa đơn" |
| /returns/[id] | Chi tiết phiếu trả | như trên | MT | Xem/sửa phiếu | Hoàn thành — nhập kho, Huỷ nhập kho, Huỷ phiếu trả, Lưu, Xoá vĩnh viễn, đổi ngày (`DoiNgayPhieuTra`), Xuất Excel, Mở hóa đơn | `returns`, `return_lines`; RPC `complete_return`, `cancel_return` | `returns.approve` để hoàn thành |
| /returns/[id]/print | In phiếu trả hàng | như trên | In | `ReturnSlip` | PrintButton, `inTaiCho` | `returns`, `return_lines` | Dùng lại ở `/in/tra-hang/[id]` |
| /returns/new (`?invoiceId=`/`?customerId=`) | Lập phiếu trả (điện thoại) | `returns.create` | ĐT→POS | Phiếu trả kiểu /sell | `PhieuTraKhachMobile`, tạo nhanh khách/SP | `customers`, `products`, `sales_invoices`, `sales_invoice_lines`, `returns`, `return_lines` | Thanh đáy riêng |

### 1.7 Công nợ phải thu
| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /receivables | Công nợ (Quản lý công nợ) | BO, sales (của mình) | Cả hai (DocList + `MobileRecordCard`) | Danh sách khoản nợ theo HĐ | Thu tiền, Sổ chi tiết, In | `receivables`; RPC `receivables_summary` | Mỗi khoản nợ = một HĐ đã ghi sổ (không theo đơn) |
| /receivables/[id] | Chi tiết khoản nợ | BO | MT | Thanh toán / xoá | Xác nhận thanh toán, Xoá vĩnh viễn | `receivables`, `payments` | |
| /receivables/aging | Sổ chi tiết Công nợ | BO | Cả hai | Sổ chi tiết theo khách | Chọn khách, In bản kê | `customers`, `receivables` | |
| /receivables/by-customer | Công nợ theo khách hàng | BO (+ sales nếu ô quyền mở) | Cả hai | Tổng hợp theo khách | Mở chi tiết | RPC `receivables_by_customer` | |
| /receivables/by-customer/[customerId] | Công nợ 1 khách | như trên | MT | Giao dịch, thanh toán | — | `customers`, `receivables`, `customer_assignments` | |
| /receivables/by-rep | Công nợ theo nhân viên | BO | Cả hai | Tổng hợp theo NV | Mở NV | RPC `receivables_by_rep` | |
| /receivables/by-rep/[userId] | Công nợ 1 NV | BO | MT | Khách nợ của NV | — | `receivables`, `users` | |
| /receivables/collect | Thu tiền | `receivables.create` (owner, manager, accountant) | Cả hai | Thu nợ nhanh và in phiếu | Chọn khoản, Xong, In phiếu TT200 | `customers`, `receivables`, `cash_receipts`; `create_cash_receipt` | `PaymentReceiptTT`. Từng là tab của driver |
| /finance/opening-balances | Công nợ đầu kỳ | BO | MT | Nhập nợ đầu kỳ từ Excel | Tải mẫu, Đọc file, Ghi | `lib/opening-balance/*` (`receivables` opening) | `downloadXlsx`, `StickyActionBar` |

### 1.8 Phiếu thu / Phiếu chi
| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /finance/cash-receipts | Phiếu thu | BO (`finance.cash_receipts`) | Cả hai (DocList) | Danh sách phiếu thu | Lập phiếu thu, lọc kỳ/trạng thái, Xuất Excel, `CashReceiptDrawer` | `cash_receipts`, `cash_receipt_lines`, `users` | |
| /finance/cash-receipts/new | Lập phiếu thu | `receivables.create` | Cả hai | Chọn khoản nợ, nhập tiền | Lập, tạo nhanh khách | `customers`, `receivables`, `returns`; RPC `create_cash_receipt` | `useKhoaGui` chống gửi 2 lần |
| /finance/cash-receipts/[id] | Chi tiết phiếu thu | BO | MT | Xem/huỷ/xác nhận | Huỷ phiếu thu (`void_cash_receipt`, bắt buộc lý do), Xác nhận đã nhận tiền, In TT200, Xuất Excel | `cash_receipts`, `cash_receipt_lines`, `payments`, `deliveries` | |
| /finance/expenses | Phiếu chi | BO (`finance.expenses`) | Cả hai (DocList) | Chi phí + phiếu chi trả NCC | Lập phiếu chi / chi trả NCC, Huỷ, Xuất Excel | `expenses`, `expense_categories`, `suppliers`; RPC `chi_tra_ncc`, `huy_phieu_chi_ncc` | `PhieuChiNccFields` |
| /finance/phieu-chi-ncc/[id] | Phiếu chi trả NCC | như trên | MT | Xem/huỷ | Huỷ | `lib/payables/phieu-chi-ncc` | |

### 1.9 Khách hàng (tuyến / PJP / ghé thăm / ảnh / bàn giao / hàng đã lấy)
| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /customers | Khách hàng | owner, manager, accountant, sales (khách của mình) | Cả hai (tách: `MobileCustomersScreen` / `CustomerTable`) | Danh sách khách | Thêm khách, Nhập Excel (lọc trùng), Xuất Excel, thao tác hàng loạt, lọc NV/phường/nhanh, Thu tiền, Tạo đơn | `customers`, `customer_assignments`, `receivables`, `sales_routes`, `pjp_routes`, `visit_logs`, `suppliers`, `user_suppliers`, `users` | Có `loading.tsx` |
| /customers/new (`?sdt=`) | Thêm khách hàng mới | `customers.create` | Cả hai (tách) | **Bước tìm trùng SĐT** rồi mới tới form | Tìm, Thêm vào DS của tôi, Tạo khách | RPC `search_customer_dupes`, `claim_customer_for_me`; `customers` | Khoá nút tạo khi tìm thấy khách. Thanh đáy riêng |
| /customers/[id] (`#anh-diem-ban`) | Hồ sơ khách | như trên | Cả hai | Hồ sơ, đơn, nợ, ảnh, phân công, hàng đã lấy, bảng giá | Sửa thông tin, Tạo đơn (POS tab mới), Ghi nhận thanh toán, Ghé thăm (`VisitCheckinDialog`), chụp ảnh/ghim vị trí, Duyệt ảnh, Xoá | `customers`, `customer_assignments`, `customer_photos`, `payments`, `pjp_routes`, `price_lists`, `receivables`, `sales_invoices`, `sales_orders`, `sales_order_lines`, `sales_routes`, `visit_logs`, ...; RPC ảnh (`duyet_anh_diem_ban`, `xin_doi_anh_diem_ban`...), `giao_cong_no_npp`, `hang_khach_da_lay` | `/api/customers/photo-cleanup` |
| /customers/routes | Tuyến bán hàng | owner, manager | MT | CRUD tuyến | Tạo/Sửa tuyến | `sales_routes`, `customers` | `RouteForm` |
| /customers/missing-photos | Điểm bán cần cập nhật | mọi người xem được khách | Cả hai | Khách thiếu ảnh / chờ duyệt | Mở để chụp/duyệt, Tải thêm | RPC `khach_thieu_anh`, `khach_cho_duyet_anh` (lùi về đọc trực tiếp nếu chưa có) | |
| /customers/ban-giao | Bàn giao khách | owner, manager (`customers.handover`, ô riêng) | MT | Làm chung / chuyển hẳn khách giữa NV | Xem trước, Bàn giao, Bàn giao tiếp | RPC `ban_giao_khach`; `ban_giao_khach_log`, `sales_routes`, `suppliers`, `users` | |
| /customers/hang-da-lay | Hàng khách đã lấy | sales (của mình); owner/manager/accountant chọn NV | Cả hai | SL hàng khách đã lấy theo tuyến/công ty | Chọn NV, mốc 3/6/12 tháng, Xuất Excel | RPC `hang_khach_da_lay`; `sales_routes`, `users` | Chỉ số lượng, không có tiền |
| /sales/pjp | Tuyến bán hàng (PJP) / Lộ trình viếng thăm | `customers.visits` (manager, sales) | Cả hai | Lịch đi tuyến theo ngày | Tạo đơn, Tạo nhanh khách | `pjp_routes`, `customers`, `users`, `visit_logs` | |
| /sales/visits | Lịch sử đi tuyến | `customers.visits` | Cả hai | Nhật ký check-in | lọc | `visit_logs`, `users` | |

### 1.10 Sản phẩm
| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /products | Sản phẩm (Quản lý sản phẩm) | owner, manager, accountant, warehouse | Cả hai (tách: `MobileProductsScreen` / `ProductTable`) | Danh mục hàng | Thêm SP, Nhập Excel, sửa | `products`, `suppliers` | Đầu trang riêng trên điện thoại |
| /products/[id] (`new`) | Chi tiết / Thêm sản phẩm | như trên | Cả hai | Form SP (đơn vị, giá, mã vạch) | Lưu, Quét mã vạch, Xoá vĩnh viễn | `products` (+ `product_units`, giá trong `ProductForm`) | Quét mã vạch dùng `BarcodeScanner`. Enter không gửi form |

### 1.11 Kho
| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /inventory | Kho hàng (Tồn kho hiện tại) | quyền `inventory` (BO, kho) | Cả hai (tách: `KhoHangDienThoai` / `StockBalanceTable`) | Tồn theo SP, tab phiếu | Nhập kho, Xuất kho, Kiểm kê, Duyệt điều chỉnh, Tra soát, Danh sách phiếu, Xuất Excel | RPC `ton_kho_trang` (lùi về gộp `batches`); `stock_entries` | Có `loading.tsx` |
| /inventory/entries | Phiếu kho | xem: `inventory` | Cả hai (DocList + `PhieuKhoDienThoai`) | Danh sách phiếu nhập/xuất/chuyển/kiểm kê | Tạo phiếu, Duyệt nháp (`post_stock_issue`/`post_stock_transfer`), Huỷ (`cancel_stock_entry`), hàng loạt, Xuất Excel | `stock_entries` | |
| /inventory/entries/[id] | Chi tiết phiếu kho | như trên | Cả hai (`ChiTietPhieuDienThoai`) | Xem/sửa ghi chú/huỷ | Huỷ phiếu, In phiếu (`DeliverySlip`/`DriverList`), Xuất Excel, Lưu ghi chú, Xoá | `stock_entries`, `stock_entry_lines`, `sales_orders`, `deliveries`, `delivery_lines`, `returns`, `swap_stock_movements`; `post_stock_export` (luồng cũ đã khoá) | |
| /inventory/stock-in | Nhập kho | `inventory.create` (owner, warehouse) | Cả hai (`StockInMobile`) | Phiếu nhập kho | Quét mã vạch, Tạo SP/NCC nhanh, Huỷ bản nháp, Ghi | `suppliers`; RPC `post_stock_import` | Thanh đáy riêng. Ô giữa thanh nav của vai kho |
| /inventory/stock-issue | Phiếu xuất kho | `inventory.create` | MT | Xuất kho | Quét mã vạch (`ketQuaQuetXuat`), Huỷ | `batches`, `stock_entries`, `stock_entry_lines`; `cancel_stock_entry`, `post_stock_issue` | |
| /inventory/stocktake-adjust | Kiểm kê / Điều chỉnh | `inventory.create` | Cả hai (`KiemKeMobile`) | Đếm kho, lập phiếu điều chỉnh chờ duyệt | Tải toàn bộ tồn, Lưu | `batches`, `products`, `stock_entries`, `stock_entry_lines`, `expense_categories` | |
| /inventory/adjustments | Điều chỉnh kho (từ kiểm kê) | `inventory.create` | Cả hai (`DuyetDieuChinhMobile`) | Duyệt / từ chối điều chỉnh | Duyệt (`post_stock_adjustment`), Từ chối (`reject_stock_adjustment`) | `stock_entries`, `batches` | |
| /inventory/batches | Quản lý lô hàng | `inventory.cost` (BO+K) | Cả hai (DocList) | Lô, HSD, giá vốn | Tạo lô, Rà soát kho date (`refresh_warehouse_zones`) | `batches` | |
| /inventory/batches/new | Tạo lô hàng mới | `inventory.create` | MT | Nhập lô thủ công | Nhập kho | `batches` | |
| /inventory/batches/[id] | Chi tiết lô | `inventory.cost` | MT | Sửa mã lô / HSD | Lưu, Xoá | `batches`, `stock_entry_lines` | |
| /inventory/stock-card/[productId] | Thẻ kho | `inventory.cost` | Cả hai | Nhập/xuất của 1 SP | lọc ngày | `products`, `batches`, `stock_entry_lines`, `sales_invoice_lines` | |
| /inventory/audit | Tra soát kho | `inventory.cost` | MT | Soát tồn lô | tìm | `batches` (+ catalogue) | |
| /inventory/soan-hang | Soạn hàng | quyền `inventory` | Cả hai (tách: `SoanHangMayTinh` / `SoanHangDienThoai`) | Gộp HĐ thành phiếu nhặt / nhãn rổ | Tạo lượt, Bắt đầu nhặt, Đã nhặt đủ, Hoàn tất, Huỷ, In phiếu nhặt / nhãn rổ | `sales_invoices`, `sales_invoice_lines`, `sales_routes`, `users`, `luot_soan`; RPC `tao_luot_soan`, `cap_nhat_luot_soan`, `hoan_tat_luot_soan`, `huy_luot_soan`, `danh_dau_soan_hang` | `ToInSoanHang`. Thanh đáy riêng trên điện thoại |
| /inventory/stocktake | Tạo phiếu kho (đời đầu) | — | MT | **CHẶN** (`LEGACY_V2_HREFS`) | — | `stock_entries` | Luồng cũ: ghi `posted` mà không trừ lô |
| /inventory/stocktake-check | Kiểm kê tồn kho (đời đầu) | — | MT | **CHẶN** | — | `stock_entries` | |
| /inventory/stock-out | Xuất kho & Gộp đơn | — | MT | **CHẶN** (luồng cũ) | — | `sales_orders`, `stock_entries`, `swap_stock_movements`, `merged_orders` | Ghi dở dang. Đừng dựng lại |
| /inventory/stock-out/collect/[entryId] | Thu tiền sau khi tự giao | — | MT | **CHẶN** | — | `cash_receipts`, `payments`, ... | |
| /inventory/pending | Phiếu kho chờ xử lý | — | MT | **CHẶN** | — | nhiều bảng | |
| /warehouse, /warehouse/[...slug] | — | | | redirect → `/inventory/...` | | | |
| /operations/[[...slug]] | — | | | redirect → `/warehouse/...` → `/inventory/...` | | | |

### 1.12 Mua hàng / NCC / Công nợ NCC
| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /purchasing | Mua hàng (trang tổng) | BO (`purchasing.invoices`) | MT | Tổng quan mua + công nợ NCC | Lối tắt | `stock_entries`; RPC `payables_summary` | Không có mục menu |
| /purchasing/receipts | Phiếu nhập hàng | BO (+ kho) | Cả hai (DocList) | Danh sách phiếu nhập | Tạo phiếu (POS tab mới), Xuất Excel | `purchase_invoices` | Thanh nav dưới của owner: "Nhập hàng" |
| /purchasing/receipts/new (`?ncc=`) | Phiếu nhập hàng (điện thoại) | `duocGhiMuaHang` (owner, manager, accountant, warehouse) | ĐT→POS | Lập phiếu nhập | Lưu nháp, Hoàn thành | `purchase_invoices`, `suppliers`; `complete_purchase_invoice` | `PhieuNccMobile`. Máy tính → `/pos/nhap-hang/moi` |
| /purchasing/receipts/[id] | Phiếu nhập hàng — chi tiết | BO | MT | Xem/huỷ/khôi phục | Hoàn thành, Huỷ, Khôi phục, Sửa, Xuất Excel | `purchase_invoices`, `purchase_invoice_lines` | |
| /purchasing/receipts/[id]/edit | Sửa phiếu nhập (điện thoại) | như trên | ĐT→POS | | Lưu | `purchase_invoices`, `purchase_invoice_lines`, `suppliers`; `complete_purchase_invoice`, `sua_phieu_nhap` | |
| /purchasing/invoices | Hoá đơn mua hàng (tra cứu) | BO | Cả hai (DocList) | Tra cứu (đã gỡ khỏi menu) | — | `payables`, `stock_entries` | |
| /purchasing/reorder | Đề xuất đặt hàng | BO | Cả hai | Gợi ý hàng cần đặt | → lập phiếu nhập | `batches`, `products`, `sales_order_lines`, `suppliers` | Chỉ đọc |
| /purchasing/price-list | Bảng giá nhập | BO | MT | Giá nhập theo NCC | Lưu (`luu_gia_nhap`) | `suppliers`, `useBangGiaNhap` | mig 234 |
| /purchase-returns | Trả hàng NCC | BO+K | Cả hai (DocList) | Danh sách phiếu trả NCC | Tạo, Xuất Excel | `supplier_returns` | |
| /purchase-returns/new | Lập phiếu trả NCC (điện thoại) | như trên | ĐT→POS | | Lưu, Xuất | `supplier_returns`, `suppliers`; `complete_supplier_return` | |
| /purchase-returns/[id] | Chi tiết phiếu trả NCC | như trên | MT | | Hoàn thành, Huỷ (`cancel_supplier_return`), Khôi phục, Xoá nháp, Xuất Excel | `supplier_returns`, `supplier_return_lines` | |
| /purchase-returns/[id]/edit | Sửa phiếu trả NCC | như trên | ĐT→POS | | Lưu | như trên | |
| /suppliers | Nhà cung cấp | BO (`suppliers`) | Cả hai (DocList + `MobileSuppliersScreen`) | Danh mục NCC | Thêm, Nhập Excel, Gộp NCC (`gop_nha_cung_cap`) | `suppliers` | |
| /suppliers/new | Thêm nhà cung cấp mới | `inventory.create` | MT | Form NCC | Lưu | `SupplierForm` | |
| /suppliers/[id] | Hồ sơ nhà cung cấp | BO | Cả hai | Hồ sơ, giao dịch, công nợ, SP | Sửa thông tin (`SupplierEditSheet`), Nhập hàng / Trả NCC (POS), Chi trả, Gộp, Xoá (`xoa_nha_cung_cap`) | `suppliers`, `purchase_invoices`, `purchase_invoice_lines`, `supplier_returns`, `payable_payments`, `products`, `user_suppliers`, `users`; `so_chung_tu_ncc` | |
| /payables | Công nợ NCC | BO (`payables`, ô riêng) | Cả hai (DocList) | Danh sách công nợ NCC | Tạo công nợ NCC, Theo NCC | `payables` | `CheDoCongNoNcc` |
| /payables/new | Tạo công nợ NCC | `receivables.create` | MT | Ghi nợ NCC thủ công | Lưu | `payables`, `stock_entries`, `suppliers` | |
| /payables/[id] | Chi tiết công nợ NCC | BO | MT | Thanh toán | Xác nhận thanh toán (`record_payable_payment`), Đặt lại trạng thái mở, Xoá | `payables`, `payable_payments` | |
| /payables/by-supplier | Công nợ theo nhà cung cấp | BO | Cả hai | Tổng theo NCC | — | RPC `payables_by_supplier` | |

### 1.13 Khuyến mãi
| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /promotions | Khuyến mãi | mọi vai có `promotions` (sales chỉ xem) | Cả hai (DocList) | Danh sách CTKM | Tạo | `promotions` | |
| /promotions/new | Tạo chương trình khuyến mãi | `promotions.create` | MT | Form CTKM | Lưu | `promotions` | |
| /promotions/[id] | Chi tiết khuyến mãi | như trên | MT | Sửa/xoá | Lưu, Xoá vĩnh viễn | `promotions` | |

### 1.14 Hoa hồng
| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /commissions | Hoa hồng (báo cáo) | `commissions` (owner, manager, accountant, sales xem) | MT | Ví hoa hồng | Lọc nâng cao, link Chính sách | `commission_wallets` | |
| /commissions/policies | Chính sách hoa hồng | như trên | Cả hai (DocList) | Danh sách | Tạo | `commission_policies` | |
| /commissions/policies/new | Tạo chính sách hoa hồng | `commissions.create` | MT | Bậc lũy kế / % / cố định | Lưu, Huỷ | `commission_policies` | |
| /commissions/policies/[id] | Chi tiết chính sách | như trên | MT | | Lưu, Xoá vĩnh viễn | `commission_policies` | |

### 1.15 Nhân sự / Lương
| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /hr | Nhân sự | `hr` (owner, mặc định module settings) | MT | Trang tổng nhân sự | lối tắt | `payroll_runs`, `users` | |
| /hr/overview | — | | | redirect → `/hr/attendance` | | | |
| /hr/attendance | Chấm công | `hr` | Cả hai | Chấm công tháng | Chấm công, chấm hàng loạt | `hr_attendance`, `users` | |
| /hr/bonus-config | Thưởng doanh số (Cấu hình thưởng) | `hr` | MT | Thưởng theo SP/đơn vị | Lưu, Khôi phục mặc định | `hr_monthly_bonus`, `product_units` | |
| /hr/salary-config | Cấu hình lương | `hr` | MT | Lương cơ bản / phụ cấp | Lưu cấu hình | `hr_salary_config` | |
| /hr/payroll | — | | | redirect → `/hr/payroll/runs` | | | |
| /hr/payroll/runs | Bảng lương | `hr` | MT | Tính / khoá bảng lương tháng | Tính (`compute_payroll_run`), Lưu điều chỉnh, Khoá (`lock_payroll_run`), In phiếu lương, Xuất Excel | `payroll_runs`, `payroll_run_items`, `sales_invoices`, `users` | `Payslip` |
| /hr/payroll/[id] | Chi tiết bảng lương (cũ) | `hr` | MT | Sửa dòng lương | Lưu điều chỉnh, Xoá, In | `hr_payroll` | |
| /luong-cua-toi | Phiếu lương của tôi | mọi người (`always`) | Cả hai | Phiếu lương cá nhân | xem / in | RPC `my_payslips` | |
| /settings/users/[id]/salary | Cấu hình lương theo NV | `settings.users` | MT | Bậc KPI, thưởng số đơn | Lưu | `salary_kpi_tiers`, `salary_order_count_bonus_configs`, `monthly_activity_bonuses`, `users` | |

### 1.16 Báo cáo
**a) Báo cáo tổng hợp `/bao-cao/*`.** Bộ 6 màn mới (26/09/2026), có thiết kế riêng cho cả máy tính và điện thoại. Khung `bao-cao/khung.tsx`. Trên điện thoại dùng đầu trang xanh + ☰ riêng. Có đào sâu xuống chứng từ (`xem-nhanh.tsx`), In và Xuất Excel.

| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /bao-cao | Tổng quan | `reports.dashboard` (BO+K) | Cả hai | KPI, biểu đồ doanh thu thuần, Top 5 | đào sâu, In, Excel | `ManTongQuan`: `bao_cao_so_ban`, `bao_cao_cong_no`, `bao_cao_ton_kho`, `nap-don-dat` | |
| /bao-cao/ban-hang | Bán hàng | `reports.sales` (gồm sales) | Cả hai | Doanh số thuần, chênh lệch | Xem theo..., đào sâu, Excel | RPC `bao_cao_so_ban` (`docSoBanMotLuot`) | Tab "Báo cáo" trên thanh nav dưới của NVBH |
| /bao-cao/nhan-vien | Nhân viên (Hàng bán theo NV) | `reports.employees` (BO) | Cả hai | = `/reports/employees` chỉ phần hàng bán | bấm NV → chi tiết, Excel | như `/reports/employees` | Xuất lại chính trang `reports/employees` (`laManHangBanNv`). Màn này giữ app bar chuẩn |
| /bao-cao/cuoi-ngay | Cuối ngày | `reports.end_of_day` | Cả hai | Tiền trong ngày, trạng thái đơn | Excel | `bao_cao_so_ban`, `nap-tien`, `nap-don-dat` | |
| /bao-cao/kho | Kho | `reports.inventory` | Cả hai | Tồn, cận date, chậm bán, XNT | Excel | RPC `bao_cao_ton_kho` | |
| /bao-cao/cong-no | Công nợ | `receivables` | Cả hai | Theo khách / tuổi nợ / NV / HĐ | Excel | RPC `bao_cao_cong_no` | |
| /bao-cao/tai-chinh | Tài chính | `reports.finance` | Cả hai | KQKD / Dòng tiền / ... | Excel | `finance_pnl`, `finance_cash_flow`, `nap-cong-no`, `nap-tien` | |

**b) Báo cáo cũ `/reports/*` và `/dashboard`.** Khung `ReportShell`, `ReportFrame` (`downloadXlsx`), `ReportTable`, `useFilterCatalogs`. Thiết kế cho máy tính trước; bộ lọc gập lại trên điện thoại.

| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /dashboard | Tổng quan kinh doanh | `reports.dashboard` | Cả hai (`TongQuanMobile` trên điện thoại) | KPI, kênh, top khách, tồn thấp, lô sắp hết hạn, việc chờ | Thử lại | RPC `dashboard_summary`, `dashboard_channel_revenue`, `dashboard_top_customers`; `batches`, `sales_orders`; `PendingWorkWidget` | Trang đầu của khối văn phòng khi gõ `/` |
| /reports | Báo cáo (trang gộp) | `reports.dashboard` | MT | Tổng hợp + so với tháng trước, lối tắt | Xuất báo cáo, In | `sales_invoices`, `sales_orders`, `receivables`, `batches`, `products`, `users` | |
| /reports/end-of-day | Báo cáo cuối ngày | `reports.end_of_day` | MT | | | `sales_invoices`, `cash_receipts`, `expenses`, `returns` | |
| /reports/sales | Báo cáo bán hàng | `reports.sales` | MT | Nhiều "mối quan tâm" (variant) | Excel | `docSoBanKy` (`bao_cao_so_ban`) | |
| /reports/orders | Báo cáo đặt hàng | `reports.orders` | MT | Theo đơn hàng | Excel | `sales_order_lines` | |
| /reports/products | Báo cáo hàng hóa | `reports.products` | MT | Lợi nhuận, giá trị kho, XNT | Excel | `bao_cao_so_ban`, `nap-kho`, `batches` | |
| /reports/customers | Báo cáo khách hàng | `reports.customers` | MT | | Excel | `bao_cao_so_ban`, `receivables` | |
| /reports/suppliers | Báo cáo nhà cung cấp | `reports.suppliers` | MT | | Excel | `payables`, `purchase_invoices`, `purchase_order_lines`, `stock_entry_lines` | |
| /reports/employees | Báo cáo nhân viên | `reports.employees` | Cả hai | Hàng bán theo NV, chênh lệch giá | Excel, bấm NV xem chi tiết | `docSoBanMotLuot` | Tệp 1.643 dòng |
| /reports/channels | Báo cáo theo kênh bán hàng | `reports.channels` | MT | | Excel | `lib/analytics/sales` | |
| /reports/inventory | Báo cáo Chi tiết Kho hàng | `reports.inventory` | Cả hai | | In | `batches`, `sales_order_lines`, `suppliers` | |
| /reports/finance | Báo cáo tài chính | `reports.finance` | MT | | Excel | RPC `receivables_summary`, `payables_summary`, `stock_value_summary`, `cash_received_total`; `expenses`; `bao_cao_so_ban` | layout `SectionTabs` |
| /reports/finance/pnl | Báo cáo Lãi Lỗ (P&L) | `reports.finance` | MT | | In | RPC `finance_pnl` | |
| /reports/finance/cash-flow | Báo cáo dòng tiền | như trên | MT | | In | RPC `finance_cash_flow` | |
| /reports/finance/balance-sheet | Bảng cân đối tài sản | như trên | MT | | In | RPC `finance_balance_sheet` | |

**c) Phân tích `/analytics/*`.** Mặc định chỉ BO. Dùng `KpiCard`, `TopListCard`, `TrendChart`, `DateRangePicker`. Layout của từng nhóm có `SectionTabs`.

| route | tên màn | ai dùng | máy | nguồn dữ liệu |
|---|---|---|---|---|
| /analytics | redirect → `/analytics/business/overview` | | | |
| /analytics/business/overview | Tổng quan kinh doanh | `analytics.business` | MT | `docSoBanKy` ×2 (kỳ này + kỳ trước), `customers`, `products`, `users` |
| /analytics/business/cost-profit | Chi phí - Lợi nhuận | `analytics.business` | MT | `docSoBanKy`, `expenses` |
| /analytics/products/overview | Tổng quan hàng hóa | `analytics.products` | MT | `docSoBanKy`, `products` |
| /analytics/products/categories | Phân loại hàng hóa | `analytics.products` | MT | `docSoBanKy`, `products`, `suppliers` |
| /analytics/products/stock | Tồn kho | `analytics.products` | MT | `batches`, `products` |
| /analytics/customers/overview | Tổng quan khách hàng | `analytics.customers` | MT | `customers` + `lib/analytics/sales` |
| /analytics/customers/categories | Phân loại khách hàng | `analytics.customers` | MT | `customers`, nhóm khách |
| /analytics/performance/receivables | Công nợ khách hàng | `analytics.performance` | MT | `receivables`, `customers`, `users` |

### 1.17 Cài đặt
| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /settings | Cài đặt (Tổng quan) | `settings` | MT | Lối tắt | — | — | Middleware gác thô mọi `/settings*` (`duocQuaCongSettings`) |
| /settings/users | Quản lý người dùng (Danh sách nhân viên) | `settings.users` (owner) | Cả hai (DocList + `DsNhanVienDienThoai`) | NV, mã QR | Tạo NV, Mã QR đăng nhập, Đăng nhập thay, Xoá / cho nghỉ việc (`cho_nhan_vien_nghi`) | `users`; `/api/admin/users/qr-links`, `so_chung_tu_nhan_vien` | Thanh nav dưới của owner: "Nhân viên" |
| /settings/users/new | Tạo nhân viên | `settings.users` | MT | Tài khoản + hồ sơ + QR | Tự động tạo, Tải ảnh, Tạo tiếp, Phân quyền chi tiết | `/api/admin/users` (POST) | |
| /settings/users/[id] | Sửa người dùng | `settings.users` | MT | Vai trò, NCC phụ trách, giảm giá | Lưu, Chọn/Bỏ tất cả NCC, → Phân quyền tuỳ chỉnh, → Cấu hình lương | `users`, `user_suppliers`, `suppliers`; `PermissionMatrix` | |
| /settings/users/[id]/permissions | Phân quyền tuỳ chỉnh | `settings.users` | MT | Quyền riêng 1 người | Lưu | `users`, `user_permission_overrides` (`PermissionMatrix`) | |
| /settings/permissions | Phân quyền & Template | `settings.permissions` | MT | Ma trận vai trò × mô-đun/tính năng | Lưu, Huỷ thay đổi | `role_permissions` | |
| /settings/org | Cấu hình tổ chức (Tổ chức / NPP) | `settings.org` | MT | Thông tin NPP, header in | Lưu | `organizations` | |
| /settings/approval-rules | Ngưỡng cảnh báo đơn hàng | `settings.approval_rules` | MT | Ngưỡng duyệt | Thêm/Sửa/Xoá | `approval_rules` | |
| /settings/einvoice | Hoá đơn điện tử (MISA meInvoice) | `einvoice.config` (owner, accountant) | MT | Cấu hình MISA | Lưu, Kiểm tra kết nối | `/api/einvoice/config`, `/api/einvoice/test-connection` | |
| /setup | Trình hướng dẫn cài đặt (Thiết lập ban đầu) | owner (`settings.org`) | MT | Wizard ban đầu | các bước | `organizations`, `pricing_rules`, `hr_salary_config` | `SetupBanner` ở /home |

### 1.18 Giao hàng — DEPRECATED, cả cây đã chặn (`LEGACY_V2_HREFS` có `/deliveries`)
| route | tên màn | ai dùng (cũ) | máy | mục đích | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|
| /deliveries | Chuyến giao hàng | manager, warehouse, driver | Cả hai | Danh sách chuyến | `deliveries`, `delivery_lines` | **CHẶN**. Không dựng lại |
| /deliveries/new | Tạo phiếu giao hàng | | MT | | `deliveries`, `delivery_lines`, `sales_orders`, `users` | CHẶN |
| /deliveries/[id] | Chi tiết chuyến giao | | Cả hai | Bắt đầu giao, ký nhận (`PodCaptureSheet`), huỷ | `deliveries`, `delivery_lines`, `cash_receipts`, `stock_entries` | CHẶN |
| /deliveries/[id]/handover | Nhận bàn giao lại từ tài xế | | ĐT | | RPC `confirm_driver_handover`; nhiều bảng | CHẶN |
| /deliveries/[id]/settle | Nộp tiền chuyến giao | | ĐT | | `cash_receipts`, `payments`, `receivables` | CHẶN |

### 1.19 Thông báo / Trợ giúp / Trang chủ
| route | tên màn | ai dùng | máy | mục đích | hành động chính | nguồn dữ liệu | ghi chú |
|---|---|---|---|---|---|---|---|
| /home | Trang chủ | mọi người (`always`) | Cả hai | Lưới chức năng theo quyền; NVBH dùng `SalesHome` | Tạo đơn, Đi tuyến, Thu công nợ, Cập nhật ảnh điểm bán, việc cần làm | `sales_orders`, `customers`, `visit_logs`; RPC `my_sales_target`; `lib/home/sales-home` | Có `SetupBanner`, câu nói hằng ngày |
| /notifications | Thông báo | mọi người | Cả hai | Danh sách thông báo | Đánh dấu đã đọc, Về trang chủ | `notifications` | Chuông `NotificationBell` + `NotificationPanel` (tải lười) ở header |
| /help | Trợ giúp & Hướng dẫn | mọi người | Cả hai | Hướng dẫn theo vai/mô-đun | — | tĩnh | |

### 1.20 In ấn
| route | tên màn | ghi chú |
|---|---|---|
| /in/don-hang/[id] | In đơn (POS) | `export { default } from orders/[id]/print`. Layout `in/layout.tsx` không có khung dashboard; bắt buộc `print:min-h-0` |
| /in/hoa-don/[id] (`?auto=1`) | In hoá đơn (POS) | Xuất lại `sales-invoices/[id]/print`. POS nạp vào iframe ẩn `npp-khung-in` (`inTaiCho`), xong gửi `postMessage {type:"npp:in-xong"}`. Header phải là `X-Frame-Options: SAMEORIGIN` |
| /in/tra-hang/[id] | In phiếu trả (POS) | Xuất lại `returns/[id]/print` |
| /orders/[id]/print, /sales-invoices/[id]/print, /invoices/[id]/print, /returns/[id]/print | Bản in của phần quản lý | `PrintButton` / `moHopThoaiIn`, `useLeaveAfterPrint` |
| (component) | `DeliverySlip`, `DriverList`, `PaymentReceiptTT` (Mẫu 01-TT), `Payslip`, `ReturnSlip`, `SalesInvoice`, `ToInSoanHang` | In bằng `window.print()` trong trang |

### 1.21 Trang ngoài khung (auth / hệ thống)
| route | tên | ai dùng | mục đích | nguồn | ghi chú |
|---|---|---|---|---|---|
| / | — | — | Server redirect: nhân viên → `/home`, khối văn phòng → `/dashboard`; chưa đăng nhập → `/login` | `users.role` | `trangGoc`. Sau khi đăng nhập: NV → `/home`, văn phòng → `/orders` (`trangSauDangNhap`) |
| /login | npp.sale (Đăng nhập) | mọi người | Email/mật khẩu | `signInWithPassword`, `users` (chặn tài khoản đã khoá) | |
| /qr-login?t= (route.ts GET) | — | NV | Đăng nhập bằng mã QR | token QR | Service worker không cache |
| /maintenance | Đang nâng cấp hệ thống | — | Trang bảo trì | không gọi DB | Middleware **rewrite** về đây khi bảo trì |
| /debug | Chẩn đoán hệ thống | dev | Kiểm env, ping, session, truy vấn mẫu | `users`, `sales_orders`, RPC `user_role`, `user_org_id` | |
| /backup, /backup/privacy, /backup/terms | nppsale backup — Giới thiệu / Chính sách / Điều khoản | công khai | Trang tĩnh | `BackupPublicInfo` | Middleware bỏ qua |
| error.tsx (gốc + dashboard), global-error.tsx, not-found.tsx, loading.tsx (dashboard, customers, inventory, orders) | | | Màn lỗi / tải | | |

### 1.22 API routes (`src/app/api/**/route.ts` + `/qr-login`)
| route | method | mục đích |
|---|---|---|
| /api/admin/users | POST | Tạo nhân viên (auth + hồ sơ + mã QR) — owner |
| /api/admin/users/[id] | DELETE | Xoá user (auth + profile) — owner |
| /api/admin/users/[id]/qr | GET, POST, DELETE | Xem / tạo lại / thu hồi mã QR đăng nhập |
| /api/admin/users/qr-links | GET | Link QR của mọi NV cùng tổ chức — owner |
| /api/client-error | POST | Nhận lỗi trình duyệt, ghi log Vercel |
| /api/cron/daily | GET, POST | Một cửa cho mọi việc theo lịch (gói Hobby) |
| /api/customers/photo-cleanup | POST | Xoá file ảnh điểm bán (dùng service key) |
| /api/customers/photo-reminders | GET, POST | Nhắc chụp ảnh điểm bán (thông báo) |
| /api/customers/route-reminders | GET, POST | Nhắc gán tuyến cho khách chưa có tuyến |
| /api/do-nap | POST | Nhận số đo thời gian nạp POS / báo cáo → log `[pos-nap]` / `[bao-cao-nap]` |
| /api/einvoice/config | GET, POST | Đọc/lưu cấu hình MISA (owner, accountant) |
| /api/einvoice/publish | POST | Phát hành HĐĐT `{invoiceId, mode, poNote}` |
| /api/einvoice/pull-snapshots | GET, POST | Kéo danh sách HĐ từ MISA → `misa_invoice_snapshots` |
| /api/einvoice/reconcile-action | POST | Ba thao tác đối soát tay |
| /api/einvoice/refresh-status | POST | Làm mới trạng thái 1 HĐ |
| /api/einvoice/sync | GET, POST | Đồng bộ theo lô (cron) |
| /api/einvoice/test-connection | POST | Thử kết nối MISA |
| /qr-login | GET | Điểm đến khi quét QR đăng nhập |

### 1.23 Offline / PWA
- `public/manifest.webmanifest`: `start_url: "/orders"`, `display: standalone`, `theme_color #2563eb`, có icons.
- `public/sw.js` (`CACHE_VERSION npp-v2`):
  - Tài sản tĩnh: cache-first.
  - Điều hướng trang: network-first, mất mạng thì trả bản đã cache; bật tải trước điều hướng (`preloadResponse`).
  - Không bao giờ cache `/api`, `/login`, `/qr-login` và request khác origin (Supabase).
- `src/components/offline/sw-register.tsx`: đăng ký SW, chỉ chạy ở production.
- `src/components/offline/offline-indicator.tsx`: chỉ báo trên header (ngoại tuyến + số đơn offline đang chờ).
- `src/lib/offline/{idb,outbox,ref-cache,sync}.ts`: hàng đợi đơn offline và cache danh mục bằng IndexedDB.
- `OrderSyncProvider` (`use-order-sync`) đặt ở `DashboardShell`.
- `GhiKhoMan` (`src/components/nav/ghi-kho-man.tsx`) ở layout gốc ghi cookie `npp_kho` (`rong`/`hep`) để middleware nhận diện máy tính và chuyển thẳng sang POS.

---

## 2. Cấu trúc điều hướng

### 2.1 Khung
`(dashboard)/layout.tsx` đọc hồ sơ phía máy chủ (`layHoSoMayChu`), dựng `NapHoSo`, rồi `DashboardShell`. `DashboardShell` gồm:
- `Sidebar`: chỉ dựng khi `useKhoMay() !== false`; ở máy tính là cột `lg:w-60`.
- `Header`: app bar.
- `MobileNav`: thanh dưới, chỉ dưới `lg`.
- `Sheet` dưới đáy: menu điện thoại, là `Sidebar mobile` dạng lưới 3 cột.
- Các provider khác: `PermissionsLoader`, `PosNewTab` (bắt `<a>` dẫn vào POS để mở tab mới), `PageTitleProvider`, `OrderSyncProvider`.

`/home` và `/sell*` là "launcher": không có Header, không có `main` padding.

### 2.2 Sidebar (máy tính) — `src/components/layout/sidebar.tsx` `NAV_GROUPS`
Accordion, mỗi lúc chỉ mở một nhóm. Trên cùng: nút "Tạo đơn mới" (→ `/sell`; hiện khi `canSeeHref(role, "/sell")`) và "Trang chủ" luôn ghim. Chân: Hỗ trợ (`/help`), Đăng xuất. Mỗi mục hiện khi `canSeeHref(role, href)`. Quyền tra theo `NAV_PERMISSION` (module · feature · action):

- **Bán hàng**
  - Bán hàng `/sell` (orders · orders · create)
  - Đơn hàng `/orders` (orders · orders)
  - Hóa đơn bán `/sales-invoices` (orders · orders)
  - Trả hàng `/returns` (returns · returns)
  - Khách hàng `/customers` (customers · customers)
  - Tuyến bán hàng `/customers/routes` (customers)
  - Điểm bán cần cập nhật `/customers/missing-photos` (customers)
  - Bàn giao khách `/customers/ban-giao` (customers · customers.handover · update — ô riêng owner/manager)
  - Hàng khách đã lấy `/customers/hang-da-lay` (customers)
  - Lịch sử đi tuyến `/sales/visits` (customers · customers.visits)
  - Khuyến mãi `/promotions` (promotions)
- **Mua hàng**
  - Phiếu nhập hàng `/purchasing/receipts` (inventory · purchasing.invoices · create)
  - Trả hàng NCC `/purchase-returns` (inventory · purchasing.returns)
  - Bảng giá nhập `/purchasing/price-list` (purchasing.invoices)
  - Đề xuất đặt hàng `/purchasing/reorder` (purchasing.invoices)
  - Nhà cung cấp `/suppliers` (inventory · suppliers)
  - Công nợ NCC `/payables` (receivables · payables)
- **Kho vận**
  - Kho hàng `/inventory` (inventory)
  - Phiếu kho `/inventory/entries` (inventory)
  - Soạn hàng `/inventory/soan-hang` (inventory)
  - Sản phẩm `/products` (products)
  - Giao hàng `/deliveries` → **luôn ẩn vì luồng cũ đã chặn**
- **Kế toán**
  - Công nợ `/receivables` (receivables)
  - CN theo KH `/receivables/by-customer` (receivables.by_customer)
  - CN theo NV `/receivables/by-rep` (receivables.by_rep — BO)
  - Công nợ đầu kỳ `/finance/opening-balances` (finance.opening_balances — BO)
  - Phiếu thu `/finance/cash-receipts` (finance.cash_receipts — BO)
  - Phiếu chi `/finance/expenses` (settings · finance.expenses — BO)
  - Hóa đơn điện tử `/invoices` (invoices)
  - Cấu hình HĐ điện tử `/settings/einvoice` (settings · einvoice.config — BO)
- **Nhân sự**
  - Danh sách nhân viên `/settings/users` (settings.users)
  - Tạo nhân viên `/settings/users/new` (settings.users)
  - Phân quyền & Template `/settings/permissions` (settings.permissions)
  - Chấm công `/hr/attendance`, Cấu hình thưởng `/hr/bonus-config`, Cấu hình lương `/hr/salary-config`, Bảng lương `/hr/payroll/runs` (settings · hr)
  - Hoa hồng (báo cáo) `/commissions` (commissions)
  - Phiếu lương của tôi `/luong-cua-toi` (always)
- **Báo cáo tổng hợp**
  - Tổng quan `/bao-cao` (reports.dashboard)
  - Bán hàng `/bao-cao/ban-hang` (reports.sales)
  - Nhân viên `/bao-cao/nhan-vien` (reports.employees)
  - Cuối ngày `/bao-cao/cuoi-ngay` (reports.end_of_day)
  - Kho `/bao-cao/kho` (reports.inventory)
  - Công nợ `/bao-cao/cong-no` (receivables · receivables)
  - Tài chính `/bao-cao/tai-chinh` (reports.finance)
- **Phân tích**
  - Kinh doanh `/analytics/business/overview` (analytics.business)
  - Hàng hóa `/analytics/products/overview` (analytics.products)
  - Khách hàng `/analytics/customers/overview` (analytics.customers)
  - Công nợ khách hàng `/analytics/performance/receivables` (analytics.performance)
- **Báo cáo**
  - Tổng quan `/dashboard` (reports.dashboard)
  - Cuối ngày `/reports/end-of-day`
  - Bán hàng `/reports/sales`
  - Đặt hàng `/reports/orders`
  - Hàng hóa `/reports/products`
  - Khách hàng `/reports/customers`
  - Nhà cung cấp `/reports/suppliers`
  - Nhân viên `/reports/employees`
  - Kênh bán hàng `/reports/channels`
  - Tài chính `/reports/finance`
  - Mỗi mục có khoá `reports.*` tương ứng.
- **Cài đặt**
  - Tổng quan `/settings` (settings)
  - Trình hướng dẫn cài đặt `/setup` (settings.org)
  - Tổ chức / NPP `/settings/org` (settings.org)
  - Ngưỡng cảnh báo đơn `/settings/approval-rules` (settings.approval_rules)

Nhóm nào không còn mục nào thì bị bỏ hẳn (`filterNavGroups`).

**Cửa vào không phải mục menu** (`CUA_VAO`), chỉ dùng để gác trang:
- `/notifications` (always)
- `/sell/cart|customer|done|drafts|returns|scan|terms` (orders · create)
- `/customers/new` (create), `/returns/new` (create)
- `/sales/pjp` (customers.visits)
- `/commissions/policies`
- `/finance/cash-receipts/new` (create)
- `/receivables/aging`, `/payables/by-supplier`, `/purchasing`
- `/invoices/reconcile` (invoices · update)
- `/warehouse`
- `/inventory/batches` và `/inventory/audit` (inventory.cost), `/inventory/batches/new` (create), `/inventory/adjustments` (create)
- `/hr/overview`, `/hr/payroll`
- Các trang con của analytics
- `/reports/inventory`, `/reports/finance/{pnl,cash-flow,balance-sheet}`

Màn con động được kiểm như mục cha qua `NAV_TIEN_TO`, ví dụ `/suppliers/<id>` theo `/suppliers`, `/inventory/stock-card/<id>` theo `/inventory/batches`, `/finance/phieu-chi-ncc/<id>` theo `/finance/expenses`.

### 2.3 LEGACY_V2_HREFS — chặn hẳn
`/deliveries`, `/inventory/stock-out`, `/inventory/pending`, `/inventory/stocktake`, `/inventory/stocktake-check`.
- So khớp theo tiền tố có dấu `/` nên chặn cả màn con.
- Chặn trước mọi quyền, kể cả owner.
- `LEGACY_FLOW_WRITES_LOCKED = true` (`src/lib/nav/legacy-flow.ts`) còn khoá các nút ghi luồng cũ ở `/inventory/entries/[id]`.

### 2.4 Thanh nav dưới (điện thoại) — `src/components/layout/mobile-nav.tsx`
4 mục cố định theo vai (vẫn lọc bằng `canSeeHref`) + ô hành động ở giữa:

| vai | trái | ô giữa | phải |
|---|---|---|---|
| owner | Trang chủ `/home`, Đơn hàng `/orders` | **Bán hàng** `/sell` | Nhập hàng `/purchasing/receipts`, Nhân viên `/settings/users` |
| manager | Tổng quan `/dashboard`, Đơn hàng | **Bán hàng** | Khách `/customers`, Giao hàng `/deliveries` (bị ẩn vì luồng cũ) |
| accountant | Công nợ `/receivables`, Đơn hàng | (không có) | Hoá đơn `/invoices`, Báo cáo `/reports` |
| sales | Trang chủ, Đơn hàng | **Bán hàng** | Khách, Báo cáo `/bao-cao/ban-hang` (sáng ở mọi `/bao-cao/*`) |
| warehouse | Kho `/inventory`, Đơn hàng | **Nhập kho** `/inventory/stock-in` | Giao hàng (bị ẩn), Sản phẩm `/products` |
| driver | Chuyến `/deliveries` (bị ẩn), Thu tiền `/receivables/collect` | — | — |

**Thanh nav dưới bị ẩn** (`showsBottomNav`):
- Đúng đường dẫn: `/sell`, `/sell/customer`.
- Theo tiền tố: `/sell/cart|terms|returns|scan`, `/purchasing/receipts/new`, `/purchase-returns/new`, `/returns/new`, `/inventory/stock-in`, `/inventory/stocktake-adjust`, `/customers/new`, `/inventory/soan-hang`.
- Màn sửa phiếu NCC `/(purchasing/receipts|purchase-returns)/<id>/edit`.

### 2.5 App bar điện thoại — `src/components/layout/header.tsx`
- Gồm: ← quay lại hoặc ☰ (danh sách của khối văn phòng hiện ☰ — `laTrangDanhSach`), tiêu đề, 🔍, `NotificationBell`, `UserMenu` (tải lười `user-menu-day`).
- Tiêu đề lấy từ `PAGE_TITLES` theo tiền tố dài nhất, hoặc trang tự đẩy qua `usePageTitle`.
- 🔍 mở `MobileSearchOverlay`; tìm nhanh trên máy tính → `/orders?q=`.
- **App bar bị ẩn trên điện thoại** (`hidesMobileAppBar`) vì trang tự dựng đầu trang (`DauTrangXanh`/`DauTrangTrang` hoặc `DocListMobileHead`):
  - `DOC_LIST_MOBILE_ROUTES`: commissions/policies, finance/cash-receipts, finance/expenses, inventory/batches, invoices, payables, promotions, purchase-returns, purchasing/invoices, purchasing/receipts, receivables.
  - `DAU_TRANG_RIENG_ROUTES`: dashboard, products, inventory/stock-in, inventory/stocktake-adjust, inventory/adjustments, inventory, inventory/entries, settings/users, suppliers, customers/new, inventory/soan-hang.
  - Thêm: `/inventory/entries/<id>`, `/orders`, `/customers`, `/returns`, `/sales-invoices`, `/orders/<id>`, `/purchasing/receipts/new`, `/purchase-returns/new`, `/returns/new`, các màn sửa phiếu NCC, `/bao-cao`, `/bao-cao/*` (trừ `/bao-cao/nhan-vien`).

### 2.6 Lưới Trang chủ (`/home` `TILES`, lọc bằng `canSeeHref`)
- Bán hàng: Bán hàng, Đơn hàng, Khách hàng, Sản phẩm, Khuyến mãi, Lịch sử đi tuyến.
- Vận hành: Kho hàng, Giao hàng, Trả hàng.
- Mua hàng: Đề xuất đặt hàng, Nhà cung cấp.
- Kế toán: Hóa đơn bán (`/invoices`), Công nợ KH, Công nợ NCC, Phiếu thu, Phiếu chi, Hoa hồng.
- Báo cáo: Phân tích, Báo cáo `/reports`, Tài chính.
- Hệ thống: Nhân sự, Phiếu lương, Cài đặt, Phân quyền, Trợ giúp.

NVBH có `TILES_NVBH` + thứ tự `THU_TU_NVBH`: /sell, /orders, /sales-invoices, /returns, /customers, /customers/hang-da-lay, /bao-cao/ban-hang, /luong-cua-toi, /promotions, /commissions.

---

## 3. Vai trò và trang đầu

| vai | ma trận mặc định (tóm tắt) | gõ `/` | sau đăng nhập | trang chủ |
|---|---|---|---|---|
| owner | Toàn quyền mọi mô-đun; `canAccessFeature` luôn true | /dashboard | /orders | /home (lưới đầy đủ) |
| manager | orders r/c/u/approve/export; customers r/c/u; inventory r; products r/c/u; receivables r/c/u; deliveries r/c/u; promotions r/c/u; invoices r; returns r/approve; reports r; settings r | /dashboard | /orders | /home |
| accountant | orders r; customers r; inventory r; receivables r/c/u; invoices r/c/u; commissions r/u; reports r; settings r | /dashboard | /orders | /home |
| sales | orders r/c/u; customers r/c/u; commissions r; receivables r; promotions r; returns r; reports r (chỉ `reports.sales` vì các ô `reports.*` khác là ô riêng); không có inventory/products/settings | /home | /home | /home có `SalesHome`: nút Tạo đơn, Đi tuyến, Thu công nợ, Cập nhật ảnh điểm bán, việc cần làm (đơn nháp, nợ quá hạn, tồn thấp), chỉ tiêu (`my_sales_target`), đơn gần đây, khách cần ghé, ô chức năng NVBH |
| warehouse | orders r; inventory r/c/u/export; products r; deliveries r/u; returns r/u/approve; reports r | /home | /home | /home |
| driver | không có hàng trong ma trận → mọi quyền false (tài khoản đã khoá) | /home | /home | — |

Nguồn: `src/lib/nav/trang-dau.ts` (`KHOI_VAN_PHONG` = owner/manager/accountant), `src/app/page.tsx`, `src/app/(dashboard)/home/page.tsx`, `src/components/home/sales-home.tsx`, `src/lib/home/sales-home.ts`.

---

## 4. POS chi tiết (`src/app/pos/**`, `src/components/pos/**`, `src/store/pos/*`)

**Store**
- `tabs.tsx`: nhiều chứng từ mở cùng lúc, tối đa `POS_TAB_MAX = 8`. Loại tab: SO / INV / RET / PUR / PRET. URL và tab đồng bộ hai chiều qua `posHref` / `parsePosPath`. Mỗi loại có chấm màu riêng.
- `settings.tsx`: thiết lập hiển thị lưu ở localStorage.
- `ref-data.tsx`: danh mục khách / hàng / tồn qua `loadSellRefData`, cache IndexedDB theo số phiên `danh_muc_ban_phien`.
- `product-search.tsx`: một ô tìm hàng duy nhất cho cả `/pos`.

**Component**
- Khung và thanh trên:
  - `pos-shell.tsx`: topbar + dãy tab + thân. Bắt phím ở khung. Màn hẹp hiện "Màn hình quá hẹp — dùng /sell trên điện thoại".
  - `pos-top-bar.tsx`: logo, tab, nút **Xử lý đặt hàng** (`PendingOrdersModal` — đơn đang tạm → lập HĐ), ⚙ `DisplaySettingsDrawer`, người dùng.
  - `doc-tabs.tsx`: dãy tab, nút + mở chứng từ mới.
- Bảy màn chứng từ:
  - `order-screen.tsx`: đơn lập / sửa, 106 KB.
  - `invoice-screen.tsx`: xuất hàng / sửa HĐ, 82 KB.
  - `return-screen.tsx`: phiếu trả.
  - `purchase-screen.tsx`: phiếu nhập.
  - `supplier-return-screen.tsx`: phiếu trả NCC.
  - Màn xem HĐ nằm thẳng trong `app/pos/hoa-don/[id]/page.tsx`.
- Khối dùng chung:
  - `doc-sub-header.tsx`: loại · mã · huy hiệu · ô ngày.
  - `line-table.tsx`: một bảng dòng hàng cho cả 6 loại, khác nhau ở cấu hình cột.
  - `unit-select.tsx`: chọn đơn vị.
  - `money-panel.tsx`: cột phải gồm thẻ đối tác, thẻ tiền, hàng nút 46px.
  - `partner-card.tsx`: bấm vào mở modal.
  - `partner-info-modal.tsx`: `KhachPosModal` / `NccPosModal`, sửa tại chỗ bằng `CustomerForm` / `SupplierFields`. Chặn phím POS lọt ra ngoài (`chanPhimPos`).
  - `search-dropdown.tsx`: tìm khách / NCC (F4).
  - `product-search-box.tsx`: ô tìm hàng ở cột phải.
  - `source-invoice-modal.tsx`: chọn HĐ gốc để trả.
  - `pending-orders-modal.tsx`: xử lý đặt hàng.
  - `seller-picker.tsx`, `doc-people.tsx`: người tạo / NV được gán.
  - `delta-preview-strip.tsx`: dải xem trước thay đổi khi sửa chứng từ đã ghi sổ.
  - `display-settings-drawer.tsx`: thiết lập hiển thị, rộng 452px.

**Phím tắt** (`src/lib/pos/keys.ts`; F* và Esc bắt cả khi đang gõ trong ô nhập):

| Phím | Chức năng |
|---|---|
| F2 | Thêm sản phẩm |
| F3 | Thêm sản phẩm (bí danh cũ) |
| F4 | Tìm khách hàng / NCC |
| F6 | Lưu nháp |
| F7 | Thêm hàng đổi |
| F8 | Thêm hàng trả |
| F9 | Gửi đơn / Xuất hàng |
| Esc | Đóng |

Gợi ý ở chân bảng: "Enter thêm dòng · F6 lưu nháp · F9 gửi đơn".

**Mở POS ở tab mới**
- `PosNewTab` (gắn trong `DashboardShell`) bắt mọi thẻ `<a>` dẫn vào lối POS.
- Nút đi bằng `router.push` phải gọi `diHoacMoPos(router.push, …)`.
- `openInNewTab` (`src/components/ui/new-tab-link.tsx`) tự đổi sang đích POS (`posTargetFor`).
- Middleware trả 307 khi cookie `npp_kho=rong` và đây là lượt mở trang (`dichPosMayChu`, `src/lib/nav/kho-man.ts`).
- Bảng ánh xạ (`src/lib/nav/pos-preview.ts`):

| Lối cũ | Đích POS |
|---|---|
| `/sell` | `/pos/don-hang/moi?customerId=` |
| `/sell/edit/<id>` | `/pos/don-hang/<id>/sua` |
| `/sales-invoices/new?order=` | `/pos/hoa-don/moi?order=` |
| `/sales-invoices/<id>/edit` | `/pos/hoa-don/<id>/sua` |
| `/returns/new` | `/pos/tra-hang/moi?invoice=&customerId=` |
| `/purchasing/receipts/new` | `/pos/nhap-hang/moi?ncc=` |
| `/purchasing/receipts/<id>/edit` | `/pos/nhap-hang/<id>/sua` |
| `/purchase-returns/new` | `/pos/tra-ncc/moi?ncc=` |
| `/purchase-returns/<id>/edit` | `/pos/tra-ncc/<id>/sua` |

**In**
- `posPrintHref`: SO → `/in/don-hang/<id>`, INV → `/in/hoa-don/<id>`, RET → `/in/tra-hang/<id>`. PUR và PRET chưa có mẫu in.
- `inTaiCho(url)` (`src/lib/pos/print-window.ts`) tạo iframe ẩn `#npp-khung-in` với `?auto=1`. Trang in tự gọi `print()` rồi `postMessage("npp:in-xong")`; POS gỡ iframe.
- Xuất hàng xong thì tự in qua `trangInHoaDon(id)`.

**Quét mã vạch**
- Trên POS: ô tìm hàng nhận máy quét USB (gõ mã rồi Enter); tra mã một luật bằng `findByCode` (mã vạch trước, rồi SKU).
- Trên điện thoại: `BarcodeScanner` ở `/sell/scan`, `/inventory/stock-in`, `/inventory/stock-issue`, form sản phẩm.

**RPC POS**
- `create_order_with_lines`
- `get_invoiceable_lines` (GET), `post_invoice`, `reissue_invoice`, `cancel_invoice`
- `save_pos_return`, `create_return_with_lines`
- `complete_purchase_invoice`, `sua_phieu_nhap`
- `complete_supplier_return`, `cancel_supplier_return`
- `assign_doc_seller`, `ton_ban_theo_hang`
- Khoá thực thể: `acquire_entity_lock`, `heartbeat_entity_lock`, `release_entity_lock`
- Đo thời gian nạp: `baoNapSauKhiVe` → `/api/do-nap`

---

## 5. Thư viện component dùng chung

### 5.1 `src/components/ui/*` (63 tệp)
- **shadcn/Radix cơ bản:** avatar, badge, button, card, checkbox, dialog, dropdown-menu, input, label, popover, scroll-area, select (có ô tìm khi danh sách dài, `mucCanDung`), separator, sheet (tấm trượt), skeleton, switch, table (cuộn ngang), tabs, textarea, toast, toaster.
- **Danh sách chứng từ:**
  - doc-list-layout: khuôn danh sách Đơn/HĐ — `DocListLayout`, `DocListSearch`, `LocNhanhButton`, `XoaLocButton`, `LocNhanhField`, `KetQuaThieu`.
  - doc-table: lưới máy tính, có sắp xếp — `DocTable`, `DocCodeLink`, `DocCellText`, `DocCellDate`.
  - doc-card-list: thẻ chứng từ trên điện thoại.
  - doc-list-mobile-head: đầu trang xanh của danh sách trên điện thoại.
  - doc-list-row: dòng và tiêu đề nhóm trên điện thoại.
  - doc-list-summary, doc-list-totals: dải tóm tắt và tổng.
  - doc-quick-view: ngăn xem nhanh.
  - doc-search-box: ô tìm + tìm theo trường.
  - status-chips, status-badge (kèm `PaymentStatusBadge`).
  - list-view-toolbar: `ColumnPicker`, `FilterPicker`.
  - advanced-filter: bộ lọc trường → phép so → giá trị.
  - bulk-actions-bar, data-pagination, load-more.
  - period-select: Hôm nay / Tuần / Tháng / Tất cả.
  - segmented-scroller: hàng chip cuộn ngang.
  - mobile-filter-bar, mobile-record-card.
  - empty-state, hop-loi-tai (hộp lỗi tải + Thử lại).
- **Nhập liệu:** money-input, percent-input, search-select, compact-select, product-picker, barcode-scanner (camera tự quản + ZXing đã vá + nhập tay), dong-tao-moi, khung-tao-nhanh (khung tạo mới tại chỗ).
- **Hành động / xuất:** print-button (`PrintButton`, `moHopThoaiIn`), xuat-excel-button (Excel danh sách), xuat-excel-phieu (Excel một phiếu), new-tab-link (`NewTabLink`, `openInNewTab`), confirm-dialog, sticky-action-bar.
- **Khác:** collapsible-section (chỉ gập trên điện thoại), catalogue-short-note, error-boundary, link (`next/link` tắt prefetch), page-header, qr-code (dựng phía client).

### 5.2 Các nhóm khác
- **`detail/detail-chrome.tsx`**: `DetailHero`, `StatusPill`, `DetailColumns`, `DetailCard`, `DetailRow`, `DetailTimeline`, `DetailCustomerCard`. Dùng cho chi tiết đơn và chi tiết HĐ bán.
- **`tao-nhanh/*`**: `TaoNhanhKhach` (hai bước lọc trùng SĐT → form, máy tính và điện thoại), `TaoNhanhNcc`, `TaoNhanhSanPham`, `TaoNhanhTuyen`.
- **`printing/*`**: `SalesInvoice` (mẫu KiotViet; `grossUpLines`, `bangChu`), `ReturnSlip`, `DeliverySlip` (A5), `DriverList`, `PaymentReceiptTT` (Mẫu 01-TT, TT200), `Payslip`.
- **`offline/*`**: `OfflineIndicator`, `ServiceWorkerRegister`.
- **`soan-hang/*`**: `ChonHoaDon`, `SoanHangMayTinh`, `SoanHangDienThoai`, `ToInSoanHang` (`inPhieuNhat` / `inNhanRo`), hook `useLuotSoan`.
- **`mobile/*`**: `dau-trang` (`DauTrangXanh` / `DauTrangTrang`), `so-thu-tu` (số thứ tự dòng).
- **`layout/*`**: dashboard-shell, sidebar, header, mobile-nav, mobile-search-overlay, notification-bell, notification-panel (lazy), page-title-context, mo-menu-context, user-menu, user-menu-day (lazy).
- **`nav/ghi-kho-man.tsx`**: ghi cookie `npp_kho`.
- **`sell/*`**: bottom-bar, customer-deeplink, don-do-modal, line-edit-sheet, pos-desktop-redirect, pos-new-tab (`PosNewTab`, `diHoacMoPos`), prefetch, product-card, return-line-sheet, return-price-input.
- **`orders/*`**: approval-badge, customer-quick-info, desktop-order-table, invoice-editor, invoice-money-summary, mobile-order-detail, mobile-order-list, mobile-orders-screen, order-drawer, order-table, related-docs, return-summary, route-filter.
- **`analytics/*`**: analytics-sidebar, date-range-picker, kpi-card, report-frame (`downloadXlsx`), report-shell, report-table, section-tabs, top-list, trend-chart.
- **`bao-cao/*`**: bang, bieu-do, dung-chung, khoi, khung, thanh-loc, xem-nhanh, và 6 màn man-*.
- **`customers/*` (16):** assignment-manager, chon-moc-thoi-gian, customer-dupe-finder, customer-form, customer-import-dialog, customer-managers, customer-photo-capture, customer-profile-card, customer-quick-view, customer-table, hang-da-lay-khach, mobile-customers-screen, route-form, tao-khach-dien-thoai, tim-khach-truoc-khi-tao, visit-checkin-dialog.
- **`inventory/*` (8):** chi-tiet-phieu-dien-thoai, duyet-dieu-chinh-mobile, kho-hang-dien-thoai, kiem-ke-mobile, phieu-kho-dien-thoai, stock-balance-table, stock-history-drawer, stock-in-mobile.
- **`purchasing/*` (5):** phieu-ncc-mobile, purchase-receipt-form, purchase-return-form, purchasing-lines-editor, truong-phieu-ncc.
- **`returns/*` (7):** doi-ngay-phieu-tra, hoi-tra-da-nhap, mobile-return-sheet, mobile-returns-screen, o-ngay-nhap, phieu-tra-khach-mobile, return-drawer.
- **`suppliers/*` (7):** merge-supplier-dialog, mobile-suppliers-screen, supplier-danger-zone, supplier-edit-sheet, supplier-fields, supplier-form, supplier-import-dialog.
- **`users/*` (4):** ds-nhan-vien-dien-thoai, nut-dang-nhap-nhan-vien, qr-login-dialog, xoa-nhan-vien-dialog.
- **Một tệp mỗi nhóm:** settings/permission-matrix, products (4 tệp), sales-invoices (desktop-invoice-table, invoice-drawer), finance (cash-receipt-drawer, phieu-chi-ncc), payables/che-do-cong-no-ncc, deliveries/pod-capture-sheet, dashboard (pending-work-widget, tong-quan-mobile), home/sales-home, setup/setup-banner, brand/brand-mark, backup/public-info.
- **Ở gốc `src/components`:** error-screen, icon, permissions-loader.

Hooks đáng chú ý (`src/hooks/*`, 33 tệp): use-role-guard, use-khoMay (`use-is-desktop.ts`), use-auth, use-sell-cart, use-sell-data, use-committed-stock, use-order-sync, use-entity-lock, use-list-view-prefs, use-pagination, use-phan-trang-tai-cho, use-advanced-filter, use-field-search, use-khach-loc, use-do-trung-khach, use-luot-nap, use-bao-cao, use-bang-gia-nhap, use-khoa-gui, use-leave-after-print, use-online-status.

---

## 6. Số lượng

**Tệp route**
| loại | số |
|---|---|
| page.tsx | 180 |
| layout.tsx | 11 (gốc, `(dashboard)`, pos, in, sell, reports, reports/finance, analytics, analytics/business, analytics/customers, analytics/products) |
| route.ts | 18 (17 dưới `/api` + `/qr-login`) |
| loading / error / not-found / global-error | 8 |

**Số route theo module** (page.tsx)
| module | số |
|---|---|
| POS `/pos` | 11 |
| Bán hàng điện thoại `/sell` | 10 |
| Đơn hàng | 4 (1 redirect) |
| Hoá đơn bán | 5 |
| HĐĐT `/invoices` | 5 |
| Trả hàng | 4 |
| Công nợ phải thu (receivables 8 + opening-balances 1) | 9 |
| Phiếu thu / chi | 5 |
| Khách hàng + tuyến / PJP / visits | 9 |
| Sản phẩm | 2 |
| Kho (`/inventory`: 15 trang dùng được + 5 trang bị chặn) + 3 trang chỉ chuyển hướng (warehouse ×2, operations) | 23 |
| Mua hàng / NCC / công nợ NCC (purchasing 7, purchase-returns 4, suppliers 3, payables 4) | 18 |
| Khuyến mãi | 3 |
| Hoa hồng | 4 |
| Nhân sự / lương (hr 8 + luong-cua-toi) | 9 |
| Báo cáo (`/bao-cao` 7, `/reports` 14, `/analytics` 9, `/dashboard` 1) | 31 |
| Cài đặt (settings 9 + setup) | 10 |
| Giao hàng (đã ngưng, bị chặn) | 5 |
| Trang chủ / Thông báo / Trợ giúp | 3 |
| In `/in` | 3 |
| Ngoài khung (`/`, login, maintenance, debug, backup ×3) | 7 |
| **Tổng** | **180** |

Màn thật cần dựng lại: khoảng 160. Loại khỏi 180: 9 trang chuyển hướng / xuất lại, 12 trang bị chặn (deliveries ×5, stock-out ×2, pending, stocktake, stocktake-check, …), và debug/backup.

**Component**
| nhóm | số tệp |
|---|---|
| `src/components` (.tsx) | 228 (+2 .ts) |
| ui | 63 |
| pos | 22 |
| customers | 16 |
| bao-cao | 13 (12 tsx) |
| orders | 13 |
| layout | 11 |
| sell | 10 |
| analytics | 9 |
| inventory | 8 |
| returns, suppliers | 7 mỗi nhóm |
| printing | 6 |
| purchasing, soan-hang | 5 mỗi nhóm |
| products, tao-nhanh, users | 4 mỗi nhóm |
| còn lại | 1–2 mỗi nhóm |
| Store POS (`src/store/pos`) | 4 |
| Hooks | 33 |

**Tệp tham chiếu chính:** `/home/user/nppsale/src/lib/nav/nav-permission.ts`, `/home/user/nppsale/src/components/layout/sidebar.tsx`, `/home/user/nppsale/src/components/layout/mobile-nav.tsx`, `/home/user/nppsale/src/components/layout/header.tsx`, `/home/user/nppsale/src/lib/nav/mobile-chrome.ts`, `/home/user/nppsale/src/lib/nav/pos-preview.ts`, `/home/user/nppsale/src/lib/nav/kho-man.ts`, `/home/user/nppsale/src/lib/nav/trang-dau.ts`, `/home/user/nppsale/src/lib/permissions.ts`, `/home/user/nppsale/src/lib/permissions-features.ts`, `/home/user/nppsale/src/lib/pos/keys.ts`, `/home/user/nppsale/src/lib/pos/tabs.ts`, `/home/user/nppsale/src/lib/pos/print-window.ts`, `/home/user/nppsale/src/middleware.ts`, `/home/user/nppsale/public/sw.js`.
