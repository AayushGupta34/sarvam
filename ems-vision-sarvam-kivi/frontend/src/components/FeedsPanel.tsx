"use client";
import { Activity, Camera, CircuitBoard, Copy, Link2, Radio, Scan, Thermometer, Trash2, Usb, Video, X, Zap } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, API_URL, feedUrl, wsUrl } from "@/lib/api";
import { DeviceCard, RadarLoader, SceneToggle, Sparkline, TiltCard } from "./ui";

type Source = { id: string; kind: string; role: string; title: string; note: string; icon: React.ReactNode; url?: boolean };
const SOURCES: Source[] = [
  { id: "webcam", kind: "browser_camera", role: "aoi_top", title: "This device's camera", note: "Webcam or USB microscope, through the browser", icon: <Camera size={22} /> },
  { id: "ip", kind: "ip_camera", role: "aoi_top", title: "IP camera", note: "Public MJPEG, snapshot or RTSP address", icon: <Video size={22} />, url: true },
  { id: "edge", kind: "edge_camera", role: "aoi_top", title: "Factory camera", note: "GigE Vision, RTSP or USB through the edge agent", icon: <Scan size={22} /> },
  { id: "xray", kind: "edge_camera", role: "xray", title: "X-ray (AXI)", note: "Slice images through the edge agent", icon: <Zap size={22} /> },
  { id: "thermal", kind: "edge_camera", role: "thermal", title: "Thermal camera", note: "Thermal frames through the edge agent", icon: <Thermometer size={22} /> },
  { id: "sensor", kind: "sensor", role: "sensor", title: "Test fixture sensors", note: "Rail voltage, temperature, contact resistance", icon: <Activity size={22} /> },
  { id: "plc", kind: "plc_trigger", role: "trigger", title: "PLC trigger", note: "Modbus TCP or OPC-UA, through the edge agent", icon: <CircuitBoard size={22} /> },
];
const RANGES: [string, number][] = [["1H", 3600e3], ["1D", 864e5], ["1W", 6048e5], ["1M", 2592e6], ["ALL", Infinity]];
const UNITS: Record<string, string> = { rail_5v_v: " V", board_temp_c: " °C", j3_contact_mohm: " mΩ" };
const NAMES: Record<string, string> = { rail_5v_v: "5 V rail", board_temp_c: "Board temperature", j3_contact_mohm: "J3 contact" };

/** Webcam capture sends JPEG frames over a socket. Stays mounted while other tabs are open. */
function useBrowserCameras(notify: (m: string) => void) {
  const running = useRef(new Map<string, () => void>());
  const [active, setActive] = useState<string[]>([]);

  const start = useCallback(async (feedId: string, deviceId?: string) => {
    if (running.current.has(feedId)) return;
    const stream = await navigator.mediaDevices.getUserMedia({ video: deviceId ? { deviceId: { exact: deviceId } } : { width: { ideal: 1920 }, height: { ideal: 1080 } } });
    const video = document.createElement("video");
    video.srcObject = stream;
    video.muted = true;
    await video.play();
    const canvas = document.createElement("canvas");
    const socket = new WebSocket(wsUrl(`/ws/ingest/${feedId}`));
    socket.binaryType = "arraybuffer";
    socket.onclose = (e) => { if (e.code === 4401) notify("The server refused this feed"); };
    const timer = window.setInterval(() => {
      if (socket.readyState !== WebSocket.OPEN || !video.videoWidth) return;
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d")!.drawImage(video, 0, 0);
      canvas.toBlob((b) => b?.arrayBuffer().then((buffer) => { if (socket.readyState === WebSocket.OPEN) socket.send(buffer); }), "image/jpeg", 0.85);
    }, 200);
    running.current.set(feedId, () => {
      clearInterval(timer);
      socket.close();
      stream.getTracks().forEach((t) => t.stop());
    });
    setActive([...running.current.keys()]);
  }, [notify]);

  const stop = useCallback((feedId: string) => {
    running.current.get(feedId)?.();
    running.current.delete(feedId);
    setActive([...running.current.keys()]);
  }, []);

  return { active, start, stop };
}

