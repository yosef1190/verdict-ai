"use client";

import type { Source } from "@/lib/report/reportTypes";

export default function InlineText({
  text,
  sources = [],
  onCitation,
  className = "",
}: {
  text: string;
  sources?: Source[];
  onCitation?: (number: number) => void;
  className?: string;
}) {
  const parts = text.replace(/\*\*/g, "").split(/(\[\d+\])/g);
  return (
    <span className={className}>
      {parts.map((part, index) => {
        const match = part.match(/^\[(\d+)\]$/);
        if (!match || !onCitation) return <span key={index}>{part}</span>;
        const number = Number(match[1]);
        const source = sources.find((item) => item.number === number);
        return (
          <button
            key={index}
            type="button"
            onClick={() => onCitation(number)}
            className="group relative mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-md border border-verdict-line bg-verdict-mint/60 px-1 align-middle font-mono text-[10px] font-medium text-verdict-forest transition-colors duration-180 hover:border-verdict-forest hover:bg-verdict-mint dark:border-verdict-line dark:bg-white/5 dark:text-verdict-forest"
            aria-label={`Go to source ${number}${source ? `: ${source.title}` : ""}`}
          >
            {number}
            {source && (
              <span className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 hidden w-max max-w-56 -translate-x-1/2 rounded-lg bg-verdict-ink px-2.5 py-1.5 text-left text-[11px] font-normal leading-snug text-white shadow-lift group-hover:block group-focus-visible:block dark:bg-verdict-cream dark:text-verdict-ink">
                {source.title}
              </span>
            )}
          </button>
        );
      })}
    </span>
  );
}
