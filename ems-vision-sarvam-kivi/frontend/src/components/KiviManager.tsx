"use client";
import { BookOpen, ChevronDown, History, Mic, Palette, Plus, Trash2, Zap } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { LANGUAGES } from "@/config/languages";
import { api } from "@/lib/api";
import { useRecorder } from "@/lib/useRecorder";
import { MicButton } from "./ui";

type Section = "record" | "history" | "dictionary" | "shortcuts" | "styles";
const NAV: [Section, string, React.ReactNode][] = [
  ["record", "Record", <Mic size={15} key="r" />], ["history", "History", <History size={15} key="h" />], ["dictionary", "Dictionary", <BookOpen size={15} key="d" />],
  ["shortcuts", "Shortcuts", <Zap size={15} key="s" />], ["styles", "Styles", <Palette size={15} key="t" />],
];

function Arrow() {
  return <svg width="52" height="30" viewBox="0 0 52 30" fill="none" aria-hidden className="flex-none"><path d="M3 5C14 27 34 27 46 11" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" /><path d="M38 10l8 1 1-8" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

export function KiviManager({ notify }: { notify: (m: string) => void }) {
  const [section, setSection] = useState<Section>("dictionary");
  const [entries, setEntries] = useState<any[]>([]);
  const [shortcuts, setShortcuts] = useState<any[]>([]);
  const [styles, setStyles] = useState<any[]>([]);
  const [history, setHistory] = useState<any[]>([]);
  const [teachOpen, setTeachOpen] = useState(false);
  const [term, setTerm] = useState({ canonical_term: "", description: "", also: "", add_to_keyterms: true });
  const [shortcut, setShortcut] = useState({ trigger: "", expansion: "" });
  const [language, setLanguage] = useState("hi-IN");
  const [mode, setMode] = useState("codemix");
  const [styleId, setStyleId] = useState("rework-operator-log");
  const [output, setOutput] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const { recording, start, stop } = useRecorder();

  const load = useCallback(() => {
    api("/api/kivi/dictionary").then((d) => setEntries(d.entries)).catch((e) => notify(e.message));
    api("/api/kivi/shortcuts").then(setShortcuts).catch(() => {});
    api("/api/kivi/styles").then(setStyles).catch(() => {});
    api("/api/kivi/history").then(setHistory).catch(() => {});
  }, [notify]);
  useEffect(load, [load]);

  const toggleRecord = async () => {
    if (!recording) return start().catch(() => notify("Microphone permission was refused"));
    const blob = await stop();
    if (!blob) return;
    setBusy(true);
    const form = new FormData();
    form.append("audio", blob, "speech.webm");
    form.append("language", language);
    form.append("mode", mode);
    form.append("style_id", styleId);
    try {
      setOutput(await api("/api/kivi/transcribe", form));
      load();
    } catch (e: any) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  };

  const teach = async () => {
    await api("/api/kivi/dictionary", { canonical_term: term.canonical_term, description: term.description, add_to_keyterms: term.add_to_keyterms,
      spoken_variants: term.also.split(",").map((s) => s.trim()).filter(Boolean) });
    setTerm({ canonical_term: "", description: "", also: "", add_to_keyterms: true });
    setTeachOpen(false);
    load();
  };

  const addShortcut = async () => {
    await api("/api/kivi/shortcuts", shortcut);
    setShortcut({ trigger: "", expansion: "" });
    load();
  };

  const remove = (kind: string, id: string) => api(`/api/kivi/${kind}/${id}`, undefined, "DELETE").then(load).catch((e) => notify(e.message));
  const preview = entries[0];

  return (
    <div className="kivi grid gap-4 rounded-3xl p-4 md:grid-cols-[180px_1fr]">
      <nav className="flex gap-1 overflow-x-auto md:flex-col" aria-label="Kivi sections">
        {NAV.map(([id, label, icon]) => (
          <button key={id} type="button" aria-current={section === id} className={`btn justify-start ${section === id ? "btn-outline" : "btn-ghost"}`} onClick={() => setSection(id)}>{icon}{label}</button>
        ))}
      </nav>

      <div className="min-w-0">
        {section === "dictionary" && (
          <>
            <h2 className="serif text-4xl">dictionary</h2>
            <div className="glass mt-4 p-5">
              <h3 className="serif text-xl">words kivi never misspells</h3>
              {preview && (
                <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
                  <div><div className="muted text-xs">you say</div>“{preview.spoken_variants.at(-1)}”</div><Arrow />
                  <div><div className="muted text-xs">kivi writes</div><span style={{ color: "var(--accent)" }}>{preview.canonical_term}</span></div>
                </div>
              )}
            </div>
            <div className="glass mt-3 p-4">
              <button type="button" aria-expanded={teachOpen} className="flex w-full items-center justify-between text-sm font-medium" onClick={() => setTeachOpen(!teachOpen)}>
                <span className="flex items-center gap-2"><Plus size={15} />teach kivi a term</span><ChevronDown size={15} className={teachOpen ? "rotate-180 transition" : "transition"} />
              </button>
              {teachOpen && (
                <div className="mt-3 flex flex-col gap-2">
                  <input className="field" aria-label="Term" placeholder="kivi writes, e.g. QFP-100" value={term.canonical_term} onChange={(e) => setTerm({ ...term, canonical_term: e.target.value })} />
                  <input className="field" aria-label="Description" placeholder="description" value={term.description} onChange={(e) => setTerm({ ...term, description: e.target.value })} />
                  <input className="field" aria-label="Also heard as" placeholder="also heard as (separate with commas)" value={term.also} onChange={(e) => setTerm({ ...term, also: e.target.value })} />
                  <label className="muted flex items-center gap-2 text-xs"><input type="checkbox" checked={term.add_to_keyterms} onChange={(e) => setTerm({ ...term, add_to_keyterms: e.target.checked })} />Send to Saaras as a keyterm</label>
                  <button type="button" className="btn btn-primary self-end" disabled={!term.canonical_term.trim()} onClick={() => teach().catch((e) => notify(e.message))}>Save term</button>
                </div>
              )}
            </div>
            <ul className="mt-3 grid gap-2 md:grid-cols-2">
              {entries.map((e) => (
                <li key={e.id} className="glass flex items-start gap-2 p-3">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">{e.canonical_term}</div>
                    <div className="muted text-xs">{e.description}</div>
                    <div className="muted mt-1 truncate text-xs" title={e.spoken_variants.join(", ")}>also heard as: {e.spoken_variants.join(", ")}</div>
                  </div>
                  <button type="button" className="btn btn-ghost icon-btn" aria-label={`Delete ${e.canonical_term}`} onClick={() => remove("dictionary", e.id)}><Trash2 size={14} /></button>
                </li>
              ))}
            </ul>
          </>
        )}

        {section === "record" && (
          <>
            <h2 className="serif text-4xl">record</h2>
            <div className="glass mt-4 grid gap-2 p-4 sm:grid-cols-3">
              <select className="field" aria-label="Language" value={language} onChange={(e) => setLanguage(e.target.value)}>{LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.name} · {l.native}</option>)}</select>
              <select className="field" aria-label="Speech mode" value={mode} onChange={(e) => setMode(e.target.value)}>{["transcribe", "translate", "verbatim", "translit", "codemix"].map((m) => <option key={m}>{m}</option>)}</select>
              <select className="field" aria-label="Style" value={styleId} onChange={(e) => setStyleId(e.target.value)}>{styles.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
            </div>
            <div className="mt-8 flex flex-col items-center gap-3"><MicButton on={recording} onToggle={toggleRecord} hint="Tap to start or stop" /><p className="muted text-sm">{busy ? "Working…" : recording ? "Listening. Tap to finish." : "Tap to dictate"}</p></div>
            {output && (
              <dl className="glass mt-6 space-y-3 p-4 text-sm">
                <div><dt className="muted text-xs">Heard</dt><dd>{output.raw_transcript}</dd></div>
                <div><dt className="muted text-xs">After dictionary</dt><dd>{output.dictionary_text}</dd></div>
                <div><dt className="muted text-xs">Final</dt><dd className="whitespace-pre-wrap">{output.styled_text}</dd></div>
              </dl>
            )}
          </>
        )}

        {section === "history" && (
          <>
            <h2 className="serif text-4xl">history</h2>
            {history.length === 0 && <p className="muted mt-4 text-sm">Nothing recorded yet.</p>}
            <ul className="mt-4 space-y-2">{history.map((h) => (
              <li key={h.id} className="glass p-3 text-sm"><div className="muted mb-1 text-xs">{new Date(h.created_at).toLocaleString()} · {h.serial ?? "no board"} · {h.style_id}</div><div className="whitespace-pre-wrap">{h.styled_text}</div></li>
            ))}</ul>
          </>
        )}

        {section === "shortcuts" && (
          <>
            <h2 className="serif text-4xl">shortcuts</h2>
            <div className="glass mt-4 flex flex-col gap-2 p-4">
              <input className="field" aria-label="Trigger" placeholder="say this, e.g. log wick used" value={shortcut.trigger} onChange={(e) => setShortcut({ ...shortcut, trigger: e.target.value })} />
              <textarea className="field" aria-label="Expansion" rows={2} placeholder="kivi writes this" value={shortcut.expansion} onChange={(e) => setShortcut({ ...shortcut, expansion: e.target.value })} />
              <button type="button" className="btn btn-primary self-end" disabled={!shortcut.trigger.trim() || !shortcut.expansion.trim()} onClick={() => addShortcut().catch((e) => notify(e.message))}>Add shortcut</button>
            </div>
            <ul className="mt-3 space-y-2">{shortcuts.map((s) => (
              <li key={s.id} className="glass flex items-start gap-2 p-3 text-sm">
                <div className="min-w-0 flex-1"><div style={{ color: "var(--accent)" }}>“{s.trigger}”</div><div className="muted text-xs">{s.expansion}</div></div>
                <button type="button" className="btn btn-ghost icon-btn" aria-label={`Delete ${s.trigger}`} onClick={() => remove("shortcuts", s.id)}><Trash2 size={14} /></button>
              </li>
            ))}</ul>
          </>
        )}

        {section === "styles" && (
          <>
            <h2 className="serif text-4xl">styles</h2>
            <ul className="mt-4 grid gap-3 md:grid-cols-3">{styles.map((s) => (
              <li key={s.id} className="glass p-4 text-sm"><div className="serif text-lg">{s.name}</div><div className="text-xs" style={{ color: "var(--accent)" }}>{s.persona}</div><p className="muted mt-2 text-xs">{s.instructions}</p></li>
            ))}</ul>
          </>
        )}
      </div>
    </div>
  );
}
