/** Tailwind của portal = cấu hình của nppsale (nguon/) + quét thêm mã khung / mã thay thế của portal. */
import type { Config } from "tailwindcss"
import goc from "./nguon/tailwind.config"

const config: Config = {
  ...goc,
  content: ["./nguon/src/**/*.{js,ts,jsx,tsx,mdx}", "./src/**/*.{js,ts,jsx,tsx,mdx}"],
}

export default config
