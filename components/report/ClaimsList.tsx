"use client";

import { useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ChevronDown, CircleCheck, CircleHelp, CircleX, Sparkles } from "lucide-react";
import type { Claim, ClaimStatus, Source } from "@/lib/report/reportTypes";
import InlineText from "./InlineText";

type Filter = "all" | "supported" | "partial" | "false";

function statusMeta(status: ClaimStatus): { label: string; className: string; Icon: typeof CircleCheck } {
  if (status === "supported") {
    return { label: "Supported", className: "bg-verdict-mint text-verdict-forest dark:bg-verdict-forest/25", Icon: CircleCheck };
  }
  if (status === "partial") {
    return { label: "Partially supported", className: "bg-verdict-sand text-verdict-amber dark:bg-verdict-amber/20", Icon: CircleHelp };
  }
  if (status === "exceeded") {
    return { label: "Exceeded", className: "bg-blue-100 text-verdict-blue dark:bg-verdict-blue/20", Icon: Sparkles };
  }
  return { label: "Unsupported", className: "bg-verdict-rose text-verdict-red dark:bg-verdict-red/20", Icon: CircleX };
}

export default function ClaimsList({
  claims,
  sources,
  onCitation,
}: {
  claims: Claim[];
  sources: Source[];
  onCitation?: (number: number) => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [open, setOpen] = useState<number | null>(0);
  const reduceMotion = useReducedMotion();
  const counts = {
    supported: claims.filter((claim) => claim.status === "supported").length,
    partial: claims.filter((claim) => claim.status === "partial").length,
    false: claims.filter((claim) => claim.status === "unsupported" || claim.status === "exceeded").length,
  };
  const filters: Array<[Filter, string, number]> = [
    ["all", "All claims", claims.length],
    ["supported", "Supported", counts.supported],
    ["partial", "Partial", counts.partial],
    ["false", "False / exceeded", counts.false],
  ];
  const visible = claims.filter((claim) => {
    if (filter === "all") return true;
    if (filter === "false") return claim.status === "unsupported" || claim.status === "exceeded";
    return claim.status === filter;
  });

  return (
    <div>
      <div className="mb-5 flex flex-wrap gap-2" role="group" aria-label="Filter claims by verdict">
        {filters.map(([id, label, count]) => (
          <button
            key={id}
            type="button"
            onClick={() => setFilter(id)}
            aria-pressed={filter === id}
            className={`rounded-full border px-3.5 py-2 text-sm transition-colors duration-180 ${
              filter === id
                ? "border-verdict-ink bg-verdict-ink text-white dark:border-verdict-forest dark:bg-verdict-forest"
                : "border-verdict-line bg-verdict-card text-verdict-muted hover:text-verdict-ink dark:bg-white/5 dark:hover:text-verdict-cream"
            }`}
          >
            {label} <span className="font-mono text-xs opacity-70">{count}</span>
          </button>
        ))}
      </div>
      <div className="space-y-3">
        {visible.length === 0 && (
          <p className="rounded-2xl border border-verdict-line bg-verdict-card p-6 text-center text-sm text-verdict-muted">
            No claims match this filter.
          </p>
        )}
        {visible.map((claim) => {
          const originalIndex = claims.indexOf(claim);
          const meta = statusMeta(claim.status);
          const expanded = open === originalIndex;
          return (
            <div
              key={originalIndex}
              className="overflow-hidden rounded-2xl border border-verdict-line bg-verdict-card transition-shadow duration-180 hover:shadow-card"
            >
              <button
                type="button"
                onClick={() => setOpen(expanded ? null : originalIndex)}
                aria-expanded={expanded}
                className="flex w-full items-start justify-between gap-4 p-4 text-left sm:p-5"
              >
                <span className="min-w-0 flex-1">
                  <span className={`mb-2 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider ${meta.className}`}>
                    <meta.Icon size={12} aria-hidden="true" /> {meta.label}
                  </span>
                  <span className="block text-[15px] font-medium leading-snug text-verdict-ink dark:text-verdict-cream">
                    <InlineText text={claim.claim || claim.verdict || "Claim"} sources={sources} onCitation={onCitation} />
                  </span>
                </span>
                <ChevronDown
                  size={18}
                  className={`mt-1 shrink-0 text-verdict-muted transition-transform duration-180 ${expanded ? "rotate-180" : ""}`}
                  aria-hidden="true"
                />
              </button>
              <AnimatePresence initial={false}>
                {expanded && (
                  <motion.div
                    initial={reduceMotion ? false : { opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={reduceMotion ? undefined : { opacity: 0, height: 0 }}
                    transition={{ duration: reduceMotion ? 0 : 0.22, ease: "easeOut" }}
                  >
                    <div className="border-t border-verdict-line px-4 py-4 sm:px-5">
                      <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-verdict-muted">Evidence</p>
                      <p className="mt-1.5 text-sm leading-relaxed text-verdict-muted">
                        <InlineText text={claim.evidence || "No evidence detail was provided."} sources={sources} onCitation={onCitation} />
                      </p>
                      {claim.verdict && (
                        <p className="mt-3 text-sm font-medium text-verdict-ink dark:text-verdict-cream">
                          Verdict: {claim.verdict}
                        </p>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </div>
  );
}
