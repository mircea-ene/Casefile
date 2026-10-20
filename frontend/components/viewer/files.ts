"use client";

import { getDocumentFileUrl, type DocumentFileUrl } from "@/lib/api";

export type FileKind = "pdf" | "image" | "other";

// PDFs and PNG/JPEG get the highlighting viewer; everything else (TIFF, Word, text) is download-only.
export function fileKind(contentType: string | undefined, name: string): FileKind {
  const type = contentType ?? extensionType(name);
  if (type === "application/pdf") return "pdf";
  if (type === "image/png" || type === "image/jpeg") return "image";
  return "other";
}

function extensionType(name: string): string | undefined {
  const ext = name.split(".").pop()?.toLowerCase();
  if (ext === "pdf") return "application/pdf";
  if (ext === "png") return "image/png";
  if (ext === "jpg" || ext === "jpeg") return "image/jpeg";
  return undefined;
}

// Presigned URLs live only in memory, reused until shortly before they expire.
const cache = new Map<string, DocumentFileUrl>();
const EXPIRY_MARGIN_MS = 30_000;

export async function fileUrl(documentId: string, fresh = false): Promise<DocumentFileUrl> {
  const hit = cache.get(documentId);
  if (!fresh && hit && Date.parse(hit.expires_at) - Date.now() > EXPIRY_MARGIN_MS) return hit;
  const next = await getDocumentFileUrl(documentId);
  cache.set(documentId, next);
  return next;
}

export async function downloadOriginal(documentId: string) {
  const { url } = await getDocumentFileUrl(documentId, true);
  // The URL answers with Content-Disposition: attachment, so this doesn't leave the page.
  const link = document.createElement("a");
  link.href = url;
  link.rel = "noopener";
  document.body.append(link);
  link.click();
  link.remove();
}

export async function openInNewTab(documentId: string) {
  // Opened before the request so popup blockers still see a user gesture.
  const tab = window.open("", "_blank");
  try {
    const { url } = await fileUrl(documentId, true);
    if (tab) {
      tab.opener = null;
      tab.location.href = url;
    }
  } catch (e) {
    tab?.close();
    throw e;
  }
}
