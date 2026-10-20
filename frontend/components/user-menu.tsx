"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import Link from "next/link";
import { signOut } from "aws-amplify/auth";
import { Avatar, displayName } from "./avatar";
import { ChevronDownIcon, SignOutIcon, UserIcon } from "./icons";
import type { CurrentUser } from "./use-current-user";

const ITEM =
  "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm text-ink hover:bg-paper focus:bg-paper focus:outline-none";

// Menu button pattern: arrows move between items, Escape closes and returns focus.
export function UserMenu({ user }: { user: CurrentUser }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const name = displayName(user);

  useEffect(() => {
    if (!open) return;
    menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  function close() {
    setOpen(false);
    buttonRef.current?.focus();
  }

  function onMenuKeyDown(event: KeyboardEvent) {
    const items = [...(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])];
    const index = items.indexOf(document.activeElement as HTMLElement);
    const focusAt = (i: number) => items[(i + items.length) % items.length]?.focus();
    switch (event.key) {
      case "ArrowDown":
        focusAt(index + 1);
        break;
      case "ArrowUp":
        focusAt(index - 1);
        break;
      case "Home":
        focusAt(0);
        break;
      case "End":
        focusAt(items.length - 1);
        break;
      case "Escape":
        close();
        break;
      case "Tab":
        setOpen(false);
        return;
      default:
        return;
    }
    event.preventDefault();
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={`Account: ${name}`}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" && !open) {
            e.preventDefault();
            setOpen(true);
          }
        }}
        className="flex items-center gap-2 rounded-full py-0.5 pr-2 pl-0.5 text-sm hover:bg-paper aria-expanded:bg-paper"
      >
        <Avatar user={user} />
        <span className="hidden max-w-40 truncate font-medium sm:block">{name}</span>
        <ChevronDownIcon
          className={`size-4 text-muted transition-transform motion-reduce:transition-none ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-label="Account"
          onKeyDown={onMenuKeyDown}
          className="absolute right-0 z-20 mt-2 w-64 origin-top-right rounded-lg border border-rule bg-surface p-1.5 shadow-pop"
        >
          <div className="flex items-center gap-3 px-2.5 pt-2 pb-3">
            <Avatar user={user} />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{name}</p>
              <p className="truncate text-xs text-muted">{user.email}</p>
            </div>
          </div>
          <div role="none" className="border-t border-rule pt-1.5">
            <Link href="/profile" role="menuitem" tabIndex={-1} onClick={() => setOpen(false)} className={ITEM}>
              <UserIcon className="size-4 text-muted" />
              Profile
            </Link>
            <button
              type="button"
              role="menuitem"
              tabIndex={-1}
              onClick={() => signOut()}
              className={ITEM}
            >
              <SignOutIcon className="size-4 text-muted" />
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
