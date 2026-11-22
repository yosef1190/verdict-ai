"use client";

import { Check, Copy, Download, FileText, RefreshCw, Share2 } from "lucide-react";
import type { TextSection, VerdictSummary } from "@/lib/report/reportTypes";

export default function FinalRecommendation({
  final,
  verdict,
  copied,
  onShare,
  onCopy,
  onDownload,
  onPdf,
  onNewResearch,
}: {
  final: TextSection;
  verdict?: VerdictSummary;
  copied: "" | "ok" | "fail";
  onShare: () => void;
  onCopy: () => void;
  onDownload: () => void;
  onPdf: () => void;
  onNewResearch: () => void;
}) {
  return (
    <div className="relative overflow-hidden rounded-2xl bg-verdict-ink p-6 text-white shadow-lift sm:p-9 dark:bg-verdict-mint/10 dark:text-verdict-cream">
      <div className="absolute -right-20 -top-24 h-64 w-64 rounded-full bg-verdict-forest/30 blur-3xl" aria-hidden="true" />
      <div className="relative">
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-white/55 dark:text-verdict-muted">The bottom line</p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <h3 className="font-serif text-[clamp(30px,4vw,48px)] leading-tight">Final recommendation</h3>
          {verdict && (
            <span className="inline-flex items-center gap-2 rounded-full bg-verdict-forest px-3 py-1.5 text-sm font-medium text-white">
              <Check size={14} aria-hidden="true" /> {verdict.recommendation}
              {verdict.score != null && ` · ${verdict.score}/100`}
            </span>
          )}
        </div>
        {final.text && (
          <p className="mt-4 max-w-3xl text-lg font-medium leading-relaxed text-white/90 dark:text-verdict-cream/90 sm:text-xl">
            {final.text}
          </p>
        )}
        {final.bullets.length > 0 && (
          <ul className="mt-4 grid gap-2 sm:grid-cols-2">
            {final.bullets.map((item, index) => (
              <li key={index} className="flex gap-2 text-sm text-white/70 dark:text-verdict-muted">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-verdict-gold" aria-hidden="true" />
                {item}
              </li>
            ))}
          </ul>
        )}
        <div className="rv-print-hide mt-7 flex flex-wrap gap-2">
          <button type="button" onClick={onShare} className="btn light sm"><Share2 size={15} aria-hidden="true" /> Share</button>
          <button type="button" onClick={onCopy} className="btn outline sm">
            {copied === "ok" ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}
            {copied === "ok" ? "Copied" : copied === "fail" ? "Copy failed" : "Copy Markdown"}
          </button>
          <button type="button" onClick={onDownload} className="btn outline sm"><Download size={15} aria-hidden="true" /> Download .md</button>
          <button type="button" onClick={onPdf} className="btn outline sm"><FileText size={15} aria-hidden="true" /> Download PDF</button>
          <button type="button" onClick={onNewResearch} className="btn soft sm"><RefreshCw size={15} aria-hidden="true" /> New research</button>
        </div>
      </div>
    </div>
  );
}
