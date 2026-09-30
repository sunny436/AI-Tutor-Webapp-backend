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
      // TWO FACES, both the platform's own: nothing to download, and each
      // device shows the face its reader is used to.
      //
      //   display  SERIF. Headings: a textbook's voice for the things a
      //            student reads first.
      //   sans     Everything the interface says.
      //   mono     `--font-mono`, set by the app's root layout: the system code
      //            face, because code is read at length in a tutor's answers.
      fontFamily: {
        // Noto Sans everywhere, Latin then its Devanagari companion (apps/app/src/lib/fonts.ts);
        // code stays monospace.
        sans: [
          "var(--font-noto-sans)",
          "var(--font-noto-sans-devanagari)",
          ...defaultTheme.fontFamily.sans,
        ],
        mono: ["var(--font-mono)", ...defaultTheme.fontFamily.mono],
        display: [
          "var(--font-noto-sans)",
          "var(--font-noto-sans-devanagari)",
          ...defaultTheme.fontFamily.sans,
        ],
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
        // The acting colour (slate blue). See globals.css.
        brand: {
          DEFAULT: "hsl(var(--brand))",
          foreground: "hsl(var(--brand-foreground))",
          soft: "hsl(var(--brand-soft))",
          hover: "hsl(var(--brand-hover))",
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
        // Marks rather than acts (streaks, highlights, sources): never a button,
        // so it never competes with the brand.
        "accent-warm": {
          DEFAULT: "hsl(var(--accent-warm))",
          soft: "hsl(var(--accent-warm-soft))",
        },
        // The learning tools' own colours. Named for the colour, not the tool,
        // so a renamed tool does not rename a token.
        "accent-purple": {
          DEFAULT: "hsl(var(--accent-purple))",
          foreground: "hsl(var(--accent-purple-foreground))",
          soft: "hsl(var(--accent-purple-soft))",
        },
        "accent-pink": {
          DEFAULT: "hsl(var(--accent-pink))",
          soft: "hsl(var(--accent-pink-soft))",
        },
        // Text on the brand gradient (`.bg-hero`, `.bg-hero-deep`).
        hero: {
          foreground: "hsl(var(--hero-foreground))",
          muted: "hsl(var(--hero-muted))",
          deep: "hsl(var(--hero-deep-from))",
        },
        // Decorative fill behind the streak's flame; never text.
        streak: "hsl(var(--streak))",
        sage: {
          DEFAULT: "hsl(var(--sage))",
          soft: "hsl(var(--sage-soft))",
        },
        ivory: "hsl(var(--ivory))",
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
          6: "hsl(var(--chart-6))",
        },
        // The tutor's study cards (features/markdown): the brand, 50 points lighter.
        "study-card": "hsl(var(--study-card-background))",
      },
      borderRadius: {
        // With --radius at 0.5rem these equal Tailwind's own steps (md 6, lg 8,
        // xl 12, 2xl 16). By role: controls are `xl`, cards and bubbles `2xl`,
        // banners `3xl`, pills and avatars-that-are-dots `full`.
        "2xl": "calc(var(--radius) + 8px)",
        xl: "calc(var(--radius) + 4px)",
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      // Tailwind's own type scale, plus one step below `xs` for the smallest
      // labels (badges, timestamps). Small sizes get a little positive tracking
      // so they stay legible.
      // The type scale (Noto Sans), in rem so the student's text-size setting scales it all:
      // body 16/1.65, UI 14/1.45, captions 13/1.40, and the headings H3 17, H2 20, H1 24 (600).
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.02em" }],
        xs: ["0.8125rem", { lineHeight: "1.4" }],
        sm: ["0.875rem", { lineHeight: "1.45" }],
        base: ["1rem", { lineHeight: "1.65", letterSpacing: "-0.005em" }],
        lg: ["1.0625rem", { lineHeight: "1.4" }],
        xl: ["1.25rem", { lineHeight: "1.35" }],
        "2xl": ["1.5rem", { lineHeight: "1.3" }],
      },
      maxWidth: {
        // One comfortable measure for conversation, used by the chat column so
        // text never runs the full width of a large monitor.
        prose: "42.5rem", // 680px: the reading width (660-700px)
      },
      // Motion tokens (globals.css, "motion"). DEFAULT retunes every bare `transition*`;
      // tailwindcss-animate derives its durations and easings from these too.
      transitionDuration: {
        DEFAULT: "var(--motion-fast)",
        fast: "var(--motion-fast)",
        base: "var(--motion-base)",
        slow: "var(--motion-slow)",
      },
      transitionTimingFunction: {
        DEFAULT: "var(--ease-standard)",
        standard: "var(--ease-standard)",
        enter: "var(--ease-enter)",
        exit: "var(--ease-exit)",
      },
      // The accordion keyframes and their animations were removed with the rest
      // of the starter's leftovers: `packages/ui` has no Accordion component, so
      // they described a `--radix-accordion-content-height` variable that
      // nothing ever set. They come back with the component, if it is ever
      // needed.
    },
  },
  plugins: [require("tailwindcss-animate")],
  // `hover:` only where a pointer can hover: a tap on a phone or tablet never leaves a
  // hover style stuck on.
  future: { hoverOnlyWhenSupported: true },
} satisfies Config;

export default config;
