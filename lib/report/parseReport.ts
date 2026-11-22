import type {
  Alternative,
  BulletItem,
  Claim,
  ClaimStatus,
  Confidence,
  CustomerFeedback,
  PersonaSection,
  ReportData,
  SectionId,
  SectionMap,
  Severity,
  Source,
  TextSection,
  ValueAssessment,
  VerdictSummary,
} from "./reportTypes";

const SECTION_PATTERNS: Array<[SectionId, RegExp]> = [
  ["overall", /overall verdict|verdict score|executive summary|tl;?dr/i],
  ["overview", /product overview|what the page covers|key findings/i],
  ["pros", /what looks good|strengths|positive findings/i],
  ["cons", /problems and red flags|red flags|problems|concerns|caveats/i],
  ["customers", /real customers|customer feedback|customer experience|customers are saying/i],
  ["claims", /claims vs reality|claims and reality|marketing claims/i],
  ["value", /value for money|price and value/i],
  ["trust", /brand and seller|seller trust|brand trust/i],
  ["alternatives", /alternatives|competition/i],
  ["buy", /who should buy/i],
  ["avoid", /who should avoid/i],
  ["final", /final recommendation|bottom line/i],
  ["sources", /sources/i],
];

const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2190}-\u{21FF}\u{FE0F}\u{200D}]/gu;

