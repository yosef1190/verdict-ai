"use client";

import { useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { AlertTriangle, CheckCircle2, ChevronDown } from "lucide-react";
import type { BulletItem, Source } from "@/lib/report/reportTypes";
import InlineText from "./InlineText";

function severityClass(severity?: string): string {
  if (severity === "Deal-breaker") return "bg-verdict-rose text-verdict-red dark:bg-verdict-red/20";
  if (severity === "Major") return "bg-verdict-sand text-verdict-amber dark:bg-verdict-amber/20";
  return "bg-verdict-line/60 text-verdict-muted";
}

function Item({
  item,
  positive,
  sources,
  onCitation,
}: {
  item: BulletItem;
  positive: boolean;
  sources: Source[];
  onCitation?: (number: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const reduceMotion = useReducedMotion();
  const long = item.description.length > 120;
  const shown = long ? `${item.description.slice(0, 120).trimEnd()}${expanded ? "" : "…"}` : item.description;
  const Icon = positive ? CheckCircle2 : AlertTriangle;

  return (
    <div
      className={`rounded-2xl border p-4 transition-shadow duration-180 hover:shadow-card ${
        positive
          ? "border-verdict-forest/20 bg-verdict-mint/40 dark:bg-verdict-forest/10"
          : "border-verdict-red/20 bg-verdict-rose/50 dark:bg-verdict-red/10"
      }`}
    >
      <div className="flex gap-3">
        <Icon
          size={18}
          className={`mt-0.5 shrink-0 ${positive ? "text-verdict-forest" : "text-verdict-red"}`}
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-medium leading-snug text-verdict-ink dark:text-verdict-cream">
              <InlineText text={item.title} sources={sources} onCitation={onCitation} />
            </p>
            {item.severity && (
              <span className={`rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider ${severityClass(item.severity)}`}>
                {item.severity}
              </span>
            )}
          </div>
          {item.description && (
            <div className="mt-1.5 text-sm leading-relaxed text-verdict-muted">
              <InlineText text={shown} sources={sources} onCitation={onCitation} />
              {long && (
                <AnimatePresence initial={false}>
                  {expanded && (
                    <motion.span
                      initial={reduceMotion ? false : { opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={reduceMotion ? undefined : { opacity: 0, height: 0 }}
                      transition={{ duration: reduceMotion ? 0 : 0.2 }}
                      className="block overflow-hidden"
                    >
                      <InlineText text={item.description.slice(120)} sources={sources} onCitation={onCitation} />
                    </motion.span>
                  )}
                </AnimatePresence>
              )}
            </div>
          )}
          {long && (
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              aria-expanded={expanded}
              className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-verdict-forest transition-opacity duration-180 hover:opacity-70"
            >
              {expanded ? "Read less" : "Read more"}
              <ChevronDown size={13} className={`transition-transform duration-180 ${expanded ? "rotate-180" : ""}`} aria-hidden="true" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ProsCons({
  pros,
  cons,
  sources,
  onCitation,
}: {
  pros: BulletItem[];
  cons: BulletItem[];
  sources: Source[];
  onCitation?: (number: number) => void;
}) {
  if (!pros.length && !cons.length) return null;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {pros.length > 0 && (
        <div>
          <p className="mb-3 flex items-center gap-2 text-sm font-medium text-verdict-forest">
            <CheckCircle2 size={16} aria-hidden="true" /> What looks good
          </p>
          <div className="space-y-3">
            {pros.map((item, index) => (
              <Item key={`pro-${index}`} item={item} positive sources={sources} onCitation={onCitation} />
            ))}
          </div>
        </div>
      )}
      {cons.length > 0 && (
        <div>
          <p className="mb-3 flex items-center gap-2 text-sm font-medium text-verdict-red">
            <AlertTriangle size={16} aria-hidden="true" /> Problems & red flags
          </p>
          <div className="space-y-3">
            {cons.map((item, index) => (
              <Item key={`con-${index}`} item={item} positive={false} sources={sources} onCitation={onCitation} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
