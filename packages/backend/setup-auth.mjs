// setup-auth.mjs
// One-time: generate the RS256 login keys that Convex Auth needs, and set them
// on your Convex deployment (JWT_PRIVATE_KEY, JWKS, SITE_URL).
// Run from packages/backend:   bun setup-auth.mjs
//
// This replaces the interactive `npx @convex-dev/auth` step (which can hang on
// Windows). No prompts, and your private key never leaves your computer.

import { generateKeyPair, exportPKCS8, exportJWK } from "jose";

const SITE_URL = process.env.SITE_URL || "http://localhost:3000";

console.log("Generating RS256 keypair...");
const { publicKey, privateKey } = await generateKeyPair("RS256", {
  extractable: true,
});

// Private key in the "spaces instead of newlines" format Convex Auth expects.
const privatePem = (await exportPKCS8(privateKey)).trimEnd().replace(/\n/g, " ");

// Public key as a JWKS (what other services use to verify the login token).
const jwk = await exportJWK(publicKey);
jwk.use = "sig";
jwk.alg = "RS256";
const jwks = JSON.stringify({ keys: [jwk] });

function setEnv(name, value) {
  console.log(`Setting ${name} on Convex...`);
  // Array args = no shell quoting problems (important: the key has spaces).
  // "--" tells the Convex CLI to stop reading flags (key starts with "-----").
  const proc = Bun.spawnSync(["bun", "x", "convex", "env", "set", "--", name, value], {
    stdout: "inherit",
    stderr: "inherit",
  });
  if (proc.exitCode !== 0) {
    throw new Error(`Failed to set ${name}`);
  }
}

setEnv("JWT_PRIVATE_KEY", privatePem);
setEnv("JWKS", jwks);
setEnv("SITE_URL", SITE_URL);

console.log("\n✅ Done! Login keys are set on Convex. You can now sign up / log in.");
