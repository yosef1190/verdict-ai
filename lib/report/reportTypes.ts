export type SectionId =
  | "overall"
  | "overview"
  | "pros"
  | "cons"
  | "customers"
  | "claims"
  | "value"
  | "trust"
  | "alternatives"
  | "buy"
  | "avoid"
  | "final"
  | "sources";

export type Confidence = "Low" | "Medium" | "High";
export type Severity = "Minor" | "Major" | "Deal-breaker";
export type ClaimStatus = "supported" | "partial" | "unsupported" | "exceeded";

export interface VerdictSummary {
  score: number | null;
  recommendation: string;
  confidence: Confidence | null;
  text: string;
  productCredibility: number | null;
  evidenceStrength: number | null;
  purchasingConfidence: number | null;
}

export interface BulletItem {
  title: string;
  description: string;
  citations: number[];
  severity?: Severity;
}

export interface Claim {
  claim: string;
  evidence: string;
  verdict: string;
  status: ClaimStatus;
  citations: number[];
}

export interface Source {
  number: number;
  title: string;
  url: string;
  domain: string;
  quality?: string;
  note?: string;
}

export interface Alternative {
  name: string;
  price: string | null;
  tradeoff: string;
  betterFor: string | null;
}

export interface CustomerFeedback {
  positives: string[];
  complaints: string[];
  summary: string;
  insufficient: boolean;
}

export interface ValueAssessment {
  text: string;
  price: string | null;
  extraCosts: string[];
  highlights: string[];
}

export interface PersonaSection {
  text: string;
  items: string[];
}

export interface TextSection {
  text: string;
  bullets: string[];
}

export interface SectionMap {
  overall?: VerdictSummary;
  overview?: TextSection;
  pros?: BulletItem[];
  cons?: BulletItem[];
  customers?: CustomerFeedback;
  claims?: Claim[];
  value?: ValueAssessment;
  trust?: TextSection;
  alternatives?: Alternative[];
  buy?: PersonaSection;
  avoid?: PersonaSection;
  final?: TextSection;
  sources?: Source[];
}

export interface QuickStats {
  price: string | null;
  sourcesAnalyzed: number | null;
  biggestRedFlag: string | null;
}

export interface ReportData {
  title: string;
  sections: SectionMap;
  quickStats: QuickStats;
  meta: {
    parser: "markdown" | "json";
    version: number;
  };
  markdown: string;
}
