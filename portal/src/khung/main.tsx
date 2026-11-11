/** Điểm vào của portal nppsale trên Frappe: React Router dưới basename "/nppsale" (route sinh từ src/app bằng scripts/tao-route.mjs). */
import { createRoot } from "react-dom/client"
import { createBrowserRouter, RouterProvider } from "react-router-dom"
import { routes } from "./routes.generated"
import { caiApiCu } from "./api-cu"
import { caiCuaSo } from "./cua-so"

// Trước khi bất kỳ màn nào chạy: lời gọi `/api/<route Next cũ>` → method Frappe; đường dẫn tuyệt đối → tiền tố /nppsale.
caiApiCu()
caiCuaSo()

const router = createBrowserRouter(routes, { basename: "/nppsale" })

const goc = document.getElementById("goc")
if (goc) createRoot(goc).render(<RouterProvider router={router} />)