/** Browser-side sensor links: Web Serial where Chrome or Edge offers it, or a labelled simulator. */
function useBrowserSensors(notify: (m: string) => void) {
  const running = useRef(new Map<string, () => void>());
  const [active, setActive] = useState<string[]>([]);

  const open = (feedId: string) => {
    const socket = new WebSocket(wsUrl(`/ws/ingest/${feedId}`));
    return { socket, send: (values: Record<string, number>) => { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "reading", values })); } };
  };
  const track = (feedId: string, stop: () => void) => { running.current.set(feedId, stop); setActive([...running.current.keys()]); };

  const simulate = (feedId: string) => {
    const { socket, send } = open(feedId);
    const noise = (mean: number, sd: number) => +(mean + (Math.random() + Math.random() - 1) * sd * 1.7).toFixed(2);
    const timer = window.setInterval(() => send({ rail_5v_v: noise(5, 0.15), board_temp_c: noise(54, 8), j3_contact_mohm: noise(30, 15) }), 1000);
    track(feedId, () => { clearInterval(timer); socket.close(); });
  };

  const serial = async (feedId: string) => {
    const nav = navigator as any;
    if (!nav.serial) return notify("USB serial needs Chrome or Edge. Use the edge agent on other browsers");
    const port = await nav.serial.requestPort();
    await port.open({ baudRate: 115200 });
    const { socket, send } = open(feedId);
    const reader = port.readable.pipeThrough(new TextDecoderStream()).getReader();
    let open_ = true;
    track(feedId, () => { open_ = false; reader.cancel(); socket.close(); });
    let buffer = "";
    while (open_) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        try { send(JSON.parse(line)); } catch { /* ignore partial lines from the fixture */ }
      }
    }
  };

  const stop = (feedId: string) => {
    running.current.get(feedId)?.();
    running.current.delete(feedId);
    setActive([...running.current.keys()]);
  };
  return { active, simulate, serial, stop };
}

function MetricCard({ name, points, alert }: { name: string; points: [number, number][]; alert: boolean }) {
  const [range, setRange] = useState("1H");
  const span = RANGES.find(([r]) => r === range)![1];
  const now = Date.now();
  const shown = points.filter(([t]) => now - t <= span).map(([, v]) => v);
  const latest = shown[shown.length - 1] ?? 0;
  const delta = shown.length > 1 && shown[0] ? ((latest - shown[0]) / Math.abs(shown[0])) * 100 : 0;
  const up = !alert && delta >= 0;
  return (
    <div className="glass overflow-hidden p-4" style={alert ? { borderColor: "var(--bad)" } : undefined}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="muted text-xs">{NAMES[name] ?? name}</div>
          <div className="text-3xl font-bold tabular-nums">{latest}{UNITS[name] ?? ""}</div>
          <div className="text-xs tabular-nums" style={{ color: delta >= 0 ? "var(--good)" : "var(--bad)" }}>{delta >= 0 ? "+" : ""}{delta.toFixed(2)}%{alert ? " · out of limit" : ""}</div>
        </div>
        <div className="flex gap-0.5">{RANGES.map(([r]) => <button key={r} type="button" className={`range ${r === range ? "on" : ""}`} onClick={() => setRange(r)}>{r}</button>)}</div>
      </div>
      <Sparkline values={shown.slice(-90)} up={up} />
    </div>
  );
}

function AgentCommand({ feed }: { feed: any }) {
  const flag = feed.kind === "sensor" ? "--sensor simulated" : feed.kind === "plc_trigger" ? "--trigger sim:10 --camera-feed <camera id>" : "--camera rtsp://<camera address>/stream";
  const command = `python edge-sensing/agent.py --server ${API_URL.replace(/^http/, "ws")} --feed ${feed.id} ${flag}`;
  return (
    <div className="flex items-center gap-2 rounded-xl bg-black/40 p-2">
      <code className="mono min-w-0 flex-1 truncate text-xs" title={command}>{command}</code>
      <button type="button" className="btn btn-ghost icon-btn" aria-label="Copy command" title="Copy command" onClick={() => navigator.clipboard.writeText(command)}><Copy size={14} /></button>
    </div>
  );
}

