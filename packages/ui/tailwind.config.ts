import type { Config } from "tailwindcss";
import defaultTheme from "tailwindcss/defaultTheme";

const config = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}",
  ],
  prefix: "",
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      // THREE ROLES, AND WHY THE MAPPING HAS TO EXIST AT ALL
      //
      // `[locale]/layout.tsx` has always loaded Geist Sans and Geist Mono and
      // put `.variable` on <body>. But `.variable` only DEFINES the custom
      // properties — it does not set `font-family` on anything. Nothing here
      // mapped them either, and `globals.css` sets no font on `body`. So two
      // font files were downloaded and parsed on every page load, and the whole
      // product rendered in Tailwind's fallback stack (Segoe UI on Windows).
      // Every `font-mono` in the app resolved to the stock monospace stack too.
      //
      // The roles are deliberate, not decorative:
      //   sans     everything the interface says
      //   display  headings and the six plan section titles — a reading serif,
      //            so a health answer looks like a reference work rather than a
      //            chat log. Explicitly NOT Inter or Space Grotesk.
      //   mono     provenance ONLY — note filename and relevance score — so a
      //            citation reads as data rather than as marketing copy.
      //
      // `departure` was here before and pointed at `--font-departure-mono`,
      // which is defined nowhere and used by no class. Starter leftover, gone.
      fontFamily: {
        sans: ["var(--font-geist-sans)", ...defaultTheme.fontFamily.sans],
        mono: ["var(--font-geist-mono)", ...defaultTheme.fontFamily.mono],
        display: ["var(--font-display)", ...defaultTheme.fontFamily.serif],
      },
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        // The herbal accent, as a token rather than a hard-coded emerald shade.
        // The existing emerald utility classes are the same family and are left
        // alone: rewriting 140 call sites would be churn with real regression
        // risk and no visible gain.
        brand: {
          DEFAULT: "hsl(var(--brand))",
          foreground: "hsl(var(--brand-foreground))",
          soft: "hsl(var(--brand-soft))",
        },
      },
      borderRadius: {
        // xl and 2xl added so surfaces can differ in softness by role — a page
        // panel should not have the same corner as a chip inside it.
        "2xl": "calc(var(--radius) + 8px)",
        xl: "calc(var(--radius) + 4px)",
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontSize: {
        // A tighter scale than Tailwind's default, with line heights and tracking
        // set per size. Headings get negative tracking (large type looks loose
        // without it); body keeps generous leading because this app is read, not
        // scanned.
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.01em" }],
        xs: ["0.75rem", { lineHeight: "1.125rem" }],
        sm: ["0.8125rem", { lineHeight: "1.375rem" }],
        base: ["0.9375rem", { lineHeight: "1.65rem" }],
        lg: ["1.0625rem", { lineHeight: "1.7rem", letterSpacing: "-0.005em" }],
        xl: ["1.25rem", { lineHeight: "1.75rem", letterSpacing: "-0.01em" }],
        "2xl": ["1.5rem", { lineHeight: "2rem", letterSpacing: "-0.015em" }],
        "3xl": ["1.875rem", { lineHeight: "2.25rem", letterSpacing: "-0.02em" }],
        "4xl": ["2.25rem", { lineHeight: "2.5rem", letterSpacing: "-0.025em" }],
      },
      maxWidth: {
        // One comfortable measure for conversation, used by the chat column so
        // text never runs the full width of a large monitor.
        prose: "68ch",
      },
      // The accordion keyframes and their animations were removed with the rest
      // of the starter's leftovers: `packages/ui` has no Accordion component, so
      // they described a `--radix-accordion-content-height` variable that
      // nothing ever set. They come back with the component, if it is ever
      // needed.
    },
  },
  plugins: [require("tailwindcss-animate")],
} satisfies Config;

export default config;
