"use client";

import { useMemo } from "react";
import { encode } from "uqr";

/**
 * A QR code drawn as SVG paths from uqr's module matrix (no HTML string is ever injected: the
 * encoded text, here an otpauth:// address with the student's email, never reaches the DOM).
 * Black on white in every theme, which is what a camera reads.
 */
export function QrCode({ value, label }: { value: string; label: string }) {
  const { path, size } = useMemo(() => {
    const { data, size } = encode(value, { ecc: "M", border: 2 });
    const squares: string[] = [];
    data.forEach((row, y) => {
      row.forEach((dark, x) => {
        if (dark) squares.push(`M${x} ${y}h1v1h-1z`);
      });
    });
    return { path: squares.join(""), size };
  }, [value]);

  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${size} ${size}`}
      shapeRendering="crispEdges"
      className="h-44 w-44 rounded-lg bg-white text-black"
    >
      <path d={path} fill="currentColor" />
    </svg>
  );
}
