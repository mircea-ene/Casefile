import type { CurrentUser } from "./use-current-user";

export function displayName(user: CurrentUser): string {
  return user.nickname || `${user.givenName} ${user.familyName}`.trim() || user.email;
}

function initials(user: CurrentUser): string {
  const fromNames = `${user.givenName.charAt(0)}${user.familyName.charAt(0)}`;
  return (fromNames || displayName(user).charAt(0)).toUpperCase();
}

const SIZES = {
  sm: "size-8 text-xs",
  lg: "size-14 text-lg",
};

// Decorative: callers always render the name next to it or in an accessible label.
export function Avatar({ user, size = "sm" }: { user: CurrentUser; size?: keyof typeof SIZES }) {
  return (
    <span
      aria-hidden="true"
      className={`grid shrink-0 select-none place-items-center rounded-full bg-brand font-semibold tracking-wide text-brand-ink ring-2 ring-surface ${SIZES[size]}`}
    >
      {initials(user)}
    </span>
  );
}