function cleanInline(value: string): string {
  return value
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\\([\[\]])/g, "$1")
    .replace(/\*\*/g, "")
    .replace(/^_|_$/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function stripEmoji(value: string): string {
  return value.replace(EMOJI, "").replace(/\s+/g, " ").trim();
}

function citationsIn(value: string): number[] {
  const numbers = [...value.matchAll(/\[(\d+)\]/g)].map((match) => Number(match[1]));
  return [...new Set(numbers.filter((number) => number > 0))].sort((a, b) => a - b);
}

function headingId(heading: string): SectionId | null {
  const normalized = stripEmoji(heading).toLowerCase();
  for (const [id, pattern] of SECTION_PATTERNS) {
    if (pattern.test(normalized)) return id;
  }
  return null;
}

function splitSections(markdown: string): { title: string; blocks: Partial<Record<SectionId, string>> } {
  const blocks: Partial<Record<SectionId, string>> = {};
  let title = "";
  let current: SectionId | null = null;
  let buffer: string[] = [];

  const flush = () => {
    if (!current) return;
    const body = buffer.join("\n").replace(/^\s*---+\s*$/gm, "").trim();
    if (body) blocks[current] = body;
    buffer = [];
  };

  for (const line of markdown.split("\n")) {
    const match = line.match(/^(#{1,3})\s+(.+?)\s*$/);
    if (!match || match[1].length === 3) {
      buffer.push(line);
      continue;
    }
    flush();
    const id = headingId(match[2]);
    if (id) {
      current = id;
    } else {
      current = null;
      if (!title && match[1] === "#") title = cleanInline(match[2]);
    }
  }
  flush();
  return { title, blocks };
}

function bullets(body: string): string[] {
  const lines = body.split("\n");
  const result: string[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const match = lines[index].match(/^\s*(?:[-*]|\d+\.)\s+(.+)$/);
    if (!match) continue;
    let value = match[1];
    while (index + 1 < lines.length) {
      const next = lines[index + 1];
      if (/^\s*(?:[-*]|\d+\.)\s+/.test(next) || /^#{1,6}\s/.test(next) || !next.trim()) break;
      value += ` ${next.trim()}`;
      index += 1;
    }
    const cleaned = cleanInline(value);
    if (cleaned) result.push(cleaned);
  }
  return result;
}

function prose(body: string): string {
  return body
    .split("\n")
    .filter((line) => {
      const trimmed = line.trim();
      return (
        trimmed &&
        !/^(?:[-*]|\d+\.)\s+/.test(trimmed) &&
        !/^#{1,6}\s/.test(trimmed) &&
        !/^\*\*[^\n]*:\s*[^\n]*\*\*$/.test(trimmed) &&
        !/^(?:verdict score|verdict|product credibility|evidence strength|purchasing confidence|recommendation|confidence)\s*:/i.test(trimmed) &&
        !/^---+$/.test(trimmed)
      );
    })
    .map(cleanInline)
    .join(" ")
    .trim();
}

function inferSeverity(text: string): Severity {
  if (/deal.?breaker|showstopper|do not buy|avoid at all costs|fatal/i.test(text)) return "Deal-breaker";
  if (
    /major|serious|significant|critical|severe|repeated|frequent|widespread|safety|scam|fraud|defect/i.test(
      text,
    )
  ) {
    return "Major";
  }
  return "Minor";
}

function parseBulletItems(body: string, withSeverity: boolean): BulletItem[] {
  const lines = body.split("\n");
  const items: BulletItem[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const match = lines[index].match(/^\s*(?:[-*]|\d+\.)\s+(.+)$/);
    if (!match) continue;
    let raw = match[1];
    while (index + 1 < lines.length) {
      const next = lines[index + 1];
      if (/^\s*(?:[-*]|\d+\.)\s+/.test(next) || /^#{1,6}\s/.test(next) || !next.trim()) break;
      raw += ` ${next.trim()}`;
      index += 1;
    }
    const bold = raw.match(/^\*\*(.+?)\*\*\s*[:：]?\s*(.*)$/);
    const split = bold ? [bold[1], bold[2]] : raw.split(/[:：]\s*/, 2);
    const title = cleanInline(split[0] || "Finding").replace(/[:：]\s*$/, "").replace(/[.。]$/, "");
    const description = cleanInline(split.slice(1).join(" ") || raw);
    if (!title && !description) continue;
    items.push({
      title: title || description.slice(0, 60),
      description: title && description ? description : "",
      citations: citationsIn(raw),
      ...(withSeverity ? { severity: inferSeverity(`${title} ${description}`) } : {}),
    });
  }
  if (items.length) return items;
  const summary = prose(body);
  return summary ? [{ title: summary.slice(0, 70), description: "", citations: citationsIn(body) }] : [];
}

function normalizeConfidence(value: string | undefined): Confidence | null {
  if (!value) return null;
  if (/high/i.test(value)) return "High";
  if (/medium|moderate/i.test(value)) return "Medium";
  if (/low|limited/i.test(value)) return "Low";
  return null;
}

function normalizeRecommendation(value: string | undefined): string {
  if (!value) return "Mixed";
  const cleaned = stripEmoji(cleanInline(value.split(/[—–-]/)[0])).replace(/[.!]/g, "");
  if (/not recommended|avoid|do not buy|poor/i.test(cleaned)) return "Avoid";
  if (/recommend|buy|good choice|strong/i.test(cleaned)) return "Recommended";
  return cleaned.split(/\s+/).slice(0, 3).join(" ") || "Mixed";
}

function parseVerdict(body: string | undefined): VerdictSummary | undefined {
  if (!body) return undefined;
  const scoreMatch = body.match(/(?:verdict(?:\s+score)?|score)\s*:?\s*\**\s*(\d{1,3})\s*\/\s*100/i);
  const credibility = body.match(/product credibility\s*:?\s*\**\s*(\d{1,3})/i);
  const evidence = body.match(/evidence strength\s*:?\s*\**\s*(\d{1,3})/i);
  const purchasing = body.match(/purchasing confidence\s*:?\s*\**\s*(\d{1,3})/i);
  const recommendation = body.match(/recommendation\s*:\s*([^\n]+)/i);
  const confidence = body.match(/(?:^|\n)\s*\*{0,2}confidence\s*:\s*([^\n]+)/i);
  const summary = prose(body);
  if (!scoreMatch && !recommendation && !summary) return undefined;
  return {
    score: scoreMatch ? Math.max(0, Math.min(100, Number(scoreMatch[1]))) : null,
    recommendation: normalizeRecommendation(recommendation?.[1]),
    confidence: normalizeConfidence(confidence?.[1]),
    text: summary,
    productCredibility: credibility ? Number(credibility[1]) : null,
    evidenceStrength: evidence ? Number(evidence[1]) : null,
    purchasingConfidence: purchasing ? Number(purchasing[1]) : null,
  };
}

function parseText(body: string | undefined): TextSection | undefined {
  if (!body?.trim()) return undefined;
  return { text: prose(body), bullets: bullets(body) };
}

function splitCustomers(body: string | undefined): CustomerFeedback | undefined {
  if (!body?.trim()) return undefined;
  const positives: string[] = [];
  const complaints: string[] = [];
  let target: string[] | null = null;
  const other: string[] = [];
  for (const line of body.split("\n")) {
    const sub = line.match(/^###\s+(.+)$/);
    if (sub) {
      const label = stripEmoji(sub[1]).toLowerCase();
      target = /positive|good|praise|strength/i.test(label)
        ? positives
        : /complaint|negative|problem|concern/i.test(label)
          ? complaints
          : null;
      continue;
    }
    const item = line.match(/^\s*(?:[-*]|\d+\.)\s+(.+)$/);
    if (item) {
      const value = cleanInline(item[1]);
      if (target) target.push(value);
      else other.push(value);
    }
  }
  const summary = prose(body);
  const insufficient =
    !positives.length && !complaints.length
      ? /insufficient|not enough|limited evidence|no reliable|unable to find|no customer/i.test(summary) ||
        summary.length < 60
      : false;
  if (insufficient || (!summary && !positives.length && !complaints.length)) {
    return { positives, complaints, summary, insufficient: true };
  }
  return { positives, complaints, summary, insufficient };
}

function claimStatus(value: string): ClaimStatus {
  if (/exceed/i.test(value)) return "exceeded";
  if (/partial|mixed|somewhat|partly/i.test(value)) return "partial";
  if (/unsupported|false|not supported|exaggerated|cannot be (independently )?verified|unverified/i.test(value)) {
    return "unsupported";
  }
  if (/supported|confirmed|accurate|true/i.test(value)) return "supported";
  return "partial";
}

function tableCells(line: string): string[] {
  return line
    .replace(/^\s*\|/, "")
    .replace(/\|\s*$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function parseClaimGroups(body: string): Claim[] {
  const groups: string[] = [];
  let current = "";
  for (const line of body.split("\n")) {
    if (/^\s*(\*\*)?claim(\*\*)?\s*:/i.test(line)) {
      if (current.trim()) groups.push(current);
      current = line;
    } else if (current) {
      current += `\n${line}`;
    }
  }
  if (current.trim()) groups.push(current);
  return groups.map((group) => {
    const claim = group.match(/claim\s*:\s*([^\n]+)/i)?.[1] ?? "";
    const evidence =
      group.match(/(?:available\s+)?evidence\s*:\s*([^\n]+)/i)?.[1] ??
      group.split("\n").filter((line) => !/^(claim|verdict)\s*:/i.test(line)).join(" ");
    const verdict = group.match(/verdict\s*:\s*([^\n]+)/i)?.[1] ?? "";
    return {
      claim: cleanInline(claim),
      evidence: cleanInline(evidence),
      verdict: cleanInline(verdict),
      status: claimStatus(verdict),
      citations: citationsIn(group),
    };
  });
}

function parseClaims(body: string | undefined): Claim[] | undefined {
  if (!body?.trim()) return undefined;
  const tableLines = body.split("\n").filter((line) => line.trim().startsWith("|"));
  if (tableLines.length > 1) {
    const header = tableCells(tableLines[0]).map((cell) => cell.toLowerCase());
    const claimIndex = header.findIndex((cell) => /claim/.test(cell));
    const evidenceIndex = header.findIndex((cell) => /evidence|reality|finding/.test(cell));
    const statusIndex = header.findIndex((cell) => /verdict|status|supported/.test(cell));
    const rows = tableLines
      .slice(1)
      .filter((line) => tableCells(line).some((cell) => !/^[\s:-]+$/.test(cell)))
      .map((line) => tableCells(line))
      .filter((cells) => cells.some((cell) => cell.trim()))
      .map((cells) => {
        const verdict = cells[statusIndex >= 0 ? statusIndex : 2] ?? "";
        return {
          claim: cleanInline(cells[claimIndex >= 0 ? claimIndex : 0] ?? ""),
          evidence: cleanInline(cells[evidenceIndex >= 0 ? evidenceIndex : 1] ?? ""),
          verdict: cleanInline(verdict),
          status: claimStatus(verdict),
          citations: citationsIn(cells.join(" ")),
        };
      });
    if (rows.length) return rows;
  }
  const groups = parseClaimGroups(body);
  return groups.length ? groups : undefined;
}

function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url.replace(/^https?:\/\//, "").split("/")[0] || "source";
  }
}

function parseSources(body: string | undefined): Source[] | undefined {
  if (!body?.trim()) return undefined;
  const sources: Source[] = [];
  for (const line of body.split("\n")) {
    const linked = line.match(/^\s*(\d+)\.\s*\[([^\]]+)\]\((?:<)?([^)>]+)>?\)(.*)$/);
    const plain = line.match(/^\s*(\d+)\.\s*(.*)$/);
    if (!linked && !plain) continue;
    const number = Number(linked?.[1] ?? plain?.[1]);
    const title = cleanInline(linked?.[2] ?? plain?.[2] ?? "Source");
    const url = (linked?.[3] ?? "").trim();
    const note = cleanInline(linked?.[4] ?? "").replace(/^[-—–]\s*/, "") || undefined;
    sources.push({
      number,
      title,
      url,
      domain: domainOf(url),
      ...(note ? { note } : {}),
      ...(note && /independent|credible|primary|official|verified|quality/i.test(note)
        ? { quality: note }
        : {}),
    });
  }
  return sources.length ? sources : undefined;
}

function parseAlternatives(body: string | undefined): Alternative[] | undefined {
  if (!body?.trim()) return undefined;
  const values = bullets(body);
  if (!values.length) return undefined;
  return values.map((value) => {
    const price = value.match(/\$\s?[\d,.]+(?:\s*(?:\/|per)\s*\w+)?/)?.[0]?.replace(/\s+/g, "") ?? null;
    const better = value.match(/better (?:for|suited for)\s+([^.;]+)/i)?.[1]?.trim() ?? null;
    const withoutBetter = better ? value.replace(/better (?:for|suited for)\s+[^.;]+/i, "").trim() : value;
    const separator = withoutBetter.match(/^([^:—]+?)\s*(?:[—–-]|:)\s*(.+)$/);
    const name = (separator?.[1] ?? withoutBetter).replace(/\s*\([^)]*\)\s*$/, "").trim();
    const tradeoff = (separator?.[2] ?? withoutBetter)
      .replace(/\s*\([^)]*\)\s*$/, "")
      .replace(/[.;]+$/, "")
      .trim();
    return { name: name || "Alternative", price, tradeoff: tradeoff || "See source for details", betterFor: better };
  });
}

function parseValue(body: string | undefined): ValueAssessment | undefined {
  if (!body?.trim()) return undefined;
  const lines = body.split("\n").map(cleanInline).filter(Boolean);
  const text = lines.join(" ");
  const price = text.match(/\$\s?[\d,.]+(?:\s*(?:\/|per)\s*\w+)?/)?.[0]?.replace(/\s+/g, "") ?? null;
  const extraCosts = lines.filter((line) =>
    /subscription|hidden fee|extra cost|additional cost|shipping|warranty|fee|monthly/i.test(line),
  );
  return {
    text,
    price,
    extraCosts,
    highlights: bullets(body).slice(0, 4),
  };
}

function parsePersona(body: string | undefined): PersonaSection | undefined {
  if (!body?.trim()) return undefined;
  return { text: prose(body), items: bullets(body) };
}

export function parseMarkdown(markdown: string, fallbackTitle = "Verdict research report"): ReportData {
  const { title, blocks } = splitSections(markdown);
  const sections: SectionMap = {};
  const verdict = parseVerdict(blocks.overall);
  const pros = parseBulletItems(blocks.pros ?? "", false);
  const cons = parseBulletItems(blocks.cons ?? "", true);
  const claims = parseClaims(blocks.claims);
  const sources = parseSources(blocks.sources);
  const value = parseValue(blocks.value);
  const overview = parseText(blocks.overview);
  const trust = parseText(blocks.trust);
  const final = parseText(blocks.final);
  const customers = splitCustomers(blocks.customers);
  const alternatives = parseAlternatives(blocks.alternatives);
  const buy = parsePersona(blocks.buy);
  const avoid = parsePersona(blocks.avoid);

  if (verdict) sections.overall = verdict;
  if (overview) sections.overview = overview;
  if (pros.length) sections.pros = pros;
  if (cons.length) sections.cons = cons;
  if (customers) sections.customers = customers;
  if (claims?.length) sections.claims = claims;
  if (value) sections.value = value;
  if (trust) sections.trust = trust;
  if (alternatives?.length) sections.alternatives = alternatives;
  if (buy) sections.buy = buy;
  if (avoid) sections.avoid = avoid;
  if (final) sections.final = final;
  if (sources?.length) sections.sources = sources;

  return {
    title: title || fallbackTitle,
    sections,
    quickStats: {
      price:
        value?.price ??
        alternatives?.find((alternative) => alternative.price)?.price ??
        null,
      sourcesAnalyzed: sources?.length ?? null,
      biggestRedFlag: cons[0]?.title ?? null,
    },
    meta: { parser: "markdown", version: 1 },
    markdown,
  };
}

export function parseReport(
  input: string | Partial<ReportData>,
  fallbackTitle = "Verdict research report",
): ReportData {
  if (typeof input === "string") return parseMarkdown(input, fallbackTitle);
  return {
    title: input.title || fallbackTitle,
    sections: input.sections ?? {},
    quickStats: input.quickStats ?? { price: null, sourcesAnalyzed: null, biggestRedFlag: null },
    meta: input.meta ?? { parser: "json", version: 1 },
    markdown: input.markdown ?? "",
  };
}
