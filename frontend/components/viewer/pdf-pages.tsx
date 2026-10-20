"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import type { PDFDocumentProxy } from "pdfjs-dist";
import "react-pdf/dist/Page/TextLayer.css";
import type { BoundingBox } from "@/lib/api";
import { Highlights, type ScrollRequest } from "./highlights";

// Must be set in the module that renders <Document> (react-pdf docs).
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

// S3's CORS rule doesn't expose Content-Range, so pdf.js can't use range requests.
const OPTIONS = { disableRange: true, disableStream: true };
const GUTTER = 16;

type Props = {
  url: string;
  zoom: number; // 1 = fit width
  bboxes: BoundingBox[];
  scroll: ScrollRequest;
  onLoad: (numPages: number) => void;
  onError: () => void;
  onPageChange: (page: number) => void;
};

// Renders every page in a scrolling column. Page boxes get their size from the PDF up front, so
// scrolling to a passage works before the canvases have rendered.
export function PdfPages({ url, zoom, bboxes, scroll, onLoad, onError, onPageChange }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<(HTMLDivElement | null)[]>([]);
  const [containerWidth, setContainerWidth] = useState(0);
  const [ratios, setRatios] = useState<number[] | null>(null); // height / width per page
  // Scroll position as a fraction of the content height, kept when zoom or panel width changes.
  const scrollFraction = useRef(0);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setContainerWidth(el.clientWidth));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  async function onLoadSuccess(pdf: PDFDocumentProxy) {
    const pages = await Promise.all(
      Array.from({ length: pdf.numPages }, (_, i) => pdf.getPage(i + 1)),
    );
    setRatios(
      pages.map((page) => {
        const viewport = page.getViewport({ scale: 1 });
        return viewport.height / viewport.width;
      }),
    );
    onLoad(pdf.numPages);
  }

  const ready = ratios !== null && containerWidth > 0;
  useEffect(() => {
    const container = containerRef.current;
    const pageEl = pageRefs.current[scroll.page - 1];
    if (!ready || !container || !pageEl) return;
    const top =
      pageEl.getBoundingClientRect().top -
      container.getBoundingClientRect().top +
      container.scrollTop +
      scroll.y * pageEl.offsetHeight;
    container.scrollTo({ top: Math.max(0, top - 24) });
    // Only a new request (or the first layout) scrolls; zooming keeps the reader's place.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scroll.key, ready]);

  function onScroll() {
    const container = containerRef.current;
    if (!container) return;
    scrollFraction.current = container.scrollTop / container.scrollHeight;
    const probe = container.getBoundingClientRect().top + container.clientHeight / 3;
    let current = 1;
    pageRefs.current.forEach((el, i) => {
      if (el && el.getBoundingClientRect().top <= probe) current = i + 1;
    });
    onPageChange(current);
  }

  // The container reserves its scrollbar gutter, so the width (and every page's position) doesn't
  // change when the scrollbar appears after the first scroll to a passage.
  const width = Math.max(200, (containerWidth - GUTTER * 2) * zoom);

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (container) container.scrollTop = scrollFraction.current * container.scrollHeight;
  }, [width]);

  return (
    <div ref={containerRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-auto bg-paper py-4 [scrollbar-gutter:stable]">
      <Document
        file={url}
        options={OPTIONS}
        suspense={false}
        onLoadSuccess={onLoadSuccess}
        onLoadError={onError}
        onSourceError={onError}
        loading={<p className="p-6 text-sm text-muted">Loading document…</p>}
        error={null}
      >
        {ready &&
          ratios.map((ratio, i) => (
            <div
              key={i}
              ref={(el) => {
                pageRefs.current[i] = el;
              }}
              className="relative mx-auto mb-4 bg-white shadow-sm"
              style={{ width, height: width * ratio }}
            >
              <Page
                pageNumber={i + 1}
                width={width}
                suspense={false}
                renderAnnotationLayer={false}
                loading={null}
              />
              <Highlights bboxes={bboxes} page={i + 1} />
            </div>
          ))}
      </Document>
    </div>
  );
}
