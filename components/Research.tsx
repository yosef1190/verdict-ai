"use client";
import { useEffect, useRef, useState } from "react";
import { supabase } from "@/lib/supabase";

type Status = { version: string; engines: string[]; ai_ready: boolean; scrape_ready: boolean };
type Report = { title: string; markdown: string; html: string };
type Step = { text: string; done: boolean };

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function api(path: string, init: RequestInit = {}) {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
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
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [steps, setSteps] = useState<Step[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [copied, setCopied] = useState<"" | "ok" | "fail">("");
  const alive = useRef(true);
  const articleRef = useRef<HTMLElement>(null);
  const reportRef = useRef<HTMLElement>(null);
  const urlRef = useRef<HTMLInputElement>(null);

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
    return () => { alive.current = false; };
  }, []);

  // Report HTML is rendered server-side with raw HTML disabled; just harden the links.
  useEffect(() => {
    articleRef.current?.querySelectorAll("a").forEach((a) => {
      a.target = "_blank";
      a.rel = "noopener noreferrer nofollow";
    });
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
    setError(""); setReport(null); setSteps([]); setBusy(true);
    addStep("Starting");
    try {
      const { res, body } = await api("/api/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: url, keywords, focus, engine, render, no_ai: noAi }),
      });
      if (!res.ok) throw new Error(body.error || "Could not start research.");
      const data = await poll(body.id);
      if (!alive.current) return;
      setSteps((s) => s.map((x) => ({ ...x, done: true })));
      setReport(data);
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

  const engines = status?.engines?.length ? status.engines : ["yahoo"];

  return (
    <div className="rs">
      {status && !status.scrape_ready && (
        <div className="rs-banner err">OXYLABS_API_KEY isn’t set on the research server, so scraping won’t work. Add it to backend/.env and restart.</div>
      )}
      {status && status.scrape_ready && !status.ai_ready && (
        <div className="rs-banner warn">No AI key is set on the research server (NVIDIA, Gemini or OpenRouter). Reports will contain extracted text only, without AI summaries.</div>
      )}

      <form className="rs-card" onSubmit={submit} autoComplete="off">
        <div className="rs-row">
          <label className="input rs-url">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1" /></svg>
            <span className="sr">Product URL</span>
            <input ref={urlRef} type="text" inputMode="url" spellCheck={false} required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Paste a product link…" />
          </label>
          <button className="btn dark" type="submit" disabled={busy}>{busy ? "Researching…" : "Get your Verdict"}</button>
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

      {error && <div className="rs-banner err" role="alert">{error}</div>}

      {steps.length > 0 && !report && (
        <section className="rs-card rs-progress" aria-live="polite" aria-label="Progress">
          <ol>{steps.map((s, i) => <li key={i} className={s.done ? "done" : "current"}>{s.text}</li>)}</ol>
        </section>
      )}

      {report && (
        <section className="rs-card" ref={reportRef}>
          <div className="rs-bar">
            <strong className="serif">{report.title || "Verdict research report"}</strong>
            <div className="rs-actions">
              <button className="btn ghost sm" type="button" onClick={copy}>{copied === "ok" ? "Copied" : copied === "fail" ? "Copy failed" : "Copy Markdown"}</button>
              <button className="btn ghost sm" type="button" onClick={download}>Download .md</button>
              <button className="btn dark sm" type="button" onClick={again}>New research</button>
            </div>
          </div>
          <article className="rs-report" ref={articleRef} dangerouslySetInnerHTML={{ __html: report.html }} />
        </section>
      )}
    </div>
  );
}
