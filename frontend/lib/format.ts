export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// "p. 3", "pp. 3–4", or null for formats without pages.
export function formatPages(page: number | null, pageEnd: number | null): string | null {
  if (page == null) return null;
  return pageEnd != null && pageEnd !== page ? `pp. ${page}–${pageEnd}` : `p. ${page}`;
}

export function formatRelative(iso: string, now = Date.now()): string {
  const date = new Date(iso);
  const minutes = Math.round((now - date.getTime()) / 60_000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
