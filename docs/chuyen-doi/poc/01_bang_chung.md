# Bằng chứng thô của PoC P0 (05–06/11/2026)

Trích **nguyên văn** kết quả máy in ra (dòng `KQ {…}` của `bench --site poc.local execute nppsale.poc.do.<hàm>`), đọc bằng bộ giải JSON từ nhật ký phiên — không chép tay. Giờ ở phần A là **UTC** (giờ VN = UTC + 7); giờ trong sổ (`creation`) là giờ VN. Báo cáo đọc từ đây: `00_ket_qua_poc.md`.

Các kết quả đã **rút lại** vẫn để nguyên văn ở đây và ghi rõ vì sao rút — để ai đọc lại cũng thấy được lỗi cũ.

## A. Ngày 05/11 — các lượt chạy riêng lẻ

**14:23:31 UTC · nhap_ton — tồn đầu (3 phiếu nhập + Material Receipt), sau là lô -L4**

```json
{"pi": ["ACC-PINV-2026-00001", "ACC-PINV-2026-00002", "ACC-PINV-2026-00003"], "se": "MAT-STE-2026-00001"}
```

**14:24:30 UTC · ton_lo — tồn lô SP016 sau lượt 10 lần hỏng (đọc qua get_batch_qty / bundle)**

```json
{"get_batch_qty": [{"batch_no": "SP016-L1", "warehouse": "Kho ban - NPP", "qty": 42.0, "expiry_date": "2027-10-06"}, {"batch_no": "SP016-L2", "warehouse": "Kho ban - NPP", "qty": 240.0, "expiry_date": "2027-10-13"}, {"batch_no": "SP016-L3", "warehouse": "Kho ban - NPP", "qty": 240.0, "expiry_date": "2027-10-20"}], "sle": [{"batch_no": null, "qty": 522.0}], "bundle_entries": [{"batch_no": "SP016-L1", "qty": 42.0}, {"batch_no": "SP016-L2", "qty": 240.0}, {"batch_no": "SP016-L3", "qty": 240.0}], "si_moi": [{"name": "ACC-SINV-2026-00007"}, {"name": "ACC-SINV-2026-00006"}, {"name": "ACC-SINV-2026-00005"}]}
```

**14:26:56 UTC · xuat_hang_tach_lo — dòng 2 thùng SP016, cách tách dòng**

```json
{"so_insert": 496, "so_submit": 142, "dong": [["SP016", "Thung", 1.75, 24.0, "SP016-L1"], ["SP016", "Thung", 0.25, 24.0, "SP016-L2"]], "si_insert": 113, "dong_sau_insert": [["SP016", "Thung", 1.75, 42.0, "SP016-L1", null], ["SP016", "Thung", 0.25, 6.0, "SP016-L2", null]], "si_submit": 190, "tong": 942, "so": "SAL-ORD-2026-00011", "si": "ACC-SINV-2026-00011", "so_dong": 2, "tag": ""}
```

**14:26:56 UTC · xuat_hang_tach_lo — dòng 2 thùng SP016, cách bundle (lô đầu đã hết nên thực tế một lô)**

```json
{"so_insert": 482, "so_submit": 127, "dong": [["SP016", "Thung", 2.0, 24.0, null]], "si_insert": 105, "dong_sau_insert": [["SP016", "Thung", 2.0, 48.0, null, "2828c701cbf6fab915c3"]], "si_submit": 134, "tong": 848, "so": "SAL-ORD-2026-00012", "si": "ACC-SINV-2026-00012", "so_dong": 1, "tag": ""}
```

**14:27:55 UTC · xuat_hang_nhieu — 10 lượt × 15 dòng (13 theo lô + 2 không lô), bundle**

```json
{"lan": 10, "loi": [], "tong_ms_min": 1156, "tong_ms_tb": 1300, "tong_ms_max": 1783, "buoc_tb": {"so_insert": 173, "so_submit": 150, "si_insert": 405, "si_submit": 573}}
```

**14:27:55 UTC · thue_lam_tron BẢN CŨ — ĐÃ RÚT LẠI 06/11 (so bằng round() của Python, làm tròn nửa về số chẵn; 5 dòng / HĐ; ngưỡng ≥ 1 đ)**

```json
{"n": 50, "precision": "0", "rounding": "Commercial Rounding", "lech_vat": 1, "lech_tong": 0, "mau": [{"si": "ACC-SINV-2026-00036", "vat_lõi": 7307.0, "vat_npp": 7306, "tong_lõi": 390156.0, "tong_npp": 390156, "net_lõi": 382849.0, "net_npp": 382849.0, "rounding_adj": 0.0}]}
```

**14:27:55 UTC · thue_lam_tron BẢN CŨ — ĐÃ RÚT LẠI 06/11 (so bằng round() của Python, làm tròn nửa về số chẵn; 5 dòng / HĐ; ngưỡng ≥ 1 đ)**

```json
{"n": 30, "precision": "0", "rounding": "Commercial Rounding", "lech_vat": 0, "lech_tong": 0, "mau": []}
```

**14:27:55 UTC · thue_lam_tron BẢN CŨ — ĐÃ RÚT LẠI 06/11 (so bằng round() của Python, làm tròn nửa về số chẵn; 5 dòng / HĐ; ngưỡng ≥ 1 đ)**

```json
{"n": 50, "precision": "2", "rounding": "Commercial Rounding", "lech_vat": 1, "lech_tong": 2, "mau": [{"si": "ACC-SINV-2026-00028", "vat_lõi": 16394.0, "vat_npp": 16394, "tong_lõi": 353033.0, "tong_npp": 353032, "net_lõi": 336639.0, "net_npp": 336639.0, "rounding_adj": 0.0}, {"si": "ACC-SINV-2026-00061", "vat_lõi": 11513.0, "vat_npp": 11512, "tong_lõi": 231155.0, "tong_npp": 231154, "net_lõi": 219642.0, "net_npp": 219642.0, "rounding_adj": 0.0}]}
```

**14:28:33 UTC · giam_dau_phieu_nhap — lượt đầu, template thuế CHƯA có tài khoản đầu vào → VAT sai**

```json
{"deduct_row": {"pi": "ACC-PINV-2026-00004", "net_total": 630000.0, "vat": -50000.0, "grand_total": 580000.0, "rounded_total": 580000.0, "net_dong": [200000.0, 210000.0, 220000.0], "gia_von_lo": [["SP003", 22000.0], ["SP002", 21000.0], ["SP001", 20000.0]]}, "apply_discount_on": {"pi": "ACC-PINV-2026-00005", "net_total": 580000.0, "vat": 0.0, "grand_total": 580000.0, "rounded_total": 580000.0, "net_dong": [184127.0, 193333.0, 202540.0], "gia_von_lo": [["SP003", 20254.0], ["SP002", 19333.3], ["SP001", 18412.7]]}}
```

**14:28:33 UTC · lcv_sua_gia — LCV −30.000 lên ACC-PINV-2026-00001 (dòng 'repost' rỗng vì lọc theo voucher_no; số việc thật ở mục D-Q1)**

```json
{"lcv": "MAT-LCV-2026-00001", "pi_van_la": "ACC-PINV-2026-00001", "repost": []}
```

**14:28:33 UTC · hai_dong_cung_lo — 1 thùng + 3 lon cùng mã cùng lô**

```json
{"allow_multiple_items=1": {"ok": "ACC-SINV-2026-00023"}, "allow_multiple_items=0": {"LOI": "Item <strong>SP002</strong> entered multiple times.<br><br>Please enable <strong>Allow Item to Be Added Multiple Times in a Transaction</strong> in <a href=\"http://poc.local/desk/selling-settings/Sell"}}
```

**14:28:33 UTC · doi_ma_lo — đổi tên Batch đã có sổ**

```json
{"doi_duoc": false, "LOI": "Batch not allowed to be renamed"}
```

**14:28:33 UTC · nhap_lai_lo_het_han (bản 1) — lô SP001-HETHAN chưa commit nên bundle báo thiếu lô**

```json
{"dong_co_batch_no": {"LOI": "BatchExpiredError: Row #1: The batch <a href=\"http://poc.local/desk/batch/SP001-HETHAN\">SP001-HETHAN</a> has already expired."}, "bundle_inward": {"LOI": "LinkValidationError: Could not find Row #1: Batch No: SP001-HETHAN"}}
```

**14:28:33 UTC · dau_ky_giu_ma — tờ đầu kỳ giữ mã HĐ cũ**

```json
{"ten": "HD-0042", "outstanding": 1250000.0, "is_opening": "Yes"}
```

**14:28:33 UTC · ghi_co_doc_lap (bản 1) — app tra giá vốn qua SLE.batch_no nên gửi incoming_rate = 0 (ACC-SINV-2026-00024)**

```json
{"cn": "ACC-SINV-2026-00024", "outstanding": -55755.0, "gia_von_goc": 0.0, "gia_ban_dong": 11150.7, "dat_incoming_rate": true, "ban_het": false, "sle": [{"warehouse": "Kho can date - NPP", "batch_no": null, "actual_qty": 5.0, "incoming_rate": 11150.7, "valuation_rate": 11150.7, "stock_value_difference": 55754.0}]}
```

**14:30:04 UTC · va_thue_mua — thêm tài khoản thuế đầu vào vào 4 Item Tax Template**

```json
{"ok": true}
```

**14:30:04 UTC · giam_dau_phieu_nhap — sau va_thue_mua (PI 00006 dòng trừ / 00007 apply_discount_on)**

```json
{"deduct_row": {"pi": "ACC-PINV-2026-00006", "net_total": 630000.0, "vat": 400.0, "grand_total": 630400.0, "rounded_total": 630400.0, "net_dong": [200000.0, 210000.0, 220000.0], "gia_von_lo": [["SP003", 22000.0], ["SP002", 21000.0], ["SP001", 20000.0]]}, "apply_discount_on": {"pi": "ACC-PINV-2026-00007", "net_total": 583704.0, "vat": 46696.0, "grand_total": 630400.0, "rounded_total": 630400.0, "net_dong": [185303.0, 194568.0, 203833.0], "gia_von_lo": [["SP003", 20383.3], ["SP002", 19456.8], ["SP001", 18530.3]]}}
```

