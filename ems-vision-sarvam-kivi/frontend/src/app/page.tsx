"use client";
import { ArrowUp, CircuitBoard, Mic2, Radio } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { FeedsPanel } from "@/components/FeedsPanel";
import { KiviManager } from "@/components/KiviManager";
import { ReworkStation } from "@/components/ReworkStation";
import { api, getToken, setToken, wsUrl } from "@/lib/api";

type Tab = "rework" | "feeds" | "kivi";
const TABS: [Tab, string, React.ReactNode][] = [
  ["rework", "Rework station", <CircuitBoard size={15} key="r" />], ["feeds", "Feeds and sensors", <Radio size={15} key="f" />], ["kivi", "Kivi voice space", <Mic2 size={15} key="k" />],
];

export default function Home() {
  const [tab, setTab] = useState<Tab>("rework");
  const [health, setHealth] = useState<any>(null);
  const [offline, setOffline] = useState(false);
  const [needsToken, setNeedsToken] = useState(false);
  const [tokenDraft, setTokenDraft] = useState("");
  const [toast, setToast] = useState("");
  const [socketLive, setSocketLive] = useState(false);
  const [incoming, setIncoming] = useState<any>(null);
  const [connectOpen, setConnectOpen] = useState(false);
  const [session, setSession] = useState(0);

  const notify = useCallback((message: string) => {
    setToast(message);
    setTimeout(() => setToast(""), 4000);
  }, []);

  useEffect(() => {
    api("/api/health").then((h) => {
      setHealth(h);
      setNeedsToken(h.auth_required && !getToken());
    }).catch(() => setOffline(true));
  }, [session]);

  useEffect(() => {
    if (!health || needsToken) return;
    let socket: WebSocket;
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;
    const open = () => {
      socket = new WebSocket(wsUrl("/ws/shopfloor"));
      socket.onopen = () => setSocketLive(true);
      socket.onmessage = (e) => setIncoming(JSON.parse(e.data));
      socket.onclose = () => {
        setSocketLive(false);
        if (!closed) retry = setTimeout(open, 2000);
      };
    };
    open();
    return () => { closed = true; clearTimeout(retry); socket.close(); };
  }, [health, needsToken]);

  const openFeeds = useCallback(() => { setTab("feeds"); setConnectOpen(true); }, []);

  if (needsToken) {
    return (
      <main className="grid min-h-screen place-items-center p-4">
        <form className="glass flex w-full max-w-sm flex-col gap-3 p-6" onSubmit={(e) => { e.preventDefault(); setToken(tokenDraft); setNeedsToken(false); setSession(session + 1); }}>
          <h1 className="text-lg font-semibold">EMS Vision</h1>
          <input className="field" type="password" aria-label="Access code" placeholder="Access code" value={tokenDraft} onChange={(e) => setTokenDraft(e.target.value)} />
          <button className="btn btn-primary" disabled={!tokenDraft}>Enter</button>
        </form>
      </main>
    );
  }

  return (
    <main className="mx-auto flex max-w-[1500px] flex-col gap-4 p-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold">EMS Vision</h1>
        <nav className="flex flex-wrap gap-1" aria-label="Sections">
          {TABS.map(([id, label, icon]) => <button key={id} type="button" aria-current={tab === id} className={`btn ${tab === id ? "btn-outline" : "btn-ghost"}`} onClick={() => setTab(id)}>{icon}{label}</button>)}
        </nav>
        <div className="flex-1" />
        <span className="muted flex items-center gap-2 text-xs"><span className={socketLive ? "live-dot" : "off-dot"} />{socketLive ? "Connected" : offline ? "Server unreachable" : "Connecting"}</span>
        {health?.demo_mode && <span className="muted rounded-full border border-white/10 px-2 py-0.5 text-xs">Demo mode</span>}
      </header>

      {/* All tabs stay mounted so that cameras keep streaming while the operator works elsewhere. */}
      <div hidden={tab !== "rework"}><ReworkStation notify={notify} onOpenFeeds={openFeeds} incoming={incoming} /></div>
      <div hidden={tab !== "feeds"}><FeedsPanel notify={notify} incoming={incoming} connectOpen={connectOpen} setConnectOpen={setConnectOpen} /></div>
      <div hidden={tab !== "kivi"}><KiviManager notify={notify} /></div>

      <button type="button" aria-label="Back to top" title="Back to top" className="btn btn-ghost icon-btn fixed bottom-4 right-4 z-40 !rounded-full !bg-[#18181d]" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}><ArrowUp size={16} /></button>
      {toast && <div role="status" className="glass fixed bottom-6 left-1/2 z-50 -translate-x-1/2 bg-[#18181d] px-4 py-2 text-sm">{toast}</div>}
    </main>
  );
}
