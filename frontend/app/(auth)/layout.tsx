import { Logo } from "@/components/logo";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid flex-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="flex flex-col bg-surface px-4 py-8 sm:px-10">
        <Logo />
        <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-12">
          {children}
        </main>
      </div>

      <aside
        aria-hidden="true"
        className="hidden border-l border-rule bg-paper px-12 py-16 lg:flex lg:flex-col lg:justify-center"
      >
        <div className="max-w-lg">
          <p className="text-sm text-muted">Q: What notice is needed to terminate the lease?</p>
          <p className="mt-4 font-serif text-2xl leading-relaxed text-ink">
            Either party can end the lease with 90 days&rsquo; written notice
            <sup className="ml-0.5 font-sans text-sm text-brand">1</sup>, delivered to the address
            in the notices clause<sup className="ml-0.5 font-sans text-sm text-brand">2</sup>.
          </p>
          <div className="mt-8 space-y-5 border-t border-rule pt-6 font-serif text-base leading-7 text-ink/85">
            <p>
              <span className="mr-2 font-sans text-sm text-brand">1</span>
              <span className="font-sans text-sm text-muted">Lease Agreement.pdf, p. 14, §12.2</span>
              <br />
              &ldquo;&hellip;either party may terminate this Lease{" "}
              <span className="highlight">upon ninety (90) days&rsquo; prior written notice</span>{" "}
              to the other party&hellip;&rdquo;
            </p>
            <p>
              <span className="mr-2 font-sans text-sm text-brand">2</span>
              <span className="font-sans text-sm text-muted">Lease Agreement.pdf, p. 21, §18.1</span>
              <br />
              &ldquo;All notices shall be{" "}
              <span className="highlight">sent to the addresses set out in Schedule B</span>
              &hellip;&rdquo;
            </p>
          </div>
          <p className="mt-10 text-sm text-muted">
            Every answer points to the exact passage it comes from.
          </p>
        </div>
      </aside>
    </div>
  );
}
