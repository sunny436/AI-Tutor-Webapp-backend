import localFont from "next/font/local";

/**
 * Poppins, the product's one typeface (SIL Open Font License, src/fonts/poppins/OFL.txt).
 * Served from this app, not a font CDN: nothing to fetch at build time or from the browser,
 * and nothing for the CSP to allow. Latin only; other scripts (Devanagari) use the system
 * font from the fallback stack.
 */
export const poppins = localFont({
  src: [
    { path: "../fonts/poppins/poppins-latin-400.woff2", weight: "400", style: "normal" },
    { path: "../fonts/poppins/poppins-latin-500.woff2", weight: "500", style: "normal" },
    { path: "../fonts/poppins/poppins-latin-600.woff2", weight: "600", style: "normal" },
    { path: "../fonts/poppins/poppins-latin-700.woff2", weight: "700", style: "normal" },
    { path: "../fonts/poppins/poppins-latin-800.woff2", weight: "800", style: "normal" },
    { path: "../fonts/poppins/poppins-latin-900.woff2", weight: "900", style: "normal" },
  ],
  variable: "--font-poppins",
  display: "swap",
  fallback: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
});
