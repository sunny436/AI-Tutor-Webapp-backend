/**
 * argon2id for Better Auth, in exactly the format the API writes and reads with argon2-cffi
 * (backend/app/auth/security.py): a PHC string, `$argon2id$v=19$m=65536,t=3,p=2$<salt>$<hash>`
 * with standard base64 and no padding. So every password set before Better Auth still verifies,
 * and the API can re-authenticate against a hash written here.
 *
 * Node 24's built-in `crypto.argon2` (no dependency; it runs on libuv's thread pool, off the event
 * loop that streams chat replies). At most CONCURRENT hashes run at once: each costs 64 MiB, and
 * the pool is shared with file and DNS work. Bun has no `crypto.argon2`: `bun test` checks only
 * the PHC encoding here; hashing is proven under Node (scripts and the rehearsal).
 */

import * as crypto from "node:crypto";

export const PARAMS = { memory: 65_536, passes: 3, parallelism: 2, tagLength: 32 } as const;
const SALT_BYTES = 16;
const CONCURRENT = 2;
// A stored hash may name its own costs (argon2-cffi's defaults may change); refuse absurd ones.
const MAX_MEMORY_KIB = 262_144;
const MAX_PASSES = 10;

type Argon2Parameters = {
  message: Buffer;
  nonce: Buffer;
  parallelism: number;
  tagLength: number;
  memory: number;
  passes: number;
};
type Argon2 = (
  algorithm: "argon2id",
  parameters: Argon2Parameters,
  callback: (error: Error | null, key: Buffer) => void,
) => void;

export type Phc = { memory: number; passes: number; parallelism: number; salt: Buffer; hash: Buffer };

const PHC = /^\$argon2id\$v=19\$m=(\d+),t=(\d+),p=(\d+)\$([A-Za-z0-9+/]+)\$([A-Za-z0-9+/]+)$/;

const b64 = (bytes: Buffer): string => bytes.toString("base64").replace(/=+$/, "");

export function formatPhc(phc: Phc): string {
  return `$argon2id$v=19$m=${phc.memory},t=${phc.passes},p=${phc.parallelism}$${b64(phc.salt)}$${b64(phc.hash)}`;
}

export function parsePhc(value: string): Phc | null {
  const match = PHC.exec(value);
  if (!match) return null;
  const [, memory, passes, parallelism, salt, hash] = match;
  const phc = {
    memory: Number(memory),
    passes: Number(passes),
    parallelism: Number(parallelism),
    salt: Buffer.from(salt as string, "base64"),
    hash: Buffer.from(hash as string, "base64"),
  };
  if (phc.memory > MAX_MEMORY_KIB || phc.passes > MAX_PASSES || phc.parallelism < 1 || phc.hash.length < 16) {
    return null;
  }
  return phc;
}

let active = 0;
const queue: (() => void)[] = [];

async function withSlot<T>(work: () => Promise<T>): Promise<T> {
  if (active < CONCURRENT) active += 1;
  else await new Promise<void>((resolve) => queue.push(resolve));
  try {
    return await work();
  } finally {
    // A freed slot goes straight to the next in line, so the count never overshoots.
    const next = queue.shift();
    if (next) next();
    else active -= 1;
  }
}

function derive(password: string, salt: Buffer, costs: Omit<Phc, "salt" | "hash">, tagLength: number): Promise<Buffer> {
  const argon2 = (crypto as unknown as { argon2?: Argon2 }).argon2;
  if (!argon2) return Promise.reject(new Error("crypto.argon2 needs Node 24.7 or later"));
  return withSlot(
    () =>
      new Promise((resolve, reject) =>
        argon2(
          "argon2id",
          {
            message: Buffer.from(password, "utf8"),
            nonce: salt,
            parallelism: costs.parallelism,
            tagLength,
            memory: costs.memory,
            passes: costs.passes,
          },
          (error, key) => (error ? reject(error) : resolve(key)),
        ),
      ),
  );
}

export async function hashPassword(password: string): Promise<string> {
  const salt = crypto.randomBytes(SALT_BYTES);
  const hash = await derive(password, salt, PARAMS, PARAMS.tagLength);
  return formatPhc({ ...PARAMS, salt, hash });
}

export async function verifyPassword({ hash, password }: { hash: string; password: string }): Promise<boolean> {
  const phc = parsePhc(hash);
  if (!phc) return false;
  const derived = await derive(password, phc.salt, phc, phc.hash.length);
  return derived.length === phc.hash.length && crypto.timingSafeEqual(derived, phc.hash);
}
