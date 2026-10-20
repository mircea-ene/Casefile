"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ChatPanel } from "./chat-panel";
import { ConversationList } from "./conversation-list";
import { DocumentsPanel } from "./documents-panel";
import { AppHeader } from "@/components/app-header";
import { useCurrentUser } from "@/components/use-current-user";
import { BriefcaseIcon, ClockIcon, SettingsIcon, UsersIcon } from "@/components/icons";
import { useConversations } from "./use-conversations";
import { useDocuments } from "./use-documents";
import { DocumentViewer } from "@/components/viewer/document-viewer";
import { fileKind } from "@/components/viewer/files";
import { ViewerContext, type ViewerActions } from "@/components/viewer/viewer-context";
import type { PassageLocation } from "@/lib/api";

const UPCOMING_SECTIONS = [
  { name: "Matters", Icon: BriefcaseIcon },
  { name: "Clients", Icon: UsersIcon },
  { name: "Audit log", Icon: ClockIcon },
  { name: "Settings", Icon: SettingsIcon },
];

type MobileView = "chat" | "history" | "documents";

// The open conversation (?c=) and document view (?doc=&page=&passage=) live in the URL, so a
// refresh or a shared link reopens them. The presigned file URL never goes there.
type UrlParams = { c?: string | null; doc?: string | null; page?: string | null; passage?: string | null };

function updateUrl(patch: UrlParams, mode: "push" | "replace") {
  const params = new URLSearchParams(window.location.search);
  for (const [key, value] of Object.entries(patch)) {
    if (value == null) params.delete(key);
    else params.set(key, value);
  }
  const query = params.toString();
  const url = query ? `/?${query}` : "/";
  if (mode === "push") window.history.pushState(null, "", url);
  else window.history.replaceState(null, "", url);
}

