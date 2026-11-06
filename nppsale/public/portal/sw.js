/* Service worker của portal nppsale — bản khung PoC. Bản thật do Vite build ghi đè. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
