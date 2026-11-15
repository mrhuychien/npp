"""Bảng `luot_soan` (lượt soạn hàng, mig 225) trên cổng — CHỈ ĐỌC: mọi thay đổi qua RPC tao_luot_soan / cap_nhat_luot_soan /
hoan_tat_luot_soan / huy_luot_soan (nppsale.rpc.soan_hang). RLS "luot_soan_doc": NV của NPP có vai chủ NPP / quản lý / thủ kho / kế toán.
`invoice_ids` = mảng HĐ theo thứ tự rổ (idx của bảng con NPP Luot Soan Hoa Don)."""
from __future__ import annotations

from ..dang_ky import Bang, QuanHe, dang_ky
from ._chung import c, co_cot, org

VAI_SOAN = ("owner", "manager", "warehouse", "accountant")


def nap():
	if not co_cot("NPP Luot Soan", "tien_do"):
		return
	dang_ky(Bang(
		ten="luot_soan",
		nguon="`tabNPP Luot Soan`",
		cot={
			"id": c("{t}.`name`"), "org_id": org(), "ma": c("ma"),
			"invoice_ids": c("(SELECT COALESCE(JSON_ARRAYAGG(h.`hoa_don` ORDER BY h.`idx`), JSON_ARRAY()) FROM `tabNPP Luot Soan Hoa Don` h "
				"WHERE h.`parent` = {t}.`name` AND h.`parenttype` = 'NPP Luot Soan')", "json"),
			"trang_thai": c("trang_thai"),
			"tien_do": c("COALESCE({t}.`tien_do`, '{\"chia\": {}, \"nhat\": {}}')", "json"),
			"created_by": c("owner"), "created_at": c("creation", "gio"), "updated_at": c("modified", "gio"),
			"xong_luc": c("xong_luc", "gio"), "xong_boi": c("xong_boi"),
		},
		quan_he=[QuanHe("users", "created_by", "id", False, ("luot_soan_created_by_fkey", "created_by")),
			QuanHe("users", "xong_boi", "id", False, ("luot_soan_xong_boi_fkey", "xong_boi"))],
		rls=lambda nc: None if nc.bo_qua_rls or nc.vai in VAI_SOAN else False,
	))


try:
	nap()
except Exception:
	pass
