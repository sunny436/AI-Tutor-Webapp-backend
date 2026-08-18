"use client";
import { I18nProviderClient, useScopedI18n } from "@/locales/client";
import { PageShell } from "@v1/ui/page-shell";
import { cn } from "@v1/ui/utils";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { stripLocale } from "@/lib/locales";

const LayoutContainer = ({ children }: { children: React.ReactNode }) => {
  const t = useScopedI18n("settings.sidebar");
  // Same locale-prefix bug as the sidebar: the URL is `/en/settings`, so neither
  // of these was ever true and no settings tab has ever looked selected.
  const path = stripLocale(usePathname());
  const isSettingsPath = path === "/settings";
  const isBillingPath = path === "/settings/billing";
  // A real segmented rail rather than two ghost Buttons: `bg-primary/5` for the
  // selected tab was the near-black TEXT colour at 5%, which is invisible in
  // light mode and a grey smear in dark. PageShell also gives settings the
  // backdrop-wash it was the only dashboard page (with /platform) to lack.
  const tab = (selected: boolean) =>
    cn(
      "focus-ring flex h-9 shrink-0 items-center justify-center rounded-lg px-3 text-sm transition-colors lg:justify-start",
      selected
        ? "bg-surface-2 font-medium text-foreground"
        : "text-text-secondary hover:bg-surface-2/60 hover:text-foreground",
    );

  return (
    <PageShell className="flex h-full py-6 sm:py-8">
      <div className="flex h-full w-full flex-col gap-8 lg:flex-row lg:gap-12">
        {/*
          Was `hidden … lg:flex`, so below 1024px the settings navigation simply
          did not exist and Billing was unreachable from Settings on every tablet
          and phone. It becomes a horizontal, scrollable tab row instead of
          disappearing.
        */}
        <nav
          aria-label="Settings"
          className="scrollbar-subtle flex w-full shrink-0 flex-row gap-1 overflow-x-auto rounded-xl border border-border bg-surface p-1 lg:w-64 lg:flex-col lg:overflow-visible"
        >
          <Link
            href="/settings"
            aria-current={isSettingsPath ? "page" : undefined}
            className={tab(isSettingsPath)}
          >
            {t("general")}
          </Link>
          <Link
            href="/settings/billing"
            aria-current={isBillingPath ? "page" : undefined}
            className={tab(isBillingPath)}
          >
            {t("billing")}
          </Link>
        </nav>
        {children}
      </div>
    </PageShell>
  );
};

export default function Layout({
  children,
  params,
}: { children: React.ReactNode; params: { locale: string } }) {
  return (
    <I18nProviderClient locale={params.locale}>
      <LayoutContainer>{children}</LayoutContainer>
    </I18nProviderClient>
  );
}