**14:30:04 UTC · ghi_co_doc_lap2 — dat_incoming_rate=True, ban_het=False**

```json
{"cn": "ACC-SINV-2026-00025", "outstanding": -55755.0, "lo": "SP001-L1", "gia_von_goc": 8105.516666667, "gia_ban_dong": 11150.7, "dat_incoming_rate": true, "ban_het": false, "sle": [{"warehouse": "Kho can date - NPP", "actual_qty": 5.0, "incoming_rate": 8105.516666667, "valuation_rate": 9628.1583, "stock_value_difference": 40528.0}], "sbe": [{"batch_no": "SP001-L1", "qty": 5.0, "incoming_rate": 8105.516666667}]}
```

**14:30:04 UTC · nhap_lai_lo_het_han2 — lô hết hạn: bundle Inward / tờ ghi có có kho**

```json
{"bundle_inward": {"ok": "MAT-STE-2026-00002", "bundle": "15bfcbabf7ccd772691b"}, "credit_note_co_kho": {"ok": "ACC-SINV-2026-00026"}}
```

**14:33:31 UTC · ghi_co_doc_lap2 — dat_incoming_rate=False, ban_het=False**

```json
{"cn": "ACC-SINV-2026-00027", "outstanding": -55755.0, "lo": "SP001-L1", "gia_von_goc": 8105.516666667, "gia_ban_dong": 11150.7, "dat_incoming_rate": false, "ban_het": false, "sle": [{"warehouse": "Kho can date - NPP", "actual_qty": 5.0, "incoming_rate": 9628.108333334, "valuation_rate": 9655.570090909, "stock_value_difference": 48141.0}], "sbe": [{"batch_no": "SP001-L1", "qty": 5.0, "incoming_rate": 9628.108333334}]}
```

**14:33:31 UTC · ghi_co_doc_lap2 — dat_incoming_rate=False, ban_het=True**

```json
{"cn": "ACC-SINV-2026-00029", "outstanding": -55755.0, "lo": "SP001-L1", "gia_von_goc": 8105.516666667, "gia_ban_dong": 11150.7, "dat_incoming_rate": false, "ban_het": true, "sle": [{"warehouse": "Kho ban - NPP", "actual_qty": 5.0, "incoming_rate": 11150.7, "valuation_rate": 8999.435238095, "stock_value_difference": 55754.0}], "sbe": [{"batch_no": "SP001-L1", "qty": 5.0, "incoming_rate": 11150.7}]}
```

**14:33:31 UTC · repost_khi_huy — huỷ ACC-SINV-2026-00001 (danh sách việc rỗng vì lọc theo voucher_no; số việc thật ở D-Q1)**

```json
{"si": "ACC-SINV-2026-00001", "cancel_ms": 1248, "riv_sau_huy": [], "repost_ms": 4192, "riv_sau_repost": []}
```

**14:38:47 UTC (giờ tạo `ACC-PINV-2026-00008` trong sổ; dòng kết quả chép lúc 14:41:29) · nhap_ton — lô -L4: 1 phiếu nhập 30 dòng × 600 lon + Material Receipt hàng không lô, chạy giữa lượt 1 và lượt 2 của bài đồng thời 1b**

```json
{"pi": ["ACC-PINV-2026-00008"], "se": "MAT-STE-2026-00003"}
```

**lcv_kiem_lai** (05/11 14:30 UTC) — dòng kết quả bị cắt khi in (lệnh in giới hạn 1.500 ký tự) và hàm chỉ liệt kê `limit=5` việc nên bản báo cáo 05/11 ghi nhầm "5 việc": phần còn đọc được là `repost_ms: 16820`, 5 việc Queued → Completed, sổ lô SP001-L1 (PI 00001 +240 @ 8.105,52; HĐ 00003 −18). Số việc thật (30) và giá vốn lô đọc qua bundle ở mục D (Q1, Q2).

## B. Ngày 05/11 — bài đồng thời cũ (5 tiến trình, 15 dòng SL 1–3 Lon/Lốc/Thùng; lượt 1–2 mỗi tiến trình lập ĐƠN + HĐ trong một giao dịch, lượt 3 commit đơn trước rồi mới khoá Bin và lập HĐ — `xuat_hang_mot`)

Khoá `bat_dau` của bản 05/11 thực ra ghi giờ **kết thúc** lượt đo (đã sửa trong mã ngày 06/11, thêm `ket_thuc`).

### lượt 1 — lạnh (không làm nóng), không khoá

```text
p1: {"so_insert": 3351, "so_submit": 221, "si_insert": 495, "LOI": "BatchNegativeStockError: Batch No SP021-L1 of an Item SP021 has negative stock of quantity -12.0 in the warehouse Kho ban - NPP", "bat_dau": 1793889329.392}
p2: {"so_insert": 4547, "so_submit": 245, "si_insert": 493, "LOI": "BatchNegativeStockError: Batch No SP011-L1 of an Item SP011 has negative stock of quantity -12.0 in the warehouse Kho ban - NPP", "bat_dau": 1793889330.74}
p3: {"so_insert": 5903, "so_submit": 231, "si_insert": 446, "LOI": "BatchNegativeStockError: Batch No SP001-L1 of an Item SP001 has negative stock of quantity -1.0 in the warehouse Kho ban - NPP", "bat_dau": 1793889331.895}
p4: {"so_insert": 2058, "so_submit": 237, "si_insert": 456, "LOI": "BatchNegativeStockError: Batch No SP004-L1 of an Item SP004 has negative stock of quantity -2.0 in the warehouse Kho ban - NPP", "bat_dau": 1793889328.191}
p5: {"so_insert": 604, "so_submit": 233, "si_insert": 439, "si_submit": 596, "tong": 1872, "so": "SAL-ORD-2026-00023", "si": "ACC-SINV-2026-00030", "so_dong": 15, "tag": "p5", "bat_dau": 1793889326.901}
```

### lượt 2 — đã làm nóng, không khoá

```text
p1: {"so_insert": 1328, "so_submit": 143, "si_insert": 416, "LOI": "BatchNegativeStockError: Batch No SP025-L1 of an Item SP025 has negative stock of quantity -33.0 in the warehouse Kho ban - NPP", "nong": "BatchNegativeStockError: Batch No SP004-L2 of an Item SP004 has negative stock of quantity -7.0 in the warehouse Kho ban - NPP", "khoa": false, "bat_dau": 1793889606.273}
p2: {"so_insert": 150, "so_submit": 134, "si_insert": 401, "si_submit": 537, "tong": 1222, "so": "SAL-ORD-2026-00025", "si": "ACC-SINV-2026-00032", "so_dong": 15, "tag": "kFalse-p2", "nong": 1988, "khoa": false, "bat_dau": 1793889605.246}
p3: {"so_insert": 2362, "so_submit": 136, "si_insert": 451, "LOI": "BatchNegativeStockError: Batch No SP019-L1 of an Item SP019 has negative stock of quantity -37.0 in the warehouse Kho ban - NPP", "nong": "BatchNegativeStockError: Batch No SP004-L2 of an Item SP004 has negative stock of quantity -24.0 in the warehouse Kho ban - NPP", "khoa": false, "bat_dau": 1793889607.216}
p4: {"so_insert": 3311, "so_submit": 164, "si_insert": 403, "LOI": "BatchNegativeStockError: Batch No SP003-L1 of an Item SP003 has negative stock of quantity -1.0 in the warehouse Kho ban - NPP", "nong": "BatchNegativeStockError: Batch No SP017-L1 of an Item SP017 has negative stock of quantity -6.0 in the warehouse Kho ban - NPP", "khoa": false, "bat_dau": 1793889608.149}
p5: {"so_insert": 4237, "so_submit": 134, "si_insert": 393, "LOI": "BatchNegativeStockError: Batch No SP008-L1 of an Item SP008 has negative stock of quantity -12.0 in the warehouse Kho ban - NPP", "nong": "BatchNegativeStockError: Batch No SP015-L1 of an Item SP015 has negative stock of quantity -12.0 in the warehouse Kho ban - NPP", "khoa": false, "bat_dau": 1793889609.008}
```

### lượt 3 — đã làm nóng, khoá Bin trước khi lập HĐ

```text
p1: {"so_insert": 3695, "so_submit": 922, "khoa_ms": 1, "si_insert": 398, "si_submit": 535, "tong": 5550, "so": "SAL-ORD-2026-00035", "si": "ACC-SINV-2026-00042", "so_dong": 15, "tag": "kTrue-p1", "nong": 6322, "khoa": true, "bat_dau": 1793889689.588}
p2: {"so_insert": 1558, "so_submit": 989, "khoa_ms": 2, "si_insert": 411, "si_submit": 580, "tong": 3538, "so": "SAL-ORD-2026-00033", "si": "ACC-SINV-2026-00040", "so_dong": 15, "tag": "kTrue-p2", "nong": 3039, "khoa": true, "bat_dau": 1793889687.56}
p3: {"so_insert": 2688, "so_submit": 879, "khoa_ms": 1, "si_insert": 493, "si_submit": 532, "tong": 4591, "so": "SAL-ORD-2026-00034", "si": "ACC-SINV-2026-00041", "so_dong": 15, "tag": "kTrue-p3", "nong": 1957, "khoa": true, "bat_dau": 1793889688.614}
p4: {"so_insert": 486, "so_submit": 939, "khoa_ms": 3, "si_insert": 483, "si_submit": 610, "tong": 2519, "so": "SAL-ORD-2026-00032", "si": "ACC-SINV-2026-00039", "so_dong": 15, "tag": "kTrue-p4", "nong": 5300, "khoa": true, "bat_dau": 1793889686.543}
p5: {"so_insert": 199, "so_submit": 176, "khoa_ms": 1, "si_insert": 474, "si_submit": 551, "tong": 1400, "so": "SAL-ORD-2026-00031", "si": "ACC-SINV-2026-00038", "so_dong": 15, "tag": "kTrue-p5", "nong": 4246, "khoa": true, "bat_dau": 1793889685.421}
```

