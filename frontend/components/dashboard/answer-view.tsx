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

const HEADING_SEPARATOR = " > ";

type SourceGroup = {
  key: string;
  documentName: string;
  section: string | null; // top-level section label, e.g. "2. VOTOCAST'S OBLIGATIONS"
  sectionPath: string | null; // heading_path up to that section, as a tooltip
  sources: Source[];
};

// Consecutive sources from the same document and top-level section (heading_path up to its
// second part; the first part is the document's own title). Keeps the backend order: whole
// sections come in document order, so their passages stay together.
function groupBySection(sources: Source[]): SourceGroup[] {
  const groups: SourceGroup[] = [];
  for (const s of sources) {
    const parts = s.heading_path?.split(HEADING_SEPARATOR) ?? [];
    const sectionPath = parts.length ? parts.slice(0, 2).join(HEADING_SEPARATOR) : null;
    const key = `${s.document_id}|${sectionPath ?? ""}`;
    const last = groups.at(-1);
    if (last?.key === key) {
      last.sources.push(s);
      continue;
    }
    groups.push({
      key,
      documentName: s.document_name,
      section: parts.length ? parts[Math.min(1, parts.length - 1)] : null,
      sectionPath,
      sources: [s],
    });
  }
  return groups;
}

// The rest of a source's heading path below its group's section, unless it only repeats the
// `section` label the location line already shows.
function subHeading(source: Source): string | null {
  const parts = source.heading_path?.split(HEADING_SEPARATOR) ?? [];
  const below = parts.length > 2 ? parts.slice(2).join(HEADING_SEPARATOR) : null;
  return below === source.section ? null : below;
}

// Every passage the model was given. Collapsed by default; inside, the cited passages come
// first, then the rest ("Also read"), each grouped by section in the order the model saw them.
// Relevance bars compare against the best source overall but never reorder anything.
function SourcesDisclosure({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const best = Math.max(...sources.map((s) => s.similarity)) || 1;
  const cited = sources.filter((s) => s.citation != null);
  const rest = sources.filter((s) => s.citation == null);

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
        {cited.length > 0 && rest.length > 0 && (
          <span className="font-normal">
            {" "}
            · {cited.length} cited
          </span>
        )}
      </button>
      {open && (
        <div id={id} className="mt-2 space-y-5">
          {cited.length > 0 && (
            <SourceList
              title={rest.length ? `Cited (${cited.length})` : null}
              sources={cited}
              best={best}
              groupsOpen
            />
          )}
          {rest.length > 0 && (
            <SourceList
              title={cited.length ? `Also read (${rest.length})` : null}
              sources={rest}
              best={best}
              groupsOpen={false}
            />
          )}
        </div>
      )}
    </div>
  );
}

function SourceList({
  title,
  sources,
  best,
  groupsOpen,
}: {
  title: string | null;
  sources: Source[];
  best: number;
  groupsOpen: boolean;
}) {
  return (
    <section>
      {title && (
        <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{title}</h3>
      )}
      <ul className="space-y-2">
        {groupBySection(sources).map((group, i) => (
          <li key={`${group.key}-${i}`}>
            <SectionGroup group={group} best={best} defaultOpen={groupsOpen} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function SectionGroup({
  group,
  best,
  defaultOpen,
}: {
  group: SourceGroup;
  best: number;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  const count = group.sources.length;

  return (
    <div className="rounded-lg border border-rule">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        title={group.sectionPath ?? undefined}
        className="flex w-full items-start gap-1.5 rounded-lg px-3 py-2 text-left text-sm hover:bg-surface"
      >
        <ChevronRightIcon
          className={`mt-0.5 size-4 shrink-0 text-muted transition-transform motion-reduce:transition-none ${open ? "rotate-90" : ""}`}
        />
        <span className="min-w-0 flex-1">
          <span className="block font-medium break-words">{group.section ?? group.documentName}</span>
          {group.section && (
            <span className="block truncate text-xs text-muted">{group.documentName}</span>
          )}
        </span>
        <span className="shrink-0 text-xs text-muted tabular-nums">
          {count} {count === 1 ? "passage" : "passages"}
        </span>
      </button>
      {open && (
        <ol id={id} className="space-y-2 px-2 pb-2">
          {group.sources.map((s, i) => (
            <SourceCard key={`${s.id}-${i}`} source={s} best={best} />
          ))}
        </ol>
      )}
    </div>
  );
}

function SourceCard({ source: s, best }: { source: Source; best: number }) {
  const below = subHeading(s);
  return (
    <li className="rounded-md border border-rule bg-surface p-3.5">
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
      {below && (
        <p className="mt-0.5 truncate text-xs text-muted" title={s.heading_path ?? undefined}>
          {below}
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
