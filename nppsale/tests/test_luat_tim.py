"""Khoá tìm (nppsale.luat.tim) trùng từng ký tự với bản TS của nppsale (`src/lib/search.ts`).

Mẫu `du_lieu/khoa_tim_mau.json` sinh bằng chính hàm TS (node chạy thẳng search.ts — không có import). Khi có portal/nguon và
node, test chạy lại hàm TS trên cùng bộ mẫu để bắt lúc nppsale đổi luật."""
import json
import os
import shutil
import subprocess
import unittest

from nppsale.luat.tim import khoa_tim, khoa_tim_ds, tu_tim

DIR = os.path.dirname(__file__)
MAU = os.path.join(DIR, "du_lieu", "khoa_tim_mau.json")
TS = os.path.abspath(os.path.join(DIR, "..", "..", "portal", "nguon", "src", "lib", "search.ts"))


def _kiem(tc, ds):
	for m in ds:
		if "ds" in m:
			tc.assertEqual(khoa_tim_ds(*m["ds"]), m["key"], m)
			continue
		tc.assertEqual(khoa_tim(m["v"]), m["key"], m)
		if m.get("q") is not None:
			tc.assertEqual(tu_tim(m["v"]), m["q"], m)


class TestKhoaTim(unittest.TestCase):
	def test_mau_ghim(self):
		_kiem(self, json.load(open(MAU, encoding="utf-8")))

	@unittest.skipUnless(os.path.exists(TS) and (shutil.which("node") or os.path.exists("/opt/node24/bin/node")), "không có nguon/ hoặc node")
	def test_khop_ban_ts_hien_tai(self):
		node = shutil.which("node") or "/opt/node24/bin/node"
		mau = [m["v"] for m in json.load(open(MAU, encoding="utf-8")) if "v" in m]
		ma = (f"import {{ viValueKey, viQueryWords }} from {json.dumps(TS)};"
			f"const mau = {json.dumps(mau, ensure_ascii=False)};"
			"console.log(JSON.stringify(mau.map(v => ({ v, key: viValueKey(v), q: typeof v === 'string' ? viQueryWords(v) : null }))))")
		ra = subprocess.run([node, "--input-type=module", "-e", ma], capture_output=True, text=True, timeout=60)
		self.assertEqual(ra.returncode, 0, ra.stderr)
		_kiem(self, json.loads(ra.stdout))


if __name__ == "__main__":
	unittest.main()