## C. Ngày 06/11 — đo lại sau vòng soát

### C1. Thuế + làm tròn (`thue_lam_tron` bản 06/11, `dat_precision`) — **đã thay bằng C1b**: đơn giá sau giảm của bản này là bản rút gọn round(giá × (1 − %)), không phải luật nppsale; giữ lại để đối chiếu

Tên HĐ trong các dòng "mẫu" (`ACC-SINV-2026-00043`…) là tờ đã ROLLBACK; dãy số lùi lại nên cùng tên ấy nay là tờ khác trong sổ (ví dụ `00045` trong sổ là tờ bán bớt 1 dòng của bài 1c, lập 06/11 19:39:15, không phải HĐ 14 dòng ở mẫu) — đừng tra sổ theo các tên này. Các số `don_gia_npp` / `tien_hang_npp` / `vat_npp` / `tong_npp` tính đơn giá sau giảm bằng bản rút gọn round(giá × (1 − %)) (`thue_lam_tron` trong `do.py`), chưa theo đúng luật nppsale (% trên tiền dòng) — xem báo cáo mục 2.(2).

```text
## setup._thue (site cu: khong doi gi)
## p0 app khong giam don
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 0, "ty_le_giam_dong": 0.3, "cach_giam_dong": "app", "seed": 1}, "precision": "0", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 738, "dong_giam": 220, "lech_don_gia": 0, "mat_pct": 13, "lech_tien_hang": 0, "lech_vat": 0, "vat_co_le": 0, "lech_grand": 0, "lech_rounded": 0}
## p0 loi tu tinh giam dong
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 0, "ty_le_giam_dong": 0.3, "cach_giam_dong": "loi", "seed": 1}, "precision": "0", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 738, "dong_giam": 220, "lech_don_gia": 13, "mat_pct": 0, "lech_tien_hang": 12, "lech_vat": 8, "vat_co_le": 0, "lech_grand": 12, "lech_rounded": 12}
   mẫu (tối đa 4): [{"loai": "don_gia", "item": "SP011", "uom": "Thung", "gia_bang": 275668.0, "pct": 12.5, "rate_loi": 241209.0, "giam_loi": 34459.0, "don_gia_npp": 241210.0}, {"loai": "hd", "si": "ACC-SINV-2026-00045", "so_dong": 14, "tien_hang_loi": 28202908.0, "tien_hang_npp": 28202922.0, "vat_loi": 1175412.0, "vat_tho": 1175412.48, "vat_npp": 1175412.0, "grand_loi": 29378320.0, "rounded_loi": 29378320.0, "tong_npp": 29378334.0, "giam_don": 0.0}, {"loai": "don_gia", "item": "SP020", "uom": "Thung", "gia_bang": 305260.0, "pct": 12.5, "rate_loi": 267102.0, "giam_loi": 38158.0, "don_gia_npp": 267103.0}, {"loai": "hd", "si": "ACC-SINV-2026-00047", "so_dong": 20, "tien_hang_loi": 30909410.0, "tien_hang_npp": 30909428.0, "vat_loi": 1280299.0, "vat_tho": 1280299.8, "vat_npp": 1280300.0, "grand_loi": 32189709.0, "rounded_loi": 32189709.0, "tong_npp": 32189728.0, "giam_don": 0.0}]
## p0 app giam don 5%
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 5, "ty_le_giam_dong": 0.3, "cach_giam_dong": "app", "seed": 2}, "precision": "0", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 720, "dong_giam": 232, "lech_don_gia": 0, "mat_pct": 23, "lech_tien_hang": 0, "lech_vat": 0, "vat_co_le": 0, "lech_grand": 0, "lech_rounded": 0}
## dat precision 2
{"currency_precision": "2"}
## p2 app khong giam don
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 0, "ty_le_giam_dong": 0.3, "cach_giam_dong": "app", "seed": 1}, "precision": "2", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 738, "dong_giam": 220, "lech_don_gia": 0, "mat_pct": 203, "lech_tien_hang": 0, "lech_vat": 50, "vat_co_le": 50, "lech_grand": 50, "lech_rounded": 0}
   mẫu (tối đa 4): [{"loai": "hd", "si": "ACC-SINV-2026-00043", "so_dong": 12, "tien_hang_loi": 15262353.0, "tien_hang_npp": 15262353.0, "vat_loi": 821591.24, "vat_tho": 821591.24, "vat_npp": 821591.0, "grand_loi": 16083944.24, "rounded_loi": 16083944.0, "tong_npp": 16083944.0, "giam_don": 0.0}, {"loai": "hd", "si": "ACC-SINV-2026-00044", "so_dong": 15, "tien_hang_loi": 20150754.0, "tien_hang_npp": 20150754.0, "vat_loi": 1482855.88, "vat_tho": 1482855.88, "vat_npp": 1482856.0, "grand_loi": 21633609.88, "rounded_loi": 21633610.0, "tong_npp": 21633610.0, "giam_don": 0.0}, {"loai": "hd", "si": "ACC-SINV-2026-00045", "so_dong": 14, "tien_hang_loi": 28202922.0, "tien_hang_npp": 28202922.0, "vat_loi": 1175412.48, "vat_tho": 1175412.48, "vat_npp": 1175412.0, "grand_loi": 29378334.48, "rounded_loi": 29378334.0, "tong_npp": 29378334.0, "giam_don": 0.0}, {"loai": "hd", "si": "ACC-SINV-2026-00046", "so_dong": 16, "tien_hang_loi": 13337600.0, "tien_hang_npp": 13337600.0, "vat_loi": 826173.09, "vat_tho": 826173.09, "vat_npp": 826173.0, "grand_loi": 14163773.09, "rounded_loi": 14163773.0, "tong_npp": 14163773.0, "giam_don": 0.0}]
## p2 loi tu tinh giam dong
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 0, "ty_le_giam_dong": 0.3, "cach_giam_dong": "loi", "seed": 1}, "precision": "2", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 738, "dong_giam": 220, "lech_don_gia": 203, "mat_pct": 0, "lech_tien_hang": 48, "lech_vat": 50, "vat_co_le": 50, "lech_grand": 50, "lech_rounded": 43}
   mẫu (tối đa 4): [{"loai": "don_gia", "item": "SP025", "uom": "Lon", "gia_bang": 13425.0, "pct": 7.5, "rate_loi": 12418.12, "giam_loi": 1006.88, "don_gia_npp": 12418.0}, {"loai": "don_gia", "item": "SP004", "uom": "Thung", "gia_bang": 252652.0, "pct": 15.0, "rate_loi": 214754.2, "giam_loi": 37897.8, "don_gia_npp": 214754.0}, {"loai": "hd", "si": "ACC-SINV-2026-00043", "so_dong": 12, "tien_hang_loi": 15262356.08, "tien_hang_npp": 15262353.0, "vat_loi": 821591.35, "vat_tho": 821591.24, "vat_npp": 821591.0, "grand_loi": 16083947.43, "rounded_loi": 16083947.0, "tong_npp": 16083944.0, "giam_don": 0.0}, {"loai": "don_gia", "item": "SP001", "uom": "Lon", "gia_bang": 10137.0, "pct": 2.5, "rate_loi": 9883.57, "giam_loi": 253.43, "don_gia_npp": 9884.0}]
## p2 app giam don 5%
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 5, "ty_le_giam_dong": 0.3, "cach_giam_dong": "app", "seed": 2}, "precision": "2", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 720, "dong_giam": 232, "lech_don_gia": 0, "mat_pct": 211, "lech_tien_hang": 0, "lech_vat": 49, "vat_co_le": 49, "lech_grand": 49, "lech_rounded": 0}
   mẫu (tối đa 4): [{"loai": "hd", "si": "ACC-SINV-2026-00043", "so_dong": 10, "tien_hang_loi": 18588505.0, "tien_hang_npp": 18588505.0, "vat_loi": 1160186.08, "vat_tho": 1160186.08, "vat_npp": 1160186.0, "grand_loi": 18819266.08, "rounded_loi": 18819266.0, "tong_npp": 18819266.0, "giam_don": 929425.0}, {"loai": "hd", "si": "ACC-SINV-2026-00044", "so_dong": 17, "tien_hang_loi": 18050126.0, "tien_hang_npp": 18050126.0, "vat_loi": 948807.98, "vat_tho": 948807.98, "vat_npp": 948808.0, "grand_loi": 18096427.98, "rounded_loi": 18096428.0, "tong_npp": 18096428.0, "giam_don": 902506.0}, {"loai": "hd", "si": "ACC-SINV-2026-00045", "so_dong": 13, "tien_hang_loi": 18654861.0, "tien_hang_npp": 18654861.0, "vat_loi": 858848.04, "vat_tho": 858848.04, "vat_npp": 858848.0, "grand_loi": 18580966.04, "rounded_loi": 18580966.0, "tong_npp": 18580966.0, "giam_don": 932743.0}, {"loai": "hd", "si": "ACC-SINV-2026-00046", "so_dong": 18, "tien_hang_loi": 28599857.0, "tien_hang_npp": 28599857.0, "vat_loi": 1390573.02, "vat_tho": 1390573.02, "vat_npp": 1390573.0, "grand_loi": 28560437.02, "rounded_loi": 28560437.0, "tong_npp": 28560437.0, "giam_don": 1429993.0}]
## tra precision 0
{"currency_precision": "0"}
```

