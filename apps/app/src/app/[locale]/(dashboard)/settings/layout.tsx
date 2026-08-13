"use client";
import { I18nProviderClient, useScopedI18n } from "@/locales/client";
import { buttonVariants } from "@v1/ui/button";
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
  return (
    <div className="flex h-full w-full px-4 py-8 sm:px-6">
      <div className="mx-auto flex h-full w-full max-w-screen-xl flex-col gap-8 lg:flex-row lg:gap-12">
        {/*
          Was `hidden … lg:flex`, so below 1024px the settings navigation simply
          did not exist and Billing was unreachable from Settings on every tablet
          and phone. It becomes a horizontal, scrollable tab row instead of
          disappearing.
        */}
        <nav
          aria-label="Settings"
          className="flex w-full shrink-0 flex-row gap-0.5 overflow-x-auto pb-1 lg:w-64 lg:flex-col lg:overflow-visible lg:pb-0"
        >
          <Link
            href="/settings"
            aria-current={isSettingsPath ? "page" : undefined}
            className={cn(
              buttonVariants({ variant: "ghost" }),
              "shrink-0 justify-start rounded-md",
              isSettingsPath && "bg-primary/5",
            )}
          >
            <span
              className={cn(
                "text-sm text-muted-foreground",
                isSettingsPath && "font-medium text-foreground",
              )}
            >
              {t("general")}
            </span>
          </Link>
          <Link
            href="/settings/billing"
            aria-current={isBillingPath ? "page" : undefined}
            className={cn(
              buttonVariants({ variant: "ghost" }),
              "shrink-0 justify-start rounded-md",
              isBillingPath && "bg-primary/5",
            )}
          >
            <span
              className={cn(
                "text-sm text-muted-foreground",
                isBillingPath && "font-medium text-foreground",
              )}
            >
              {t("billing")}
            </span>
          </Link>
        </nav>
        {children}
      </div>
    </div>
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
