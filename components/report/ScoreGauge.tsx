"use client";

import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { AlertTriangle, Link2, Quote, TrendingDown } from "lucide-react";
import type { Confidence, QuickStats } from "@/lib/report/reportTypes";

const RADIUS = 62;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

function scoreColor(score: number): string {
  if (score < 40) return "#B83A2E";
  if (score < 60) return "#D97706";
  if (score < 75) return "#D6A23A";
  return "#2F6B4A";
}

function badgeClass(recommendation: string): string {
  if (/avoid/i.test(recommendation)) return "bg-verdict-rose text-verdict-red dark:bg-verdict-red/20 dark:text-verdict-red";
  if (/recommended/i.test(recommendation)) return "bg-verdict-mint text-verdict-forest dark:bg-verdict-forest/25 dark:text-verdict-forest";
  return "bg-verdict-sand text-verdict-amber dark:bg-verdict-amber/20 dark:text-verdict-amber";
}

export default function ScoreGauge({
  score,
  recommendation,
  confidence,
  summary,
  quickStats,
}: {
  score: number | null;
  recommendation: string;
  confidence: Confidence | null;
  summary: string;
  quickStats: QuickStats;
}) {
  const reduceMotion = useReducedMotion();
  const [displayScore, setDisplayScore] = useState(0);
  const value = score ?? 0;
  const color = scoreColor(value);

  useEffect(() => {
    if (reduceMotion) {
      setDisplayScore(value);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / 900);
      setDisplayScore(Math.round(value * (1 - Math.pow(1 - progress, 3))));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, reduceMotion]);

  const confidenceLevel = confidence === "High" ? 3 : confidence === "Medium" ? 2 : confidence === "Low" ? 1 : 0;

  return (
    <div className="relative overflow-hidden rounded-2xl border border-verdict-line bg-verdict-card shadow-card dark:border-verdict-line dark:bg-verdict-card">
      <div className="grid gap-8 p-6 sm:p-8 lg:grid-cols-[220px_1fr] lg:items-center lg:gap-10 lg:p-10">
        <div className="flex flex-col items-center gap-4">
          <div className="relative h-44 w-44" role="img" aria-label={`Verdict score ${value} out of 100`}>
            <svg className="h-full w-full -rotate-90" viewBox="0 0 160 160" aria-hidden="true">
              <circle cx="80" cy="80" r={RADIUS} fill="none" stroke="currentColor" strokeWidth="12" className="text-verdict-line dark:text-white/10" />
              <motion.circle
                cx="80"
                cy="80"
                r={RADIUS}
                fill="none"
                stroke={color}
                strokeWidth="12"
                strokeLinecap="round"
                strokeDasharray={CIRCUMFERENCE}
                initial={reduceMotion ? false : { strokeDashoffset: CIRCUMFERENCE }}
                animate={{ strokeDashoffset: CIRCUMFERENCE * (1 - value / 100) }}
                transition={{ duration: reduceMotion ? 0 : 0.9, ease: [0.22, 1, 0.36, 1] }}
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="font-serif text-6xl leading-none text-verdict-ink dark:text-verdict-cream">{displayScore}</span>
              <span className="mt-1 font-mono text-[11px] uppercase tracking-[0.18em] text-verdict-muted">/ 100</span>
            </div>
          </div>
          <span className={`inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-sm font-medium ${badgeClass(recommendation)}`}>
            <span className="h-2 w-2 rounded-full bg-current" aria-hidden="true" />
            {recommendation}
          </span>
        </div>

        <div className="min-w-0">
          <p className="mb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-verdict-muted">Verdict at a glance</p>
          <p className="text-[clamp(19px,2.4vw,28px)] font-medium leading-snug text-verdict-ink dark:text-verdict-cream">
            {summary || "The evidence snapshot is still being assembled."}
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-3">
            <div className="flex items-center gap-2">
              <span className="text-sm text-verdict-muted">Confidence</span>
              <div className="flex gap-1" role="img" aria-label={`${confidence ?? "Unknown"} confidence`}>
                {[1, 2, 3].map((segment) => (
                  <span
                    key={segment}
                    className={`h-1.5 w-8 rounded-full ${segment <= confidenceLevel ? "bg-verdict-forest" : "bg-verdict-line dark:bg-white/15"}`}
                  />
                ))}
              </div>
              <span className="font-mono text-xs text-verdict-ink dark:text-verdict-cream">{confidence ?? "—"}</span>
            </div>
            {quickStats.price && (
              <span className="inline-flex items-center gap-2 rounded-xl border border-verdict-line bg-verdict-cream px-3 py-2 text-sm dark:bg-white/5">
                <span className="font-medium text-verdict-ink dark:text-verdict-cream">{quickStats.price}</span>
                <span className="text-verdict-muted">price</span>
              </span>
            )}
            {quickStats.sourcesAnalyzed != null && (
              <span className="inline-flex items-center gap-2 rounded-xl border border-verdict-line bg-verdict-cream px-3 py-2 text-sm dark:bg-white/5">
                <Quote size={14} className="text-verdict-forest" aria-hidden="true" />
                <span className="font-medium text-verdict-ink dark:text-verdict-cream">{quickStats.sourcesAnalyzed}</span>
                <span className="text-verdict-muted">sources</span>
              </span>
            )}
            {quickStats.biggestRedFlag && (
              <span className="inline-flex max-w-full items-center gap-2 rounded-xl border border-verdict-rose bg-verdict-rose/60 px-3 py-2 text-sm text-verdict-red dark:bg-verdict-red/15">
                <AlertTriangle size={14} aria-hidden="true" />
                <span className="truncate">{quickStats.biggestRedFlag}</span>
              </span>
            )}
            {!quickStats.price && !quickStats.sourcesAnalyzed && !quickStats.biggestRedFlag && (
              <span className="inline-flex items-center gap-2 text-sm text-verdict-muted">
                <Link2 size={14} aria-hidden="true" /> No quick stats detected in this report.
              </span>
            )}
          </div>
          <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 font-mono text-xs text-verdict-muted">
            {["Reading product page", "Finding reviews", "Checking claims", "Scoring"].map((step, index) => (
              <span key={step} className="inline-flex items-center gap-2">
                <span className="text-verdict-forest">{String(index + 1).padStart(2, "0")}</span>
                {step}
                {index < 3 && <TrendingDown size={11} className="rotate-[-90deg] text-verdict-line" aria-hidden="true" />}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
