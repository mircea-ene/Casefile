"use client";

import { configureAmplify } from "@/lib/amplify";

// Configure at module load so Amplify is ready before any child effect runs.
configureAmplify();

export function AmplifyConfig() {
  return null;
}