export function Dashboard() {
  const user = useCurrentUser();
  const searchParams = useSearchParams();
  const conversationId = searchParams.get("c");
  const viewerDocId = searchParams.get("doc");
  const viewerPage = Number(searchParams.get("page")) || 1;
  const passageId = searchParams.get("passage");
  const docs = useDocuments(user !== null);
  const history = useConversations(user !== null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [mobileView, setMobileView] = useState<MobileView>("chat");
  // The chat panel is remounted when the URL moves to another conversation (link, back/forward,
  // delete), but not when it moves to the one the panel already shows (a new chat's first answer).
  // `urlId` is the last URL value seen; the URL can update a render after the panel adopts an id.
  const [panel, setPanel] = useState({ key: 0, conversationId, urlId: conversationId });
  if (panel.urlId !== conversationId) {
    setPanel({
      key: conversationId === panel.conversationId ? panel.key : panel.key + 1,
      conversationId,
      urlId: conversationId,
    });
  }

  // Passages seen in answers, so ?passage= can restore highlights after a refresh.
  const [passages, setPassages] = useState(() => new Map<string, PassageLocation>());
  // Bumped on every link click, so opening the same passage again scrolls back to it.
  const [openCount, setOpenCount] = useState(0);

  function rememberPassages(locations: PassageLocation[]) {
    if (!locations.length) return;
    setPassages((prev) => {
      const next = new Map(prev);
      for (const location of locations) next.set(location.id, location);
      return next;
    });
  }

  const viewer: ViewerActions = {
    openPassage(location) {
      rememberPassages([location]);
      const page = location.bboxes[0]?.page ?? location.page ?? 1;
      updateUrl({ doc: location.document_id, page: String(page), passage: location.id }, "push");
      setOpenCount((n) => n + 1);
    },
    openDocument(documentId) {
      updateUrl({ doc: documentId, page: "1", passage: null }, "push");
      setOpenCount((n) => n + 1);
    },
    kindOf(documentId, name) {
      const doc = docs.documents.find((d) => d.id === documentId);
      return doc ? fileKind(doc.content_type, doc.filename) : fileKind(undefined, name);
    },
  };

  const passage = passageId ? passages.get(passageId) : undefined;
  const viewerBoxes = passage && passage.document_id === viewerDocId ? passage.bboxes : [];
  const firstBox = viewerBoxes.find((box) => box.page === viewerPage);
  const viewerDoc = docs.documents.find((d) => d.id === viewerDocId);
  const viewerName = viewerDoc?.filename ?? passage?.document_name ?? "Document";

  // Drop selections for documents that no longer exist.
  const selectedDocs = useMemo(
    () => docs.documents.filter((d) => selected.has(d.id)),
    [docs.documents, selected],
  );
  const selectedIds = useMemo(() => new Set(selectedDocs.map((d) => d.id)), [selectedDocs]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function openConversation(id: string | null) {
    // An open document stays open; its highlight belonged to the previous chat.
    if (id !== conversationId) updateUrl({ c: id, passage: null }, "push");
    // "New chat" while already on an unsaved chat still clears it.
    else if (id === null) setPanel((p) => ({ ...p, key: p.key + 1 }));
    setMobileView("chat");
  }

  // Points the URL at a conversation without remounting the panel showing it.
  function adoptConversation(id: string | null) {
    setPanel((p) => ({ ...p, conversationId: id }));
    updateUrl({ c: id }, "replace");
  }

  async function removeConversation(id: string) {
    await history.remove(id);
    if (id === conversationId) updateUrl({ c: null, passage: null }, "replace");
  }

  if (!user) {
    return (
      <div className="flex flex-1 items-center justify-center text-muted" role="status">
        Opening your workspace…
      </div>
    );
  }

  const tabs: [MobileView, string][] = [
    ["chat", "Chat"],
    ["history", "History"],
    ["documents", `Documents (${docs.documents.length})`],
  ];

  const viewerOpen = viewerDocId !== null;

  return (
    <ViewerContext value={viewer}>
      <div className="flex h-dvh flex-col">
        <AppHeader user={user} />

        <div className="flex border-b border-rule bg-surface lg:hidden" role="tablist">
          {tabs.map(([view, label]) => (
            <button
              key={view}
              type="button"
              role="tab"
              aria-selected={mobileView === view}
              onClick={() => setMobileView(view)}
              className={`flex-1 border-b-2 py-2.5 text-sm font-medium transition-colors ${
                mobileView === view
                  ? "border-brand text-ink"
                  : "border-transparent text-muted hover:text-ink"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* With a document open, it takes the documents column (about half the width) and the
            history list gives way below xl. On phones the viewer is a full-screen sheet. */}
        <div
          className={`grid min-h-0 flex-1 ${
            viewerOpen
              ? "lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] xl:grid-cols-[15rem_minmax(0,1fr)_minmax(0,1.15fr)]"
              : "lg:grid-cols-[16rem_minmax(0,1fr)_22rem]"
          }`}
        >
          <nav
            aria-label="Chats"
            className={`min-h-0 flex-col border-rule bg-paper lg:border-r ${
              mobileView === "history" ? "flex" : "hidden"
            } ${viewerOpen ? "lg:hidden xl:flex" : "lg:flex"}`}
          >
            <ConversationList
              conversations={history.conversations}
              loaded={history.loaded}
              activeId={conversationId}
              onSelect={openConversation}
              rename={history.rename}
              remove={removeConversation}
            />
            <ul aria-label="Coming soon" className="hidden border-t border-rule px-3 py-3 text-sm lg:block">
              {UPCOMING_SECTIONS.map(({ name, Icon }) => (
                <li key={name}>
                  <span
                    aria-disabled="true"
                    className="flex cursor-default items-center gap-2.5 px-3 py-1.5 text-muted/80"
                  >
                    <Icon className="size-4" />
                    <span className="flex-1">{name}</span>
                    <span className="rounded-full border border-rule px-1.5 py-px text-[0.6875rem] leading-4">
                      Soon
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </nav>

          <section
            aria-label="Chat"
            className={`min-h-0 flex-col ${mobileView === "chat" ? "flex" : "hidden"} lg:flex`}
          >
            <ChatPanel
              key={panel.key}
              conversationId={panel.conversationId}
              documents={docs.documents}
              selectedDocs={selectedDocs}
              onClearSelection={() => setSelected(new Set())}
              onConversationSaved={(response) => {
                if (response.conversation_id !== conversationId) {
                  adoptConversation(response.conversation_id);
                }
                // Picks up the new or reordered conversation and starts title polling.
                history.refresh();
              }}
              onConversationMissing={() => {
                adoptConversation(null);
                history.refresh();
              }}
              onRestoreSelection={(ids) =>
                // Only fill an empty selection; never override one the user made.
                setSelected((prev) => (prev.size ? prev : new Set(ids)))
              }
              onPassagesLoaded={rememberPassages}
            />
          </section>

          <section
            aria-label="Documents"
            className={`min-h-0 flex-col border-rule bg-surface lg:border-l ${
              mobileView === "documents" ? "flex" : "hidden"
            } ${viewerOpen ? "lg:hidden" : "lg:flex"}`}
          >
            <DocumentsPanel {...docs} selectedIds={selectedIds} onToggle={toggle} />
          </section>

          {viewerDocId && (
            <section
              aria-label="Document viewer"
              className="fixed inset-0 z-30 flex min-h-0 flex-col lg:static lg:z-auto lg:border-l lg:border-rule"
            >
              <DocumentViewer
                key={viewerDocId}
                documentId={viewerDocId}
                name={viewerName}
                kind={viewer.kindOf(viewerDocId, viewerName)}
                bboxes={viewerBoxes}
                scroll={{
                  page: viewerPage,
                  y: firstBox?.y ?? 0,
                  key: `${openCount}:${viewerPage}:${firstBox?.y ?? 0}`,
                }}
                onClose={() => updateUrl({ doc: null, page: null, passage: null }, "push")}
              />
            </section>
          )}
        </div>
      </div>
    </ViewerContext>
  );
}
