import { describe, expect, test } from "bun:test";

import { dayHasEnded, describeRemaining } from "./countdown";

const minutes = (n: number) => n * 60_000;

describe("the learning day countdown", () => {
  test("hours and minutes, padded, and in words", () => {
    expect(describeRemaining(minutes(134))).toEqual({
      short: "02h 14m",
      spoken: "2 hours 14 minutes left in today's learning day",
    });
    expect(describeRemaining(minutes(18) + 59_000)).toEqual({
      short: "00h 18m",
      spoken: "18 minutes left in today's learning day",
    });
    expect(describeRemaining(minutes(61)).spoken).toBe("1 hour 1 minute left in today's learning day");
  });

  test("never negative at or after midnight", () => {
    expect(describeRemaining(0).short).toBe("00h 00m");
    expect(describeRemaining(-5_000).short).toBe("00h 00m");
  });

  test("the day ends exactly at the server's day end (rollover)", () => {
    const end = "2026-09-26T18:30:00Z";
    expect(dayHasEnded(end, Date.parse("2026-09-26T18:29:59Z"))).toBe(false);
    expect(dayHasEnded(end, Date.parse("2026-09-26T18:30:00Z"))).toBe(true);
  });
});
