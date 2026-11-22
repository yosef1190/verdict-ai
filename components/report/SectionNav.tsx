"use client";

import { useEffect, useRef } from "react";

export interface NavItem {
  id: string;
  label: string;
}

export default function SectionNav({
  items,
  active,
  onSelect,
}: {
  items: NavItem[];
  active: string;
  onSelect: (id: string) => void;
}) {
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listRef.current?.querySelector<HTMLButtonElement>(`[data-nav="${active}"]`)?.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
      inline: "center",
    });
  }, [active]);

  if (!items.length) return null;

  return (
    <nav
      aria-label="Report sections"
      className="rv-print-hide sticky top-[68px] z-30 -mx-4 mb-8 border-y border-verdict-line/70 bg-verdict-cream/85 px-4 py-2.5 backdrop-blur-md dark:bg-verdict-bg/85 sm:mx-0 sm:rounded-2xl sm:border sm:px-3"
    >
      <div ref={listRef} className="rv-scroll flex gap-1.5 overflow-x-auto">
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            data-nav={item.id}
            aria-current={active === item.id ? "true" : undefined}
            onClick={() => onSelect(item.id)}
            className={`shrink-0 rounded-full px-4 py-2 text-sm font-medium transition-colors duration-180 ${
              active === item.id
                ? "bg-verdict-ink text-white dark:bg-verdict-forest dark:text-white"
                : "text-verdict-muted hover:bg-verdict-line/50 hover:text-verdict-ink dark:hover:bg-white/10 dark:hover:text-verdict-cream"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>
    </nav>
  );
}
