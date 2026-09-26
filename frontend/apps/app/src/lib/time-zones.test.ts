import { expect, test } from "bun:test";

import { currentZoneName, supportedZones } from "./time-zones";

test("old ICU names become the current IANA names; others are unchanged", () => {
  expect(currentZoneName("Asia/Calcutta")).toBe("Asia/Kolkata");
  expect(currentZoneName("Europe/Kiev")).toBe("Europe/Kyiv");
  expect(currentZoneName("Asia/Kolkata")).toBe("Asia/Kolkata");
  expect(currentZoneName("Europe/London")).toBe("Europe/London");
});

test("the zone list uses current names, once each, sorted", () => {
  expect(supportedZones(["UTC", "Asia/Calcutta", "Asia/Kolkata", "America/New_York"])).toEqual([
    "America/New_York",
    "Asia/Kolkata",
    "UTC",
  ]);
});
