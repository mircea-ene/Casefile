"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { ApiError, type BoundingBox } from "@/lib/api";
import {
  ChevronDownIcon,
  ChevronUpIcon,
  ExternalLinkIcon,
  MinusIcon,
  PlusIcon,
  XIcon,
} from "@/components/icons";
import { fileUrl, openInNewTab, type FileKind } from "./files";
import { Highlights, type ScrollRequest } from "./highlights";
import { DownloadButton } from "./viewer-context";

// pdf.js needs the browser (canvas, worker), so it's loaded on the client only.
const PdfPages = dynamic(() => import("./pdf-pages").then((m) => m.PdfPages), {
  ssr: false,
  loading: () => <Status>Loading viewer…</Status>,
});

type File =
  | { status: "loading" }
  | { status: "ready"; url: string; filename: string }
  | { status: "deleted" }
  | { status: "failed" };

type Props = {
  documentId: string;
  name: string;
  kind: FileKind;
  bboxes: BoundingBox[];
  scroll: ScrollRequest;
  onClose: () => void;
};

const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3];

// Keyed by document id: a new document gets a fresh viewer, a new passage in the same one only scrolls.
export function DocumentViewer({ documentId, name, kind, bboxes, scroll, onClose }: Props) {
  const [file, setFile] = useState<File>({ status: "loading" });
  const [numPages, setNumPages] = useState(0);
  const [page, setPage] = useState(scroll.page);
  const [zoom, setZoom] = useState(1);
  const [request, setRequest] = useState(scroll);
  const [openError, setOpenError] = useState(false);
  // One automatic retry with a fresh URL when S3 refuses the file (e.g. the URL expired).
  const retried = useRef(false);

  // Follow scroll requests from links; render-time sync avoids a second pass through an effect.
  const [lastScrollKey, setLastScrollKey] = useState(scroll.key);
  if (scroll.key !== lastScrollKey) {
    setLastScrollKey(scroll.key);
    setRequest(scroll);
    setPage(scroll.page);
  }

  useEffect(() => {
    let cancelled = false;
    fileUrl(documentId)
      .then((f) => !cancelled && setFile({ status: "ready", url: f.url, filename: f.filename }))
      .catch((e) => {
        if (cancelled) return;
        setFile({ status: e instanceof ApiError && e.status === 404 ? "deleted" : "failed" });
      });
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  async function reload() {
    setFile({ status: "loading" });
    try {
      const f = await fileUrl(documentId, true);
      setFile({ status: "ready", url: f.url, filename: f.filename });
    } catch (e) {
      setFile({ status: e instanceof ApiError && e.status === 404 ? "deleted" : "failed" });
    }
  }

  function onFileError() {
    if (retried.current) {
      setFile({ status: "failed" });
      return;
    }
    retried.current = true;
    reload();
  }

  function goToPage(n: number) {
    const target = Math.min(Math.max(1, n), numPages || 1);
    setPage(target);
    setRequest({ page: target, y: 0, key: `nav-${target}-${Date.now()}` });
  }

  async function openTab() {
    setOpenError(false);
    try {
      await openInNewTab(documentId);
    } catch {
      setOpenError(true);
    }
  }

  const title = file.status === "ready" ? file.filename : name;
  const zoomIndex = ZOOM_STEPS.indexOf(zoom);
  const iconButton =
    "grid size-8 place-items-center rounded-md text-muted hover:bg-paper hover:text-ink disabled:opacity-40 disabled:hover:bg-transparent";

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface">
      <div className="flex items-center gap-2 border-b border-rule px-3 py-2">
        <h2 className="min-w-0 flex-1 truncate text-sm font-semibold" title={title}>
          {title}
        </h2>
        <button type="button" onClick={onClose} aria-label="Close document" title="Close" className={iconButton}>
          <XIcon className="size-4" />
        </button>
      </div>

      {file.status === "ready" && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-rule px-3 py-1.5 text-sm">
          {kind === "pdf" && (
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => goToPage(page - 1)}
                disabled={page <= 1}
                aria-label="Previous page"
                title="Previous page"
                className={iconButton}
              >
                <ChevronUpIcon className="size-4" />
              </button>
              <button
                type="button"
                onClick={() => goToPage(page + 1)}
                disabled={page >= numPages}
                aria-label="Next page"
                title="Next page"
                className={iconButton}
              >
                <ChevronDownIcon className="size-4" />
              </button>
              <span className="text-muted tabular-nums" aria-live="polite">
                {numPages ? `Page ${page} of ${numPages}` : "Loading…"}
              </span>
            </div>
          )}
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setZoom(ZOOM_STEPS[zoomIndex - 1])}
              disabled={zoomIndex <= 0}
              aria-label="Zoom out"
              title="Zoom out"
              className={iconButton}
            >
              <MinusIcon className="size-4" />
            </button>
            <button
              type="button"
              onClick={() => setZoom(1)}
              title="Fit width"
              className="min-w-14 rounded-md px-1.5 py-1 text-muted tabular-nums hover:bg-paper hover:text-ink"
            >
              {zoom === 1 ? "Fit" : `${Math.round(zoom * 100)}%`}
            </button>
            <button
              type="button"
              onClick={() => setZoom(ZOOM_STEPS[zoomIndex + 1])}
              disabled={zoomIndex >= ZOOM_STEPS.length - 1}
              aria-label="Zoom in"
              title="Zoom in"
              className={iconButton}
            >
              <PlusIcon className="size-4" />
            </button>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <button
              type="button"
              onClick={openTab}
              className="inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
            >
              <ExternalLinkIcon className="size-3.5" />
              {openError ? "Couldn't open, retry" : "Open in new tab"}
            </button>
            <DownloadButton documentId={documentId} name={title} label="Download" />
          </div>
        </div>
      )}

      {file.status === "loading" && <Status>Opening document…</Status>}
      {file.status === "deleted" && <Status>This document has been deleted.</Status>}
      {file.status === "failed" && (
        <Status>
          Couldn&rsquo;t load this document.{" "}
          <button
            type="button"
            onClick={() => {
              retried.current = false;
              reload();
            }}
            className="font-medium text-brand underline"
          >
            Try again
          </button>
        </Status>
      )}
      {file.status === "ready" && kind === "pdf" && (
        <PdfPages
          url={file.url}
          zoom={zoom}
          bboxes={bboxes}
          scroll={request}
          onLoad={setNumPages}
          onError={onFileError}
          onPageChange={setPage}
        />
      )}
      {file.status === "ready" && kind === "image" && (
        <ImagePage url={file.url} alt={title} zoom={zoom} bboxes={bboxes} scroll={request} onError={onFileError} />
      )}
      {file.status === "ready" && kind === "other" && (
        <Status>
          This file type can&rsquo;t be shown here.{" "}
          <DownloadButton documentId={documentId} name={title} className="text-sm" />
        </Status>
      )}
    </div>
  );
}

