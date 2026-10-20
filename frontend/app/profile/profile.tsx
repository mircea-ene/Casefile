"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import {
  deleteUserAttributes,
  updateUserAttributes,
  type UserAttributeKey,
} from "aws-amplify/auth";
import { AppHeader } from "@/components/app-header";
import { Avatar, displayName } from "@/components/avatar";
import { ArrowLeftIcon } from "@/components/icons";
import { Field, FormError, FormNotice, SubmitButton } from "@/components/form";
import {
  announceProfileUpdated,
  useCurrentUser,
  type CurrentUser,
} from "@/components/use-current-user";
import { authErrorMessage } from "@/lib/amplify";
import { listDocuments, type DocumentItem } from "@/lib/api";
import { formatSize } from "@/lib/format";

export function Profile() {
  const user = useCurrentUser();

  if (!user) {
    return (
      <div className="flex flex-1 items-center justify-center text-muted" role="status">
        Loading your profile…
      </div>
    );
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <AppHeader user={user} />
      <main className="mx-auto w-full max-w-2xl px-4 py-10 sm:px-6">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm text-muted underline-offset-4 hover:text-ink hover:underline"
        >
          <ArrowLeftIcon className="size-4" />
          Back to workspace
        </Link>
        <div className="mt-6 flex items-center gap-4">
          <Avatar user={user} size="lg" />
          <div className="min-w-0">
            <h1 className="font-serif text-3xl font-semibold tracking-tight">Profile</h1>
            <p className="truncate text-muted">
              {displayName(user)} · {user.email}
            </p>
          </div>
        </div>
        <DetailsForm user={user} />
        <Usage />
      </main>
    </div>
  );
}

const E164 = /^\+[1-9]\d{6,14}$/;

function DetailsForm({ user }: { user: CurrentUser }) {
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const values: Partial<Record<UserAttributeKey, string>> = {
      given_name: String(form.get("given_name")).trim(),
      family_name: String(form.get("family_name")).trim(),
      nickname: String(form.get("nickname")).trim(),
      phone_number: String(form.get("phone_number")).replace(/[\s()-]/g, ""),
    };
    if (values.phone_number && !E164.test(values.phone_number)) {
      setError("Enter the phone number with its country code, for example +15551234567.");
      setNotice(null);
      return;
    }

    const current: Partial<Record<UserAttributeKey, string>> = {
      given_name: user.givenName,
      family_name: user.familyName,
      nickname: user.nickname,
      phone_number: user.phoneNumber,
    };
    const toUpdate: Partial<Record<UserAttributeKey, string>> = {};
    const toDelete: UserAttributeKey[] = [];
    for (const [key, value] of Object.entries(values) as [UserAttributeKey, string][]) {
      if (value === current[key]) continue;
      // Cognito can't store an empty value; clearing an optional field deletes it.
      if (value) toUpdate[key] = value;
      else toDelete.push(key);
    }

    setError(null);
    setNotice(null);
    if (!Object.keys(toUpdate).length && !toDelete.length) {
      setNotice("Nothing to save.");
      return;
    }

    setPending(true);
    try {
      if (Object.keys(toUpdate).length) await updateUserAttributes({ userAttributes: toUpdate });
      if (toDelete.length) await deleteUserAttributes({
          userAttributeKeys: toDelete as [UserAttributeKey, ...UserAttributeKey[]],
        });
      announceProfileUpdated();
      setNotice("Profile saved.");
    } catch (e) {
      setError(authErrorMessage(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-labelledby="details-heading" className="mt-10">
      <h2 id="details-heading" className="font-serif text-xl font-semibold">
        Personal details
      </h2>
      <form onSubmit={onSubmit} className="mt-4 space-y-5 rounded-lg border border-rule bg-surface p-5 sm:p-6">
        <FormError message={error} />
        {notice && <FormNotice>{notice}</FormNotice>}
        <div className="grid gap-5 sm:grid-cols-2">
          <Field
            label="First name"
            name="given_name"
            autoComplete="given-name"
            defaultValue={user.givenName}
            required
          />
          <Field
            label="Last name"
            name="family_name"
            autoComplete="family-name"
            defaultValue={user.familyName}
            required
          />
        </div>
        <Field
          label="Preferred name"
          name="nickname"
          autoComplete="nickname"
          defaultValue={user.nickname}
          hint="Shown in the header instead of your full name. Optional."
        />
        <Field
          label="Phone"
          name="phone_number"
          type="tel"
          autoComplete="tel"
          placeholder="+15551234567"
          defaultValue={user.phoneNumber}
          hint="Include the country code. Optional."
        />
        <Field
          label="Email"
          name="email"
          type="email"
          defaultValue={user.email}
          readOnly
          hint="You sign in with this address. It can't be changed yet."
        />
        <div className="sm:w-48">
          <SubmitButton pending={pending}>{pending ? "Saving…" : "Save changes"}</SubmitButton>
        </div>
      </form>
    </section>
  );
}

function Usage() {
  const [documents, setDocuments] = useState<DocumentItem[] | null>(null);

  useEffect(() => {
    // No backend or no data yet: show empty usage, same as the documents panel.
    listDocuments()
      .catch(() => [])
      .then(setDocuments);
  }, []);

  const count = (status: DocumentItem["status"]) =>
    documents?.filter((d) => d.status === status).length ?? 0;
  const totalBytes = documents?.reduce((sum, d) => sum + d.size_bytes, 0) ?? 0;

  const rows: [string, string][] = [
    ["Documents", String(documents?.length ?? 0)],
    ["Storage used", formatSize(totalBytes)],
    ["Ready to search", String(count("ready"))],
    ["Indexing", String(count("processing"))],
    ["Couldn't index", String(count("failed"))],
  ];

  return (
    <section aria-labelledby="usage-heading" className="mt-10">
      <h2 id="usage-heading" className="font-serif text-xl font-semibold">
        Usage
      </h2>
      {documents === null ? (
        <p className="mt-4 text-muted" role="status">
          Loading usage…
        </p>
      ) : (
        <dl className="mt-4 divide-y divide-rule rounded-lg border border-rule bg-surface">
          {rows.map(([label, value]) => (
            <div key={label} className="flex items-baseline justify-between px-5 py-3">
              <dt className="text-muted">{label}</dt>
              <dd className="font-medium tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}
