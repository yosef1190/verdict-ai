"use client";
import Link from "next/link";

export default function Logo({ light = false }: { light?: boolean }) {
  return (
    <Link
      href="/"
      className="logo"
      aria-label="Verdict home"
      onClick={(e) => {
        // Already on the home page: scroll to top instead of a no-op navigation.
        if (window.location.pathname === "/") { e.preventDefault(); window.scrollTo({ top: 0, behavior: "smooth" }); }
      }}
    >
      <svg width="28" height="28" viewBox="0 0 28 28" fill="none" aria-hidden="true">
        <circle cx="14" cy="14" r="12" stroke={light ? "#DAD8D1" : "#2F6B4A"} strokeWidth="2" />
        <path d="M8.5 14.5l3.8 3.8 7.2-8" stroke="#12151C" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className="serif">Verdict</span>
    </Link>
  );
}