function Status({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-1 items-center justify-center p-6 text-center text-sm text-muted" role="status">
      <p>{children}</p>
    </div>
  );
}

// PNG/JPEG: a single "page" with the same percentage overlays.
function ImagePage({
  url,
  alt,
  zoom,
  bboxes,
  scroll,
  onError,
}: {
  url: string;
  alt: string;
  zoom: number;
  bboxes: BoundingBox[];
  scroll: ScrollRequest;
  onError: () => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLDivElement>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    const image = imageRef.current;
    if (!loaded || !container || !image) return;
    container.scrollTo({ top: Math.max(0, image.offsetTop + scroll.y * image.offsetHeight - 24) });
  }, [scroll.key, loaded, scroll.y]);

  return (
    <div ref={containerRef} className="relative min-h-0 flex-1 overflow-auto bg-paper p-4 [scrollbar-gutter:stable]">
      <div ref={imageRef} className="relative mx-auto bg-white shadow-sm" style={{ width: `${zoom * 100}%` }}>
        {/* eslint-disable-next-line @next/next/no-img-element -- presigned S3 URL, not optimizable */}
        <img src={url} alt={alt} onLoad={() => setLoaded(true)} onError={onError} className="block w-full" />
        {loaded && <Highlights bboxes={bboxes} page={1} />}
      </div>
    </div>
  );
}