### C1b. Thuế + làm tròn — đo lại theo đúng luật nppsale (10/11)

Đơn giá sau giảm theo luật thật: g = round(SL × giá bảng), tiền giảm = round(g × %), đơn giá = round((g − tiền giảm) / SL) (`thue_lam_tron`, ghi `"luat_don_gia": "nppsale that (10/11)"`). Tên HĐ trong các dòng mẫu là tờ đã ROLLBACK, đừng tra sổ theo các tên ấy.

Hai lượt SL lẻ đầu tiên (seed 3 và 4, nhãn "p0 app SL le 20%") có **lỗi mã đo**: ở chế độ app, dòng không giảm vẫn gửi giá bảng thay vì đơn giá theo luật nppsale, nên ra 3 dòng "lệch đơn giá" giả. Đã sửa mã (mọi dòng gửi đơn giá theo luật) và chạy lại ở khối thứ hai; báo cáo dùng khối thứ hai.

```text
## p0 app (luat that) seed1
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 0, "ty_le_giam_dong": 0.3, "cach_giam_dong": "app", "seed": 1, "ty_le_sl_le": 0.0, "luat_don_gia": "nppsale that (10/11)"}, "precision": "0", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 738, "dong_giam": 220, "dong_sl_le": 0, "hd_co_sl_le": 0, "lech_don_gia": 0, "mat_pct": 15, "lech_tien_hang": 0, "lech_vat": 0, "vat_co_le": 0, "lech_grand": 0, "lech_rounded": 0, "lech_tong_max": 0}
## p0 loi tu tinh tu % seed1
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 0, "ty_le_giam_dong": 0.3, "cach_giam_dong": "loi", "seed": 1, "ty_le_sl_le": 0.0, "luat_don_gia": "nppsale that (10/11)"}, "precision": "0", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 738, "dong_giam": 220, "dong_sl_le": 0, "hd_co_sl_le": 0, "lech_don_gia": 15, "mat_pct": 0, "lech_tien_hang": 11, "lech_vat": 7, "vat_co_le": 0, "lech_grand": 11, "lech_rounded": 11, "lech_tong_max": 25.0}
   mẫu (tối đa 3): [{"loai": "don_gia", "item": "SP011", "uom": "Thung", "gia_bang": 275668.0, "pct": 12.5, "rate_loi": 241209.0, "giam_loi": 34459.0, "don_gia_npp": 241210.0}, {"loai": "hd", "si": "ACC-SINV-2026-00104", "so_dong": 14, "co_sl_le": false, "tien_hang_loi": 28202908.0, "tien_hang_npp": 28202922.0, "vat_loi": 1175412.0, "vat_tho": 1175412.48, "vat_npp": 1175412.0, "grand_loi": 29378320.0, "rounded_loi": 29378320.0, "tong_npp": 29378334.0, "giam_don": 0.0}, {"loai": "don_gia", "item": "SP017", "uom": "Loc", "gia_bang": 73474.0, "pct": 7.5, "rate_loi": 67963.0, "giam_loi": 5511.0, "don_gia_npp": 67964.0}]
## p0 app giam don 5% seed2
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 5, "ty_le_giam_dong": 0.3, "cach_giam_dong": "app", "seed": 2, "ty_le_sl_le": 0.0, "luat_don_gia": "nppsale that (10/11)"}, "precision": "0", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 720, "dong_giam": 232, "dong_sl_le": 0, "hd_co_sl_le": 0, "lech_don_gia": 0, "mat_pct": 20, "lech_tien_hang": 0, "lech_vat": 0, "vat_co_le": 0, "lech_grand": 0, "lech_rounded": 0, "lech_tong_max": 0}
## p0 app SL le 20% seed3
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 0, "ty_le_giam_dong": 0.3, "cach_giam_dong": "app", "seed": 3, "ty_le_sl_le": 0.2, "luat_don_gia": "nppsale that (10/11)"}, "precision": "0", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 716, "dong_giam": 183, "dong_sl_le": 133, "hd_co_sl_le": 50, "lech_don_gia": 3, "mat_pct": 27, "lech_tien_hang": 3, "lech_vat": 0, "vat_co_le": 0, "lech_grand": 16, "lech_rounded": 16, "lech_tong_max": 2.0}
   mẫu (tối đa 3): [{"loai": "hd", "si": "ACC-SINV-2026-00102", "so_dong": 13, "co_sl_le": true, "tien_hang_loi": 15574914.0, "tien_hang_npp": 15574913.5, "vat_loi": 1048402.0, "vat_tho": 1048402.43, "vat_npp": 1048402.0, "grand_loi": 16623316.0, "rounded_loi": 16623316.0, "tong_npp": 16623316.0, "giam_don": 0.0}, {"loai": "don_gia", "item": "SP039", "uom": "Lon", "gia_bang": 15343.0, "pct": 0.0, "rate_loi": 15343.0, "giam_loi": 0.0, "don_gia_npp": 15344.0}, {"loai": "hd", "si": "ACC-SINV-2026-00105", "so_dong": 16, "co_sl_le": true, "tien_hang_loi": 8037711.0, "tien_hang_npp": 8037710.5, "vat_loi": 326206.0, "vat_tho": 326205.58, "vat_npp": 326206.0, "grand_loi": 8363917.0, "rounded_loi": 8363917.0, "tong_npp": 8363916.0, "giam_don": 0.0}]
## p0 app giam don 5% SL le 20% seed4
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 5, "ty_le_giam_dong": 0.3, "cach_giam_dong": "app", "seed": 4, "ty_le_sl_le": 0.2, "luat_don_gia": "nppsale that (10/11)"}, "precision": "0", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 757, "dong_giam": 238, "dong_sl_le": 147, "hd_co_sl_le": 49, "lech_don_gia": 3, "mat_pct": 23, "lech_tien_hang": 9, "lech_vat": 2, "vat_co_le": 0, "lech_grand": 18, "lech_rounded": 18, "lech_tong_max": 2.0}
   mẫu (tối đa 3): [{"loai": "hd", "si": "ACC-SINV-2026-00102", "so_dong": 13, "co_sl_le": true, "tien_hang_loi": 9296522.0, "tien_hang_npp": 9296521.5, "vat_loi": 758002.0, "vat_tho": 758002.01, "vat_npp": 758002.0, "grand_loi": 9589698.0, "rounded_loi": 9589698.0, "tong_npp": 9589698.0, "giam_don": 464826.0}, {"loai": "hd", "si": "ACC-SINV-2026-00103", "so_dong": 10, "co_sl_le": true, "tien_hang_loi": 8112383.0, "tien_hang_npp": 8112382.5, "vat_loi": 321032.0, "vat_tho": 321031.96, "vat_npp": 321032.0, "grand_loi": 8027796.0, "rounded_loi": 8027796.0, "tong_npp": 8027795.0, "giam_don": 405619.0}, {"loai": "hd", "si": "ACC-SINV-2026-00105", "so_dong": 14, "co_sl_le": true, "tien_hang_loi": 10025861.0, "tien_hang_npp": 10025860.0, "vat_loi": 562481.0, "vat_tho": 562480.75, "vat_npp": 562481.0, "grand_loi": 10087049.0, "rounded_loi": 10087049.0, "tong_npp": 10087048.0, "giam_don": 501293.0}]
## dong dac biet (p0)
{"item": "SP001", "gia_bang": 10137.0, "a1": {"gui": {"rate": 0, "price_list_rate": 10137.0}, "rate": 10137.0, "price_list_rate": 10137.0, "discount_percentage": 0.0, "discount_amount": 0.0, "margin_type": "", "margin_rate_or_amount": 0.0, "amount": 20274.0}, "a2": {"gui": {"rate": 0, "price_list_rate": 10137.0, "discount_percentage": 100}, "rate": 0.0, "price_list_rate": 10137.0, "discount_percentage": 100.0, "discount_amount": 10137.0, "margin_type": "", "margin_rate_or_amount": 0.0, "amount": 0.0}, "a3": {"gui": {"rate": 0}, "rate": 10054.0, "price_list_rate": 10054.0, "discount_percentage": 0.0, "discount_amount": 0.0, "margin_type": "", "margin_rate_or_amount": 0.0, "amount": 20108.0}, "b": {"gui": {"rate": 11137.0, "price_list_rate": 10137.0}, "rate": 11137.0, "price_list_rate": 10137.0, "discount_percentage": 0.0, "discount_amount": 0.0, "margin_type": "Amount", "margin_rate_or_amount": 1000.0, "amount": 22274.0}, "c": {"gui": {"rate": 9360.0, "price_list_rate": 10137.0, "discount_percentage": 5}, "rate": 9360.0, "price_list_rate": 10137.0, "discount_percentage": 0.0, "discount_amount": 777.0, "margin_type": "", "margin_rate_or_amount": 0.0, "amount": 18720.0}}
## dat precision 2
{"currency_precision": "2"}
## p2 app seed1
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 0, "ty_le_giam_dong": 0.3, "cach_giam_dong": "app", "seed": 1, "ty_le_sl_le": 0.0, "luat_don_gia": "nppsale that (10/11)"}, "precision": "2", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 738, "dong_giam": 220, "dong_sl_le": 0, "hd_co_sl_le": 0, "lech_don_gia": 0, "mat_pct": 203, "lech_tien_hang": 0, "lech_vat": 50, "vat_co_le": 50, "lech_grand": 50, "lech_rounded": 0, "lech_tong_max": 0}
   mẫu (tối đa 3): [{"loai": "hd", "si": "ACC-SINV-2026-00102", "so_dong": 12, "co_sl_le": false, "tien_hang_loi": 15262353.0, "tien_hang_npp": 15262353.0, "vat_loi": 821591.24, "vat_tho": 821591.24, "vat_npp": 821591.0, "grand_loi": 16083944.24, "rounded_loi": 16083944.0, "tong_npp": 16083944.0, "giam_don": 0.0}, {"loai": "hd", "si": "ACC-SINV-2026-00103", "so_dong": 15, "co_sl_le": false, "tien_hang_loi": 20150754.0, "tien_hang_npp": 20150754.0, "vat_loi": 1482855.88, "vat_tho": 1482855.88, "vat_npp": 1482856.0, "grand_loi": 21633609.88, "rounded_loi": 21633610.0, "tong_npp": 21633610.0, "giam_don": 0.0}, {"loai": "hd", "si": "ACC-SINV-2026-00104", "so_dong": 14, "co_sl_le": false, "tien_hang_loi": 28202922.0, "tien_hang_npp": 28202922.0, "vat_loi": 1175412.48, "vat_tho": 1175412.48, "vat_npp": 1175412.0, "grand_loi": 29378334.48, "rounded_loi": 29378334.0, "tong_npp": 29378334.0, "giam_don": 0.0}]
## p2 loi seed1
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 0, "ty_le_giam_dong": 0.3, "cach_giam_dong": "loi", "seed": 1, "ty_le_sl_le": 0.0, "luat_don_gia": "nppsale that (10/11)"}, "precision": "2", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 738, "dong_giam": 220, "dong_sl_le": 0, "hd_co_sl_le": 0, "lech_don_gia": 203, "mat_pct": 0, "lech_tien_hang": 48, "lech_vat": 50, "vat_co_le": 50, "lech_grand": 50, "lech_rounded": 44, "lech_tong_max": 23.0}
   mẫu (tối đa 3): [{"loai": "don_gia", "item": "SP025", "uom": "Lon", "gia_bang": 13425.0, "pct": 7.5, "rate_loi": 12418.12, "giam_loi": 1006.88, "don_gia_npp": 12418.0}, {"loai": "don_gia", "item": "SP004", "uom": "Thung", "gia_bang": 252652.0, "pct": 15.0, "rate_loi": 214754.2, "giam_loi": 37897.8, "don_gia_npp": 214754.0}, {"loai": "hd", "si": "ACC-SINV-2026-00102", "so_dong": 12, "co_sl_le": false, "tien_hang_loi": 15262356.08, "tien_hang_npp": 15262353.0, "vat_loi": 821591.35, "vat_tho": 821591.24, "vat_npp": 821591.0, "grand_loi": 16083947.43, "rounded_loi": 16083947.0, "tong_npp": 16083944.0, "giam_don": 0.0}]
## p2 app giam don 5% seed2
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 5, "ty_le_giam_dong": 0.3, "cach_giam_dong": "app", "seed": 2, "ty_le_sl_le": 0.0, "luat_don_gia": "nppsale that (10/11)"}, "precision": "2", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 720, "dong_giam": 232, "dong_sl_le": 0, "hd_co_sl_le": 0, "lech_don_gia": 0, "mat_pct": 211, "lech_tien_hang": 0, "lech_vat": 49, "vat_co_le": 49, "lech_grand": 49, "lech_rounded": 0, "lech_tong_max": 0}
   mẫu (tối đa 3): [{"loai": "hd", "si": "ACC-SINV-2026-00102", "so_dong": 10, "co_sl_le": false, "tien_hang_loi": 18588505.0, "tien_hang_npp": 18588505.0, "vat_loi": 1160186.08, "vat_tho": 1160186.08, "vat_npp": 1160186.0, "grand_loi": 18819266.08, "rounded_loi": 18819266.0, "tong_npp": 18819266.0, "giam_don": 929425.0}, {"loai": "hd", "si": "ACC-SINV-2026-00103", "so_dong": 17, "co_sl_le": false, "tien_hang_loi": 18050126.0, "tien_hang_npp": 18050126.0, "vat_loi": 948807.98, "vat_tho": 948807.98, "vat_npp": 948808.0, "grand_loi": 18096427.98, "rounded_loi": 18096428.0, "tong_npp": 18096428.0, "giam_don": 902506.0}, {"loai": "hd", "si": "ACC-SINV-2026-00104", "so_dong": 13, "co_sl_le": false, "tien_hang_loi": 18654869.0, "tien_hang_npp": 18654869.0, "vat_loi": 858848.04, "vat_tho": 858848.04, "vat_npp": 858848.0, "grand_loi": 18580974.04, "rounded_loi": 18580974.0, "tong_npp": 18580974.0, "giam_don": 932743.0}]
## p2 app SL le 20% seed3
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 0, "ty_le_giam_dong": 0.3, "cach_giam_dong": "app", "seed": 3, "ty_le_sl_le": 0.2, "luat_don_gia": "nppsale that (10/11)"}, "precision": "2", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 716, "dong_giam": 183, "dong_sl_le": 133, "hd_co_sl_le": 50, "lech_don_gia": 3, "mat_pct": 174, "lech_tien_hang": 28, "lech_vat": 49, "vat_co_le": 49, "lech_grand": 49, "lech_rounded": 2, "lech_tong_max": 1.0}
   mẫu (tối đa 3): [{"loai": "hd", "si": "ACC-SINV-2026-00102", "so_dong": 13, "co_sl_le": true, "tien_hang_loi": 15574913.5, "tien_hang_npp": 15574913.5, "vat_loi": 1048402.43, "vat_tho": 1048402.43, "vat_npp": 1048402.0, "grand_loi": 16623315.93, "rounded_loi": 16623316.0, "tong_npp": 16623316.0, "giam_don": 0.0}, {"loai": "don_gia", "item": "SP039", "uom": "Lon", "gia_bang": 15343.0, "pct": 0.0, "rate_loi": 15343.0, "giam_loi": 0.0, "don_gia_npp": 15344.0}, {"loai": "hd", "si": "ACC-SINV-2026-00103", "so_dong": 10, "co_sl_le": true, "tien_hang_loi": 11758037.5, "tien_hang_npp": 11758038.0, "vat_loi": 584540.48, "vat_tho": 584540.5, "vat_npp": 584541.0, "grand_loi": 12342577.98, "rounded_loi": 12342578.0, "tong_npp": 12342579.0, "giam_don": 0.0}]
## tra precision 0
{"currency_precision": "0"}
```

