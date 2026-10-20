"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import {
  ApiError,
  askQuestion,
  getConversation,
  type ChatAnswer,
  type ChatResponse,
  type DocumentItem,
  type PassageLocation,
  type Turn,
} from "@/lib/api";
import { ArrowUpIcon, ChatIcon, FileIcon, XIcon } from "@/components/icons";
import { AnswerView } from "./answer-view";

type Message =
  | { key: string; role: "user"; text: string; documentIds: string[] | null }
  | { key: string; role: "assistant"; answer: ChatAnswer }
  | { key: string; role: "error"; text: string };

type Props = {
  // The panel is remounted (keyed) for each conversation opened from outside it.
  conversationId: string | null;
  documents: DocumentItem[];
  selectedDocs: DocumentItem[];
  onClearSelection: () => void;
  // An answer was saved; on a new chat the URL should now point at its conversation.
  onConversationSaved: (response: ChatResponse) => void;
  // The conversation in the URL doesn't exist (any more).
  onConversationMissing: () => void;
  // Document filter of the last turn of a reopened conversation.
  onRestoreSelection: (documentIds: string[]) => void;
  // Citations and sources shown, so a ?passage= deep link can find its highlight.
  onPassagesLoaded: (locations: PassageLocation[]) => void;
};

function answerPassages(answer: ChatAnswer): PassageLocation[] {
  return [...answer.citations, ...answer.sources];
}

function turnMessages(turn: Turn): Message[] {
  return [
    { key: `${turn.id}:q`, role: "user", text: turn.question, documentIds: turn.document_ids },
    { key: `${turn.id}:a`, role: "assistant", answer: turn },
  ];
}

export function ChatPanel({
  conversationId,
  documents,
  selectedDocs,
  onClearSelection,
  onConversationSaved,
  onConversationMissing,
  onRestoreSelection,
  onPassagesLoaded,
}: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [opening, setOpening] = useState(conversationId !== null);
  const nextKey = useRef(0);
  const endRef = useRef<HTMLDivElement>(null);
  // Follow-ups go to the conversation the first answer created.
  const savedId = useRef(conversationId);
  // Answers that arrive after the panel was swapped for another conversation are dropped.
  const alive = useRef(true);

  const localKey = () => `local-${nextKey.current++}`;

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    if (!conversationId) return;
    getConversation(conversationId)
      .then((conversation) => {
        if (!alive.current) return;
        setMessages(conversation.turns.flatMap(turnMessages));
        onPassagesLoaded(conversation.turns.flatMap(answerPassages));
        const lastFilter = conversation.turns.at(-1)?.document_ids;
        if (lastFilter?.length) onRestoreSelection(lastFilter);
      })
      .catch((e) => {
        if (!alive.current) return;
        const missing = e instanceof ApiError && e.status === 404;
        if (missing) {
          savedId.current = null;
          onConversationMissing();
        }
        setMessages([
          {
            key: localKey(),
            role: "error",
            text: missing ? "That chat no longer exists. Ask a question to start a new one." : "Couldn't open this chat.",
          },
        ]);
      })
      .finally(() => alive.current && setOpening(false));
    // Mounted once per conversation; the callbacks change on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, pending]);

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const question = draft.trim();
    if (!question || pending || opening) return;

    const documentIds = selectedDocs.map((d) => d.id);
    setDraft("");
    setPending(true);
    setMessages((all) => [
      ...all,
      { key: localKey(), role: "user", text: question, documentIds: documentIds.length ? documentIds : null },
    ]);
    try {
      const response = await askQuestion(question, documentIds, savedId.current);
      if (!alive.current) return;
      setMessages((all) => [...all, { key: `${response.id}:a`, role: "assistant", answer: response }]);
      onPassagesLoaded(answerPassages(response));
      savedId.current = response.conversation_id;
      onConversationSaved(response);
    } catch (e) {
      if (!alive.current) return;
      if (e instanceof ApiError && e.status === 404 && e.message === "Conversation not found") {
        // Deleted elsewhere: start over, keeping the question so it can be resent.
        savedId.current = null;
        onConversationMissing();
        setDraft(question);
        setMessages([
          {
            key: localKey(),
            role: "error",
            text: "This chat was deleted, so your question wasn't sent. Send it again to start a new chat.",
          },
        ]);
        return;
      }
      const text =
        e instanceof Error && e.message
          ? `Couldn't get an answer: ${e.message}.`
          : "Couldn't get an answer.";
      setMessages((all) => [...all, { key: localKey(), role: "error", text }]);
    } finally {
      if (alive.current) setPending(false);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send();
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-8">
        {opening ? (
          <p className="mx-auto max-w-2xl text-sm text-muted" role="status">
            Opening chat…
          </p>
        ) : messages.length === 0 ? (
          <div className="mx-auto flex h-full max-w-xl flex-col justify-center">
            <span className="mb-5 grid size-11 place-items-center rounded-xl bg-brand/10 text-brand">
              <ChatIcon className="size-5" />
            </span>
            <h1 className="font-serif text-3xl font-semibold tracking-tight text-balance">
              Ask about your documents
            </h1>
            <p className="mt-3 leading-7 text-pretty text-muted">
              Answers quote the passages they rely on, so you can check each one against the
              source. If your documents don&rsquo;t support an answer, you&rsquo;ll be told
              instead of getting a guess.
            </p>
          </div>
        ) : (
          <ol className="mx-auto max-w-2xl space-y-8">
            {messages.map((m) => (
              <li key={m.key}>
                <MessageView message={m} documents={documents} />
              </li>
            ))}
            {pending && (
              <li>
                <PendingNotice />
              </li>
            )}
          </ol>
        )}
        <div ref={endRef} />
      </div>

      <form onSubmit={send} className="px-4 pt-2 pb-4 sm:px-8 sm:pb-6">
        <div className="mx-auto max-w-2xl">
          <div className="mb-2 flex min-h-7 items-center gap-2 text-sm text-muted">
            {selectedDocs.length === 0 ? (
              <span>Searching all documents</span>
            ) : (
              <span className="inline-flex min-w-0 items-center gap-1.5 rounded-full border border-rule bg-surface py-0.5 pr-1 pl-2.5 text-ink">
                <FileIcon className="size-3.5 text-brand" />
                <span className="truncate">
                  {selectedDocs.length === 1
                    ? selectedDocs[0].filename
                    : `${selectedDocs.length} selected documents`}
                </span>
                <button
                  type="button"
                  onClick={onClearSelection}
                  aria-label="Search all documents instead"
                  title="Search all documents instead"
                  className="grid size-5 shrink-0 place-items-center rounded-full text-muted hover:bg-paper hover:text-ink"
                >
                  <XIcon className="size-3.5" />
                </button>
              </span>
            )}
          </div>
          <div className="flex items-end gap-2 rounded-xl border border-rule bg-surface p-2 shadow-sm transition-shadow focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/20">
            <label htmlFor="question" className="sr-only">
              Question
            </label>
            <textarea
              id="question"
              rows={2}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="What notice period does the lease require?"
              aria-describedby="question-hint"
              className="min-h-11 flex-1 resize-none bg-transparent px-2 py-1.5 text-base placeholder:text-muted/70 focus:outline-none"
            />
            <button
              type="submit"
              disabled={pending || opening || !draft.trim()}
              aria-label="Ask"
              title="Ask"
              className="grid size-9 shrink-0 place-items-center rounded-lg bg-brand text-brand-ink transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              <ArrowUpIcon className="size-4.5" />
            </button>
          </div>
          <p id="question-hint" className="mt-2 text-xs text-muted">
            Each question is answered on its own, without the earlier ones.
            <span className="hidden sm:inline"> Enter to ask, Shift+Enter for a new line.</span>
          </p>
        </div>
      </form>
    </div>
  );
}

