import type { BoundingBox } from "@/lib/api";

// Where to scroll: a page and a vertical position on it (fraction of its height).
// A new `key` means a new request, even for the same position.
export type ScrollRequest = { page: number; y: number; key: string };

// Boxes are fractions of the page, so percentages keep them in place at any zoom. Pages are
// always white, so the marker color is fixed rather than a theme token.
export function Highlights({ bboxes, page }: { bboxes: BoundingBox[]; page: number }) {
  return bboxes
    .filter((box) => box.page === page)
    .map((box, i) => (
      <span
        key={i}
        aria-hidden="true"
        className="pointer-events-none absolute z-10 rounded-sm bg-amber-300/40 mix-blend-multiply ring-1 ring-amber-500/70"
        style={{
          left: `${box.x * 100}%`,
          top: `${box.y * 100}%`,
          width: `${box.width * 100}%`,
          height: `${box.height * 100}%`,
        }}
      />
    ));
}