Chạy lại sau khi sửa mã đo (khối thứ hai):

```text
## p0 app SL le 20% seed3 (sua ma do)
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 0, "ty_le_giam_dong": 0.3, "cach_giam_dong": "app", "seed": 3, "ty_le_sl_le": 0.2, "luat_don_gia": "nppsale that (10/11)"}, "precision": "0", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 716, "dong_giam": 183, "dong_sl_le": 133, "hd_co_sl_le": 50, "lech_don_gia": 0, "mat_pct": 27, "lech_tien_hang": 3, "lech_vat": 0, "vat_co_le": 0, "lech_grand": 16, "lech_rounded": 16, "lech_tong_max": 2.0}
   mẫu (tối đa 3): [{"loai": "hd", "si": "ACC-SINV-2026-00102", "so_dong": 13, "co_sl_le": true, "tien_hang_loi": 15574914.0, "tien_hang_npp": 15574913.5, "vat_loi": 1048402.0, "vat_tho": 1048402.43, "vat_npp": 1048402.0, "grand_loi": 16623316.0, "rounded_loi": 16623316.0, "tong_npp": 16623316.0, "giam_don": 0.0}, {"loai": "hd", "si": "ACC-SINV-2026-00105", "so_dong": 16, "co_sl_le": true, "tien_hang_loi": 8037711.0, "tien_hang_npp": 8037710.5, "vat_loi": 326206.0, "vat_tho": 326205.58, "vat_npp": 326206.0, "grand_loi": 8363917.0, "rounded_loi": 8363917.0, "tong_npp": 8363916.0, "giam_don": 0.0}, {"loai": "hd", "si": "ACC-SINV-2026-00106", "so_dong": 10, "co_sl_le": true, "tien_hang_loi": 10118644.0, "tien_hang_npp": 10118643.5, "vat_loi": 872735.0, "vat_tho": 872735.2, "vat_npp": 872735.0, "grand_loi": 10991379.0, "rounded_loi": 10991379.0, "tong_npp": 10991379.0, "giam_don": 0.0}]
## p0 app giam don 5% SL le 20% seed4 (sua ma do)
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 5, "ty_le_giam_dong": 0.3, "cach_giam_dong": "app", "seed": 4, "ty_le_sl_le": 0.2, "luat_don_gia": "nppsale that (10/11)"}, "precision": "0", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 757, "dong_giam": 238, "dong_sl_le": 147, "hd_co_sl_le": 49, "lech_don_gia": 0, "mat_pct": 23, "lech_tien_hang": 9, "lech_vat": 2, "vat_co_le": 0, "lech_grand": 18, "lech_rounded": 18, "lech_tong_max": 2.0}
   mẫu (tối đa 3): [{"loai": "hd", "si": "ACC-SINV-2026-00102", "so_dong": 13, "co_sl_le": true, "tien_hang_loi": 9296522.0, "tien_hang_npp": 9296521.5, "vat_loi": 758002.0, "vat_tho": 758002.01, "vat_npp": 758002.0, "grand_loi": 9589698.0, "rounded_loi": 9589698.0, "tong_npp": 9589698.0, "giam_don": 464826.0}, {"loai": "hd", "si": "ACC-SINV-2026-00103", "so_dong": 10, "co_sl_le": true, "tien_hang_loi": 8112383.0, "tien_hang_npp": 8112382.5, "vat_loi": 321032.0, "vat_tho": 321031.96, "vat_npp": 321032.0, "grand_loi": 8027796.0, "rounded_loi": 8027796.0, "tong_npp": 8027795.0, "giam_don": 405619.0}, {"loai": "hd", "si": "ACC-SINV-2026-00105", "so_dong": 14, "co_sl_le": true, "tien_hang_loi": 10025861.0, "tien_hang_npp": 10025860.0, "vat_loi": 562481.0, "vat_tho": 562480.75, "vat_npp": 562481.0, "grand_loi": 10087049.0, "rounded_loi": 10087049.0, "tong_npp": 10087048.0, "giam_don": 501293.0}]
## p0 app seed1 (kiem lai sau sua: phai y het)
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 0, "ty_le_giam_dong": 0.3, "cach_giam_dong": "app", "seed": 1, "ty_le_sl_le": 0.0, "luat_don_gia": "nppsale that (10/11)"}, "precision": "0", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 738, "dong_giam": 220, "dong_sl_le": 0, "hd_co_sl_le": 0, "lech_don_gia": 0, "mat_pct": 15, "lech_tien_hang": 0, "lech_vat": 0, "vat_co_le": 0, "lech_grand": 0, "lech_rounded": 0, "lech_tong_max": 0}
## dat precision 2
{"currency_precision": "2"}
## p2 app SL le 20% seed3 (sua ma do)
{"tham_so": {"n": 50, "dong": [10, 20], "giam_don_pct": 0, "ty_le_giam_dong": 0.3, "cach_giam_dong": "app", "seed": 3, "ty_le_sl_le": 0.2, "luat_don_gia": "nppsale that (10/11)"}, "precision": "2", "rounding": "Commercial Rounding", "round_row_wise_tax": 0, "hd": 50, "dong": 716, "dong_giam": 183, "dong_sl_le": 133, "hd_co_sl_le": 50, "lech_don_gia": 0, "mat_pct": 174, "lech_tien_hang": 25, "lech_vat": 49, "vat_co_le": 49, "lech_grand": 49, "lech_rounded": 0, "lech_tong_max": 0}
   mẫu (tối đa 3): [{"loai": "hd", "si": "ACC-SINV-2026-00102", "so_dong": 13, "co_sl_le": true, "tien_hang_loi": 15574913.5, "tien_hang_npp": 15574913.5, "vat_loi": 1048402.43, "vat_tho": 1048402.43, "vat_npp": 1048402.0, "grand_loi": 16623315.93, "rounded_loi": 16623316.0, "tong_npp": 16623316.0, "giam_don": 0.0}, {"loai": "hd", "si": "ACC-SINV-2026-00103", "so_dong": 10, "co_sl_le": true, "tien_hang_loi": 11758038.0, "tien_hang_npp": 11758038.0, "vat_loi": 584540.5, "vat_tho": 584540.5, "vat_npp": 584541.0, "grand_loi": 12342578.5, "rounded_loi": 12342579.0, "tong_npp": 12342579.0, "giam_don": 0.0}, {"loai": "hd", "si": "ACC-SINV-2026-00104", "so_dong": 14, "co_sl_le": true, "tien_hang_loi": 18457560.0, "tien_hang_npp": 18457560.0, "vat_loi": 1112203.05, "vat_tho": 1112203.05, "vat_npp": 1112203.0, "grand_loi": 19569763.05, "rounded_loi": 19569763.0, "tong_npp": 19569763.0, "giam_don": 0.0}]
## tra precision 0
{"currency_precision": "0"}
```

