"use client";

import { useRef, useState, type DragEvent } from "react";
import type { DocumentItem } from "@/lib/api";
import { formatSize } from "@/lib/format";
import type { PendingUpload } from "./use-documents";
import { DownloadIcon, FileIcon, PanelOpenIcon, TrashIcon, UploadIcon } from "@/components/icons";
import { downloadOriginal } from "@/components/viewer/files";
import { useViewer } from "@/components/viewer/viewer-context";

const ACCEPT = ".pdf,.doc,.docx,.txt,.rtf,.png,.jpg,.jpeg,.tif,.tiff";

const STATUS_LABEL: Record<DocumentItem["status"], string> = {
  processing: "Indexing…",
  ready: "Ready",
  failed: "Couldn't index",
};

const STATUS_DOT: Record<DocumentItem["status"], string> = {
  processing: "bg-brand motion-safe:animate-pulse",
  ready: "bg-ok",
  failed: "bg-danger",
};

type Props = {
  documents: DocumentItem[];
  loaded: boolean;
  uploads: PendingUpload[];
  deleteErrors: Record<string, string>;
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
  upload: (files: Iterable<File>) => void;
  retryUpload: (key: string) => void;
  dismissUpload: (key: string) => void;
  remove: (id: string) => Promise<void>;
};

