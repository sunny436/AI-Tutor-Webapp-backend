/**
 * The generated contract must be current, and the web app's limits must come from it.
 *
 * A backend change to an enum or a limit regenerates docs/openapi.json; without
 * `bun run contract` this file would silently keep the old values, so the test fails.
 */

import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { CONTRACT } from "./contract.gen";
import { renderContract } from "./contract-render";
import { CODE_LENGTH, DISPLAY_NAME_MAX, MESSAGE_MAX, PASSWORD_MAX, PASSWORD_MIN, TITLE_MAX } from "./types";

const here = dirname(fileURLToPath(import.meta.url));
const openapi = JSON.parse(readFileSync(join(here, "../../../../../../docs/openapi.json"), "utf8"));

describe("generated contract", () => {
  test("contract.gen.ts is current (run `bun run contract`)", () => {
    expect(readFileSync(join(here, "contract.gen.ts"), "utf8")).toBe(renderContract(openapi));
  });

  test("the web app's limits are the backend's", () => {
    expect(MESSAGE_MAX).toBe(CONTRACT.ChatRequest.message.maxLength);
    expect(TITLE_MAX).toBe(CONTRACT.RenameConversationRequest.title.maxLength);
    // Passwords are set by Better Auth (8 to 128, lib/auth/config.ts); the API re-authenticates
    // with the same longest password.
    expect([PASSWORD_MIN, PASSWORD_MAX]).toEqual([8, 128]);
    expect(PASSWORD_MAX).toBe(CONTRACT.DeleteMeRequest.password.maxLength);
    expect(DISPLAY_NAME_MAX).toBe(CONTRACT.ProfileSet.displayName.maxLength);
    expect(CONTRACT.EmailConfirmRequest.code.pattern).toBe(`^\\d{${CODE_LENGTH}}$`);
  });
});
