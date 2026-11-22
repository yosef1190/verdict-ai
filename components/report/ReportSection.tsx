"use client";

import { motion, useReducedMotion } from "framer-motion";

export default function ReportSection({
  id,
  eyebrow,
  title,
  children,
  className = "",
  delay = 0,
}: {
  id: string;
  eyebrow?: string;
  title: string;
  children: React.ReactNode;
  className?: string;
  delay?: number;
}) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.section
      id={id}
      aria-labelledby={`${id}-title`}
      initial={reduceMotion ? false : { opacity: 0, y: 18 }}
      whileInView={reduceMotion ? undefined : { opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.15 }}
      transition={{ duration: 0.42, delay, ease: [0.22, 1, 0.36, 1] }}
      className={`scroll-mt-32 ${className}`}
    >
      <div className="mb-5 flex items-end justify-between gap-4">
        <div>
          {eyebrow && (
            <p className="mb-1.5 font-mono text-[11px] uppercase tracking-[0.18em] text-verdict-muted">
              {eyebrow}
            </p>
          )}
          <h2
            id={`${id}-title`}
            className="font-serif text-[clamp(28px,3.4vw,40px)] leading-tight text-verdict-ink"
          >
            {title}
          </h2>
        </div>
        <span className="hidden h-px flex-1 bg-verdict-line sm:block" aria-hidden="true" />
      </div>
      {children}
    </motion.section>
  );
}
