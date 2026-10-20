"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { signUp } from "aws-amplify/auth";
import { authErrorMessage } from "@/lib/amplify";
import { Field, FormError, SubmitButton } from "@/components/form";
import { useRedirectIfSignedIn } from "@/components/use-redirect-if-signed-in";

// Mirrors the user pool's password policy so most mistakes are caught before the round trip.
function passwordProblem(password: string): string | null {
  if (password.length < 8) return "Password must be at least 8 characters.";
  if (!/[a-z]/.test(password)) return "Password needs a lowercase letter.";
  if (!/[A-Z]/.test(password)) return "Password needs an uppercase letter.";
  if (!/[0-9]/.test(password)) return "Password needs a number.";
  return null;
}

export function RegisterForm() {
  useRedirectIfSignedIn();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const givenName = String(form.get("given_name")).trim();
    const familyName = String(form.get("family_name")).trim();
    const email = String(form.get("email")).trim().toLowerCase();
    const password = String(form.get("password"));

    const problem = passwordProblem(password);
    if (problem) {
      setError(problem);
      return;
    }
    if (password !== form.get("confirm_password")) {
      setError("Passwords don't match.");
      return;
    }

    setError(null);
    setPending(true);
    try {
      const { nextStep } = await signUp({
        username: email,
        password,
        options: {
          userAttributes: { email, given_name: givenName, family_name: familyName },
          autoSignIn: true,
        },
      });
      router.push(
        nextStep.signUpStep === "CONFIRM_SIGN_UP"
          ? `/confirm?email=${encodeURIComponent(email)}`
          : "/login",
      );
    } catch (e) {
      setError(authErrorMessage(e));
      setPending(false);
    }
  }

  return (
    <>
      <h1 className="font-serif text-3xl font-semibold tracking-tight">Create your account</h1>
      <p className="mt-2 text-muted">We&rsquo;ll email you a code to confirm your address.</p>

      <form onSubmit={onSubmit} className="mt-8 space-y-5">
        <FormError message={error} />
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="First name" name="given_name" autoComplete="given-name" required autoFocus />
          <Field label="Last name" name="family_name" autoComplete="family-name" required />
        </div>
        <Field label="Work email" name="email" type="email" autoComplete="email" required />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="new-password"
          minLength={8}
          required
          hint="At least 8 characters, with upper and lowercase letters and a number."
        />
        <Field
          label="Confirm password"
          name="confirm_password"
          type="password"
          autoComplete="new-password"
          required
        />
        <SubmitButton pending={pending}>
          {pending ? "Creating account…" : "Create account"}
        </SubmitButton>
      </form>

      <p className="mt-8 text-sm text-muted">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-brand underline underline-offset-4">
          Sign in
        </Link>
      </p>
    </>
  );
}
