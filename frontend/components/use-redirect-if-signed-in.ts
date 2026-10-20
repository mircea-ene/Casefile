"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getCurrentUser } from "aws-amplify/auth";

export function useRedirectIfSignedIn() {
  const router = useRouter();
  useEffect(() => {
    getCurrentUser()
      .then(() => router.replace("/"))
      .catch(() => {});
  }, [router]);
}