### C1c. Dòng 0 đ và dòng bán trên giá bảng (`dong_dac_biet`, 10/11 — insert rồi rollback)

```json
{"item": "SP001", "gia_bang": 10137.0, "a1": {"gui": {"rate": 0, "price_list_rate": 10137.0}, "rate": 10137.0, "price_list_rate": 10137.0, "discount_percentage": 0.0, "discount_amount": 0.0, "margin_type": "", "margin_rate_or_amount": 0.0, "amount": 20274.0}, "a2": {"gui": {"rate": 0, "price_list_rate": 10137.0, "discount_percentage": 100}, "rate": 0.0, "price_list_rate": 10137.0, "discount_percentage": 100.0, "discount_amount": 10137.0, "margin_type": "", "margin_rate_or_amount": 0.0, "amount": 0.0}, "a3": {"gui": {"rate": 0}, "rate": 10054.0, "price_list_rate": 10054.0, "discount_percentage": 0.0, "discount_amount": 0.0, "margin_type": "", "margin_rate_or_amount": 0.0, "amount": 20108.0}, "b": {"gui": {"rate": 11137.0, "price_list_rate": 10137.0}, "rate": 11137.0, "price_list_rate": 10137.0, "discount_percentage": 0.0, "discount_amount": 0.0, "margin_type": "Amount", "margin_rate_or_amount": 1000.0, "amount": 22274.0}, "c": {"gui": {"rate": 9360.0, "price_list_rate": 10137.0, "discount_percentage": 5}, "rate": 9360.0, "price_list_rate": 10137.0, "discount_percentage": 0.0, "discount_amount": 777.0, "margin_type": "", "margin_rate_or_amount": 0.0, "amount": 18720.0}, "a4": {"gui": {"rate": 0, "price_list_rate": 0}, "rate": 0.0, "price_list_rate": 0.0, "discount_percentage": 0.0, "discount_amount": 0.0, "margin_type": "", "margin_rate_or_amount": 0.0, "amount": 0.0}, "a5": {"gui": {"rate": 0, "price_list_rate": 10137.0, "discount_amount": 10137.0}, "rate": 0.0, "price_list_rate": 10137.0, "discount_percentage": 0.0, "discount_amount": 10137.0, "margin_type": "", "margin_rate_or_amount": 0.0, "amount": 0.0}}
```

Bảng giá do lõi tự sinh (đọc sổ 10/11): `Stock Settings.auto_insert_price_list_rate_if_missing = 1`, `update_existing_price_list_rate = 0`; `tabItem Price` có "Standard Selling" 40 giá (lập 05/11 21:23:44–51, Administrator, ví dụ SP023 Lon 13.067,67) và "Standard Buying" 30 giá (05/11 21:23:26–27) — không do `setup.py` lập. Selling Settings `selling_price_list = Standard Selling`.

### C2. Dòng cần hai lô thật (`hai_lo_do`, 5 lượt mỗi cách)

```json
{"bundle": [{"item": "SP001", "si": "ACC-SINV-2026-00044", "tong": 1094, "si_insert": 129, "si_submit": 182, "lo": [["SP001-L2", -20.0], ["SP001-L3", -28.0]], "dong": [[2.0, "Thung", 48.0, null]]}, {"item": "SP003", "si": "ACC-SINV-2026-00048", "tong": 364, "si_insert": 111, "si_submit": 163, "lo": [["SP003-L2", -20.0], ["SP003-L3", -28.0]], "dong": [[2.0, "Thung", 48.0, null]]}, {"item": "SP005", "si": "ACC-SINV-2026-00052", "tong": 413, "si_insert": 114, "si_submit": 191, "lo": [["SP005-L2", -20.0], ["SP005-L3", -28.0]], "dong": [[2.0, "Thung", 48.0, null]]}, {"item": "SP007", "si": "ACC-SINV-2026-00056", "tong": 398, "si_insert": 127, "si_submit": 164, "lo": [["SP007-L2", -20.0], ["SP007-L3", -28.0]], "dong": [[2.0, "Thung", 48.0, null]]}, {"item": "SP009", "si": "ACC-SINV-2026-00060", "tong": 391, "si_insert": 104, "si_submit": 194, "lo": [["SP009-L2", -20.0], ["SP009-L3", -28.0]], "dong": [[2.0, "Thung", 48.0, null]]}], "tach_dong": [{"item": "SP002", "si": "ACC-SINV-2026-00046", "tong": 464, "si_insert": 113, "si_submit": 225, "lo": [["SP002-L2", -19.992], ["SP002-L3", -28.008]], "dong": [[0.833, "Thung", 19.992, "SP002-L2"], [1.167, "Thung", 28.008, "SP002-L3"]]}, {"item": "SP004", "si": "ACC-SINV-2026-00050", "tong": 460, "si_insert": 119, "si_submit": 237, "lo": [["SP004-L4", -28.008], ["SP004-L3", -19.992]], "dong": [[0.833, "Thung", 19.992, "SP004-L3"], [1.167, "Thung", 28.008, "SP004-L4"]]}, {"item": "SP006", "si": "ACC-SINV-2026-00054", "tong": 396, "si_insert": 99, "si_submit": 218, "lo": [["SP006-L3", -28.008], ["SP006-L2", -19.992]], "dong": [[0.833, "Thung", 19.992, "SP006-L2"], [1.167, "Thung", 28.008, "SP006-L3"]]}, {"item": "SP008", "si": "ACC-SINV-2026-00058", "tong": 393, "si_insert": 97, "si_submit": 203, "lo": [["SP008-L3", -28.008], ["SP008-L2", -19.992]], "dong": [[0.833, "Thung", 19.992, "SP008-L2"], [1.167, "Thung", 28.008, "SP008-L3"]]}, {"item": "SP010", "si": "ACC-SINV-2026-00062", "tong": 447, "si_insert": 115, "si_submit": 214, "lo": [["SP010-L3", -28.008], ["SP010-L2", -19.992]], "dong": [[0.833, "Thung", 19.992, "SP010-L2"], [1.167, "Thung", 28.008, "SP010-L3"]]}], "bundle_tb_ms": 532, "bundle_min_max": [364, 1094], "tach_dong_tb_ms": 432, "tach_dong_min_max": [393, 464]}
```

### C3. Đồng thời, chỉ đo phần Xuất HĐ của đơn đã chốt (`xuat_hd_dong_thoi`, 8 dòng: 6 theo lô + 2 không lô, 2 lon / dòng)

Dòng `KQ` gốc còn khoá `hang` (mặt hàng của từng tiến trình); khi chép xuống đây em đã bỏ khoá này. Hàng rời nhau: p1 SP001–SP006 + SP031–SP032, p2 SP007–SP012 + SP033–SP034, p3 SP013–SP018 + SP035–SP036, p4 SP019–SP024 + SP037–SP038, p5 SP025–SP030 + SP039–SP040 (nhật ký `dt2-rieng-*.log`). Hàng trùng: cả năm tiến trình dùng SP001–SP006 + SP031–SP032 (nhật ký `dt2-chung-*.log`; riêng p5 của bài trùng không khoá chết vì bế tắc trước khi in `KQ`, nhóm hàng của nó lấy theo `_nhom_hang` trong `do.py`). Số dòng `do.py` trong vết lỗi ở dưới là của bản mã lúc chạy (06/11) — mã đổi sau đó thì tra theo tên hàm.

