"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { resendSignUpCode, signIn } from "aws-amplify/auth";
import { authErrorMessage } from "@/lib/amplify";
import { Field, FormError, SubmitButton } from "@/components/form";
import { useRedirectIfSignedIn } from "@/components/use-redirect-if-signed-in";

export function LoginForm() {
  useRedirectIfSignedIn();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email")).trim().toLowerCase();
    const password = String(form.get("password"));

    setError(null);
    setPending(true);
    try {
      const { nextStep } = await signIn({ username: email, password });
      switch (nextStep.signInStep) {
        case "DONE":
          router.replace("/");
          return;
        case "CONFIRM_SIGN_UP":
          await resendSignUpCode({ username: email });
          router.push(`/confirm?email=${encodeURIComponent(email)}`);
          return;
        default:
          setError("This account needs extra steps to sign in that aren't supported yet.");
      }
    } catch (e) {
      if (e instanceof Error && e.name === "UserAlreadyAuthenticatedException") {
        router.replace("/");
        return;
      }
      setError(authErrorMessage(e));
    }
    setPending(false);
  }

  return (
    <>
      <h1 className="font-serif text-3xl font-semibold tracking-tight">Sign in</h1>
      <p className="mt-2 text-muted">Use your work email to open your firm&rsquo;s workspace.</p>

      <form onSubmit={onSubmit} className="mt-8 space-y-5">
        <FormError message={error} />
        <Field label="Email" name="email" type="email" autoComplete="email" required autoFocus />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
        />
        <SubmitButton pending={pending}>{pending ? "Signing in…" : "Sign in"}</SubmitButton>
      </form>

      <p className="mt-8 text-sm text-muted">
        New here?{" "}
        <Link href="/register" className="font-medium text-brand underline underline-offset-4">
          Create an account
        </Link>
      </p>
    </>
  );
}
