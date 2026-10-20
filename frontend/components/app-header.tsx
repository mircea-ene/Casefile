"use client";

import { Logo } from "./logo";
import { UserMenu } from "./user-menu";
import type { CurrentUser } from "./use-current-user";

export function AppHeader({ user }: { user: CurrentUser }) {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-rule bg-surface px-4 sm:px-6">
      <Logo />
      <UserMenu user={user} />
    </header>
  );
}
