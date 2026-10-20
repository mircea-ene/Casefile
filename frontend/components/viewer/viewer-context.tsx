"use client";

import { createContext, useContext, useState } from "react";
import { ApiError, type PassageLocation } from "@/lib/api";
import { DownloadIcon } from "@/components/icons";
import { downloadOriginal, type FileKind } from "./files";

export type ViewerActions = {
  openPassage: (location: PassageLocation) => void;
  openDocument: (documentId: string) => void;
  kindOf: (documentId: string, name: string) => FileKind;
};

export const ViewerContext = createContext<ViewerActions | null>(null);

export function useViewer(): ViewerActions {
  const viewer = useContext(ViewerContext);
  if (!viewer) throw new Error("useViewer needs a ViewerContext provider");
  return viewer;
}

// "page 3", "pages 3–4", or "" when the format has no pages.
export function pagesLabel(page: number | null, pageEnd: number | null): string {
  if (page == null) return "";
  return pageEnd != null && pageEnd !== page ? `pages ${page}–${pageEnd}` : `page ${page}`;
}

export function DownloadButton({
  documentId,
  name,
  label = "Download original",
  className = "",
}: {
  documentId: string;
  name: string;
  label?: string;
  className?: string;
}) {
  const [state, setState] = useState<"idle" | "busy" | "deleted" | "failed">("idle");

  async function download() {
    setState("busy");
    try {
      await downloadOriginal(documentId);
      setState("idle");
    } catch (e) {
      setState(e instanceof ApiError && e.status === 404 ? "deleted" : "failed");
    }
  }

  if (state === "deleted") {
    return <span className="text-xs text-muted">This document has been deleted</span>;
  }
  return (
    <button
      type="button"
      onClick={download}
      disabled={state === "busy"}
      aria-label={`${label}: ${name}`}
      className={`inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline disabled:opacity-60 ${className}`}
    >
      <DownloadIcon className="size-3.5" />
      {state === "failed" ? "Download failed, retry" : label}
    </button>
  );
}
