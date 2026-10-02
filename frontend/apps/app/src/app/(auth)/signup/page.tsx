import { AuthForm } from "@/components/auth-form";
import { googleEnabled, turnstileSiteKey } from "@/lib/auth/options";
import { safeRedirect } from "@/lib/safe-redirect";

export const metadata = { title: "Create account" };

export default async function SignupPage(props: { searchParams: Promise<{ redirect?: string; error?: string }> }) {
  const searchParams = await props.searchParams;
  return (
    <AuthForm
      initialMode="signUp"
      redirectTo={safeRedirect(searchParams.redirect)}
      googleEnabled={googleEnabled()}
      turnstileSiteKey={turnstileSiteKey()}
      oauthError={searchParams.error ?? null}
    />
  );
}
