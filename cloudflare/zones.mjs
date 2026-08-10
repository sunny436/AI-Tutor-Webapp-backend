/**
 * List the Cloudflare zones (domains) this account actually owns.
 *
 *   node cloudflare/zones.mjs
 *
 * WHY THIS EXISTS
 * The production hostname must come from the account, not from a guess. Nothing
 * in this repository records a domain — the only Cloudflare history is ephemeral
 * `*.trycloudflare.com` quick tunnels — so inventing one would mean creating DNS
 * records on a zone nobody asked for. This asks Cloudflare instead.
 *
 * It also doubles as a credential check: a token with the wrong permissions
 * fails here, before anything has been created.
 *
 * SECRECY
 * The token is read from cloudflare/.env and sent only as an Authorization
 * header. It is never printed, never logged, and never written anywhere. Errors
 * from the API are echoed, so this scrubs anything token-shaped out of them
 * before display, in case a message quotes the credential back at us.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const API = "https://api.cloudflare.com/client/v4";

/** Minimal .env reader — no dependency, and it must not choke on `=` in values. */
function readEnv(file) {
  const out = {};
  let text;
  try {
    text = readFileSync(file, "utf8");
  } catch {
    return out;
  }
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    out[trimmed.slice(0, eq).trim()] = trimmed.slice(eq + 1).trim();
  }
  return out;
}

const env = readEnv(join(HERE, ".env"));
const token = env.CLOUDFLARE_API_TOKEN || process.env.CLOUDFLARE_API_TOKEN || "";

/** Never let the credential reach stdout, even inside an API error message. */
const scrub = (text) => (token ? String(text).split(token).join("<redacted>") : String(text));

if (!token) {
  console.error("CLOUDFLARE_API_TOKEN is empty.");
  console.error("Paste the token after `CLOUDFLARE_API_TOKEN=` in cloudflare/.env, then rerun.");
  process.exit(2);
}

const call = async (path) => {
  const response = await fetch(`${API}${path}`, {
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  });
  return { status: response.status, body: await response.json().catch(() => ({})) };
};

// 1. Sanity-check the credential.
//
//    NOT via /user/tokens/verify. That endpoint only accepts *user-owned* API
//    tokens; an **account-owned** token is perfectly valid but always gets
//    `401 [1000] Invalid API Token` there. Checking it first therefore rejects a
//    working credential — which is exactly what happened on the first run here.
//
//    /zones is the honest check: it is the permission we actually need, and it
//    answers for both token types.
const verified = await call("/zones?per_page=1");
if (!verified.body?.success) {
  console.error(`Token check FAILED (HTTP ${verified.status}).`);
  for (const error of verified.body?.errors ?? []) {
    console.error(`  - [${error.code}] ${scrub(error.message)}`);
  }
  console.error("\nLikely causes: token mistyped, expired, revoked, or missing Zone|Zone|Read.");
  process.exit(1);
}
console.log("Token accepted by the Cloudflare API.\n");

// 2. The zones themselves.
const zones = await call("/zones?per_page=50");
if (!zones.body?.success) {
  console.error(`Could not list zones (HTTP ${zones.status}).`);
  for (const error of zones.body?.errors ?? []) {
    console.error(`  - [${error.code}] ${scrub(error.message)}`);
  }
  console.error("\nIf this says the token lacks permission, add: Zone | Zone | Read");
  process.exit(1);
}

const list = zones.body.result ?? [];
if (list.length === 0) {
  console.log("No domains are on this Cloudflare account yet.");
  console.log("Add one with 'Add a site' in the dashboard, or tell me which domain to use.");
  process.exit(0);
}

console.log(`${list.length} domain(s) on this account:\n`);
for (const zone of list) {
  // `status` matters: a zone stuck on "pending" has not had its nameservers
  // moved to Cloudflare yet, so DNS records on it would not resolve. Better to
  // see that now than to debug it after the tunnel is running.
  const warning = zone.status === "active" ? "" : "   <-- NOT ACTIVE, nameservers not switched yet";
  console.log(`  ${zone.name}`);
  console.log(`      status:  ${zone.status}${warning}`);
  console.log(`      plan:    ${zone.plan?.name ?? "unknown"}`);
  console.log(`      zone id: ${zone.id}`);
  console.log(`      account: ${zone.account?.name ?? "unknown"} (${zone.account?.id ?? "?"})`);
  console.log("");
}

const active = list.filter((zone) => zone.status === "active");
console.log(
  active.length
    ? `Pick one of the ${active.length} active domain(s) above; the app and API subdomains go under it.`
    : "None are active yet — DNS records cannot work until a zone's nameservers point at Cloudflare.",
);
