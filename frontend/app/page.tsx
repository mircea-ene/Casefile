import { Suspense } from "react";
import type { Metadata } from "next";
import { Dashboard } from "@/components/dashboard/dashboard";

export const metadata: Metadata = { title: "Workspace · Casefile" };

export default function Home() {
  // The dashboard reads ?c= with useSearchParams, which needs a Suspense boundary to prerender.
  return (
    <Suspense
      fallback={
        <div className="flex flex-1 items-center justify-center text-muted" role="status">
          Opening your workspace…
        </div>
      }
    >
      <Dashboard />
    </Suspense>
  );
}
