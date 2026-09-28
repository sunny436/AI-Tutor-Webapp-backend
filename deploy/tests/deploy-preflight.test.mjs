/**
 * deploy/deploy.sh's pre-flight, for real, against throwaway repositories: a bare repository
 * stands in for GitHub, and a stub `ssh` reports a chosen live release and refuses the upload
 * (reaching the upload is how a test knows the pre-flight passed). Rehearsal mode, so nothing
 * here can reach a real host.
 */
import { afterAll, describe, expect, setDefaultTimeout, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { chmodSync, copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, dirname, join } from "node:path";

import { REQUIRED_JOBS } from "../ci-gate.mjs";

const ROOT = join(import.meta.dir, "..", "..");
const FILES = ["deploy/deploy.sh", "deploy/local-gate.mjs", "deploy/ci-gate.mjs", "deploy/server/bootstrap.sh", "deploy/server/verify-release.py"];
const posix = (path) => path.replaceAll("\\", "/");
// Each case runs the real deploy.sh: git, bun and a fetch take a few seconds, more on Windows.
setDefaultTimeout(60_000);
const created = [];
afterAll(() => {
  for (const dir of created) rmSync(dir, { recursive: true, force: true });
});

function repository() {
  const dir = mkdtempSync(join(tmpdir(), "deploy-preflight-"));
  created.push(dir);
  const origin = join(dir, "origin.git");
  const work = join(dir, "work");
  const bin = join(dir, "bin");
  const git = (...args) => {
    const result = spawnSync("git", ["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "core.autocrlf=false", ...args], {
      cwd: work,
      encoding: "utf8",
    });
    if (result.status !== 0) throw new Error(`git ${args.join(" ")}: ${result.stderr}`);
    return result.stdout.trim();
  };
  spawnSync("git", ["init", "-q", "--bare", "-b", "main", origin]);
  mkdirSync(work);
  git("init", "-q", "-b", "main");
  for (const file of FILES) {
    mkdirSync(dirname(join(work, file)), { recursive: true });
    copyFileSync(join(ROOT, file), join(work, file));
  }
  writeFileSync(join(work, ".gitignore"), ".deploy/\n");
  writeFileSync(join(work, "app.txt"), "base\n");
  git("add", "-A");
  git("commit", "-q", "-m", "base");
  git("remote", "add", "origin", posix(origin));
  git("push", "-q", "origin", "main");
  // The stub ssh: the rehearsal marker exists, the live release is $FAKE_LIVE, uploads fail.
  mkdirSync(bin);
  writeFileSync(
    join(bin, "ssh"),
    '#!/usr/bin/env bash\ncase "$*" in\n  *REHEARSAL*) exit 0 ;;\n  *readlink*) echo "live=${FAKE_LIVE:-}" ;;\n  *) echo "stub ssh: upload refused" >&2; exit 42 ;;\nesac\n',
  );
  chmodSync(join(bin, "ssh"), 0o755);

  const repo = {
    git,
    commit(message, file = "app.txt") {
      writeFileSync(join(work, file), `${message}\n`);
      git("add", "-A");
      git("commit", "-q", "-m", message);
      return git("rev-parse", "HEAD");
    },
    verified(sha, result = "success") {
      mkdirSync(join(work, ".deploy", "verified"), { recursive: true });
      const evidence = {
        version: 1,
        sha,
        tree: git("rev-parse", `${sha}^{tree}`),
        source: "local",
        rehearsal: true,
        result,
        log_sha256: "-",
        jobs: REQUIRED_JOBS.map((name) => ({ name, conclusion: result })),
      };
      writeFileSync(join(work, ".deploy", "verified", `${sha}.json`), JSON.stringify(evidence));
    },
    deploy(args, { live = "", host = "fakehost" } = {}) {
      const result = spawnSync("bash", ["deploy/deploy.sh", "--yes", ...args], {
        cwd: work,
        encoding: "utf8",
        env: {
          ...process.env,
          PATH: `${bin}${delimiter}${process.env.PATH}`,
          DEPLOY_REHEARSAL: "1",
          DEPLOY_REHEARSAL_SOURCE: posix(origin),
          DEPLOY_HOST: host,
          FAKE_LIVE: live,
        },
      });
      const output = `${result.stdout}\n${result.stderr}`;
      return { status: result.status, output, passed: output.includes("stub ssh: upload refused") };
    },
    head: () => git("rev-parse", "HEAD"),
    write: (file, text) => writeFileSync(join(work, file), text),
  };
  return repo;
}

describe("deploy pre-flight: only the verified, pushed commit checked out here", () => {
  test("a verified commit on GitHub that contains main and the live release passes", () => {
    const repo = repository();
    const live = repo.head();
    const sha = repo.commit("feature");
    repo.git("push", "-q", "origin", "HEAD:refs/heads/feature");
    repo.verified(sha);
    const run = repo.deploy(["--ref", sha], { live });
    expect(run.output).toContain("contains it, plus 1 commit(s)");
    expect(run.passed).toBe(true);
  });

  test("--ref is required", () => {
    const repo = repository();
    expect(repo.deploy([]).output).toContain("--ref <commit> is required");
  });

  test("a --ref that is not the commit checked out here is refused", () => {
    const repo = repository();
    const first = repo.head();
    repo.commit("second");
    repo.git("push", "-q", "origin", "main");
    repo.verified(first);
    const run = repo.deploy(["--ref", first]);
    expect(run.output).toContain("but this checkout is at");
    expect(run.passed).toBe(false);
  });

  test("an uncommitted change is refused", () => {
    const repo = repository();
    const sha = repo.head();
    repo.verified(sha);
    repo.write("app.txt", "edited but not committed\n");
    expect(repo.deploy(["--ref", sha]).output).toContain("uncommitted or untracked");
  });

  test("an untracked file is refused", () => {
    const repo = repository();
    const sha = repo.head();
    repo.verified(sha);
    repo.write("stray.txt", "x");
    expect(repo.deploy(["--ref", sha]).output).toContain("uncommitted or untracked");
  });

  test("an unverified commit is refused", () => {
    const repo = repository();
    const run = repo.deploy(["--ref", repo.head()]);
    expect(run.output).toContain("has no passing verification");
    expect(run.passed).toBe(false);
  });

  test("a commit whose verification failed is refused", () => {
    const repo = repository();
    const sha = repo.head();
    repo.verified(sha, "failure");
    expect(repo.deploy(["--ref", sha]).output).toContain("has no passing verification");
  });

  test("a commit that is on no GitHub branch (never pushed) is refused", () => {
    const repo = repository();
    const sha = repo.commit("local only");
    repo.verified(sha);
    const run = repo.deploy(["--ref", sha]);
    expect(run.output).toContain("is on no branch");
    expect(run.passed).toBe(false);
  });

  test("a commit behind GitHub's main is refused (without --older)", () => {
    const repo = repository();
    const old = repo.head();
    repo.commit("newer on main");
    repo.git("push", "-q", "origin", "main");
    repo.git("checkout", "-q", "--detach", old);
    repo.verified(old);
    expect(repo.deploy(["--ref", old]).output).toContain("does not contain GitHub's main");
  });

  test("a commit that would drop the live release's commits is refused", () => {
    const repo = repository();
    const base = repo.head();
    const other = repo.commit("deployed from another machine");
    repo.git("push", "-q", "origin", "HEAD:refs/heads/other-work");
    repo.git("checkout", "-q", "-b", "mine", base);
    const mine = repo.commit("mine", "mine.txt");
    repo.git("push", "-q", "origin", "HEAD:refs/heads/mine");
    repo.verified(mine);
    const run = repo.deploy(["--ref", mine], { live: other });
    expect(run.output).toContain("does not contain the live release");
    expect(run.passed).toBe(false);
  });

  test("a live release that is not on GitHub stops the deploy", () => {
    const repo = repository();
    const sha = repo.head();
    repo.verified(sha);
    expect(repo.deploy(["--ref", sha], { live: "f".repeat(40) }).output).toContain("is on no branch");
  });

  test("an older commit of main: refused, unless --older on purpose (a downgrade of the live release)", () => {
    const repo = repository();
    const old = repo.head();
    const tip = repo.commit("tip");
    repo.git("push", "-q", "origin", "main");
    repo.git("checkout", "-q", "--detach", old);
    repo.verified(old);
    expect(repo.deploy(["--ref", old], { live: tip }).passed).toBe(false);
    const run = repo.deploy(["--ref", old, "--older"], { live: tip });
    expect(run.output).toContain("a downgrade");
    expect(run.passed).toBe(true);
  });

  test("rehearsal mode never reaches the production host", () => {
    const repo = repository();
    const sha = repo.head();
    repo.verified(sha);
    expect(repo.deploy(["--ref", sha], { host: "root@10.1.30.37" }).output).toContain("never deploys to production");
  });
});
