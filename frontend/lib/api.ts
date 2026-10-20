import { fetchAuthSession } from "aws-amplify/auth";

// Contract with the FastAPI backend lives in docs/backend-api.md.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type DocumentStatus = "processing" | "ready" | "failed";

export type DocumentItem = {
  id: string;
  filename: string;
  size_bytes: number;
  content_type: string;
  status: DocumentStatus;
  created_at: string;
};

export type BoundingBox = {
  page: number; // 1-based
  x: number; // left edge, fraction of page width (0–1)
  y: number; // top edge, fraction of page height (0–1), origin top-left
  width: number;
  height: number;
};

// Where a passage sits in its document. A citation and a source with the same id are the same passage.
export type PassageLocation = {
  id: string;
  document_id: string;
  document_name: string;
  page: number | null;
  page_end: number | null;
  section: string | null;
  heading_path: string | null;
  element_type: "text" | "table" | "definition";
  text_source: "text_layer" | "ocr";
  bboxes: BoundingBox[];
};

export type Citation = PassageLocation & {
  quote: string;
};

export type Source = PassageLocation & {
  content: string;
  similarity: number;
  citation: number | null; // the [n] in `answer` that cites this source
};

export type ChatAnswer = {
  answer: string;
  citations: Citation[];
  sources: Source[];
  insufficient_evidence: boolean;
};

export type Turn = ChatAnswer & {
  id: string;
  question: string;
  document_ids: string[] | null; // null = all documents
  created_at: string;
};

export type ChatResponse = Turn & { conversation_id: string };

export type ConversationSummary = {
  id: string;
  title: string;
  title_is_custom: boolean;
  title_pending: boolean;
  created_at: string;
  updated_at: string;
};

export type ConversationDetail = ConversationSummary & { turns: Turn[] };

export const MAX_TITLE_LENGTH = 200;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function accessToken(): Promise<string> {
  // Refreshes the access token when it's close to expiring.
  const session = await fetchAuthSession();
  const token = session.tokens?.accessToken?.toString();
  if (!token) throw new ApiError(401, "Not signed in");
  return token;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${await accessToken()}`);
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!res.ok) throw new ApiError(res.status, await errorDetail(res));
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

async function errorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {}
  return `Request failed (${res.status})`;
}

export async function listDocuments(): Promise<DocumentItem[]> {
  const body = await request<{ documents: DocumentItem[] }>("/documents");
  return body?.documents ?? [];
}

export type DocumentFileUrl = {
  url: string; // presigned S3 URL: no auth header, never put it in the address bar or storage
  expires_at: string;
  filename: string;
  content_type: string;
};

export function getDocumentFileUrl(id: string, download = false): Promise<DocumentFileUrl> {
  return request(`/documents/${encodeURIComponent(id)}/file${download ? "?download=true" : ""}`);
}

export function deleteDocument(id: string): Promise<void> {
  return request(`/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function askQuestion(
  question: string,
  documentIds: string[],
  conversationId: string | null,
): Promise<ChatResponse> {
  return request("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      document_ids: documentIds.length ? documentIds : null,
      conversation_id: conversationId,
    }),
  });
}

export async function listConversations(): Promise<ConversationSummary[]> {
  const body = await request<{ conversations: ConversationSummary[] }>("/conversations");
  return body?.conversations ?? [];
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return request(`/conversations/${encodeURIComponent(id)}`);
}

// A null or blank title goes back to the generated one.
export function renameConversation(id: string, title: string | null): Promise<ConversationSummary> {
  return request(`/conversations/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

export function deleteConversation(id: string): Promise<void> {
  return request(`/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
}

// XHR instead of fetch so the UI can show upload progress.
export async function uploadDocument(
  file: File,
  onProgress: (fraction: number) => void,
): Promise<DocumentItem> {
  const token = await accessToken();
  const form = new FormData();
  form.append("file", file);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}/documents`);
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as DocumentItem);
      else {
        const detail = (xhr.response as { detail?: unknown } | null)?.detail;
        reject(
          new ApiError(
            xhr.status,
            typeof detail === "string" ? detail : `Upload failed (${xhr.status})`,
          ),
        );
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "Can't reach the server"));
    xhr.send(form);
  });
}
