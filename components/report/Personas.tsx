"use client";

import { Check, UserCheck, UserX, X } from "lucide-react";
import type { PersonaSection, Source } from "@/lib/report/reportTypes";
import InlineText from "./InlineText";

function PersonaCard({
  title,
  section,
  positive,
  sources,
  onCitation,
}: {
  title: string;
  section: PersonaSection;
  positive: boolean;
  sources: Source[];
  onCitation?: (number: number) => void;
}) {
  return (
    <div
      className={`rounded-2xl border p-5 sm:p-6 ${
        positive
          ? "border-verdict-forest/25 bg-verdict-mint/40 dark:bg-verdict-forest/10"
          : "border-verdict-red/25 bg-verdict-rose/50 dark:bg-verdict-red/10"
      }`}
    >
      <div className="mb-4 flex items-center gap-3">
        <span
          className={`grid h-10 w-10 place-items-center rounded-full ${
            positive ? "bg-verdict-forest text-white" : "bg-verdict-red text-white"
          }`}
          aria-hidden="true"
        >
          {positive ? <UserCheck size={20} /> : <UserX size={20} />}
        </span>
        <h3 className="font-serif text-2xl text-verdict-ink dark:text-verdict-cream">{title}</h3>
      </div>
      {section.text && (
        <p className="text-sm leading-relaxed text-verdict-muted">
          <InlineText text={section.text} sources={sources} onCitation={onCitation} />
        </p>
      )}
      {section.items.length > 0 && (
        <ul className="mt-4 space-y-2.5">
          {section.items.map((item, index) => (
            <li key={index} className="flex gap-2.5 text-sm leading-relaxed text-verdict-ink dark:text-verdict-cream">
              <span
                className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full ${
                  positive ? "bg-verdict-forest text-white" : "bg-verdict-red text-white"
                }`}
                aria-hidden="true"
              >
                {positive ? <Check size={12} /> : <X size={12} />}
              </span>
              <InlineText text={item} sources={sources} onCitation={onCitation} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function Personas({
  buy,
  avoid,
  sources,
  onCitation,
}: {
  buy?: PersonaSection;
  avoid?: PersonaSection;
  sources: Source[];
  onCitation?: (number: number) => void;
}) {
  if (!buy && !avoid) return null;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {buy && <PersonaCard title="Who should buy it" section={buy} positive sources={sources} onCitation={onCitation} />}
      {avoid && <PersonaCard title="Who should avoid it" section={avoid} positive={false} sources={sources} onCitation={onCitation} />}
    </div>
  );
}
