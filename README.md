# nppsale — app ERPNext v16 cho nhà phân phối (chuyển từ npp.sale)

App Frappe độc lập, cài lên bench ERPNext `version-16`, mỗi nhà phân phối một site. Toàn bộ giao diện là SPA chạy ngoài Desk ở
tiền tố `/nppsale/`; mọi thao tác tiền / kho / trạng thái đi qua whitelisted method Python.

- Bản bàn bạc và quyết định đã chốt: `docs/chuyen-doi/00_ban_bac_chot.md`
- Kết quả PoC P0 (đo thật trên bench v16, 05/11/2026): `docs/chuyen-doi/poc/00_ket_qua_poc.md`
- Blueprint (duyệt từng tệp): `docs/chuyen-doi/blueprint/`
- Khảo sát nppsale (màn hình, dữ liệu, nghiệp vụ, kiểm chứng ERPNext): `docs/chuyen-doi/khao-sat/`

## Cài

```bash
bench get-app nppsale https://github.com/mrhuychien/npp
bench --site <site> install-app nppsale
```

(Gọi `get-app` kèm tên `nppsale` để thư mục là `apps/nppsale` dù repo tên `npp`.)

## Thư mục

| | |
|---|---|
| `nppsale/hooks.py` | route vỏ SPA `/nppsale/<path>` → `www/nppsale`, `page_renderer` cho `sw.js` / manifest |
| `nppsale/portal/` | phục vụ tệp portal không cache (`tinh.py`) |
| `nppsale/www/nppsale/` | vỏ SPA (`no_cache = 1`) |
| `nppsale/public/portal/` | `sw.js`, `manifest.webmanifest` (bản khung; Vite build sẽ ghi đè) |
| `nppsale/poc/` | script dựng site thử (`setup.py`) và mười điểm đo (`do.py`) — **không** chạy trên site thật |
| `nppsale/npp_sale/` | module "NPP Sale" — DocType sẽ sinh ở đây theo blueprint |
