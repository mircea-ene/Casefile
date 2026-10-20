"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteDocument,
  listDocuments,
  uploadDocument,
  type DocumentItem,
} from "@/lib/api";

export type PendingUpload = {
  key: string;
  file: File;
  progress: number;
  error: string | null;
};

const POLL_MS = 4000;

export function useDocuments(enabled: boolean) {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [uploads, setUploads] = useState<PendingUpload[]>([]);
  const [deleteErrors, setDeleteErrors] = useState<Record<string, string>>({});
  const uploadSeq = useRef(0);

  const refresh = useCallback(async () => {
    try {
      setDocuments(await listDocuments());
    } catch {
      // No backend or no data yet: show the empty state.
      setDocuments([]);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (enabled) refresh();
  }, [enabled, refresh]);

  // Keep polling while the backend is still indexing something.
  const indexing = documents.some((d) => d.status === "processing");
  useEffect(() => {
    if (!indexing) return;
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [indexing, refresh]);

  const startUpload = useCallback(async (upload: PendingUpload) => {
    const update = (patch: Partial<PendingUpload>) =>
      setUploads((all) => all.map((u) => (u.key === upload.key ? { ...u, ...patch } : u)));
    try {
      const doc = await uploadDocument(upload.file, (progress) => update({ progress }));
      setUploads((all) => all.filter((u) => u.key !== upload.key));
      setDocuments((all) => [doc, ...all.filter((d) => d.id !== doc.id)]);
    } catch (e) {
      update({ error: e instanceof Error ? e.message : "Upload failed" });
    }
  }, []);

  const upload = useCallback(
    (files: Iterable<File>) => {
      for (const file of files) {
        const pending = { key: `u${uploadSeq.current++}`, file, progress: 0, error: null };
        setUploads((all) => [...all, pending]);
        startUpload(pending);
      }
    },
    [startUpload],
  );

  const retryUpload = useCallback(
    (key: string) => {
      const pending = uploads.find((u) => u.key === key);
      if (!pending) return;
      const reset = { ...pending, progress: 0, error: null };
      setUploads((all) => all.map((u) => (u.key === key ? reset : u)));
      startUpload(reset);
    },
    [uploads, startUpload],
  );

  const dismissUpload = useCallback((key: string) => {
    setUploads((all) => all.filter((u) => u.key !== key));
  }, []);

  const remove = useCallback(async (id: string) => {
    setDeleteErrors((errs) => {
      const next = { ...errs };
      delete next[id];
      return next;
    });
    try {
      await deleteDocument(id);
      setDocuments((all) => all.filter((d) => d.id !== id));
    } catch (e) {
      setDeleteErrors((errs) => ({
        ...errs,
        [id]: e instanceof Error ? e.message : "Delete failed",
      }));
    }
  }, []);

  return {
    documents,
    loaded,
    uploads,
    deleteErrors,
    upload,
    retryUpload,
    dismissUpload,
    remove,
  };
}
