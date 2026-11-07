"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import Dial from "@/components/Dial";
import Logo from "@/components/Logo";
import AnalyzeForm from "@/components/AnalyzeForm";
import { NavAuth, CtaAuth } from "@/components/AuthButtons";

const problems = [
  ["Fake reviews", "Paid or incentivized reviews inflate ratings and drown out real buyers."],
  ["Generic feedback", "“Great product, fast shipping” tells you nothing about how it holds up."],
  ["Biased recommendations", "Affiliate lists and sponsored posts rarely mention the downsides."],
  ["Manipulated ratings", "Star averages can be gamed, merged across variants, or quietly reset."],
  ["Buried negative experiences", "The complaints that matter sit on page twelve—or on a forum."],
];
const signals = [
  ["Product Quality", "Build, materials and performance as reported by owners.", "M12 3l2.4 1.6 2.9-.2 1.2 2.7 2.5 1.5-.7 2.8 1.1 2.6-2 2.1-.2 2.9-2.8.9L12 21l-2.4-1.6-2.9.2-1.2-2.7-2.5-1.5.7-2.8L2.6 10l2-2.1.2.2-2.9 2.8-.9zM8.5 12.2l2.5 2.5 4.5-5"],
  ["Review Credibility", "Patterns that suggest paid, generic or duplicated reviews.", "M12 3l8 3v6c0 4.5-3.2 8-8 9-4.8-1-8-4.5-8-9V6zM8.5 12l2.5 2.5 4.5-5"],
  ["Real Customer Experiences", "Specific, long-term accounts from people who bought it.", "M9 11a3 3 0 100-6 3 3 0 000 6zM3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M16 5.5a3 3 0 010 5.5M18 14.5c2 .6 3 2.7 3 5.5"],
  ["Red Flags", "Safety issues, recalls, misleading claims and seller risk.", "M12 21a9 9 0 100-18 9 9 0 000 18zM12 8v5M12 16v.01"],
  ["Value for Money", "What you get for the price compared with alternatives.", "M12 4v16M5 20h14M5 8h14M5 8l-2.5 6a3 3 0 005 0zM19 8l-2.5 6a3 3 0 005 0z"],
  ["Brand Reputation", "Track record, warranty handling and support history.", "M5 21V4h9v17M14 9h5v12M3 21h18M8 8h2M8 12h2M8 16h2"],
  ["Common Complaints", "The issues that come up again and again—ranked.", "M4 5h16v11H9l-5 4zM12 8.5v3M12 13.5v.01"],
];
const bars = [["Product quality", 86], ["Review credibility", 78], ["Value for money", 84], ["Brand reputation", 80]] as const;
const pros = ["Strong customer satisfaction", "Positive performance feedback", "Good value for money", "Multiple positive customer experiences"];
const cons = ["Some durability complaints", "Inconsistent customer support experiences"];
const old = ["Search dozens of websites", "Read hundreds of reviews", "Miss important negative feedback", "Struggle to identify suspicious reviews", "Spend hours researching"];
const neu = ["Paste one product link", "AI-powered research", "Important signals summarized clearly", "Potential red flags surfaced", "Clear Verdict Score from 0–100", "Detailed final recommendation"];

const Icon = ({ d }: { d: string }) => (
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
);
const Label = ({ n, children }: { n: string; children: React.ReactNode }) => (
  <p className="label mono"><b>{n}</b><i />{children}</p>
);