export function FeedsPanel({ notify, incoming, connectOpen, setConnectOpen }: { notify: (m: string) => void; incoming: any; connectOpen: boolean; setConnectOpen: (v: boolean) => void }) {
  const [feeds, setFeeds] = useState<any[]>([]);
  const [source, setSource] = useState<Source>(SOURCES[0]);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [cameras, setCameras] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const [history, setHistory] = useState<Record<string, Record<string, [number, number][]>>>({});
  const webcams = useBrowserCameras(notify);
  const sensors = useBrowserSensors(notify);

  const refresh = useCallback(() => api("/api/feeds").then(setFeeds).catch(() => {}), []);
  useEffect(() => { refresh(); const t = setInterval(refresh, 2000); return () => clearInterval(t); }, [refresh]);

  useEffect(() => {
    if (incoming?.type !== "sensor_reading") return;
    const now = Date.now();
    setHistory((h) => {
      const feed = { ...(h[incoming.feed_id] ?? {}) };
      for (const [k, v] of Object.entries(incoming.values)) feed[k] = [...(feed[k] ?? []).slice(-3600), [now, v as number]];
      return { ...h, [incoming.feed_id]: feed };
    });
  }, [incoming]);

  const scan = async () => {
    setConnecting(true);
    try {
      const probe = await navigator.mediaDevices.getUserMedia({ video: true });
      probe.getTracks().forEach((t) => t.stop());
      const found = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
      setCameras(found);
      setDeviceId(found[0]?.deviceId ?? "");
      notify(`${found.length} camera${found.length === 1 ? "" : "s"} found`);
    } catch {
      notify("Camera permission was refused or no camera is attached");
    } finally {
      setConnecting(false);
    }
  };

  const connect = async () => {
    setConnecting(true);
    try {
      const feed = await api("/api/feeds", { name: name || source.title, kind: source.kind, role: source.role, url: source.url ? url : undefined });
      if (source.kind === "browser_camera") await webcams.start(feed.id, deviceId || undefined);
      setConnectOpen(false);
      setName("");
      setUrl("");
      await refresh();
    } catch (e: any) {
      notify(e.message);
    } finally {
      setConnecting(false);
    }
  };

  const act = async (run: () => Promise<any>, done?: string) => {
    try {
      await run();
      if (done) notify(done);
      refresh();
    } catch (e: any) {
      notify(e.message);
    }
  };

  const remove = (id: string) => act(async () => {
    webcams.stop(id);
    sensors.stop(id);
    await api(`/api/feeds/${id}`, undefined, "DELETE");
  });

  const cams = useMemo(() => feeds.filter((f) => f.kind.endsWith("camera")), [feeds]);
  const others = useMemo(() => feeds.filter((f) => !f.kind.endsWith("camera")), [feeds]);
  const liveCount = feeds.filter((f) => f.live).length;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-semibold">Feeds and sensors</h2>
        <span className="muted flex items-center gap-2 text-sm"><span className={liveCount ? "live-dot" : "off-dot"} />{liveCount} of {feeds.length} live</span>
        <div className="flex-1" />
        <button type="button" className="btn btn-primary" onClick={() => setConnectOpen(true)}><Link2 size={15} />Connect device</button>
      </div>

      {feeds.length === 0 && (
        <button type="button" className="glass muted p-10 text-center text-sm" onClick={() => setConnectOpen(true)}>
          No feeds yet. Connect a camera, X-ray, sensor or PLC. Any number can run at once.
        </button>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {cams.map((f) => {
          const browser = f.kind === "browser_camera";
          const on = browser ? webcams.active.includes(f.id) : f.live;
          return (
            <article key={f.id} className="glass overflow-hidden" style={f.live ? { boxShadow: "0 0 18px var(--accent-soft)" } : undefined}>
              <div className="relative aspect-video bg-black/50">
                {f.frames > 0 ? <img alt={f.name} src={feedUrl(f.id, "stream.mjpg")} className="h-full w-full object-contain" /> : <p className="muted absolute inset-0 grid place-items-center p-4 text-center text-xs">{f.error ?? "Waiting for the first frame"}</p>}
                <span className="absolute left-2 top-2 flex items-center gap-2 rounded-full bg-black/60 px-2 py-0.5 text-xs"><span className={f.live ? "live-dot" : "off-dot"} />{f.role.replace("_", " ")}</span>
              </div>
              <div className="flex flex-col gap-2 p-3">
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{f.name}</span>
                  {browser && <SceneToggle label={`${f.name} active`} on={on} onChange={(v) => act(() => (v ? webcams.start(f.id) : Promise.resolve(webcams.stop(f.id))))} />}
                  <button type="button" className="btn btn-ghost icon-btn" aria-label="Remove feed" title="Remove feed" onClick={() => remove(f.id)}><Trash2 size={14} /></button>
                </div>
                {f.kind === "edge_camera" && !f.live && <AgentCommand feed={f} />}
                <div className="flex flex-wrap gap-2">
                  <button type="button" className="btn btn-outline" disabled={!f.frames} onClick={() => act(() => api(`/api/feeds/${f.id}/golden`, {}), "Golden frame captured")}>{f.has_golden ? "Retake golden" : "Capture golden"}</button>
                  <button type="button" className="btn btn-primary" disabled={!f.has_golden} onClick={() => act(() => api(`/api/feeds/${f.id}/inspect`, {}), "Inspection sent to the Rework tab")}>Inspect</button>
                </div>
              </div>
            </article>
          );
        })}
      </div>

      {others.map((f) => {
        const on = sensors.active.includes(f.id);
        const metrics = history[f.id] ?? {};
        return (
          <section key={f.id} className="grid gap-4 md:grid-cols-[280px_1fr]">
            <div className="flex flex-col gap-2">
              <DeviceCard id={f.id} name={f.name} kind={f.kind} live={f.live} />
              {f.kind === "sensor" && (
                <div className="flex flex-wrap items-center gap-2">
                  {on ? <button type="button" className="btn btn-ghost" onClick={() => sensors.stop(f.id)}>Stop</button> : <>
                    <button type="button" className="btn btn-outline" onClick={() => sensors.serial(f.id).catch((e) => notify(e.message))}><Usb size={14} />USB serial</button>
                    <button type="button" className="btn btn-ghost" onClick={() => sensors.simulate(f.id)}>Simulate</button>
                  </>}
                  <button type="button" className="btn btn-ghost icon-btn" aria-label="Remove feed" title="Remove feed" onClick={() => remove(f.id)}><Trash2 size={14} /></button>
                </div>
              )}
              {f.kind === "plc_trigger" && <button type="button" className="btn btn-ghost" onClick={() => remove(f.id)}><Trash2 size={14} />Remove</button>}
              {!f.live && !on && <AgentCommand feed={f} />}
            </div>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {Object.entries(metrics).map(([k, points]) => <MetricCard key={k} name={k} points={points} alert={f.alerts?.some((a: any) => a.reading === k)} />)}
              {Object.keys(metrics).length === 0 && <div className="glass muted grid place-items-center p-6 text-sm"><span className="flex items-center gap-2"><Radio size={15} />{f.kind === "plc_trigger" ? "Trigger events go straight to inspection" : "No readings yet"}</span></div>}
            </div>
          </section>
        );
      })}

      {connectOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-black/70 p-4" role="dialog" aria-modal="true" aria-label="Connect a device">
          <div className="glass w-full max-w-3xl bg-[#101014] p-5">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-lg font-semibold">Connect a device</h3>
              <button type="button" className="btn btn-ghost icon-btn" aria-label="Close" onClick={() => setConnectOpen(false)}><X size={15} /></button>
            </div>
            {connecting ? <RadarLoader label="Connecting…" /> : (
              <>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  {SOURCES.map((s) => (
                    <TiltCard key={s.id} selected={s.id === source.id} onClick={() => setSource(s)}>
                      {s.icon}<div className="mt-2 text-sm font-semibold">{s.title}</div><div className="muted mt-1 text-xs">{s.note}</div>
                    </TiltCard>
                  ))}
                </div>
                <div className="mt-4 flex flex-col gap-2">
                  <input className="field" aria-label="Feed name" placeholder={`Name (${source.title})`} value={name} onChange={(e) => setName(e.target.value)} />
                  {source.url && <input className="field" aria-label="Camera address" placeholder="https://camera.example.com/video.mjpg" value={url} onChange={(e) => setUrl(e.target.value)} />}
                  {source.kind === "browser_camera" && cameras.length > 0 && (
                    <select className="field" aria-label="Camera" value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
                      {cameras.map((c, i) => <option key={c.deviceId} value={c.deviceId}>{c.label || `Camera ${i + 1}`}</option>)}
                    </select>
                  )}
                  {source.kind !== "browser_camera" && !source.url && source.kind !== "sensor" && <p className="muted text-xs">You will get a one-line command to run on a computer on the factory network.</p>}
                </div>
                <div className="mt-4 flex flex-wrap justify-end gap-2">
                  {source.kind === "browser_camera" && <button type="button" className="btn btn-outline" onClick={scan}><Scan size={15} />Scan for devices</button>}
                  <button type="button" className="btn btn-primary" disabled={source.url && !url} onClick={connect}><Link2 size={15} />Connect</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
