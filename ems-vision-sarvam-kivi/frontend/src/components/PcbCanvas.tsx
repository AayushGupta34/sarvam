"use client";
import { RotateCcw } from "lucide-react";
import { MouseEvent, useCallback, useEffect, useRef, useState, WheelEvent } from "react";

export interface Box { bbox: number[]; label: string; selected: boolean }

export function PcbCanvas({ src, boxes, homography, onPick }: { src: string | null; boxes: Box[]; homography?: number[][]; onPick?: (i: number) => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const view = useRef({ zoom: 1, x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);

  const fit = useCallback(() => {
    const c = canvas.current;
    if (!c || !image) return;
    const zoom = Math.min(c.width / image.width, c.height / image.height);
    view.current = { zoom, x: (c.width - image.width * zoom) / 2, y: (c.height - image.height * zoom) / 2 };
  }, [image]);

  const draw = useCallback(() => {
    const c = canvas.current;
    if (!c) return;
    const ctx = c.getContext("2d")!;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, c.width, c.height);
    if (!image) return;
    const { zoom, x, y } = view.current;
    ctx.setTransform(zoom, 0, 0, zoom, x, y);
    ctx.save();
    // Boxes are in golden-frame pixels, so the frame is drawn through the registration transform.
    if (homography) ctx.transform(homography[0][0], homography[1][0], homography[0][1], homography[1][1], homography[0][2], homography[1][2]);
    ctx.drawImage(image, 0, 0);
    ctx.restore();
    const accent = getComputedStyle(c).getPropertyValue("--accent");
    boxes.forEach((b) => {
      const [x0, y0, x1, y1] = b.bbox;
      ctx.lineWidth = (b.selected ? 3 : 2) / zoom;
      ctx.strokeStyle = accent;
      ctx.shadowColor = accent;
      ctx.shadowBlur = 14;
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
      ctx.shadowBlur = 0;
      ctx.font = `${13 / zoom}px sans-serif`;
      const width = ctx.measureText(b.label).width + 10 / zoom;
      ctx.fillStyle = accent;
      ctx.fillRect(x0, y0 - 19 / zoom, width, 18 / zoom);
      ctx.fillStyle = "#0a0a0a";
      ctx.fillText(b.label, x0 + 5 / zoom, y0 - 5 / zoom);
    });
  }, [image, boxes, homography]);

  useEffect(() => {
    if (!src) { setImage(null); return; }
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => setImage(img);
    img.src = src;
  }, [src]);

  useEffect(() => {
    const c = canvas.current!;
    const resize = () => {
      const box = c.parentElement!.getBoundingClientRect();
      c.width = box.width;
      c.height = box.height;
      fit();
      draw();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(c.parentElement!);
    return () => observer.disconnect();
  }, [fit, draw]);

  useEffect(() => { fit(); draw(); }, [image, fit, draw]);
  useEffect(draw, [boxes, draw]);

  const zoomAt = (e: WheelEvent) => {
    const box = canvas.current!.getBoundingClientRect();
    const px = e.clientX - box.left, py = e.clientY - box.top;
    const v = view.current;
    const next = Math.min(12, Math.max(0.05, v.zoom * (e.deltaY < 0 ? 1.15 : 0.87)));
    v.x = px - ((px - v.x) / v.zoom) * next;
    v.y = py - ((py - v.y) / v.zoom) * next;
    v.zoom = next;
    draw();
  };

  const move = (e: MouseEvent) => {
    if (!drag.current) return;
    view.current.x += e.clientX - drag.current.x;
    view.current.y += e.clientY - drag.current.y;
    drag.current = { x: e.clientX, y: e.clientY, moved: true };
    draw();
  };

  const up = (e: MouseEvent) => {
    const clicked = drag.current && !drag.current.moved;
    drag.current = null;
    if (!clicked || !onPick) return;
    const box = canvas.current!.getBoundingClientRect();
    const v = view.current;
    const x = (e.clientX - box.left - v.x) / v.zoom, y = (e.clientY - box.top - v.y) / v.zoom;
    const hit = boxes.findIndex((b) => x >= b.bbox[0] && x <= b.bbox[2] && y >= b.bbox[1] && y <= b.bbox[3]);
    if (hit >= 0) onPick(hit);
  };

  return (
    <div className="relative h-full min-h-[320px] w-full overflow-hidden rounded-2xl bg-black/40">
      <canvas ref={canvas} className="absolute inset-0 cursor-grab active:cursor-grabbing" aria-label="PCB image with defect boxes. Scroll to zoom, drag to pan."
        onWheel={zoomAt} onMouseDown={(e) => { drag.current = { x: e.clientX, y: e.clientY, moved: false }; }} onMouseMove={move} onMouseUp={up} onMouseLeave={() => { drag.current = null; }} />
      {!src && <p className="muted absolute inset-0 grid place-items-center text-sm">Pick a board and run an inspection</p>}
      {src && <button type="button" className="btn btn-ghost icon-btn absolute right-3 top-3" aria-label="Reset view" title="Reset view" onClick={() => { fit(); draw(); }}><RotateCcw size={15} /></button>}
    </div>
  );
}