// Answers can take a minute or two now that whole sections go to the model, so after a few
// seconds the notice says what's happening and how long it has been. There's no client timeout.
function PendingNotice() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="flex items-center gap-2.5 text-sm text-muted" role="status">
      <span aria-hidden="true" className="flex gap-1">
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            style={{ animationDelay: `${delay}ms` }}
            className="size-1.5 rounded-full bg-brand/60 motion-safe:animate-pulse"
          />
        ))}
      </span>
      {seconds < 8 ? "Searching your documents…" : "Reading the relevant sections…"}
      {seconds >= 8 && (
        <span aria-hidden="true" className="tabular-nums">
          {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
        </span>
      )}
      {seconds >= 30 && <span className="hidden sm:inline">Longer answers can take a minute or two.</span>}
    </div>
  );
}

function MessageView({ message, documents }: { message: Message; documents: DocumentItem[] }) {
  if (message.role === "user") {
    const scope = describeScope(message.documentIds, documents);
    return (
      <div className="ml-auto flex w-fit max-w-[85%] flex-col items-end">
        <p className="w-fit whitespace-pre-wrap rounded-2xl rounded-br-md bg-brand/10 px-4 py-2.5 leading-7">
          {message.text}
        </p>
        <p className="mt-1 max-w-full truncate text-xs text-muted" title={scope.title}>
          {scope.label}
        </p>
      </div>
    );
  }
  if (message.role === "error") {
    return (
      <p className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">
        {message.text}
      </p>
    );
  }
  return <AnswerView answer={message.answer} />;
}

// Which documents a question was limited to. Ids may point at documents deleted since.
function describeScope(ids: string[] | null, documents: DocumentItem[]) {
  if (!ids?.length) return { label: "All documents", title: undefined };
  const names = ids.map((id) => documents.find((d) => d.id === id)?.filename ?? "deleted document");
  if (names.length === 1) return { label: `In ${names[0]}`, title: names[0] };
  return { label: `In ${names.length} documents`, title: names.join("\n") };
}