export function DocumentsPanel(props: Props) {
  const { documents, loaded, uploads, upload } = props;
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length) upload(event.dataTransfer.files);
  }

  const empty = loaded && documents.length === 0 && uploads.length === 0;

  return (
    <div
      className={`flex min-h-0 flex-1 flex-col ${dragging ? "bg-brand/5 ring-2 ring-inset ring-brand/40" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={onDrop}
    >
      <div className="flex items-center justify-between gap-3 px-5 pt-5">
        <h2 className="font-serif text-lg font-semibold">
          Documents
          {documents.length > 0 && (
            <span className="ml-2 font-sans text-sm font-normal text-muted tabular-nums">
              {documents.length}
            </span>
          )}
        </h2>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="inline-flex items-center gap-1.5 rounded-md bg-brand px-3 py-1.5 text-sm font-semibold text-brand-ink transition-opacity hover:opacity-90"
        >
          <UploadIcon className="size-4" />
          Upload
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT}
          className="sr-only"
          tabIndex={-1}
          onChange={(e) => {
            if (e.target.files?.length) upload(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {empty ? (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="m-5 flex flex-1 flex-col items-center justify-center rounded-lg border-2 border-dashed border-rule px-6 text-center transition-colors hover:border-brand/50 hover:bg-paper"
        >
          <span className="mb-3 grid size-11 place-items-center rounded-xl bg-brand/10 text-brand">
            <UploadIcon className="size-5" />
          </span>
          <span className="font-medium">No documents yet</span>
          <span className="mt-1 text-sm text-muted">
            Upload files or drop them here. PDF, Word, text and scanned images work.
          </span>
        </button>
      ) : (
        <>
          <p className="px-5 pt-2 text-sm text-muted">
            Tick documents to limit the chat to them. With none ticked, the chat uses all of
            them.
          </p>
          <ul className="mt-3 min-h-0 flex-1 overflow-y-auto px-2 pb-4">
            {uploads.map((u) => (
              <UploadRow key={u.key} {...props} item={u} />
            ))}
            {documents.map((doc) => (
              <DocumentRow key={doc.id} {...props} doc={doc} />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function UploadRow({
  item: upload,
  retryUpload,
  dismissUpload,
}: { item: PendingUpload } & Props) {
  return (
    <li className="rounded-md px-3 py-2.5">
      <div className="flex items-center gap-3">
        <FileIcon className="size-4 text-muted" />
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{upload.file.name}</span>
        <span className="shrink-0 text-xs text-muted tabular-nums">{formatSize(upload.file.size)}</span>
      </div>
      {upload.error ? (
        <p className="mt-1 pl-7 text-xs text-danger">
          {upload.error}.{" "}
          <button type="button" className="underline" onClick={() => retryUpload(upload.key)}>
            Retry
          </button>{" "}
          <button type="button" className="underline" onClick={() => dismissUpload(upload.key)}>
            Dismiss
          </button>
        </p>
      ) : (
        <div
          className="mt-2 ml-7 h-1 overflow-hidden rounded-full bg-rule"
          role="progressbar"
          aria-label={`Uploading ${upload.file.name}`}
          aria-valuenow={Math.round(upload.progress * 100)}
        >
          <div
            className="h-full bg-brand transition-[width]"
            style={{ width: `${Math.round(upload.progress * 100)}%` }}
          />
        </div>
      )}
    </li>
  );
}

function DocumentRow({
  doc,
  selectedIds,
  onToggle,
  remove,
  deleteErrors,
}: { doc: DocumentItem } & Props) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [downloadFailed, setDownloadFailed] = useState(false);
  const viewer = useViewer();
  const viewable = viewer.kindOf(doc.id, doc.filename) !== "other";
  const ready = doc.status === "ready";

  async function download() {
    setDownloadFailed(false);
    try {
      await downloadOriginal(doc.id);
    } catch {
      setDownloadFailed(true);
    }
  }
  const checkboxId = `doc-${doc.id}`;

  async function onDelete() {
    setDeleting(true);
    await remove(doc.id);
    setDeleting(false);
    setConfirming(false);
  }

  return (
    <li
      className={`group rounded-md px-3 py-2.5 transition-colors ${
        selectedIds.has(doc.id) ? "bg-brand/5" : "hover:bg-paper"
      }`}
    >
      <div className="flex items-start gap-3">
        <input
          id={checkboxId}
          type="checkbox"
          checked={selectedIds.has(doc.id)}
          disabled={!ready}
          onChange={() => onToggle(doc.id)}
          className="mt-0.5 size-4 accent-[var(--brand)] disabled:opacity-40"
        />
        <label htmlFor={checkboxId} className="min-w-0 flex-1 cursor-pointer">
          <span className="block truncate text-sm font-medium">{doc.filename}</span>
          <span
            className={`mt-0.5 flex items-center gap-1.5 text-xs ${doc.status === "failed" ? "text-danger" : "text-muted"}`}
          >
            <span aria-hidden="true" className={`size-1.5 rounded-full ${STATUS_DOT[doc.status]}`} />
            <span className="tabular-nums">{formatSize(doc.size_bytes)}</span> ·{" "}
            {STATUS_LABEL[doc.status]}
          </span>
        </label>
        {viewable ? (
          <button
            type="button"
            onClick={() => viewer.openDocument(doc.id)}
            aria-label={`Open ${doc.filename}`}
            title="Open"
            className="grid size-7 shrink-0 place-items-center rounded-md text-muted hover:bg-brand/10 hover:text-brand"
          >
            <PanelOpenIcon className="size-4" />
          </button>
        ) : (
          <button
            type="button"
            onClick={download}
            aria-label={`Download ${doc.filename}`}
            title="Download original"
            className="grid size-7 shrink-0 place-items-center rounded-md text-muted hover:bg-brand/10 hover:text-brand"
          >
            <DownloadIcon className="size-4" />
          </button>
        )}
        {!confirming && (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            aria-label={`Delete ${doc.filename}`}
            title="Delete"
            className="grid size-7 shrink-0 place-items-center rounded-md text-muted opacity-100 hover:bg-danger/10 hover:text-danger lg:opacity-0 lg:group-hover:opacity-100 lg:focus:opacity-100"
          >
            <TrashIcon className="size-4" />
          </button>
        )}
      </div>
      {confirming && (
        <div className="mt-2 flex items-center gap-3 pl-7 text-sm">
          <span>Delete this document?</span>
          <button
            type="button"
            onClick={onDelete}
            disabled={deleting}
            className="font-semibold text-danger underline disabled:opacity-60"
          >
            {deleting ? "Deleting…" : "Delete"}
          </button>
          <button type="button" onClick={() => setConfirming(false)} className="underline">
            Cancel
          </button>
        </div>
      )}
      {downloadFailed && <p className="mt-1 pl-7 text-xs text-danger">Couldn&rsquo;t download.</p>}
      {deleteErrors[doc.id] && (
        <p className="mt-1 pl-7 text-xs text-danger">{deleteErrors[doc.id]}</p>
      )}
    </li>
  );
}
