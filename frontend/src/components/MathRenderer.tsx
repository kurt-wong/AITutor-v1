/**
 * MathRenderer — 数学公式渲染组件
 *
 * 支持 LaTeX 公式渲染（KaTeX）和图文混排
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

interface MathPart {
  type: "text" | "math";
  content: string;
  display?: boolean;
}

function parseMathContent(content: string): MathPart[] {
  const parts: MathPart[] = [];

  const patterns = [
    { regex: /\$\$([\s\S]*?)\$\$/g, display: true },
    { regex: /\\\[([\s\S]*?)\\\]/g, display: true },
    { regex: /\$([^\$\n]+?)\$/g, display: false },
    { regex: /\\\(([\s\S]*?)\\\)/g, display: false },
  ];

  const matches: Array<{ start: number; end: number; latex: string; display: boolean }> = [];

  for (const pattern of patterns) {
    let match;
    while ((match = pattern.regex.exec(content)) !== null) {
      matches.push({
        start: match.index,
        end: match.index + match[0].length,
        latex: match[1].trim(),
        display: pattern.display,
      });
    }
  }

  matches.sort((a, b) => a.start - b.start);

  let lastEnd = 0;
  for (const match of matches) {
    if (match.start > lastEnd) {
      parts.push({ type: "text", content: content.slice(lastEnd, match.start) });
    }
    parts.push({ type: "math", content: match.latex, display: match.display });
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

export function InlineMath({ latex }: { latex: string }) {
  return <MathBlock latex={latex} display={false} />;
}

export function BlockMath({ latex }: { latex: string }) {
  return <MathBlock latex={latex} display={true} />;
}
