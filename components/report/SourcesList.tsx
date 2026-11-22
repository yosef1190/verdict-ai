"use client";

import { useState } from "react";
import { ExternalLink, Globe2, ShieldCheck } from "lucide-react";
import type { Source } from "@/lib/report/reportTypes";

function SourceRow({ source, highlighted }: { source: Source; highlighted: boolean }) {
  const [iconFailed, setIconFailed] = useState(false);
  return (
    <li
      id={`source-${source.number}`}
      className={`scroll-mt-32 rounded-2xl border p-4 transition-all duration-200 ${
        highlighted
          ? "border-verdict-gold bg-verdict-sand/70 shadow-lift dark:bg-verdict-amber/15"
          : "border-verdict-line bg-verdict-card hover:border-verdict-forest/40 hover:shadow-card"
      }`}
    >
      <a href={source.url} target="_blank" rel="noopener noreferrer nofollow" className="flex gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center overflow-hidden rounded-xl border border-verdict-line bg-white">
          {!iconFailed && source.url ? (
            <img
              src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(source.domain)}&sz=32`}
              alt=""
              width={20}
              height={20}
              onError={() => setIconFailed(true)}
            />
          ) : (
            <Globe2 size={16} className="text-verdict-muted" aria-hidden="true" />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-start gap-2">
            <span className="font-mono text-xs text-verdict-forest">[{source.number}]</span>
            <span className="line-clamp-2 text-sm font-medium leading-snug text-verdict-ink dark:text-verdict-cream">{source.title}</span>
            <ExternalLink size={13} className="ml-auto mt-0.5 shrink-0 text-verdict-muted" aria-hidden="true" />
          </span>
          <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-verdict-muted">
            <span>{source.domain}</span>
            {source.quality && (
              <span className="inline-flex items-center gap-1 rounded-full bg-verdict-mint px-2 py-0.5 text-verdict-forest dark:bg-verdict-forest/20">
                <ShieldCheck size={11} aria-hidden="true" /> {source.quality}
              </span>
            )}
            {source.note && !source.quality && <span className="truncate">{source.note}</span>}
          </span>
        </span>
      </a>
    </li>
  );
}

export default function SourcesList({ sources, highlighted }: { sources: Source[]; highlighted: number | null }) {
  return (
    <ul className="grid gap-3 md:grid-cols-2">
      {sources.map((source) => (
        <SourceRow key={source.number} source={source} highlighted={highlighted === source.number} />
      ))}
    </ul>
  );
}
