import { AuthForm } from "@/components/auth-form";
import { safeRedirect } from "@/lib/safe-redirect";

export const metadata = { title: "Create account" };

export default function SignupPage({ searchParams }: { searchParams: { redirect?: string } }) {
  return <AuthForm initialMode="signUp" redirectTo={safeRedirect(searchParams.redirect)} />;
}
