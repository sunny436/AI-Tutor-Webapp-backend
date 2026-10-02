import { AuthForm } from "@/components/auth-form";
import { googleEnabled, turnstileSiteKey } from "@/lib/auth/options";
import { safeRedirect } from "@/lib/safe-redirect";

export const metadata = { title: "Sign in" };

const NOTICES: Record<string, string> = {
  expired: "Your session has ended. Please sign in again.",
  deleted: "Your account and its chats have been deleted.",
  password: "Your password was set. Sign in with it.",
};

type Search = { redirect?: string; reason?: string; error?: string; step?: string };

export default async function LoginPage(props: { searchParams: Promise<Search> }) {
  const searchParams = await props.searchParams;
  return (
    <AuthForm
      // Google comes back here for the second step when the account has two-step sign-in.
      initialMode={searchParams.step === "two-factor" ? "twoFactor" : "signIn"}
      redirectTo={safeRedirect(searchParams.redirect)}
      notice={searchParams.reason ? (NOTICES[searchParams.reason] ?? null) : null}
      googleEnabled={googleEnabled()}
      turnstileSiteKey={turnstileSiteKey()}
      oauthError={searchParams.error ?? null}
    />
  );
}
