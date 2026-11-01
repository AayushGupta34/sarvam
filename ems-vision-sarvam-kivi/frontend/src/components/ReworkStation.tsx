"use client";
import { CheckCircle2, Copy, Volume2, XCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { LANGUAGES } from "@/config/languages";
import { api, assetUrl } from "@/lib/api";
import { useRecorder } from "@/lib/useRecorder";
import { PcbCanvas } from "./PcbCanvas";
import { Composer, GenerateButton, MicButton, QuadMenu } from "./ui";

const titleCase = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export function ReworkStation({ notify, onOpenFeeds, incoming }: { notify: (m: string) => void; onOpenFeeds: () => void; incoming: any }) {
  const [cases, setCases] = useState<any[]>([]);
  const [caseId, setCaseId] = useState("");
  const [result, setResult] = useState<any>(null);
  const [selected, setSelected] = useState(0);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<"test" | "golden" | "xray">("test");
  const [language, setLanguage] = useState("hi-IN");
  const [codeMixed, setCodeMixed] = useState(false);
  const [translated, setTranslated] = useState("");
  const [speech, setSpeech] = useState<{ note?: string; engine?: string } | null>(null);
  const [speaking, setSpeaking] = useState(false);
  const [draft, setDraft] = useState("");
  const [logged, setLogged] = useState<any>(null);
  const [sending, setSending] = useState(false);
  const { recording, start, stop } = useRecorder();
  const translateRun = useRef(0);

  useEffect(() => {
    api("/api/cases").then((c) => { setCases(c); setCaseId(c[0]?.id ?? ""); }).catch((e) => notify(e.message));
  }, [notify]);

  useEffect(() => {
    if (incoming?.type === "diagnosis_updated" && incoming.id === result?.id) setResult((r: any) => ({ ...r, diagnoses: incoming.diagnoses }));
    if (incoming?.type === "inspection" && incoming.inspection.source.startsWith("feed:")) {
      setResult(incoming.inspection);
      setSelected(0);
    }
  }, [incoming, result?.id]);

  const diagnosis = result?.diagnoses?.[selected];
  const instruction: string = diagnosis?.rework_instruction_en ?? "";

  useEffect(() => {
    setTranslated("");
    setSpeech(null);
    if (!instruction) return;
    const run = ++translateRun.current;
    api("/api/translate", { text: instruction, target: language, code_mixed: codeMixed })
      .then((r) => { if (run === translateRun.current) setTranslated(r.text); })
      .catch((e) => notify(e.message));
  }, [instruction, language, codeMixed, notify]);

  const inspect = async () => {
    setBusy(true);
    try {
      setResult(await api("/api/inspect", { case_id: caseId }));
      setSelected(0);
      setView("test");
    } catch (e: any) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  };

  const play = async () => {
    if (!translated) return;
    setSpeaking(true);
    try {
      const reply = await api("/api/tts", { text: translated, language });
      setSpeech(reply);
      if (reply.audio_base64) {
        const audio = new Audio(`data:audio/wav;base64,${reply.audio_base64}`);
        audio.onended = () => setSpeaking(false);
        await audio.play();
        return;
      }
      const utterance = new SpeechSynthesisUtterance(translated);
      utterance.lang = language;
      utterance.onend = () => setSpeaking(false);
      speechSynthesis.speak(utterance);
    } catch (e: any) {
      notify(e.message);
      setSpeaking(false);
    }
  };

  const finishRecording = useCallback(async () => {
    const blob = await stop();
    if (!blob) return;
    setSending(true);
    const form = new FormData();
    form.append("audio", blob, "speech.webm");
    form.append("language", language);
    if (result?.serial) form.append("serial", result.serial);
    try {
      setLogged(await api("/api/kivi/transcribe", form));
    } catch (e: any) {
      notify(e.message);
    } finally {
      setSending(false);
    }
  }, [stop, language, result?.serial, notify]);

  const startRecording = useCallback(() => start().catch(() => notify("Microphone permission was refused")), [start, notify]);

  // Foot pedal: hold Space to talk. Most pedals can be mapped to this key.
  useEffect(() => {
    const typing = (e: KeyboardEvent) => /INPUT|TEXTAREA|SELECT/.test((e.target as HTMLElement).tagName);
    const down = (e: KeyboardEvent) => { if (e.code === "Space" && !e.repeat && !typing(e)) { e.preventDefault(); startRecording(); } };
    const up = (e: KeyboardEvent) => { if (e.code === "Space" && !typing(e)) { e.preventDefault(); finishRecording(); } };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, [startRecording, finishRecording]);

  const sendText = async () => {
    setSending(true);
    try {
      setLogged(await api("/api/kivi/process", { text: draft, serial: result?.serial, language }));
      setDraft("");
    } catch (e: any) {
      notify(e.message);
    } finally {
      setSending(false);
    }
  };

  const exportReport = () => {
    if (!result) return notify("Run an inspection first");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }));
    link.download = `${result.serial}.json`;
    link.click();
  };

  const boxes = view === "test" ? (result?.defects ?? []).filter((d: any) => d.source !== "xray").map((d: any) => ({
    bbox: d.bbox, label: `${d.bom?.designator ?? "?"} ${titleCase(d.defect_class)}`, selected: result.defects[selected] === d,
  })) : [];
  const images = result?.images;
  const src = !images ? null : assetUrl(images[view]);
  const pass = result?.verdict === "PASS";

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_400px]">
      <section className="glass flex min-w-0 flex-col gap-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label="Board" className="field !w-auto min-w-0 flex-1" value={caseId} onChange={(e) => setCaseId(e.target.value)}>
            {cases.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </select>
          <GenerateButton busy={busy} onClick={inspect} disabled={!caseId}>Analyze board</GenerateButton>
          {(["test", "golden", "xray"] as const).map((v) => (
            <button key={v} type="button" disabled={!images} className={`btn ${view === v ? "btn-outline" : "btn-ghost"}`} onClick={() => setView(v)}>{v === "test" ? "Test" : v === "golden" ? "Golden" : "X-ray"}</button>
          ))}
        </div>
        <div className="min-h-[320px] flex-1 lg:h-[56vh] lg:flex-none">
          <PcbCanvas src={src} boxes={boxes} homography={view === "test" ? result?.registration?.homography : undefined} onPick={setSelected} />
        </div>
        {result && (
          <div className="muted flex flex-wrap gap-x-5 gap-y-1 text-xs">
            <span className="mono">{result.serial}</span>
            <span>{result.latency_ms} ms</span>
            <span>{result.registration.inliers} ORB inliers</span>
            {result.void_report && <span>{result.void_report.designator} void {result.void_report.void_pct}% (limit {result.void_report.limit_pct}%)</span>}
            <span>{result.yolo_active ? "Template + YOLOv11" : "Template stage"}</span>
          </div>
        )}
        <Composer value={draft} onChange={setDraft} onSend={sendText} busy={sending} onPlus={onOpenFeeds} placeholder="Type a rework note, or hold Space to talk…"
          mic={<MicButton on={recording} onToggle={() => (recording ? finishRecording() : startRecording())} hint="Hold Space or tap to record" />} />
        {logged && (
          <div className="glass p-3 text-sm">
            <div className="muted mb-1 text-xs">Saved to rework history{logged.style_llm ? " (formatted by Sarvam)" : ""}</div>
            <pre className="whitespace-pre-wrap font-sans">{logged.styled_text}</pre>
          </div>
        )}
      </section>

      <aside className="flex min-w-0 flex-col gap-4">
        <section className="glass p-4">
          {!result ? <p className="muted text-sm">Results appear here after an inspection.</p> : (
            <>
              <div className="mb-3 flex items-center gap-2 text-lg font-semibold">
                {pass ? <CheckCircle2 color="var(--good)" /> : <XCircle color="var(--bad)" />}{pass ? "Board passed" : `${result.defects.length} defect${result.defects.length > 1 ? "s" : ""} found`}
              </div>
              {result.defects.length > 1 && result.defects.map((d: any, i: number) => (
                <button key={i} type="button" className={`btn mb-2 mr-2 ${i === selected ? "btn-outline" : "btn-ghost"}`} onClick={() => setSelected(i)}>{d.bom?.designator ?? `#${i + 1}`}</button>
              ))}
              {result.defects[selected] && (
                <>
                  <h3 className="font-semibold">{titleCase(result.defects[selected].defect_class)}{result.defects[selected].bom ? ` on ${result.defects[selected].bom.designator}` : ""}</h3>
                  {result.defects[selected].bom && (
                    <p className="muted mono mt-1 text-xs">
                      {result.defects[selected].bom.package}
                      {result.defects[selected].bom.pins.length > 0 && ` · pins ${result.defects[selected].bom.pins.join(", ")}`}
                      {result.defects[selected].bom.nets.length > 0 && ` · ${result.defects[selected].bom.nets.join(", ")}`}
                    </p>
                  )}
                </>
              )}
              {diagnosis && (
                <div className="mt-3 space-y-3">
                  <div className="flex items-center justify-between text-xs"><span className="muted">Upstream root cause</span><span className="muted">{diagnosis.source === "llm" ? "Ranked by Sarvam" : "Rule table"}</span></div>
                  {diagnosis.hypotheses.map((h: any) => (
                    <div key={h.fault}>
                      <div className="flex justify-between gap-2 text-sm font-medium"><span>{h.fault}</span><span className="mono">{Math.round(h.confidence * 100)}%</span></div>
                      <p className="muted text-xs">{h.process_stage}: {h.corrective_action}</p>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </section>

        <section className="glass p-4">
          <label className="muted mb-1 block text-xs" htmlFor="language">Operator language</label>
          <select id="language" className="field" value={language} onChange={(e) => setLanguage(e.target.value)}>
            {LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.name} · {l.native}</option>)}
          </select>
          <label className="muted mt-2 flex items-center gap-2 text-xs">
            <input type="checkbox" checked={codeMixed} onChange={(e) => setCodeMixed(e.target.checked)} /> Keep technical words in English where supported
          </label>
          <p className="mt-3 min-h-16 text-base leading-relaxed" lang={language.split("-")[0]}>{translated || <span className="muted text-sm">{instruction ? "Translating…" : "Rework steps appear here."}</span>}</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" className="btn btn-primary" disabled={!translated || speaking} onClick={play}><Volume2 size={15} />{speaking ? "Playing" : "Play steps"}</button>
            <button type="button" className="btn btn-ghost icon-btn" aria-label="Copy steps" title="Copy steps" disabled={!translated} onClick={() => navigator.clipboard.writeText(translated)}><Copy size={15} /></button>
          </div>
          {speech?.note && <p className="muted mt-2 text-xs">{speech.note}</p>}
        </section>
        <div className="flex justify-end">
          <QuadMenu onExport={exportReport} onShare={() => navigator.clipboard.writeText(location.href).then(() => notify("Link copied"))} onSettings={onOpenFeeds} onDelete={() => { setResult(null); setLogged(null); }} />
        </div>
      </aside>
    </div>
  );
}
