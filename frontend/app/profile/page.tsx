import type { Metadata } from "next";
import { Profile } from "./profile";

export const metadata: Metadata = { title: "Profile · Casefile" };

export default function ProfilePage() {
  return <Profile />;
}