**hàng RỜI nhau, không khoá**

```text
p1: {"si_insert": 2036, "si_submit": 501, "tong": 2794, "si": "ACC-SINV-2026-00071", "bat_dau": 1793968851.004, "ket_thuc": 1793968853.798, "nong": 1577, "k": 1, "chung": false, "khoa": false, "tag": "rieng-khongkhoa-p1", "so": "SAL-ORD-2026-00053"}
p2: {"si_insert": 791, "si_submit": 442, "tong": 1424, "si": "ACC-SINV-2026-00069", "bat_dau": 1793968851.0, "ket_thuc": 1793968852.425, "nong": 1228, "k": 2, "chung": false, "khoa": false, "tag": "rieng-khongkhoa-p2", "so": "SAL-ORD-2026-00052"}
p3: {"si_insert": 163, "si_submit": 507, "tong": 828, "si": "ACC-SINV-2026-00068", "bat_dau": 1793968851.004, "ket_thuc": 1793968851.832, "nong": 910, "k": 3, "chung": false, "khoa": false, "tag": "rieng-khongkhoa-p3", "so": "SAL-ORD-2026-00051"}
p4: {"si_insert": 1356, "si_submit": 502, "tong": 2075, "si": "ACC-SINV-2026-00070", "bat_dau": 1793968851.003, "ket_thuc": 1793968853.079, "nong": 1990, "k": 4, "chung": false, "khoa": false, "tag": "rieng-khongkhoa-p4", "so": "SAL-ORD-2026-00055"}
p5: {"si_insert": 2666, "si_submit": 573, "tong": 3518, "si": "ACC-SINV-2026-00072", "bat_dau": 1793968851.005, "ket_thuc": 1793968854.523, "nong": 1806, "k": 5, "chung": false, "khoa": false, "tag": "rieng-khongkhoa-p5", "so": "SAL-ORD-2026-00054"}
```

**hàng rời nhau, khoá Bin**

```text
p1: {"khoa_ms": 1, "si_insert": 1238, "si_submit": 501, "tong": 2013, "si": "ACC-SINV-2026-00080", "bat_dau": 1793968929.003, "ket_thuc": 1793968931.016, "nong": 1331, "k": 1, "chung": false, "khoa": true, "tag": "rieng-khoa-p1", "so": "SAL-ORD-2026-00062"}
p2: {"khoa_ms": 2, "si_insert": 656, "si_submit": 437, "tong": 1377, "si": "ACC-SINV-2026-00079", "bat_dau": 1793968929.0, "ket_thuc": 1793968930.378, "nong": 955, "k": 2, "chung": false, "khoa": true, "tag": "rieng-khoa-p2", "so": "SAL-ORD-2026-00061"}
p3: {"khoa_ms": 0, "si_insert": 151, "si_submit": 451, "tong": 798, "si": "ACC-SINV-2026-00078", "bat_dau": 1793968929.005, "ket_thuc": 1793968929.804, "nong": 1908, "k": 3, "chung": false, "khoa": true, "tag": "rieng-khoa-p3", "so": "SAL-ORD-2026-00064"}
p4: {"khoa_ms": 2, "si_insert": 1850, "si_submit": 507, "tong": 2671, "si": "ACC-SINV-2026-00081", "bat_dau": 1793968929.004, "ket_thuc": 1793968931.675, "nong": 1726, "k": 4, "chung": false, "khoa": true, "tag": "rieng-khoa-p4", "so": "SAL-ORD-2026-00063"}
p5: {"khoa_ms": 1, "si_insert": 2030, "si_submit": 482, "tong": 3351, "si": "ACC-SINV-2026-00082", "bat_dau": 1793968929.002, "ket_thuc": 1793968932.353, "nong": 2167, "k": 5, "chung": false, "khoa": true, "tag": "rieng-khoa-p5", "so": "SAL-ORD-2026-00065"}
```

**hàng TRÙNG nhau, không khoá**

```text
p1: {"si_insert": 209, "si_submit": 511, "tong": 1613, "si": "ACC-SINV-2026-00089", "bat_dau": 1793969007.002, "ket_thuc": 1793969008.616, "nong": 987, "k": 1, "chung": true, "khoa": false, "tag": "chung-khongkhoa-p1", "so": "SAL-ORD-2026-00071"}
p2: {"si_insert": 157, "si_submit": 524, "tong": 2366, "si": "ACC-SINV-2026-00090", "bat_dau": 1793969007.002, "ket_thuc": 1793969009.369, "nong": 1454, "k": 2, "chung": true, "khoa": false, "tag": "chung-khongkhoa-p2", "so": "SAL-ORD-2026-00073"}
p3: {"si_insert": 162, "si_submit": 482, "tong": 814, "si": "ACC-SINV-2026-00088", "bat_dau": 1793969007.004, "ket_thuc": 1793969007.818, "nong": 1747, "k": 3, "chung": true, "khoa": false, "tag": "chung-khongkhoa-p3", "so": "SAL-ORD-2026-00074"}
p4: {"si_insert": 180, "si_submit": 536, "tong": 3168, "si": "ACC-SINV-2026-00091", "bat_dau": 1793969007.002, "ket_thuc": 1793969010.171, "nong": 1344, "k": 4, "chung": true, "khoa": false, "tag": "chung-khongkhoa-p4", "so": "SAL-ORD-2026-00072"}
p5: KHÔNG có dòng KQ — tiến trình chết ở lượt đo (sau mốc): frappe.exceptions.QueryDeadlockError: (1213, 'Deadlock found when trying to get lock; try restarting transaction')
      nppsale/poc/do.py:711 xuat_hd_dong_thoi → do.py:687 _xuat_hd → do.py:159 gan_lo_cho_tung_dong (app lập bundle)
      → erpnext/stock/serial_batch_bundle.py:1269 make_serial_and_batch_bundle
      → erpnext/stock/doctype/serial_and_batch_bundle/serial_and_batch_bundle.py:144 validate → :405 set_incoming_rate → :727 set_incoming_rate_for_outward_transaction
      → erpnext/stock/serial_batch_bundle.py:819 BatchNoValuation.__init__ → :835 calculate_avg_rate → :968 get_batch_stock_before_date (câu đọc .for_update() ở dòng 951)
```

**hàng trùng nhau, khoá Bin**

```text
p1: {"khoa_ms": 2636, "si_insert": 158, "si_submit": 461, "tong": 3475, "si": "ACC-SINV-2026-00100", "bat_dau": 1793969085.004, "ket_thuc": 1793969088.48, "nong": 808, "k": 1, "chung": true, "khoa": true, "tag": "chung-khoa-p1", "so": "SAL-ORD-2026-00085"}
p2: {"khoa_ms": 3464, "si_insert": 167, "si_submit": 595, "tong": 4444, "si": "ACC-SINV-2026-00101", "bat_dau": 1793969085.004, "ket_thuc": 1793969089.449, "nong": 882, "k": 2, "chung": true, "khoa": true, "tag": "chung-khoa-p2", "so": "SAL-ORD-2026-00082"}
p3: {"khoa_ms": 1772, "si_insert": 154, "si_submit": 531, "tong": 2646, "si": "ACC-SINV-2026-00099", "bat_dau": 1793969085.004, "ket_thuc": 1793969087.651, "nong": 968, "k": 3, "chung": true, "khoa": true, "tag": "chung-khoa-p3", "so": "SAL-ORD-2026-00084"}
p4: {"khoa_ms": 863, "si_insert": 162, "si_submit": 568, "tong": 1781, "si": "ACC-SINV-2026-00098", "bat_dau": 1793969085.003, "ket_thuc": 1793969086.785, "nong": 908, "k": 4, "chung": true, "khoa": true, "tag": "chung-khoa-p4", "so": "SAL-ORD-2026-00081"}
p5: {"khoa_ms": 1, "si_insert": 195, "si_submit": 522, "tong": 873, "si": "ACC-SINV-2026-00097", "bat_dau": 1793969085.003, "ket_thuc": 1793969085.876, "nong": 859, "k": 5, "chung": true, "khoa": true, "tag": "chung-khoa-p5", "so": "SAL-ORD-2026-00083"}
```

### C4. Sửa HĐ = huỷ + amend (`sua_hd_amend`, hai lần liền)

```json
{"goc": "ACC-SINV-2026-00101", "lan": [{"tu": "ACC-SINV-2026-00101", "ra": "ACC-SINV-2026-00101-1", "ms": 2602, "cu_docstatus": 2, "bundle_moi": []}, {"tu": "ACC-SINV-2026-00101-1", "ra": "ACC-SINV-2026-00101-2", "ms": 1091, "cu_docstatus": 2, "bundle_moi": []}]}
```

