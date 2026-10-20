"use client";

import { useState, type KeyboardEvent, type MouseEvent } from "react";
import { MAX_TITLE_LENGTH, type ConversationSummary } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { PencilIcon, PlusIcon, TrashIcon } from "@/components/icons";

type Props = {
  conversations: ConversationSummary[];
  loaded: boolean;
  activeId: string | null;
  onSelect: (id: string | null) => void;
  rename: (id: string, title: string | null) => Promise<void>;
  remove: (id: string) => Promise<void>;
};

export function ConversationList({ conversations, loaded, activeId, onSelect, rename, remove }: Props) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="px-3 pt-4">
        <button
          type="button"
          onClick={() => onSelect(null)}
          className="flex w-full items-center justify-center gap-1.5 rounded-md border border-rule bg-surface px-3 py-2 text-sm font-medium hover:bg-paper"
        >
          <PlusIcon className="size-4" />
          New chat
        </button>
      </div>
      <p className="px-6 pt-5 pb-2 text-xs font-semibold tracking-wider text-muted uppercase">
        History
      </p>
      {loaded && conversations.length === 0 ? (
        <p className="px-6 text-sm text-muted">Your chats will be listed here.</p>
      ) : (
        <ul className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-3 pb-4" aria-label="Chats">
          {conversations.map((c) => (
            <ConversationRow
              key={c.id}
              conversation={c}
              active={c.id === activeId}
              onSelect={onSelect}
              rename={rename}
              remove={remove}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function ConversationRow({
  conversation: c,
  active,
  onSelect,
  rename,
  remove,
}: { conversation: ConversationSummary; active: boolean } & Pick<
  Props,
  "onSelect" | "rename" | "remove"
>) {
  const [mode, setMode] = useState<"view" | "rename" | "delete">("view");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function open(event: MouseEvent<HTMLAnchorElement>) {
    // Let modified clicks open the chat in a new tab.
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    onSelect(c.id);
  }

  async function run(action: () => Promise<void>, failure: string) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setMode("view");
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : failure);
    } finally {
      setBusy(false);
    }
  }

  function onRenameKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setMode("view");
      setError(null);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const title = event.currentTarget.value.trim();
      // Empty resets to the generated title.
      run(() => rename(c.id, title || null), "Couldn't rename");
    }
  }

  if (mode === "rename") {
    return (
      <li className="rounded-md bg-surface px-2 py-2">
        <label htmlFor={`rename-${c.id}`} className="sr-only">
          Chat title
        </label>
        <input
          id={`rename-${c.id}`}
          autoFocus
          defaultValue={c.title_is_custom ? c.title : ""}
          placeholder={c.title_is_custom ? "Automatic title" : c.title}
          maxLength={MAX_TITLE_LENGTH}
          disabled={busy}
          onKeyDown={onRenameKeyDown}
          onBlur={() => !busy && setMode("view")}
          className="block w-full rounded border border-brand bg-surface px-2 py-1 text-sm focus:ring-2 focus:ring-brand/25 focus:outline-none"
        />
        <p className="mt-1 text-xs text-muted">
          Enter to save, Esc to cancel. Leave empty for the automatic title.
        </p>
        {error && <p className="mt-1 text-xs text-danger">{error}</p>}
      </li>
    );
  }

  return (
    <li
      className={`group relative rounded-md ${
        active ? "bg-surface shadow-[inset_2px_0_0_var(--brand)]" : "hover:bg-surface/70"
      }`}
    >
      <a
        href={`/?c=${encodeURIComponent(c.id)}`}
        onClick={open}
        aria-current={active ? "page" : undefined}
        className="block rounded-md px-3 py-2 pr-16"
      >
        <span
          className={`block truncate text-sm ${active ? "font-medium text-ink" : "text-ink/90"} ${
            c.title_pending ? "text-muted italic" : ""
          }`}
        >
          {c.title}
        </span>
        <span className="block text-xs text-muted">{formatRelative(c.updated_at)}</span>
      </a>
      {mode === "view" && (
        <div className="absolute top-1.5 right-1.5 flex opacity-100 lg:opacity-0 lg:group-hover:opacity-100 lg:focus-within:opacity-100">
          <button
            type="button"
            onClick={() => setMode("rename")}
            aria-label={`Rename ${c.title}`}
            title="Rename"
            className="grid size-7 place-items-center rounded-md text-muted hover:bg-paper hover:text-ink"
          >
            <PencilIcon className="size-3.5" />
          </button>
          <button
            type="button"
            onClick={() => setMode("delete")}
            aria-label={`Delete ${c.title}`}
            title="Delete"
            className="grid size-7 place-items-center rounded-md text-muted hover:bg-danger/10 hover:text-danger"
          >
            <TrashIcon className="size-3.5" />
          </button>
        </div>
      )}
      {mode === "delete" && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 pb-2 text-sm">
          <span>Delete this chat?</span>
          <button
            type="button"
            autoFocus
            onClick={() => run(() => remove(c.id), "Couldn't delete")}
            disabled={busy}
            className="font-semibold text-danger underline disabled:opacity-60"
          >
            {busy ? "Deleting…" : "Delete"}
          </button>
          <button type="button" onClick={() => setMode("view")} className="underline">
            Cancel
          </button>
        </div>
      )}
      {error && <p className="px-3 pb-2 text-xs text-danger">{error}</p>}
    </li>
  );
}
