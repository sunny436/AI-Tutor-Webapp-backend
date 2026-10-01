import { AuthForm } from "@/components/auth-form";
import { googleEnabled } from "@/lib/auth/options";
import { safeRedirect } from "@/lib/safe-redirect";

export const metadata = { title: "Create account" };

export default function SignupPage({ searchParams }: { searchParams: { redirect?: string; error?: string } }) {
  return (
    <AuthForm
      initialMode="signUp"
      redirectTo={safeRedirect(searchParams.redirect)}
      googleEnabled={googleEnabled()}
      oauthError={searchParams.error ?? null}
    />
  );
}
