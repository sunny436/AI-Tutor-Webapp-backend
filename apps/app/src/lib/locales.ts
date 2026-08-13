/**
 * The locale list, and the one function that removes a locale from a path.
 *
 * WHY THIS FILE EXISTS
 *
 * Two separate problems shared one root cause.
 *
 * 1. The list was written out three times in `middleware.ts` alone — once for
 *    `createI18nMiddleware`, once as `LOCALES`, and once inside the regex
 *    `/^\/(en|fr|es)(?=\/|$)/`. Three copies of a list that must agree is a bug
 *    waiting for whoever adds the fourth language.
 *
 * 2. `urlMappingStrategy: "redirect"` means the browser URL ALWAYS carries the
 *    locale: `/en/consult`, never `/consult`. But the app compared bare paths
 *    against it everywhere:
 *
 *        sidebar.tsx       pathname === item.href      // "/consult"
 *        topbar.tsx        TITLES[pathname]            // keyed "/consult"
 *        settings/layout   pathname === "/settings"
 *
 *    `usePathname()` returns "/en/consult", so every one of those comparisons
 *    was false on every render. The consequence was visible on the live site and
 *    had been there long enough to look intentional: **no sidebar item has ever
 *    highlighted**, and the topbar breadcrumb read "Dashboard" on every page,
 *    including the chat, because `TITLES[pathname]` always missed and fell
 *    through to its default.
 */

export const LOCALES = ["en", "fr", "es"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en";

/** `/en/consult` → `/consult`, `/en` → `/`, `/consult` → `/consult`. */
export function stripLocale(pathname: string): string {
  for (const locale of LOCALES) {
    if (pathname === `/${locale}`) return "/";
    if (pathname.startsWith(`/${locale}/`)) return pathname.slice(locale.length + 1);
  }
  return pathname || "/";
}

/**
 * Is `pathname` this nav item, or somewhere inside it?
 *
 * `/settings/billing` must light up "Settings" as well as itself, but `/` must
 * not light up for every page in the app — hence the exact check for the root.
 */
export function isActivePath(pathname: string, href: string): boolean {
  const path = stripLocale(pathname);
  const target = href.split("?")[0] ?? href;
  if (target === "/") return path === "/";
  return path === target || path.startsWith(`${target}/`);
}