Sổ của tờ `ACC-SINV-2026-00101-2`: 6 dòng theo lô đều có bundle do **lõi tự lập** lúc ghi sổ (SP001-L3, SP002-L3, SP003-L3, SP004-L4, SP005-L3, SP006-L3 — mỗi dòng −2; `Stock Ledger Entry.auto_created_serial_and_batch_bundle = 1`), 2 dòng không lô trừ thẳng; tờ `-1` và tờ gốc docstatus 2. Lô ấy **trùng đúng** lô app đã gán cho tờ gốc: gói lô (đã huỷ) của `ACC-SINV-2026-00101` (app lập lúc 19:44:48) và của `ACC-SINV-2026-00101-1` (lõi lập lúc 19:47:25) cũng là SP001-L3, SP002-L3, SP003-L3, SP004-L4, SP005-L3, SP006-L3, −2 mỗi dòng — phải tra `tabSerial and Batch Bundle` theo `voucher_no`, vì dòng của tờ đã huỷ không còn trỏ tới gói lô (huỷ đã xoá `serial_and_batch_bundle` và `batch_no` trên dòng). `bundle_moi` rỗng ở dòng `KQ` trên là do hàm đọc dòng của tờ mới trong bộ nhớ, còn lõi gắn gói lô tự lập thẳng vào sổ (`frappe.db.set_value`, `erpnext/stock/serial_batch_bundle.py:325`) — không phải tờ mới thiếu gói lô. Hai lần huỷ sinh 16 việc tính lại giá vốn (8 mặt hàng × 2, tạo lúc 19:47:24,98–25,02 và 19:47:26,25–26,29), vẫn `Queued`; lần huỷ thứ hai không bị chặn.

### C5. Đổi mã lô ép `force=True` (`doi_ma_lo_ep`, `doi_ma_lo_ep_do_sot` — 06/11 12:51 UTC; mỗi hàm đổi trong một giao dịch rồi ROLLBACK cuối hàm, sổ không còn dấu)

```json
{"doi_duoc": true, "lo": "SP003-L3", "ra": "SP003-L3-DOI", "ms": 429, "truoc_ma_cu": {"sbe": 27, "sii": 0, "pii": 1, "batch": 1}, "sau_ma_cu": {"sbe": 0, "sii": 0, "pii": 0, "batch": 0}, "sau_ma_moi": {"sbe": 27, "sii": 0, "pii": 1, "batch": 1}, "batch_id_moi": "SP003-L3-DOI", "sau_rollback_con_ma_cu": true}
{"lo": "SP003-L3", "so_cot_da_do": 10371, "con_giu_ma_cu": []}
```

### C6. Vỏ SPA, `sw.js`, manifest (05/11, `bench --site poc.local serve --port 8000` + `curl -D -`; lượt 14:45 UTC trước khi renderer nhìn `request.path`, lượt 14:46 UTC sau khi sửa; chỉ chép dòng trạng thái và các header đáng chú ý, bỏ `Set-Cookie` và thân trang)

```text
(14:45) === GET /nppsale/khong-co-that/abc
HTTP/1.0 200 OK
Content-Type: text/html; charset=utf-8
Cache-Control: no-store,no-cache,must-revalidate,max-age=0
(14:45: /nppsale/, /nppsale/pos/orders, /nppsale/sell/new ra y hệt; /nppsale/sw.js và /nppsale/manifest.webmanifest lúc ấy cũng ra vỏ HTML — route rule đổi endpoint trước renderer)
(14:45) === GET /assets/nppsale/portal/sw.js
HTTP/1.0 200 OK
Cache-Control: max-age=43200, public
Content-Type: text/javascript; charset=utf-8
(14:46) === GET /nppsale/sw.js
HTTP/1.0 200 OK
Content-Type: application/javascript; charset=utf-8
Cache-Control: no-cache, must-revalidate
X-Content-Type-Options: nosniff
Service-Worker-Allowed: /nppsale/
(14:46) === GET /nppsale/manifest.webmanifest
HTTP/1.0 200 OK
Content-Type: application/manifest+json; charset=utf-8
Cache-Control: no-cache, must-revalidate
X-Content-Type-Options: nosniff
(14:46) === GET /nppsale/pos/orders
HTTP/1.0 200 OK
Content-Type: text/html; charset=utf-8
Cache-Control: no-store,no-cache,must-revalidate,max-age=0
(14:46) === dang nhap Administrator roi mo vo SPA (csrf trong meta?)
login 200
name="csrf_token" content="870c…
npp-nguoi-dung" content="Admi…
```

### C7. Việc tính lại giá vốn gom theo phút tạo (SELECT, 06/11; `creation` là giờ VN = UTC + 7, nên 19:43 ở đây là 12:43 UTC) — 40 việc của ngày 06/11 còn Queued

```text
| phut             | status    | so_viec | so_mat_hang | tu_ngay    | tu_gio          |
| 2026-11-05 21:28 | Completed |      30 |          30 | 2026-10-06 | 21:23:26.300168 |
| 2026-11-05 21:33 | Completed |      15 |          15 | 2026-11-05 | 21:23:44.842112 |
| 2026-11-06 19:43 | Queued    |      24 |           8 | 2026-11-06 | 19:43:27.003240 |
| 2026-11-06 19:47 | Queued    |      16 |           8 | 2026-11-06 | 19:44:48.470700 |
```

## D. Đối chiếu sổ (chỉ SELECT, chạy 06/11)

```text
+----------------------------------------+
| q                                      |
+----------------------------------------+
| Q1 viec tinh lai theo phut tao (05/11) |
+----------------------------------------+
+------------------+--------------------+-----------+---------+-------------+------------+---------------------------+
| phut             | based_on           | status    | so_viec | so_mat_hang | tu_ngay    | giay_tu_viec_dau_toi_cuoi |
+------------------+--------------------+-----------+---------+-------------+------------+---------------------------+
| 2026-11-05 21:28 | Item and Warehouse | Completed |      30 |          30 | 2026-10-06 |                 15.987977 |
| 2026-11-05 21:33 | Item and Warehouse | Completed |      15 |          15 | 2026-11-05 |                  3.893247 |
+------------------+--------------------+-----------+---------+-------------+------------+---------------------------+
+-------------------------------------------------------------------+
| q                                                                 |
+-------------------------------------------------------------------+
| Q2 gia von lo SP001-L1 tren phieu nhap va HD da xuat (qua bundle) |
+-------------------------------------------------------------------+
+---------------------+-----------+----------------+----------------------------+----------------+
| parent              | item_code | rate           | landed_cost_voucher_amount | valuation_rate |
+---------------------+-----------+----------------+----------------------------+----------------+
| ACC-PINV-2026-00001 | SP001     | 8109.000000000 |             -836.000000000 | 8105.516666667 |
+---------------------+-----------+----------------+----------------------------+----------------+
+---------------------+---------------+----------------+------------------------+
| voucher_no          | qty           | incoming_rate  | stock_value_difference |
+---------------------+---------------+----------------+------------------------+
| ACC-SINV-2026-00003 | -18.000000000 | 8105.516666667 |      -145899.300000006 |
| ACC-SINV-2026-00007 | -72.000000000 | 8105.516666667 |      -583597.200000024 |
| ACC-SINV-2026-00009 | -12.000000000 | 8105.516666667 |       -97266.200000004 |
| ACC-SINV-2026-00013 |  -1.000000000 | 8105.516666667 |        -8105.516666667 |
+---------------------+---------------+----------------+------------------------+
+---------------------+---------------+----------------+------------------------+
| voucher_no          | actual_qty    | valuation_rate | stock_value_difference |
+---------------------+---------------+----------------+------------------------+
| ACC-SINV-2026-00003 | -18.000000000 | 8118.154843305 |      -145899.000000000 |
+---------------------+---------------+----------------+------------------------+
+----------------------------------+
| q                                |
+----------------------------------+
| Q3 bon to ghi co cua lo SP001-L1 |
+----------------------------------+
+---------------------+--------------------+-------------+-----------------+------------------------+
| voucher_no          | warehouse          | qty         | incoming_rate   | stock_value_difference |
+---------------------+--------------------+-------------+-----------------+------------------------+
| ACC-SINV-2026-00024 | Kho can date - NPP | 5.000000000 | 11150.700000000 |        55753.500000000 |
| ACC-SINV-2026-00025 | Kho can date - NPP | 5.000000000 |  8105.516666667 |        40527.583333335 |
| ACC-SINV-2026-00027 | Kho can date - NPP | 5.000000000 |  9628.108333334 |        48140.541666670 |
| ACC-SINV-2026-00029 | Kho ban - NPP      | 5.000000000 | 11150.700000000 |        55753.500000000 |
+---------------------+--------------------+-------------+-----------------+------------------------+
+-----------------------------------------------------------+
| q                                                         |
+-----------------------------------------------------------+
| Q4 HD ban tiep lo SP001-L1 sau to tra 00029 (gia von lan) |
+-----------------------------------------------------------+
+---------------------+--------------+-----------------+
| voucher_no          | qty          | incoming_rate   |
+---------------------+--------------+-----------------+
| ACC-SINV-2026-00030 | -3.000000000 | 11150.700000000 |
| ACC-SINV-2026-00033 | -2.000000000 | 11150.700000000 |
+---------------------+--------------+-----------------+
+-----------------------------------------------------------+
| q                                                         |
+-----------------------------------------------------------+
| Q5 so cai phieu nhap giam dau phieu bang dong tru (00006) |
+-----------------------------------------------------------+
+------------------------------+------------------+------------------+
| account                      | no               | co               |
+------------------------------+------------------+------------------+
| Creditors - NPP              |      0.000000000 | 630400.000000000 |
| Miscellaneous Expenses - NPP |      0.000000000 |  50000.000000000 |
| Stock In Hand - NPP          | 630000.000000000 |      0.000000000 |
| Thue GTGT dau vao - NPP      |  50400.000000000 |      0.000000000 |
+------------------------------+------------------+------------------+
+-----------------------+
| q                     |
+-----------------------+
| Q6 muc co lap MariaDB |
+-----------------------+
+-----------------+-----------------------+----------------------------+
| @@tx_isolation  | @@global.tx_isolation | @@innodb_lock_wait_timeout |
+-----------------+-----------------------+----------------------------+
| REPEATABLE-READ | REPEATABLE-READ       |                         50 |
+-----------------+-----------------------+----------------------------+
```

## E. Phiên bản

```text
frappe 16.55.2 · erpnext 16.53.0 · bench 5.31.1 · Python 3.14.6 · Node 24.11.0 · MariaDB 10.11.14 (REPEATABLE-READ) · container 4 vCPU / 16 GB
```
