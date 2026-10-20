import type { Metadata } from "next";
import { RegisterForm } from "./register-form";

export const metadata: Metadata = { title: "Create account · Casefile" };

export default function RegisterPage() {
  return <RegisterForm />;
}
