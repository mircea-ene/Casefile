"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { autoSignIn, confirmSignUp, resendSignUpCode } from "aws-amplify/auth";
import { authErrorMessage } from "@/lib/amplify";
import { Field, FormError, FormNotice, SubmitButton } from "@/components/form";

export function ConfirmForm() {
  const router = useRouter();
  const email = useSearchParams().get("email") ?? "";
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = String(new FormData(event.currentTarget).get("code")).trim();

    setError(null);
    setNotice(null);
    setPending(true);
    try {
      const { nextStep } = await confirmSignUp({ username: email, confirmationCode: code });
      if (nextStep.signUpStep === "COMPLETE_AUTO_SIGN_IN") {
        // Only works in the tab that created the account; otherwise fall back to sign-in.
        try {
          const result = await autoSignIn();
          if (result.isSignedIn) {
            router.replace("/");
            return;
          }
        } catch {}
      }
      router.replace("/login");
    } catch (e) {
      setError(authErrorMessage(e));
      setPending(false);
    }
  }

  async function onResend() {
    setError(null);
    setNotice(null);
    try {
      await resendSignUpCode({ username: email });
      setNotice(`We sent a new code to ${email}.`);
    } catch (e) {
      setError(authErrorMessage(e));
    }
  }

  if (!email) {
    return (
      <>
        <h1 className="font-serif text-3xl font-semibold tracking-tight">Confirm your email</h1>
        <p className="mt-2 text-muted">
          This link is missing an email address.{" "}
          <Link href="/login" className="font-medium text-brand underline underline-offset-4">
            Sign in
          </Link>{" "}
          and we&rsquo;ll send you a new code.
        </p>
      </>
    );
  }

  return (
    <>
      <h1 className="font-serif text-3xl font-semibold tracking-tight">Check your email</h1>
      <p className="mt-2 text-muted">
        Enter the 6-digit code we sent to <span className="font-medium text-ink">{email}</span>.
      </p>

      <form onSubmit={onSubmit} className="mt-8 space-y-5">
        <FormError message={error} />
        {notice && <FormNotice>{notice}</FormNotice>}
        <Field
          label="Confirmation code"
          name="code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6}"
          maxLength={6}
          required
          autoFocus
        />
        <SubmitButton pending={pending}>{pending ? "Confirming…" : "Confirm email"}</SubmitButton>
      </form>

      <p className="mt-8 text-sm text-muted">
        No code?{" "}
        <button
          type="button"
          onClick={onResend}
          className="font-medium text-brand underline underline-offset-4"
        >
          Send a new code
        </button>
      </p>
    </>
  );
}
