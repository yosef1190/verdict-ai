"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Moon, Sun } from "lucide-react";
import { parseReport } from "@/lib/report/parseReport";
import type { Source } from "@/lib/report/reportTypes";
import AlternativesCarousel from "./AlternativesCarousel";
import ClaimsList from "./ClaimsList";
import CustomersSection from "./CustomersSection";
import FinalRecommendation from "./FinalRecommendation";
import InlineText from "./InlineText";
import Personas from "./Personas";
import ProsCons from "./ProsCons";
import ReportSection from "./ReportSection";
import ScoreGauge from "./ScoreGauge";
import SectionNav, { type NavItem } from "./SectionNav";
import SourcesList from "./SourcesList";
import ValueForMoney from "./ValueForMoney";

export default function ReportView({
  markdown,
  title,
  copied,
  onCopy,
  onDownload,
  onNewResearch,
  onDeep,
}: {
  markdown: string;
  title: string;
  copied: "" | "ok" | "fail";
  onCopy: () => void;
  onDownload: () => void;
  onNewResearch: () => void;
  onDeep: () => void;
}) {
  const data = useMemo(() => parseReport(markdown, title), [markdown, title]);
  const reduceMotion = useReducedMotion();
  const sources = data.sections.sources ?? [];
  const [active, setActive] = useState("");
  const [highlightedSource, setHighlightedSource] = useState<number | null>(null);
  const [dark, setDark] = useState(false);
  const [shared, setShared] = useState(false);
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const navItems = useMemo<NavItem[]>(() => {
    const items: NavItem[] = [];
    if (data.sections.overview || data.sections.trust) items.push({ id: "report-overview", label: "Overview" });
    if (data.sections.pros || data.sections.cons) items.push({ id: "report-pros-cons", label: "Pros & Cons" });
    if (data.sections.customers) items.push({ id: "report-customers", label: "Customers" });
    if (data.sections.claims) items.push({ id: "report-claims", label: "Claims" });
    if (data.sections.value) items.push({ id: "report-value", label: "Value" });
    if (data.sections.alternatives) items.push({ id: "report-alternatives", label: "Alternatives" });
    if (data.sections.buy || data.sections.avoid) items.push({ id: "report-personas", label: "Who" });
    if (data.sections.final) items.push({ id: "report-final", label: "Final" });
    if (data.sections.sources) items.push({ id: "report-sources", label: "Sources" });
    return items;
  }, [data.sections]);

  const navKey = navItems.map((item) => item.id).join("|");

  useEffect(() => {
    const stored = window.localStorage.getItem("verdict:report-theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const next = stored ? stored === "dark" : prefersDark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
  }, []);

  useEffect(() => {
    if (!navKey) return;
    const elements = navKey
      .split("|")
      .map((id) => document.getElementById(id))
      .filter((element): element is HTMLElement => Boolean(element));
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: "-120px 0px -62% 0px", threshold: 0 },
    );
    elements.forEach((element) => observer.observe(element));
    if (elements[0]) setActive(elements[0].id);
    return () => observer.disconnect();
  }, [navKey]);

  useEffect(() => {
    return () => {
      if (highlightTimer.current) clearTimeout(highlightTimer.current);
    };
  }, []);

  const handleCitation = useCallback((number: number) => {
    setHighlightedSource(number);
    document.getElementById(`source-${number}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    if (highlightTimer.current) clearTimeout(highlightTimer.current);
    highlightTimer.current = setTimeout(() => setHighlightedSource(null), 2200);
  }, []);

  const scrollToSection = (id: string) => {
    setActive(id);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const toggleTheme = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    window.localStorage.setItem("verdict:report-theme", next ? "dark" : "light");
  };

  const handleShare = async () => {
    try {
      if (navigator.share) {
        await navigator.share({ title: data.title, url: window.location.href });
      } else {
        await navigator.clipboard.writeText(window.location.href);
      }
      setShared(true);
      setTimeout(() => setShared(false), 1600);
    } catch {
      setShared(false);
    }
  };

  const handlePdf = () => window.print();
  const allSources: Source[] = sources;
  const hasSections = Object.keys(data.sections).length > 0;

  return (
    <section className="rv-report-shell mx-auto w-full max-w-5xl space-y-8" aria-label="Verdict research report">
      <div className="rv-print-hide flex flex-wrap items-center justify-between gap-3">
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-verdict-muted">
          Verdict research report
        </p>
        <button
          type="button"
          onClick={toggleTheme}
          className="inline-flex items-center gap-2 rounded-full border border-verdict-line bg-verdict-card px-3 py-2 text-sm text-verdict-muted transition-colors duration-180 hover:text-verdict-ink dark:bg-white/5 dark:hover:text-verdict-cream"
          aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
        >
          {dark ? <Sun size={15} aria-hidden="true" /> : <Moon size={15} aria-hidden="true" />}
          {dark ? "Light" : "Dark"}
        </button>
      </div>

      <motion.div
        initial={reduceMotion ? false : { opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: reduceMotion ? 0 : 0.4 }}
      >
        <ScoreGauge
          score={data.sections.overall?.score ?? null}
          recommendation={data.sections.overall?.recommendation ?? "Mixed"}
          confidence={data.sections.overall?.confidence ?? null}
          summary={data.sections.overall?.text ?? ""}
          quickStats={data.quickStats}
        />
      </motion.div>

      <SectionNav items={navItems} active={active} onSelect={scrollToSection} />

      {!hasSections && (
        <div className="rounded-2xl border border-dashed border-verdict-line bg-verdict-card p-8 text-center text-sm text-verdict-muted">
          No structured sections were found in this report. You can still copy or download the original markdown.
        </div>
      )}

      <div className="space-y-14">
        {(data.sections.overview || data.sections.trust) && (
          <ReportSection id="report-overview" eyebrow="01 / Snapshot" title="Product overview" delay={0.04}>
            <div className="space-y-4">
              {data.sections.overview && (
                <div className="rounded-2xl border border-verdict-line bg-verdict-card p-5 sm:p-6">
                  {data.sections.overview.text && (
                    <p className="text-[15px] leading-relaxed text-verdict-muted">
                      <InlineText text={data.sections.overview.text} sources={allSources} onCitation={handleCitation} />
                    </p>
                  )}
                  {data.sections.overview.bullets.length > 0 && (
                    <ul className="mt-4 grid gap-2 sm:grid-cols-2">
                      {data.sections.overview.bullets.map((item, index) => (
                        <li key={index} className="flex gap-2 text-sm leading-relaxed text-verdict-ink dark:text-verdict-cream">
                          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-verdict-forest" aria-hidden="true" />
                          <InlineText text={item} sources={allSources} onCitation={handleCitation} />
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              {data.sections.trust && (
                <div className="rounded-2xl border border-verdict-gold/30 bg-verdict-sand/40 p-5 sm:p-6 dark:bg-verdict-amber/10">
                  <h3 className="mb-2 font-serif text-xl text-verdict-ink dark:text-verdict-cream">Brand & seller trust</h3>
                  {data.sections.trust.text && (
                    <p className="text-sm leading-relaxed text-verdict-muted">
                      <InlineText text={data.sections.trust.text} sources={allSources} onCitation={handleCitation} />
                    </p>
                  )}
                  {data.sections.trust.bullets.length > 0 && (
                    <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                      {data.sections.trust.bullets.map((item, index) => (
                        <li key={index} className="text-sm leading-relaxed text-verdict-muted">
                          <InlineText text={item} sources={allSources} onCitation={handleCitation} />
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          </ReportSection>
        )}

        {(data.sections.pros || data.sections.cons) && (
          <ReportSection id="report-pros-cons" eyebrow="02 / Evidence" title="Strengths and red flags" delay={0.08}>
            <ProsCons
              pros={data.sections.pros ?? []}
              cons={data.sections.cons ?? []}
              sources={allSources}
              onCitation={handleCitation}
            />
          </ReportSection>
        )}

        {data.sections.customers && (
          <ReportSection id="report-customers" eyebrow="03 / Voices" title="What real customers say" delay={0.12}>
            <CustomersSection
              feedback={data.sections.customers}
              sources={allSources}
              onCitation={handleCitation}
              onDeep={onDeep}
            />
          </ReportSection>
        )}

        {data.sections.claims && (
          <ReportSection id="report-claims" eyebrow="04 / Verification" title="Claims vs reality" delay={0.16}>
            <ClaimsList claims={data.sections.claims} sources={allSources} onCitation={handleCitation} />
          </ReportSection>
        )}

        {data.sections.value && (
          <ReportSection id="report-value" eyebrow="05 / Cost" title="Value for money" delay={0.2}>
            <ValueForMoney value={data.sections.value} alternatives={data.sections.alternatives ?? []} />
          </ReportSection>
        )}

        {data.sections.alternatives && (
          <ReportSection id="report-alternatives" eyebrow="06 / Market" title="Alternatives" delay={0.24}>
            <AlternativesCarousel alternatives={data.sections.alternatives} />
          </ReportSection>
        )}

        {(data.sections.buy || data.sections.avoid) && (
          <ReportSection id="report-personas" eyebrow="07 / Fit" title="Who this is for" delay={0.28}>
            <Personas buy={data.sections.buy} avoid={data.sections.avoid} sources={allSources} onCitation={handleCitation} />
          </ReportSection>
        )}

        {data.sections.final && (
          <ReportSection id="report-final" eyebrow="08 / Decision" title="Final recommendation" delay={0.32}>
            <FinalRecommendation
              final={data.sections.final}
              verdict={data.sections.overall}
              copied={copied}
              onShare={handleShare}
              onCopy={onCopy}
              onDownload={onDownload}
              onPdf={handlePdf}
              onNewResearch={onNewResearch}
            />
          </ReportSection>
        )}

        {data.sections.sources && (
          <ReportSection id="report-sources" eyebrow="09 / Evidence base" title="Sources" delay={0.36}>
            <SourcesList sources={data.sections.sources} highlighted={highlightedSource} />
          </ReportSection>
        )}
      </div>

      {shared && (
        <div className="rv-print-hide fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-full bg-verdict-ink px-4 py-2 text-sm text-white shadow-lift" role="status">
          Link copied
        </div>
      )}
    </section>
  );
}
