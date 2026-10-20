import type { Metadata } from "next";
import { Suspense } from "react";
import { ConfirmForm } from "./confirm-form";

export const metadata: Metadata = { title: "Confirm email · Casefile" };

export default function ConfirmPage() {
  // ConfirmForm reads the email from the URL, which isn't known until request time.
  return (
    <Suspense>
      <ConfirmForm />
    </Suspense>
  );
}
