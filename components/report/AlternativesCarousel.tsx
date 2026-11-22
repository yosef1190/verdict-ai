"use client";

import { useRef } from "react";
import { ArrowLeft, ArrowRight, BadgeCheck, Tags } from "lucide-react";
import type { Alternative } from "@/lib/report/reportTypes";

export default function AlternativesCarousel({ alternatives }: { alternatives: Alternative[] }) {
  const track = useRef<HTMLDivElement>(null);

  const scroll = (direction: 1 | -1) => {
    track.current?.scrollBy({ left: direction * 320, behavior: "smooth" });
  };

  return (
    <div>
      <div className="mb-3 flex justify-end gap-2">
        <button
          type="button"
          onClick={() => scroll(-1)}
          className="grid h-9 w-9 place-items-center rounded-full border border-verdict-line bg-verdict-card text-verdict-muted transition-colors duration-180 hover:text-verdict-ink dark:bg-white/5 dark:hover:text-verdict-cream"
          aria-label="Previous alternatives"
        >
          <ArrowLeft size={16} aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={() => scroll(1)}
          className="grid h-9 w-9 place-items-center rounded-full border border-verdict-line bg-verdict-card text-verdict-muted transition-colors duration-180 hover:text-verdict-ink dark:bg-white/5 dark:hover:text-verdict-cream"
          aria-label="Next alternatives"
        >
          <ArrowRight size={16} aria-hidden="true" />
        </button>
      </div>
      <div
        ref={track}
        className="rv-scroll flex snap-x snap-mandatory gap-3 overflow-x-auto pb-2"
        aria-label="Alternative products"
      >
        {alternatives.map((alternative, index) => (
          <article
            key={`${alternative.name}-${index}`}
            className="w-[280px] shrink-0 snap-start rounded-2xl border border-verdict-line bg-verdict-card p-5 transition-shadow duration-180 hover:shadow-card sm:w-[320px]"
          >
            <div className="flex items-start justify-between gap-3">
              <h3 className="font-serif text-xl leading-tight text-verdict-ink dark:text-verdict-cream">{alternative.name}</h3>
              {alternative.price && (
                <span className="shrink-0 rounded-lg bg-verdict-mint px-2.5 py-1 font-mono text-sm text-verdict-forest dark:bg-verdict-forest/20">
                  {alternative.price}
                </span>
              )}
            </div>
            <p className="mt-3 min-h-12 text-sm leading-relaxed text-verdict-muted">{alternative.tradeoff}</p>
            {alternative.betterFor && (
              <span className="mt-4 inline-flex items-center gap-1.5 rounded-full border border-verdict-gold/40 bg-verdict-sand/60 px-3 py-1.5 text-xs font-medium text-verdict-amber dark:bg-verdict-amber/15">
                <BadgeCheck size={13} aria-hidden="true" /> Better for {alternative.betterFor}
              </span>
            )}
          </article>
        ))}
      </div>
      <p className="mt-2 flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-verdict-muted">
        <Tags size={12} aria-hidden="true" /> Swipe or use arrows to compare
      </p>
    </div>
  );
}
