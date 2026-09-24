import { AuthForm } from "@/components/auth-form";
import { safeRedirect } from "@/lib/safe-redirect";

export const metadata = { title: "Sign in" };

const NOTICES: Record<string, string> = {
  expired: "Your session has ended. Please sign in again.",
  deleted: "Your account and its chats have been deleted.",
};

export default function LoginPage({ searchParams }: { searchParams: { redirect?: string; reason?: string } }) {
  return (
    <AuthForm
      initialMode="signIn"
      redirectTo={safeRedirect(searchParams.redirect)}
      notice={searchParams.reason ? (NOTICES[searchParams.reason] ?? null) : null}
    />
  );
}
