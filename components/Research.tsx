"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { getAccessToken } from "@/lib/supabase";
import ReportView from "@/components/report/ReportView";
import ReportSkeleton from "@/components/report/ReportSkeleton";

type Status = { version: string; engines: string[]; ai_ready: boolean; scrape_ready: boolean };
type Report = { title: string; markdown: string; html: string };
type Step = { text: string; done: boolean };
type Mode = "light" | "medium" | "deep";
type Wallet = { subscription_credits: number; purchased_credits: number; total: number; free_light_available: boolean };

const MODES: { id: Mode; name: string; desc: string; time: string; queries: string }[] = [
  { id: "light", name: "Light", desc: "Identity check, key reviews, main complaints, basic credibility.", time: "under 5 min", queries: "3 searches" },
  { id: "medium", name: "Medium", desc: "Everything in Light, plus community discussion and claims vs reality.", time: "under 10 min", queries: "4 searches" },
  { id: "deep", name: "Deep", desc: "Everything in Medium, plus safety, warranty, testing and alternatives.", time: "under 15 min", queries: "5 searches" },
];

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function api(path: string, init: RequestInit = {}) {
  const token = await getAccessToken();
  const res = await fetch(path, {
    ...init,
    headers: { ...(init.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  const body = await res.json().catch(() => ({}));
  return { res, body };
}

export default function Research() {
  const [url, setUrl] = useState("");
  const [keywords, setKeywords] = useState("");
  const [focus, setFocus] = useState("");
  const [engine, setEngine] = useState("yahoo");
  const [render, setRender] = useState(false);
  const [noAi, setNoAi] = useState(false);
  const [mode, setMode] = useState<Mode>("light");
  const [status, setStatus] = useState<Status | null>(null);
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [costs, setCosts] = useState<Record<string, number>>({ light: 1, medium: 2, deep: 3 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [needsCredits, setNeedsCredits] = useState(false);
  const [steps, setSteps] = useState<Step[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [copied, setCopied] = useState<"" | "ok" | "fail">("");
  const alive = useRef(true);
  const reportRef = useRef<HTMLDivElement>(null);
  const urlRef = useRef<HTMLInputElement>(null);

  const refreshWallet = async () => {
    const { res, body } = await api("/api/wallet");
    if (res.ok) { setWallet(body); if (body.mode_costs) setCosts(body.mode_costs); }
  };

  useEffect(() => {
    alive.current = true;
    // A link pasted on the landing page before logging in
    try {
      const pending = sessionStorage.getItem("verdict:pending-url");
      if (pending) { setUrl(pending); sessionStorage.removeItem("verdict:pending-url"); }
    } catch {}
    api("/api/research/status").then(({ res, body }) => {
      if (alive.current && res.ok) setStatus(body);
    });
    refreshWallet();
    return () => { alive.current = false; };
  }, []);

  useEffect(() => {
    if (report) reportRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [report]);

  const addStep = (text: string) =>
    setSteps((s) => [...s.map((x) => ({ ...x, done: true })), { text, done: false }]);

  async function poll(id: string): Promise<Report> {
    let seen = 0, failures = 0;
    for (;;) {
      await sleep(1200);
      if (!alive.current) throw new Error("cancelled");
      const { res, body } = await api(`/api/research/jobs/${id}?since=${seen}`).catch(() => ({ res: null, body: {} as any }));
      if (!res) { if (++failures >= 5) throw new Error("Lost connection to the server."); continue; }
      if (res.status === 404) throw new Error("This job expired. Please run it again.");
      if (res.status === 401) throw new Error("Your session expired. Please log in again.");
      if (!res.ok && res.status >= 500) { if (++failures >= 5) throw new Error(body.error || "Lost connection to the server."); continue; }
      failures = 0;
      (body.steps || []).forEach((t: string) => addStep(t));
      seen = body.step_count ?? seen;
      if (body.status === "done") return body;
      if (body.status === "error") throw new Error(body.error || "Research failed.");
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    const cost = costs[mode] ?? 1;
    const available = wallet?.total ?? 0;
    const freeOk = mode === "light" && wallet?.free_light_available;
    if (!freeOk && available < cost) {
      setError("");
      setNeedsCredits(true);
      return;
    }
    setError(""); setNeedsCredits(false); setReport(null); setSteps([]); setBusy(true);
    addStep("Starting");
    try {
      const { res, body } = await api("/api/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: url, keywords, focus, engine, render, no_ai: noAi, mode }),
      });
      if (res.status === 402) {
        setNeedsCredits(true);
        throw new Error(body.error || "You don't have enough credits for this mode.");
      }
      if (!res.ok) throw new Error(body.error || "Could not start research.");
      refreshWallet();
      const data = await poll(body.id);
      if (!alive.current) return;
      setSteps((s) => s.map((x) => ({ ...x, done: true })));
      setReport(data);
      refreshWallet();
    } catch (err: any) {
      if (!alive.current) return;
      setSteps([]);
      setError(err?.message || "Something went wrong.");
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  async function copy() {
    try { await navigator.clipboard.writeText(report?.markdown ?? ""); setCopied("ok"); }
    catch { setCopied("fail"); }
    setTimeout(() => setCopied(""), 1500);
  }

  function download() {
    const slug = (report?.title || "report").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "report";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([report?.markdown ?? ""], { type: "text/markdown" }));
    a.download = `${slug}.md`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function again() {
    setReport(null); setSteps([]); setUrl("");
    window.scrollTo({ top: 0, behavior: "smooth" });
    urlRef.current?.focus();
  }

  function deep() {
    setMode("deep");
    setReport(null);
    setSteps([]);
    window.scrollTo({ top: 0, behavior: "smooth" });
    setTimeout(() => urlRef.current?.focus(), 350);
  }

  const engines = status?.engines?.length ? status.engines : ["yahoo"];
  const cost = costs[mode] ?? 1;
  const sub = wallet?.subscription_credits ?? 0;
  const bought = wallet?.purchased_credits ?? 0;
  const total = wallet?.total ?? 0;
  const freeEligible = mode === "light" && !!wallet?.free_light_available;
  const after = freeEligible ? total : Math.max(0, total - cost);
  const blocked = !freeEligible && total < cost;

  return (
    <div className="rs">
      {status && !status.scrape_ready && (
        <div className="rs-banner err">OXYLABS_API_KEY isn’t set on the research server, so scraping won’t work. Add it to backend/.env and restart.</div>
      )}
      {status && status.scrape_ready && !status.ai_ready && (
        <div className="rs-banner warn">No AI key is set on the research server (NVIDIA, Gemini or OpenRouter). Reports will contain extracted text only, without AI summaries.</div>
      )}

      <form className="rs-card" onSubmit={submit} autoComplete="off">
        <p className="mono small" style={{ marginBottom: 10 }}>01 — Choose research depth</p>
        <div className="modes" role="radiogroup" aria-label="Research depth">
          {MODES.map((m) => (
            <button
              key={m.id} type="button" role="radio" aria-checked={mode === m.id}
              className={`mode${mode === m.id ? " on" : ""}`}
              onClick={() => { setMode(m.id); setNeedsCredits(false); }}
              disabled={busy}
            >
              <span className="name">{m.name}<span className="cost">{costs[m.id] ?? 1} cr</span></span>
              <span className="meta">{m.time} · {m.queries}</span>
              <span className="desc">{m.desc}</span>
            </button>
          ))}
        </div>

        <div className="bal">
          <span>Subscription <b>{sub}</b></span><span className="sep">·</span>
          <span>Purchased <b>{bought}</b></span><span className="sep">·</span>
          {freeEligible
            ? <span>This Light run is <b>free</b> (one per account)</span>
            : <span>After this run <b>{after}</b> credit{after === 1 ? "" : "s"}</span>}
          {!freeEligible && (
            <span className={`after${blocked ? " low" : ""}`}>{blocked ? "Need more credits" : "—"}</span>
          )}
          <Link href="/pricing" className="link-btn" style={{ marginLeft: 8 }}>Buy credits</Link>
        </div>

        <p className="mono small" style={{ margin: "22px 0 10px" }}>02 — Paste the product</p>
        <div className="rs-row">
          <label className="input rs-url">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1" /></svg>
            <span className="sr">Product URL</span>
            <input ref={urlRef} type="text" inputMode="url" spellCheck={false} required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Paste a product link…" />
          </label>
          <button className="btn dark" type="submit" disabled={busy || blocked}>
            {busy ? "Researching…" : blocked ? "Not enough credits" : `Get your Verdict · ${freeEligible ? "free" : `${cost} cr`}`}
          </button>
        </div>
        <p className="mono note left">Reads the product page, finds independent reviews and complaints across the web, then scores it from 0 to 100.</p>

        <details className="rs-opts">
          <summary className="mono">Options</summary>
          <div className="rs-grid">
            <label className="rs-field full"><span>Search keywords (optional)</span>
              <input type="text" value={keywords} onChange={(e) => setKeywords(e.target.value)} placeholder="e.g. Sony WH-1000XM5 — leave blank to let the AI choose" /></label>
            <label className="rs-field"><span>Focus (optional)</span>
              <input type="text" value={focus} onChange={(e) => setFocus(e.target.value)} placeholder="e.g. durability, returns, sizing" /></label>
            <label className="rs-field"><span>Search engine</span>
              <select value={engine} onChange={(e) => setEngine(e.target.value)}>
                {engines.map((x) => <option key={x} value={x}>{x[0].toUpperCase() + x.slice(1)}</option>)}
              </select></label>
            <label className="rs-check"><input type="checkbox" checked={render} onChange={(e) => setRender(e.target.checked)} /> Render JavaScript (slower, uses more Oxylabs credits)</label>
            <label className="rs-check"><input type="checkbox" checked={noAi} onChange={(e) => setNoAi(e.target.checked)} /> Extract only, skip AI</label>
          </div>
        </details>
      </form>

      {needsCredits && (
        <div className="rs-banner err" role="alert">
          This {mode} investigation costs {cost} credit{cost === 1 ? "" : "s"}, and you have {total}.{" "}
          <Link href="/pricing" style={{ textDecoration: "underline" }}>Buy credits</Link> or pick a cheaper mode.
        </div>
      )}

      {error && !needsCredits && <div className="rs-banner err" role="alert">{error}</div>}

      {busy && !report && <ReportSkeleton steps={steps.map((step) => step.text)} />}

      {report && (
        <div ref={reportRef}>
          <ReportView
            markdown={report.markdown}
            title={report.title || "Verdict research report"}
            copied={copied}
            onCopy={copy}
            onDownload={download}
            onNewResearch={again}
            onDeep={deep}
          />
        </div>
      )}
    </div>
  );
}
