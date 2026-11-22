"use client";

import { ArrowUpRight, MessageCircle, Quote, ThumbsDown, ThumbsUp } from "lucide-react";
import type { CustomerFeedback, Source } from "@/lib/report/reportTypes";
import InlineText from "./InlineText";

export default function CustomersSection({
  feedback,
  sources,
  onCitation,
  onDeep,
}: {
  feedback: CustomerFeedback;
  sources: Source[];
  onCitation?: (number: number) => void;
  onDeep: () => void;
}) {
  if (feedback.insufficient) {
    return (
      <div className="flex flex-col items-start gap-5 rounded-2xl border border-dashed border-verdict-line bg-verdict-card p-6 sm:flex-row sm:items-center sm:p-8">
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-verdict-mint text-verdict-forest dark:bg-verdict-forest/20">
          <MessageCircle size={22} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-serif text-2xl text-verdict-ink dark:text-verdict-cream">Customer evidence is thin</h3>
          <p className="mt-1 text-sm leading-relaxed text-verdict-muted">
            {feedback.summary || "There isn't enough reliable customer feedback yet to summarize real experiences."}
          </p>
        </div>
        <button type="button" onClick={onDeep} className="btn dark sm shrink-0">
          Run a Deep investigation <ArrowUpRight size={15} aria-hidden="true" />
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {feedback.summary && (
        <p className="flex gap-3 rounded-2xl border border-verdict-line bg-verdict-card p-5 text-sm leading-relaxed text-verdict-muted">
          <Quote size={17} className="mt-0.5 shrink-0 text-verdict-forest" aria-hidden="true" />
          <InlineText text={feedback.summary} sources={sources} onCitation={onCitation} />
        </p>
      )}
      {(feedback.positives.length > 0 || feedback.complaints.length > 0) && (
        <div className="grid gap-4 md:grid-cols-2">
          {feedback.positives.length > 0 && (
            <div className="rounded-2xl border border-verdict-forest/20 bg-verdict-mint/30 p-5 dark:bg-verdict-forest/10">
              <p className="mb-3 flex items-center gap-2 text-sm font-medium text-verdict-forest">
                <ThumbsUp size={16} aria-hidden="true" /> Common positives
              </p>
              <ul className="space-y-2">
                {feedback.positives.map((item, index) => (
                  <li key={index} className="text-sm leading-relaxed text-verdict-ink dark:text-verdict-cream">
                    <InlineText text={item} sources={sources} onCitation={onCitation} />
                  </li>
                ))}
              </ul>
            </div>
          )}
          {feedback.complaints.length > 0 && (
            <div className="rounded-2xl border border-verdict-red/20 bg-verdict-rose/40 p-5 dark:bg-verdict-red/10">
              <p className="mb-3 flex items-center gap-2 text-sm font-medium text-verdict-red">
                <ThumbsDown size={16} aria-hidden="true" /> Common complaints
              </p>
              <ul className="space-y-2">
                {feedback.complaints.map((item, index) => (
                  <li key={index} className="text-sm leading-relaxed text-verdict-ink dark:text-verdict-cream">
                    <InlineText text={item} sources={sources} onCitation={onCitation} />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
