"use client";

/**
 * The last-resort screen: shown when the root layout itself failed to render.
 *
 * Two things make this file unlike every other page.
 *
 * 1. It REPLACES the root layout, so it must supply its own `<html>` and
 *    `<body>`. That is also why it cannot inherit anything: importing
 *    `globals.css` here is the only way it gets styling at all.
 *
 * 2. It renders outside every provider — no ThemeProvider, no Convex, no
 *    Tailwind class from the app's stylesheet if that stylesheet is what broke.
 *
 * It previously rendered `<NextError statusCode={0} />`, Next's built-in error
 * page: a bare serif "Application error" on white, with no stylesheet, no dark
 * mode and no way out except the back button. So the one screen a user sees when
 * everything is broken was the least considered screen in the product.
 *
 * The styles below are INLINE on purpose. If the failure is in the CSS pipeline,
 * a class-based layout renders as unstyled text; inline styles always paint.
 * `color-scheme` plus a media query give it a correct dark appearance without
 * next-themes, which is not mounted here.
 */

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <html lang="en">
      <head>
        <title>Something went wrong · Ayurveda</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </head>
      <body style={{ margin: 0 }}>
        <style>{`
          :root { color-scheme: light dark; --ge-bg:#F3F0E7; --ge-fg:#1C1A17;
                  --ge-soft:#5F594F; --ge-line:#D5D0C3; --ge-brand:#2C6349; }
          @media (prefers-color-scheme: dark) {
            :root { --ge-bg:#171512; --ge-fg:#EDE9DE; --ge-soft:#B1ABA0;
                    --ge-line:#38342E; --ge-brand:#65B38C; }
          }
        `}</style>
        <main
          style={{
            minHeight: "100dvh",
            display: "grid",
            placeItems: "center",
            padding: "1.5rem",
            background: "var(--ge-bg)",
            color: "var(--ge-fg)",
            fontFamily:
              'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
          }}
        >
          <div style={{ maxWidth: "27rem", textAlign: "center" }}>
            <p
              style={{
                margin: 0,
                fontSize: ".72rem",
                letterSpacing: ".14em",
                textTransform: "uppercase",
                color: "var(--ge-brand)",
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
              }}
            >
              Ayurveda
            </p>
            <h1
              style={{
                margin: ".6rem 0 0",
                fontSize: "1.6rem",
                lineHeight: 1.2,
                fontWeight: 600,
                fontFamily: 'ui-serif, Georgia, "Times New Roman", serif',
              }}
            >
              Something went wrong
            </h1>
            {/* No stack trace, no digest, no jargon — this screen is read by a
                person trying to get help with their health, and the exception
                has already gone to Sentry where it is useful. */}
            <p style={{ margin: ".65rem 0 0", color: "var(--ge-soft)", lineHeight: 1.6 }}>
              The page could not be loaded. Your consultations are saved and
              nothing has been lost.
            </p>
            <div
              style={{
                display: "flex",
                gap: ".6rem",
                justifyContent: "center",
                flexWrap: "wrap",
                marginTop: "1.4rem",
              }}
            >
              <button
                type="button"
                onClick={() => reset()}
                style={{
                  cursor: "pointer",
                  border: 0,
                  borderRadius: ".6rem",
                  padding: ".62rem 1.1rem",
                  fontSize: ".92rem",
                  fontWeight: 600,
                  background: "var(--ge-brand)",
                  color: "var(--ge-bg)",
                }}
              >
                Try again
              </button>
              <a
                href="/"
                style={{
                  borderRadius: ".6rem",
                  padding: ".62rem 1.1rem",
                  fontSize: ".92rem",
                  fontWeight: 600,
                  textDecoration: "none",
                  border: "1px solid var(--ge-line)",
                  color: "var(--ge-fg)",
                }}
              >
                Go home
              </a>
            </div>
          </div>
        </main>
      </body>
    </html>
  );
}
