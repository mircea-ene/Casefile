import Link from "next/link";

export function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2.5 text-ink">
      <span
        aria-hidden="true"
        className="grid size-7 place-items-center rounded-md bg-brand font-serif text-base font-semibold text-brand-ink"
      >
        C
      </span>
      <span className="font-serif text-xl font-semibold tracking-tight">Casefile</span>
    </Link>
  );
}
