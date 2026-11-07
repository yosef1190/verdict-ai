"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "./AuthProvider";

export default function AnalyzeForm() {
  const { user } = useAuth();
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  return (
    <form className="analyze" onSubmit={(e) => {
      e.preventDefault();
      if (!url.trim()) return setStatus("Paste a product link first.");
      // Carry the link through login; the dashboard pre-fills it.
      try { sessionStorage.setItem("verdict:pending-url", url.trim()); } catch {}
      if (!user) { setStatus("Log in to get your Verdict."); return router.push("/login"); }
      router.push("/dashboard");
    }}>
      <label className="input">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1" /></svg>
        <span className="sr">Product link</span>
        <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Paste a product link…" />
      </label>
      <button className="btn dark" type="submit">Analyze a Product <Arrow /></button>
      <p className="mono note" role="status">{status ?? "No complicated research. Just paste a link."}</p>
    </form>
  );
}
function Arrow() { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>; }
