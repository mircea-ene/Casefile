"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import type { ChatAnswer, PassageLocation, Source } from "@/lib/api";
import { formatPages } from "@/lib/format";
import { ChevronRightIcon, PanelOpenIcon } from "@/components/icons";
import { AnswerMarkdown } from "./answer-markdown";
import { DownloadButton, pagesLabel, useViewer } from "@/components/viewer/viewer-context";

export function AnswerView({ answer }: { answer: ChatAnswer }) {
  const { answer: text, citations, sources, insufficient_evidence } = answer;
  const baseId = useId();
  const citationId = (n: number) => `${baseId}-cite-${n}`;

  function jumpToCitation(n: number) {
    const el = document.getElementById(citationId(n));
    el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    el?.focus({ preventScroll: true });
  }

  return (
    <article>
      {insufficient_evidence && (
        <div className="mb-3">
          <p className="w-fit rounded-full border border-rule bg-surface px-2.5 py-0.5 text-sm font-medium text-muted">
            Your documents don&rsquo;t clearly answer this.
          </p>
          <p className="mt-2 text-sm text-muted">
            {sources.length
              ? `Searched ${sources.length} ${sources.length === 1 ? "passage" : "passages"}; none clearly answers the question.`
              : "Nothing in your documents was close enough to the question."}
          </p>
        </div>
      )}
      {text && (
        <AnswerMarkdown text={text} citationCount={citations.length} onCite={jumpToCitation} />
      )}
      {citations.length > 0 && (
        <ol className="mt-5 space-y-2.5" aria-label="Citations">
          {citations.map((c, i) => (
            <li
              key={`${c.id}-${i}`}
              id={citationId(i + 1)}
              tabIndex={-1}
              className="flex scroll-mt-4 gap-3 rounded-lg border border-rule bg-surface p-3.5 focus:ring-2 focus:ring-brand/40 focus:outline-none"
            >
              <span className="grid size-5 shrink-0 place-items-center rounded-full bg-brand/10 text-xs font-semibold text-brand">
                {i + 1}
              </span>
              <div className="min-w-0">
                <LocationLine location={c} />
                <Clamp collapsedClass="line-clamp-2" label="full quote" className="mt-1 font-serif leading-7">
                  &ldquo;<span className="highlight">{c.quote}</span>&rdquo;
                </Clamp>
              </div>
            </li>
          ))}
        </ol>
      )}
      {sources.length > 0 && <SourcesDisclosure sources={sources} />}
    </article>
  );
}

// The location opens the document at the passage when the browser can show the file (PDF, PNG,
// JPEG); other types offer the original as a download instead.
function LocationLine({ location, children }: { location: PassageLocation; children?: ReactNode }) {
  const viewer = useViewer();
  const viewable = viewer.kindOf(location.document_id, location.document_name) !== "other";
  const label = [
    location.document_name,
    location.section,
    formatPages(location.page, location.page_end),
  ]
    .filter(Boolean)
    .join(", ");
  const where = pagesLabel(location.page, location.page_end);
  return (
    <p
      className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted"
      title={location.heading_path ?? undefined}
    >
      {viewable ? (
        <button
          type="button"
          onClick={() => viewer.openPassage(location)}
          aria-label={`Open ${location.document_name}${where ? ` at ${where}` : ""}`}
          className="min-w-0 text-left break-words underline-offset-2 hover:text-ink hover:underline"
        >
          {label}
          <PanelOpenIcon className="ml-1 inline size-3.5 align-[-2px] text-brand" />
        </button>
      ) : (
        <>
          <span className="min-w-0 break-words">{label}</span>
          <DownloadButton documentId={location.document_id} name={location.document_name} />
        </>
      )}
      {location.text_source === "ocr" && (
        <span
          title="Read from a scan. The text may differ slightly from the printed page."
          className="rounded border border-rule px-1 text-[0.6875rem] leading-4 font-semibold tracking-wide"
        >
          OCR
        </span>
      )}
      {children}
    </p>
  );
}

// Every passage the model was given, in retrieval order. Collapsed by default.
function SourcesDisclosure({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const best = Math.max(...sources.map((s) => s.similarity)) || 1;

  return (
    <div className="mt-4">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1 rounded-md py-1 pr-2 text-sm font-medium text-muted hover:text-ink"
      >
        <ChevronRightIcon
          className={`size-4 transition-transform motion-reduce:transition-none ${open ? "rotate-90" : ""}`}
        />
        Sources ({sources.length})
      </button>
      {open && (
        <ol id={id} className="mt-2 space-y-2.5">
          {sources.map((s, i) => (
            <li key={`${s.id}-${i}`} className="rounded-lg border border-rule bg-surface p-3.5">
              <div className="flex items-start justify-between gap-3">
                <LocationLine location={s}>
                  {s.citation != null && (
                    <span className="rounded-full bg-brand/10 px-1.5 text-xs leading-5 font-semibold text-brand">
                      Cited [{s.citation}]
                    </span>
                  )}
                </LocationLine>
                <Relevance value={s.similarity / best} />
              </div>
              {s.heading_path && (
                <p className="mt-0.5 truncate text-xs text-muted" title={s.heading_path}>
                  {s.heading_path}
                </p>
              )}
              {s.element_type === "table" ? (
                <Clamp collapsedClass="max-h-32" label="full table" className="mt-2">
                  <pre className="overflow-x-auto font-mono text-xs leading-5">{s.content}</pre>
                </Clamp>
              ) : (
                <Clamp
                  collapsedClass="line-clamp-4"
                  label="full passage"
                  className="mt-2 font-serif leading-7 whitespace-pre-line"
                >
                  {s.content}
                </Clamp>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// Similarity is only meaningful relative to the other sources, so it's a bar, not a number.
function Relevance({ value }: { value: number }) {
  return (
    <span
      title="Relevance compared with the other sources"
      className="mt-1.5 h-1 w-12 shrink-0 overflow-hidden rounded-full bg-rule"
    >
      <span className="block h-full rounded-full bg-brand/60" style={{ width: `${value * 100}%` }} />
    </span>
  );
}

// Starts collapsed; the toggle only appears when the content overflows.
function Clamp({
  collapsedClass,
  label,
  className = "",
  children,
}: {
  collapsedClass: string;
  label: string;
  className?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const id = useId();

  useEffect(() => {
    const el = ref.current;
    if (!el || expanded) return;
    const observer = new ResizeObserver(() => setOverflows(el.scrollHeight > el.clientHeight + 1));
    observer.observe(el);
    return () => observer.disconnect();
  }, [expanded]);

  return (
    <div>
      <div
        id={id}
        ref={ref}
        className={`${className} ${expanded ? "" : `overflow-hidden ${collapsedClass}`}`}
      >
        {children}
      </div>
      {(overflows || expanded) && (
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={id}
          onClick={() => setExpanded((e) => !e)}
          className="mt-1 text-sm font-medium text-brand underline-offset-4 hover:underline"
        >
          {expanded ? "Show less" : `Show ${label}`}
        </button>
      )}
    </div>
  );
}
