"use client";

import { motion, useReducedMotion } from "framer-motion";
import { Check, LoaderCircle } from "lucide-react";

const CANONICAL = ["Reading product page", "Finding reviews", "Checking claims", "Scoring"];

function activeIndex(steps: string[]): number {
  const joined = steps.join(" ").toLowerCase();
  if (/score|verdict|recommendation/i.test(joined)) return 3;
  if (/claim|evidence|fact/i.test(joined)) return 2;
  if (/review|discussion|forum|customer/i.test(joined)) return 1;
  return 0;
}

export default function ReportSkeleton({ steps = [] }: { steps?: string[] }) {
  const reduceMotion = useReducedMotion();
  const active = activeIndex(steps);

  return (
    <section className="rv-report-shell space-y-5" aria-busy="true" aria-live="polite" aria-label="Generating report">
      <div className="rounded-2xl border border-verdict-line bg-verdict-card p-6">
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-verdict-muted">Building your verdict</p>
        <ol className="mt-5 flex flex-wrap gap-x-5 gap-y-3">
          {CANONICAL.map((label, index) => {
            const done = index < active;
            const current = index === active;
            return (
              <li key={label} className="flex items-center gap-2 text-sm">
                <span
                  className={`grid h-6 w-6 place-items-center rounded-full font-mono text-[11px] ${
                    done
                      ? "bg-verdict-forest text-white"
                      : current
                        ? "bg-verdict-sand text-verdict-amber"
                        : "bg-verdict-line/60 text-verdict-muted"
                  }`}
                >
                  {done ? <Check size={13} aria-hidden="true" /> : current ? <LoaderCircle size={13} className="animate-spin" aria-hidden="true" /> : index + 1}
                </span>
                <span className={done || current ? "text-verdict-ink dark:text-verdict-cream" : "text-verdict-muted"}>{label}</span>
              </li>
            );
          })}
        </ol>
        {steps.length > 0 && (
          <p className="mt-4 truncate font-mono text-xs text-verdict-muted">{steps[steps.length - 1]}</p>
        )}
      </div>
      {[0, 1, 2].map((index) => (
        <motion.div
          key={index}
          initial={reduceMotion ? false : { opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: reduceMotion ? 0 : 0.35, delay: reduceMotion ? 0 : index * 0.08 }}
          className="rounded-2xl border border-verdict-line bg-verdict-card p-6"
        >
          <div className="h-3 w-24 rounded-full bg-verdict-line/70" />
          <div className="mt-4 h-5 w-2/5 rounded-full bg-verdict-line/60" />
          <div className="mt-5 space-y-2.5">
            <div className="h-3 w-full rounded-full bg-verdict-line/40" />
            <div className="h-3 w-11/12 rounded-full bg-verdict-line/40" />
            <div className="h-3 w-3/4 rounded-full bg-verdict-line/40" />
          </div>
        </motion.div>
      ))}
    </section>
  );
}
