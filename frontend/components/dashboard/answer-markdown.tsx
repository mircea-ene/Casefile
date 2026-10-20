"use client";

import Markdown, { type Components } from "react-markdown";
import type { Nodes, Parent, Root } from "mdast";

// The answer prompt asks for this Markdown subset only. Anything else (headings, links, tables,
// code) is unwrapped to its text. Raw HTML is escaped: there is deliberately no rehype-raw.
const ALLOWED_ELEMENTS = ["p", "ul", "ol", "li", "strong", "em", "br", "sup"];

const MARKER = /\[(\d+)\]/g;

// Remark plugin: splits "[n]" markers out of every text node into <sup data-cite="n"> elements,
// wherever they sit (paragraphs, list items, after bold text, inside unwrapped elements).
// Markers outside 1..citationCount stay plain text.
function remarkCitations({ citationCount }: { citationCount: number }) {
  function split(parent: Parent) {
    parent.children = parent.children.flatMap((child) => {
      if ("children" in child) split(child as Parent);
      if (child.type !== "text") return [child];
      const parts: Nodes[] = [];
      let last = 0;
      for (const match of child.value.matchAll(MARKER)) {
        const n = Number(match[1]);
        if (n < 1 || n > citationCount) continue;
        if (match.index > last) parts.push({ type: "text", value: child.value.slice(last, match.index) });
        // Unknown node types become the element named in data.hName when converted to HTML.
        parts.push({
          type: "text",
          value: String(n),
          data: { hName: "sup", hProperties: { dataCite: n } },
        });
        last = match.index + match[0].length;
      }
      if (!parts.length) return [child];
      if (last < child.value.length) parts.push({ type: "text", value: child.value.slice(last) });
      return parts;
    }) as Parent["children"];
  }
  return (tree: Root) => split(tree);
}

type Props = {
  text: string;
  citationCount: number;
  onCite: (n: number) => void;
};

export function AnswerMarkdown({ text, citationCount, onCite }: Props) {
  const components: Components = {
    // Single newlines inside a paragraph stay line breaks, as in answers saved before Markdown.
    p: ({ children }) => <p className="mt-4 whitespace-pre-line first:mt-0">{children}</p>,
    ul: ({ children }) => (
      <ul className="mt-2 list-disc space-y-2 pl-6 [li_&]:pl-5">{children}</ul>
    ),
    ol: ({ children, start }) => (
      <ol start={start} className="mt-2 list-decimal space-y-2 pl-6 [li_&]:pl-5">
        {children}
      </ol>
    ),
    // A scanning aid for clause labels, not an accent: same color as the text.
    strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
    sup: ({ node, children }) => {
      const n = Number(node?.properties?.dataCite);
      return (
        <sup className="ml-0.5 font-sans text-xs font-semibold text-brand">
          <button
            type="button"
            onClick={() => onCite(n)}
            aria-label={`Citation ${n}`}
            className="rounded-sm px-0.5 hover:underline"
          >
            {children}
          </button>
        </sup>
      );
    },
  };

  return (
    <div className="font-serif text-lg leading-8">
      <Markdown
        allowedElements={ALLOWED_ELEMENTS}
        unwrapDisallowed
        remarkPlugins={[[remarkCitations, { citationCount }]]}
        components={components}
      >
        {text}
      </Markdown>
    </div>
  );
}
