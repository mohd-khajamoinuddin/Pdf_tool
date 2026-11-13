import type Konva from 'konva'
import { forwardRef, useEffect, useState, type ReactNode } from 'react'
import { Arrow, Ellipse, Group, Image as KonvaImage, Layer, Line, Rect, Stage, Text } from 'react-konva'
import { isLine, type El, type Slide } from './model'

const cache = new Map<string, HTMLImageElement>()

/** An <img> for a data URL, shared between every view that draws the same picture. */
export function useImage(src: string): HTMLImageElement | null {
  const [image, setImage] = useState<HTMLImageElement | null>(() => {
    const hit = cache.get(src)
    return hit?.complete ? hit : null
  })
  useEffect(() => {
    let img = cache.get(src)
    if (!img) {
      img = new Image()
      img.src = src
      cache.set(src, img)
    }
    if (img.complete) {
      setImage(img)
      return
    }
    const ready = (): void => setImage(img as HTMLImageElement)
    img.addEventListener('load', ready)
    return () => img?.removeEventListener('load', ready)
  }, [src])
  return image
}

export const displayText = (text: string, bullets: boolean): string =>
  bullets
    ? text
        .split('\n')
        .map((line) => (line.trim() ? `•  ${line}` : line))
        .join('\n')
    : text

function Picture({ el }: { el: Extract<El, { type: 'image' }> }): ReactNode {
  const image = useImage(el.src)
  return image ? <KonvaImage image={image} width={el.w} height={el.h} /> : <Rect width={el.w} height={el.h} fill="#e4e7ec" />
}

/** The drawing of one element, in its own coordinate space (0,0 = its top-left). */
export function ElementShape({ el, hideText }: { el: El; hideText?: boolean }): ReactNode {
  if (el.type === 'image') return <Picture el={el} />
  if (el.type === 'text') {
    return (
      <Text
        width={el.w}
        height={el.h}
        text={displayText(el.text, el.bullets)}
        fontFamily={el.fontFamily}
        fontSize={el.fontSize}
        fontStyle={`${el.italic ? 'italic ' : ''}${el.bold ? 'bold' : 'normal'}`}
        textDecoration={el.underline ? 'underline' : ''}
        fill={el.color}
        align={el.align}
        lineHeight={1.2}
        visible={!hideText}
      />
    )
  }
  const common = {
    fill: el.fill ?? undefined,
    stroke: el.stroke ?? undefined,
    strokeWidth: el.stroke ? el.strokeWidth : 0,
    opacity: el.opacity
  }
  switch (el.shape) {
    case 'rect':
      return <Rect width={el.w} height={el.h} {...common} />
    case 'roundRect':
      return <Rect width={el.w} height={el.h} cornerRadius={Math.min(el.w, el.h) * 0.16} {...common} />
    case 'ellipse':
      return <Ellipse x={el.w / 2} y={el.h / 2} radiusX={Math.abs(el.w) / 2} radiusY={Math.abs(el.h) / 2} {...common} />
    case 'triangle':
      return <Line points={[el.w / 2, 0, el.w, el.h, 0, el.h]} closed {...common} />
    case 'line':
      return <Line points={[0, 0, el.w, el.h]} stroke={el.stroke ?? '#1c2128'} strokeWidth={Math.max(el.strokeWidth, 0.75)} lineCap="round" hitStrokeWidth={18} opacity={el.opacity} />
    case 'arrow':
      return (
        <Arrow
          points={[0, 0, el.w, el.h]}
          stroke={el.stroke ?? '#1c2128'}
          fill={el.stroke ?? '#1c2128'}
          strokeWidth={Math.max(el.strokeWidth, 0.75)}
          pointerLength={Math.max(10, el.strokeWidth * 3.5)}
          pointerWidth={Math.max(10, el.strokeWidth * 3.5)}
          hitStrokeWidth={18}
          opacity={el.opacity}
        />
      )
  }
}

/** Where an element's group sits: boxes rotate about their centre (as in PowerPoint); lines start at (x, y). */
export function placement(el: El): { x: number; y: number; offsetX: number; offsetY: number; rotation: number } {
  if (isLine(el)) return { x: el.x, y: el.y, offsetX: 0, offsetY: 0, rotation: 0 }
  return { x: el.x + el.w / 2, y: el.y + el.h / 2, offsetX: el.w / 2, offsetY: el.h / 2, rotation: el.rotation }
}

/** A read-only rendering of a slide at any size: thumbnails, the slide show, and image/PDF export. */
export const SlideView = forwardRef<Konva.Stage, { slide: Slide; width: number; height: number; scale: number }>(function SlideView(
  { slide, width, height, scale },
  ref
) {
  return (
    <Stage ref={ref} width={width * scale} height={height * scale} scaleX={scale} scaleY={scale} listening={false}>
      <Layer>
        <Rect width={width} height={height} fill={slide.background} />
        {slide.elements.map((el) => (
          <Group key={el.id} {...placement(el)}>
            <ElementShape el={el} />
          </Group>
        ))}
      </Layer>
    </Stage>
  )
})
