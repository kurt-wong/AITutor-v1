/**
 * MathRenderer — 数学公式渲染组件
 *
 * 支持 LaTeX 公式（KaTeX）、内联图片（Markdown ![alt](url)）、
 * 表格（GFM pipe table → HTML）。
 */

import katex from "katex";
import "katex/dist/katex.min.css";

interface MathRendererProps {
  content: string;
  className?: string;
}

export default function MathRenderer({ content, className }: MathRendererProps) {
  if (!content) return null;

  const parts = parseMathContent(content);

  return (
    <span className={className}>
      {parts.map((part, index) => {
        if (part.type === "math") {
          return <MathBlock key={index} latex={part.content} display={part.display} />;
        }
        if (part.type === "image") {
          return (
            <img
              key={index}
              src={part.src}
              alt={part.alt || "图片"}
              style={{
                maxWidth: "100%",
                height: "auto",
                borderRadius: 4,
                margin: "4px 0",
                display: part.display ? "block" : "inline",
              }}
            />
          );
        }
        if (part.type === "table") {
          return (
            <div
              key={index}
              style={{ margin: "8px 0", overflowX: "auto" }}
              dangerouslySetInnerHTML={{ __html: part.tableHtml! }}
            />
          );
        }
        return <span key={index}>{part.content}</span>;
      })}
    </span>
  );
}

function MathBlock({ latex, display = false }: { latex: string; display?: boolean }) {
  try {
    const html = katex.renderToString(latex, {
      throwOnError: false,
      displayMode: display,
      trust: true,
      macros: {
        // S#135: Bridge commonly-used-but-unsupported LaTeX commands
        "\\xlongequal": "\\stackrel{#1}{=}",
        "\\ds": "\\displaystyle",
      },
    });

    if (display) {
      return (
        <div
          style={{ textAlign: "center", margin: "12px 0" }}
          dangerouslySetInnerHTML={{ __html: html }}
        />
      );
    }

    return <span dangerouslySetInnerHTML={{ __html: html }} />;
  } catch (e) {
    return <code>{latex}</code>;
  }
}

// ── Types ───────────────────────────────────────────────────────

interface MathPart {
  type: "text" | "math" | "image" | "table";
  content: string;
  display?: boolean;
  alt?: string;
  src?: string;
  tableHtml?: string;
}

interface ContentMatch {
  start: number;
  end: number;
  type: "math" | "image" | "table";
  latex?: string;
  display?: boolean;
  alt?: string;
  src?: string;
  tableHtml?: string;
}

// ── Parser ──────────────────────────────────────────────────────

function parseMathContent(content: string): MathPart[] {
  const parts: MathPart[] = [];
  const allMatches: ContentMatch[] = [];

  // ── Markdown pipe table (S#135) ─────────────────────────────
  // Match: header row, separator row (|---|...), 1+ body rows.
  // Use [ \t] not \s to avoid matching newlines greedily.
  const tableRegex = /^\|.+\|[ \t]*\n\|[-: |]+\|[ \t]*\n(?:\|.+\|[ \t]*\n)+/gm;
  let tableMatch;
  while ((tableMatch = tableRegex.exec(content)) !== null) {
    const html = convertTableToHtml(tableMatch[0]);
    allMatches.push({
      start: tableMatch.index,
      end: tableMatch.index + tableMatch[0].length,
      type: "table",
      tableHtml: html,
    });
  }

  // ── LaTeX math patterns ──────────────────────────────────────
  const mathPatterns = [
    { regex: /\$\$([\s\S]*?)\$\$/g, display: true },
    { regex: /\\\[([\s\S]*?)\\\]/g, display: true },
    { regex: /\$((?:[^\\$\n]|\\[\s\S])+?)\$/g, display: false },
    { regex: /\\\(([\s\S]*?)\\\)/g, display: false },
  ];

  for (const pattern of mathPatterns) {
    let match;
    while ((match = pattern.regex.exec(content)) !== null) {
      allMatches.push({
        start: match.index,
        end: match.index + match[0].length,
        type: "math",
        latex: match[1].trim(),
        display: pattern.display,
      });
    }
  }

  // ── Markdown image pattern (S#135) ──────────────────────────
  const imageRegex = /!\[([^\]]*)\]\(([^)]+)\)/g;
  let imgMatch;
  while ((imgMatch = imageRegex.exec(content)) !== null) {
    allMatches.push({
      start: imgMatch.index,
      end: imgMatch.index + imgMatch[0].length,
      type: "image",
      alt: imgMatch[1],
      src: imgMatch[2],
      display: true,
    });
  }

  allMatches.sort((a, b) => a.start - b.start);

  // Filter out inline matches that fall completely inside display math blocks
  const displayRanges = allMatches
    .filter((m) => m.type === "math" && m.display)
    .map((m) => ({ start: m.start, end: m.end }));
  const filtered = allMatches.filter((m) => {
    if (m.type === "image" || m.type === "table") return true;
    if (m.display) return true;
    return !displayRanges.some((r) => m.start >= r.start && m.end <= r.end);
  });

  let lastEnd = 0;
  for (const match of filtered) {
    if (match.start > lastEnd) {
      parts.push({ type: "text", content: content.slice(lastEnd, match.start) });
    }
    if (match.type === "math") {
      parts.push({ type: "math", content: match.latex!, display: match.display });
    } else if (match.type === "image") {
      parts.push({
        type: "image",
        content: match.alt || "图",
        alt: match.alt,
        src: match.src,
        display: match.display,
      });
    } else if (match.type === "table") {
      parts.push({ type: "table", content: "", tableHtml: match.tableHtml });
    }
    lastEnd = match.end;
  }

  if (lastEnd < content.length) {
    parts.push({ type: "text", content: content.slice(lastEnd) });
  }

  if (parts.length === 0) {
    parts.push({ type: "text", content });
  }

  return parts;
}

// ── Table converter ─────────────────────────────────────────────

function convertTableToHtml(text: string): string {
  const lines = text
    .trim()
    .split("\n")
    .filter((l) => l.includes("|"));
  if (lines.length < 3) return text; // need header + separator + ≥1 body

  // Header row
  const headers = lines[0]
    .split("|")
    .slice(1, -1)
    .map((c) => c.trim());
  if (headers.length === 0) return text;

  // Body rows (skip separator at lines[1])
  const bodyLines = lines.slice(2);

  const cellStyle =
    "border:1px solid #d9d9d9;padding:6px 12px;text-align:center";
  const thStyle = `${cellStyle};background:#fafafa;font-weight:600`;

  let html =
    '<table style="border-collapse:collapse;width:100%;margin:0;font-size:14px">';
  html += "<thead><tr>";
  headers.forEach(
    (h) => (html += `<th style="${thStyle}">${h}</th>`),
  );
  html += "</tr></thead><tbody>";
  bodyLines.forEach((line) => {
    const cells = line
      .split("|")
      .slice(1, -1)
      .map((c) => c.trim());
    html += "<tr>";
    cells.forEach(
      (c) => (html += `<td style="${cellStyle}">${c}</td>`),
    );
    html += "</tr>";
  });
  html += "</tbody></table>";
  return html;
}

// ── Exports ─────────────────────────────────────────────────────

export function InlineMath({ latex }: { latex: string }) {
  return <MathBlock latex={latex} display={false} />;
}

export function BlockMath({ latex }: { latex: string }) {
  return <MathBlock latex={latex} display={true} />;
}
