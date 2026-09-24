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
      // next/font's `.variable` only DEFINES a custom property — it does not set
      // `font-family` on anything, and `globals.css` sets no font on `body`.
      // Without this mapping every font file is downloaded and parsed and the
      // app still renders in Tailwind's fallback stack (Segoe UI on Windows).
      // The app's root layout defines the three variables.
      //
      // The roles are deliberate, not decorative:
      //
      //   display  ECZAR. Headings. Real stroke contrast and a slightly
      //            calligraphic axis, so a page of answer reads as something
      //            written rather than as a log.
      //
      //   sans     HANKEN GROTESK. Everything the interface says. A humanist
      //            grotesque with open apertures and a warm, slightly
      //            irregular rhythm — it sits on warm paper without the
      //            clinical flatness of a neo-grotesque.
      //
      //   mono     The system monospace stack. Code is read at length in a
      //            chat app, and the platform's own code face does that best,
      //            with nothing to download.
      //
      // Explicitly NOT Inter, Roboto, or Space Grotesk. Those are where every
      // generated interface lands, and landing there would undo the point of
      // the direction before a single colour is applied.
      //
      // `departure` was here before and pointed at `--font-departure-mono`,
      // which is defined nowhere and used by no class. Starter leftover, gone.
      fontFamily: {
        sans: ["var(--font-ui)", ...defaultTheme.fontFamily.sans],
        mono: ["var(--font-mono)", ...defaultTheme.fontFamily.mono],
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
        // The green accent, as a token rather than a hard-coded emerald shade.
        // The existing emerald utility classes are the same family and are left
        // alone: rewriting 140 call sites would be churn with real regression
        // risk and no visible gain.
        brand: {
          DEFAULT: "hsl(var(--brand))",
          foreground: "hsl(var(--brand-foreground))",
          soft: "hsl(var(--brand-soft))",
        },
        // A raised pane when `card` is already the thing sitting on it.
        surface: {
          DEFAULT: "hsl(var(--surface))",
          2: "hsl(var(--surface-2))",
        },
        // Names what 90 call sites spell as `text-primary/60` — a colour
        // decision currently hidden inside an opacity, which is why it drifts
        // (/45, /50, /60, /70 and /75 all appear, meaning the same thing).
        "text-secondary": "hsl(var(--text-secondary))",
        // The second accent. Green acts, ochre marks: this is for sources and
        // highlights and never for a button, so the two never compete.
        "accent-warm": {
          DEFAULT: "hsl(var(--accent-warm))",
          soft: "hsl(var(--accent-warm-soft))",
        },
        success: {
          DEFAULT: "hsl(var(--success))",
          soft: "hsl(var(--success-soft))",
        },
        warning: {
          DEFAULT: "hsl(var(--warning))",
          soft: "hsl(var(--warning-soft))",
        },
        info: {
          DEFAULT: "hsl(var(--info))",
          soft: "hsl(var(--info-soft))",
        },
        // The modal scrim. See the --overlay note in globals.css.
        overlay: "hsl(var(--overlay))",
        // --chart-1..5 have existed in globals.css since the token pass and
        // were mapped nowhere, so `bg-chart-1` was not a class — five dead
        // custom properties. Mapping them costs two lines and makes the
        // stylesheet honest about what it defines.
        chart: {
          1: "hsl(var(--chart-1))",
          2: "hsl(var(--chart-2))",
          3: "hsl(var(--chart-3))",
          4: "hsl(var(--chart-4))",
          5: "hsl(var(--chart-5))",
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
        // Small sizes get POSITIVE tracking: at 11-12px on a textured warm
        // ground, letters set tight fill in and stop resolving.
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.02em" }],
        xs: ["0.75rem", { lineHeight: "1.15rem", letterSpacing: "0.01em" }],
        sm: ["0.8125rem", { lineHeight: "1.4rem" }],
        // Generous leading: this product is READ, not scanned, and a plan runs
        // to six sections.
        base: ["0.9375rem", { lineHeight: "1.7rem" }],
        // The display sizes step harder than the stock scale. Eczar has real
        // stroke contrast, and contrast needs size to show — a timid jump
        // wastes the face and leaves headings looking like bold body text.
        lg: ["1.125rem", { lineHeight: "1.75rem", letterSpacing: "-0.005em" }],
        xl: ["1.375rem", { lineHeight: "1.85rem", letterSpacing: "-0.01em" }],
        "2xl": ["1.75rem", { lineHeight: "2.1rem", letterSpacing: "-0.015em" }],
        "3xl": ["2.125rem", { lineHeight: "2.4rem", letterSpacing: "-0.02em" }],
        "4xl": [
          "2.625rem",
          { lineHeight: "2.85rem", letterSpacing: "-0.022em" },
        ],
        // The landing hero is the one heading in the product that fell through
        // to Tailwind's stock 3rem/1 with NO tracking, while every h2 below it
        // gets -0.02em — which is why the hero read looser than the sections
        // under it. Tracking continues the scale's progression (-.025 -> -.03).
        "5xl": ["3.25rem", { lineHeight: "1.05", letterSpacing: "-0.025em" }],
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
