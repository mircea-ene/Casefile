"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Hub } from "aws-amplify/utils";
import { fetchUserAttributes, getCurrentUser } from "aws-amplify/auth";

export type CurrentUser = {
  givenName: string;
  familyName: string;
  email: string;
  nickname: string;
  phoneNumber: string;
};

// Fired after the profile is saved, so pages kept mounted in the background refresh the name.
const PROFILE_UPDATED = "casefile:profile-updated";

export function announceProfileUpdated() {
  window.dispatchEvent(new Event(PROFILE_UPDATED));
}

async function fetchCurrentUser(): Promise<CurrentUser> {
  await getCurrentUser();
  const attrs = await fetchUserAttributes();
  return {
    givenName: attrs.given_name ?? "",
    familyName: attrs.family_name ?? "",
    email: attrs.email ?? "",
    nickname: attrs.nickname ?? "",
    phoneNumber: attrs.phone_number ?? "",
  };
}

// Client-side gate: tokens live in browser storage, so the server can't check them.
// The backend still verifies the JWT on every request.
export function useCurrentUser(): CurrentUser | null {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchCurrentUser()
      .then((u) => !cancelled && setUser(u))
      .catch(() => !cancelled && router.replace("/login"));

    const reload = () => {
      fetchCurrentUser()
        .then((u) => !cancelled && setUser(u))
        .catch(() => {});
    };
    window.addEventListener(PROFILE_UPDATED, reload);
    const stop = Hub.listen("auth", ({ payload }) => {
      if (payload.event === "signedOut" || payload.event === "tokenRefresh_failure") {
        router.replace("/login");
      }
    });
    return () => {
      cancelled = true;
      window.removeEventListener(PROFILE_UPDATED, reload);
      stop();
    };
  }, [router]);

  return user;
}
