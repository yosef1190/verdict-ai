"use client";

import { Banknote, CircleDollarSign, ReceiptText } from "lucide-react";
import type { Alternative, ValueAssessment } from "@/lib/report/reportTypes";

function amount(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Number(value.replace(/[^0-9.]/g, ""));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export default function ValueForMoney({
  value,
  alternatives,
}: {
  value: ValueAssessment;
  alternatives: Alternative[];
}) {
  const price = amount(value.price);
  const rivalPrices = alternatives
    .map((alternative) => ({ name: alternative.name, price: amount(alternative.price) }))
    .filter((item): item is { name: string; price: number } => item.price != null);
  const max = Math.max(price ?? 0, ...rivalPrices.map((item) => item.price), 1);
  const bar = (itemPrice: number | null) => (itemPrice == null ? 0 : Math.max(6, (itemPrice / max) * 100));

  return (
    <div className="grid gap-4 lg:grid-cols-[1.15fr_.85fr]">
      <div className="rounded-2xl border border-verdict-line bg-verdict-card p-5 sm:p-6">
        <p className="text-[15px] leading-relaxed text-verdict-ink dark:text-verdict-cream">{value.text}</p>
        {value.highlights.length > 0 && (
          <ul className="mt-4 space-y-2">
            {value.highlights.map((highlight, index) => (
              <li key={index} className="flex gap-2 text-sm text-verdict-muted">
                <CircleDollarSign size={15} className="mt-0.5 shrink-0 text-verdict-gold" aria-hidden="true" />
                {highlight}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="space-y-4">
        <div className="rounded-2xl border border-verdict-line bg-verdict-card p-5">
          <p className="mb-4 flex items-center gap-2 text-sm font-medium text-verdict-ink dark:text-verdict-cream">
            <Banknote size={16} className="text-verdict-forest" aria-hidden="true" /> Price vs alternatives
          </p>
          <div className="space-y-3">
            <div>
              <div className="mb-1 flex justify-between text-xs text-verdict-muted">
                <span>This product</span>
                <span className="font-mono text-verdict-ink dark:text-verdict-cream">{value.price ?? "Not stated"}</span>
              </div>
              <div className="h-2 rounded-full bg-verdict-line/60">
                <div className="h-full rounded-full bg-verdict-forest" style={{ width: `${bar(price)}%` }} />
              </div>
            </div>
            {rivalPrices.slice(0, 4).map((item) => (
              <div key={item.name}>
                <div className="mb-1 flex justify-between text-xs text-verdict-muted">
                  <span className="truncate">{item.name}</span>
                  <span className="font-mono text-verdict-ink dark:text-verdict-cream">${item.price.toFixed(2)}</span>
                </div>
                <div className="h-2 rounded-full bg-verdict-line/60">
                  <div className="h-full rounded-full bg-verdict-gold" style={{ width: `${bar(item.price)}%` }} />
                </div>
              </div>
            ))}
            {!price && rivalPrices.length === 0 && (
              <p className="py-3 text-center text-sm text-verdict-muted">No comparable prices were found.</p>
            )}
          </div>
        </div>
        {value.extraCosts.length > 0 && (
          <div className="rounded-2xl border border-verdict-sand bg-verdict-sand/50 p-5 dark:bg-verdict-amber/10">
            <p className="mb-3 flex items-center gap-2 text-sm font-medium text-verdict-amber">
              <ReceiptText size={16} aria-hidden="true" /> True cost breakdown
            </p>
            <ul className="space-y-2 text-sm text-verdict-muted">
              {value.extraCosts.map((cost, index) => (
                <li key={index} className="leading-relaxed">{cost}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
