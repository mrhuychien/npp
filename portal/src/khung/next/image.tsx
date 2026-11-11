/** Thay `next/image` bằng <img> (portal không có bộ tối ưu ảnh của Next). */
import { forwardRef, type CSSProperties, type ImgHTMLAttributes } from "react"

type Props = Omit<ImgHTMLAttributes<HTMLImageElement>, "src"> & {
  src: string | { src: string }
  fill?: boolean
  priority?: boolean
  quality?: number
  placeholder?: string
  blurDataURL?: string
  loader?: unknown
  unoptimized?: boolean
}

const Image = forwardRef<HTMLImageElement, Props>(function Image(
  { src, fill, priority, quality: _q, placeholder: _p, blurDataURL: _b, loader: _l, unoptimized: _u, style, width, height, ...rest },
  ref
) {
  const s = typeof src === "string" ? src : src?.src
  const st: CSSProperties | undefined = fill ? { position: "absolute", inset: 0, width: "100%", height: "100%", ...style } : style
  return (
    <img ref={ref} src={s} width={fill ? undefined : width} height={fill ? undefined : height} loading={priority ? "eager" : "lazy"} decoding="async" style={st} {...rest} />
  )
})

export default Image
