"use client";
import { ArrowUp, Cpu, Download, Loader2, Mic, Plus, Settings, Share2, Sparkles, Trash2 } from "lucide-react";
import { MouseEvent, ReactNode, useRef } from "react";

export function TiltCard({ selected, onClick, children }: { selected?: boolean; onClick?: () => void; children: ReactNode }) {
  const ref = useRef<HTMLButtonElement>(null);
  const move = (e: MouseEvent) => {
    const box = ref.current!.getBoundingClientRect();
    const x = (e.clientX - box.left) / box.width - 0.5;
    const y = (e.clientY - box.top) / box.height - 0.5;
    ref.current!.style.transform = `perspective(700px) rotateY(${x * 10}deg) rotateX(${-y * 10}deg) scale(1.03)`;
  };
  const leave = () => { ref.current!.style.transform = ""; };
  return (
    <button ref={ref} type="button" onClick={onClick} onMouseMove={move} onMouseLeave={leave} aria-pressed={selected} className={`tilt ${selected ? "selected" : ""}`}>
      {children}
    </button>
  );
}

export function SceneToggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} title={on ? "Active" : "Standby"} onClick={() => onChange(!on)} className={`scene ${on ? "on" : ""}`}>
      <span className="star" style={{ left: 36, top: 8 }} />
      <span className="star" style={{ left: 48, top: 16 }} />
      <span className="star" style={{ left: 42, top: 22 }} />
      <span className="cloud" />
      <span className="thumb" />
    </button>
  );
}

export function RadarLoader({ label }: { label: string }) {
  const rings: [number, string, number, number][] = [[0, "#22d3ee", 7, 2], [24, "#22d3ee", 4.5, 2], [48, "#22d3ee", 3, 2], [70, "#facc15", 1.8, 3]];
  return (
    <div className="flex flex-col items-center gap-4 py-6" role="status">
      <div className="radar">
        {rings.map(([inset, color, speed, width], i) => (
          <i key={i} style={{ inset, borderColor: color, borderWidth: width, animationDuration: `${speed}s`, animationDirection: i % 2 ? "reverse" : "normal" }} />
        ))}
      </div>
      <p className="muted text-sm">{label}</p>
    </div>
  );
}

export function GenerateButton({ busy, onClick, children, disabled }: { busy: boolean; onClick: () => void; children: ReactNode; disabled?: boolean }) {
  return (
    <button type="button" className="btn btn-primary relative" disabled={busy || disabled} onClick={onClick}>
      {busy ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
      {children}
      {busy && <span className="progress" />}
    </button>
  );
}

export function MicButton({ on, onToggle, hint }: { on: boolean; onToggle: () => void; hint: string }) {
  return (
    <button type="button" className={`mic ${on ? "on" : ""}`} aria-pressed={on} aria-label={on ? "Stop recording" : "Start recording"} title={hint} onClick={onToggle}>
      <Mic size={17} />
    </button>
  );
}

export function Composer({ value, onChange, onSend, placeholder, mic, onPlus, busy }: {
  value: string; onChange: (v: string) => void; onSend: () => void; placeholder: string; mic: ReactNode; onPlus?: () => void; busy?: boolean;
}) {
  const ready = value.trim().length > 0 && !busy;
  return (
    <form className="composer" onSubmit={(e) => { e.preventDefault(); if (ready) onSend(); }}>
      <button type="button" className="btn btn-ghost icon-btn" aria-label="Add a feed" title="Add a feed" onClick={onPlus}><Plus size={16} /></button>
      <input aria-label={placeholder} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
      {mic}
      <button type="submit" aria-label="Send" disabled={!ready} className={`btn icon-btn ${ready ? "btn-primary" : "btn-ghost"}`}><ArrowUp size={16} /></button>
    </form>
  );
}

export function Sparkline({ values, up }: { values: number[]; up: boolean }) {
  if (values.length < 2) return <div className="muted grid h-20 place-items-center text-xs">Waiting for readings</div>;
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const points = values.map((v, i) => [(i / (values.length - 1)) * 300, 72 - ((v - lo) / span) * 62]);
  const line = points.map((p) => p.map((n) => n.toFixed(1)).join(",")).join(" ");
  const color = up ? "var(--good)" : "var(--bad)";
  const id = `fill-${up ? "up" : "down"}`;
  return (
    <svg viewBox="0 0 300 80" preserveAspectRatio="none" className="h-20 w-full" aria-hidden>
      <defs><linearGradient id={id} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor={color} stopOpacity="0.4" /><stop offset="1" stopColor={color} stopOpacity="0" /></linearGradient></defs>
      <polygon points={`0,80 ${line} 300,80`} fill={`url(#${id})`} />
      <polyline points={line} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function DeviceCard({ id, name, kind, live }: { id: string; name: string; kind: string; live: boolean }) {
  return (
    <div className="chip flex flex-col justify-between">
      <Cpu size={24} color="#d4af37" />
      {live && <div className="arcs" aria-label="Transmitting">
        {[10, 18, 26].map((s, i) => <span key={s} style={{ width: s, height: s, animationDelay: `${i * 0.2}s` }} />)}
      </div>}
      <div className="mono truncate text-base tracking-widest">{id.match(/.{1,4}/g)?.join(" ")}</div>
      <div className="flex justify-between gap-2 text-xs"><span className="truncate">{name}</span><span className="muted">{kind.replace("_", " ")}</span></div>
    </div>
  );
}

export function QuadMenu({ onExport, onShare, onSettings, onDelete }: { onExport: () => void; onShare: () => void; onSettings: () => void; onDelete: () => void }) {
  const items: [string, ReactNode, () => void, React.CSSProperties][] = [
    ["Export data", <Download size={15} key="e" />, onExport, { left: 0, top: 0, borderTopLeftRadius: "100%" }],
    ["Copy link", <Share2 size={15} key="s" />, onShare, { right: 0, top: 0, borderTopRightRadius: "100%" }],
    ["Feeds", <Settings size={15} key="c" />, onSettings, { left: 0, bottom: 0, borderBottomLeftRadius: "100%" }],
    ["Clear view", <Trash2 size={15} key="d" />, onDelete, { right: 0, bottom: 0, borderBottomRightRadius: "100%" }],
  ];
  return (
    <div className="fab" tabIndex={0} aria-label="Quick actions">
      {items.map(([label, icon, run, style]) => <button key={label} type="button" className="fab-seg" style={style} aria-label={label} title={label} onClick={run}>{icon}</button>)}
      <span className="fab-core"><Plus size={16} /></span>
    </div>
  );
}
