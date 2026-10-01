import { AuthForm } from "@/components/auth-form";
import { googleEnabled } from "@/lib/auth/options";
import { safeRedirect } from "@/lib/safe-redirect";

export const metadata = { title: "Sign in" };

const NOTICES: Record<string, string> = {
  expired: "Your session has ended. Please sign in again.",
  deleted: "Your account and its chats have been deleted.",
  password: "Your password was set. Sign in with it.",
};

type Search = { redirect?: string; reason?: string; error?: string };

export default function LoginPage({ searchParams }: { searchParams: Search }) {
  return (
    <AuthForm
      initialMode="signIn"
      redirectTo={safeRedirect(searchParams.redirect)}
      notice={searchParams.reason ? (NOTICES[searchParams.reason] ?? null) : null}
      googleEnabled={googleEnabled()}
      oauthError={searchParams.error ?? null}
    />
  );
}