export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user) {
      router.replace("/dashboard");
    }
  }, [user, loading, router]);

  if (loading) {
    return null;
  }

  if (user) {
    return null;
  }

  return (
    <>
      <header className="nav">
        <div className="wrap nav-in">
          <Logo />
          <nav aria-label="Primary" className="links">
            <a href="#how">How it works</a><a href="#analyze">What we analyze</a><a href="#report">Example report</a><a href="#why">Why Verdict</a>
          </nav>
          <NavAuth />
        </div>
      </header>

      <main id="top">
        <section className="hero wrap">
          <Dial size={216} />
          <h1 className="serif">Know the truth <em>before you buy.</em></h1>
          <p className="lede">Paste any product link and Verdict does the research for you—analyzing product information, reviews, customer experiences, discussions, and potential red flags to give you a clear Verdict Score and detailed report.</p>
          <AnalyzeForm />
          <div className="cta-row"><a className="btn dark" href="#cta">Get Your Verdict</a><a className="btn ghost" href="#how">See How It Works</a></div>
        </section>

        <section className="sec wrap" id="problem">
          <div className="split">
            <div>
              <Label n="01">The problem</Label>
              <h2 className="serif big">Online reviews don’t always tell the full story.</h2>
              <p className="lede left">Fake reviews, generic feedback, biased recommendations, manipulated ratings and buried negative experiences make it hard to know whether a product is actually worth your money.</p>
            </div>
            <div>
              <ol className="rows">
                {problems.map(([t, d], i) => (
                  <li key={t}><span className="mono n">{String(i + 1).padStart(2, "00")}</span><h3>{t}</h3><p>{d}</p></li>
                ))}
              </ol>
              <div className="dark-card"><span className="badge"><Logo light /></span><div><h3 className="serif">Verdict does the research for you.</h3><p>It reads everything, weighs the evidence, and tells you what it found—good and bad.</p></div></div>
            </div>
          </div>
        </section>

        <section className="sec wrap" id="how">
          <Label n="02">How it works</Label>
          <h2 className="serif big">Three steps. One clear answer.</h2>
          <div className="steps">
            <article><p className="mono step">Step 01</p><h3 className="serif">Paste a Product Link</h3><p>Enter the URL of any product you are considering buying.</p><div className="chip url mono">shop.example.com/products/…</div></article>
            <article><p className="mono step">Step 02</p><h3 className="serif">Verdict Researches It</h3><p>Verdict analyzes available product information, reviews, discussions, customer experiences, and relevant trust signals.</p><div className="chips">{["Product page", "Retailer reviews", "Forums", "Q&A threads", "Return notes"].map((c) => <span key={c} className="chip mono">{c}</span>)}</div></article>
            <article><p className="mono step">Step 03</p><h3 className="serif">Get Your Verdict</h3><p>Receive a detailed report with a Verdict Score, strengths, concerns, potential red flags, and a clear final recommendation.</p><div className="mini"><Dial size={84} label /><div><b className="green">Recommended</b><span>4 strengths · 2 concerns</span></div></div></article>
          </div>
        </section>

        <section className="sec wrap" id="analyze">
          <div className="head2"><div><Label n="03">What Verdict analyzes</Label><h2 className="serif big">Every signal that matters, weighed.</h2></div><p className="lede left">Seven dimensions of evidence, each scored independently and rolled into one number you can trust.</p></div>
          <div className="grid">
            {signals.map(([t, d, p], i) => (
              <div className="cell" key={t}><div className="cell-top"><Icon d={p} /><span className="mono n">{String(i + 1).padStart(2, "00")}</span></div><h3>{t}</h3><p>{d}</p></div>
            ))}
            <div className="cell dark-cell"><Dial size={150} dark /><div><p className="mono small">Combined into</p><h3 className="serif">One Verdict Score</h3></div></div>
          </div>
        </section>

        <section className="sec wrap" id="report">
          <Label n="04">Example report</Label>
          <h2 className="serif big">Evidence, not opinions.</h2>
          <p className="lede left">Every report shows the score, what drove it, and exactly what to watch out for.</p>
          <div className="report">
            <div className="r-head mono"><span>Verdict research report</span><span>Report <b>VR-2611-0482</b> &nbsp; Sources <b>1,284 reviews · 37 threads</b></span></div>
            <div className="r-body">
              <aside>
                <p className="mono small">Verdict Score</p><p className="prod">Aurora Pro ANC Headphones</p>
                <div className="center"><Dial size={300} /></div>
                <div className="center"><span className="pill"><i />Recommended</span><p className="serif minor">with minor concerns</p></div>
                <div className="bars">{bars.map(([k, v]) => (<div key={k}><p><span>{k}</span><b className="mono">{v}</b></p><div className="bar"><i style={{ width: `${v}%` }} /></div></div>))}</div>
              </aside>
              <div className="r-main">
                <p className="mono small">Summary</p>
                <p className="serif sum">This product appears to be a generally reliable choice with strong positive feedback regarding quality and performance. However, some recurring concerns were identified and should be considered before purchasing.</p>
                <div className="pc">
                  <div><p className="mono small">Positive signals</p>{pros.map((x) => <p className="pi" key={x}><span className="ok">✓</span>{x}</p>)}</div>
                  <div><p className="mono small">Concerns</p>{cons.map((x) => <p className="pi" key={x}><span className="warn">!</span>{x}</p>)}</div>
                </div>
                <div className="cred"><p className="mono small">Review credibility</p><span className="seg" aria-hidden="true"><i /><i /><i /><i /><i className="off" /></span><b>Good</b></div>
                <p className="muted">Most available feedback appears specific and experience-based, although some generic or repetitive reviews may be present.</p>
                <div className="final"><p className="mono small">Final recommendation</p><p>Recommended for most buyers, but consider the identified concerns before purchasing.</p></div>
              </div>
            </div>
          </div>
        </section>

        <section className="sec wrap" id="why">
          <Label n="05">Why Verdict</Label>
          <h2 className="serif big">Don’t just read reviews.<br /><em className="gray">Investigate the product.</em></h2>
          <div className="vs">
            <div className="vs-card"><div className="vs-h"><h3 className="serif">Traditional research</h3><span className="mono small">Hours of tabs</span></div>{old.map((x) => <p key={x}><span className="x">✕</span>{x}</p>)}</div>
            <div className="vs-card dark"><div className="vs-h"><h3 className="serif">With Verdict</h3><span className="mono small">One link</span></div>{neu.map((x) => <p key={x}><span>✓</span>{x}</p>)}</div>
          </div>
        </section>

        <section className="wrap" id="cta">
          <div className="final-cta">
            <Dial size={280} dark />
            <div>
              <p className="mono small up">STOP GUESSING. GET THE VERDICT.</p>
              <h2 className="serif huge">Try <em>Verdict.</em></h2>
              <CtaAuth />
              <p className="mono note left">No complicated research. Just paste a link.</p>
            </div>
          </div>
        </section>
      </main>

      <footer className="wrap foot"><Logo /><span className="muted">Product research, done for you.</span><nav><a href="#how">How it works</a><a href="#analyze">What we analyze</a><a href="#report">Example report</a><span className="mono">© 2026</span></nav></footer>
    </>
  );
}
