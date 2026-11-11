// Service worker của portal nppsale trên Frappe — phạm vi /nppsale/ (nppsale.portal.tinh phục vụ, không cache).
//   - Tài sản build của Vite (/assets/nppsale/portal/app/…, tên có hash): lấy bộ nhớ trước, thiếu mới tải.
//   - Mở trang dưới /nppsale/ (trừ login / qr-login / debug): mạng trước; mất mạng thì trả bản đã lưu (giữ được vỏ app).
//   - Không bao giờ lưu: /api, /rest (dữ liệu), câu khác gốc, câu không phải GET hoặc không 200.
// Đổi cách lưu → tăng PHIEN để dọn bộ nhớ cũ.
const PHIEN = "npp-frappe-v1"
const KHO_TINH = `${PHIEN}-tinh`
const KHO_TRANG = `${PHIEN}-trang`
const GOC = "/nppsale"
const TAI_SAN = "/assets/nppsale/portal/app/"

self.addEventListener("install", () => self.skipWaiting())

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // Tải trước điều hướng: yêu cầu trang đi song song lúc SW thức dậy (trình duyệt không hỗ trợ thì thôi).
      try {
        if (self.registration.navigationPreload) await self.registration.navigationPreload.enable()
      } catch (e) {}
      const ds = await caches.keys()
      await Promise.all(ds.filter((k) => !k.startsWith(PHIEN)).map((k) => caches.delete(k)))
      await self.clients.claim()
    })()
  )
})

function laTrangLuuDuoc(url) {
  const p = url.pathname
  if (p !== GOC && !p.startsWith(GOC + "/")) return false
  const con = p.slice(GOC.length)
  return !con.startsWith("/login") && !con.startsWith("/qr-login") && !con.startsWith("/debug")
}

async function luu(kho, req, res) {
  if (!res.ok) return
  const c = await caches.open(kho)
  await c.put(req, res)
}

self.addEventListener("fetch", (event) => {
  const req = event.request
  if (req.method !== "GET") return
  const url = new URL(req.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/rest/")) return

  if (url.pathname.startsWith(TAI_SAN)) {
    event.respondWith(
      caches.match(req).then(
        (co) =>
          co ||
          fetch(req).then((res) => {
            event.waitUntil(luu(KHO_TINH, req, res.clone()))
            return res
          })
      )
    )
    return
  }

  if (req.mode === "navigate" && laTrangLuuDuoc(url)) {
    event.respondWith(
      Promise.resolve(event.preloadResponse)
        .then((truoc) => truoc || fetch(req))
        .then((res) => {
          event.waitUntil(luu(KHO_TRANG, req, res.clone()))
          return res
        })
        .catch(async () => {
          const co = await caches.match(req)
          if (co) return co
          const kho = await caches.open(KHO_TRANG)
          const ds = await kho.keys()
          if (ds.length) {
            const bat_ky = await kho.match(ds[0])
            if (bat_ky) return bat_ky
          }
          return new Response("<h1>Ngoại tuyến</h1><p>Mở lại khi có mạng để tải trang này lần đầu.</p>", {
            status: 503,
            headers: { "Content-Type": "text/html; charset=utf-8" },
          })
        })
    )
  }
})
