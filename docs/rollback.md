# Rollback

A rollback is a deploy of an earlier commit: the same path as `bun run deploy`
([deployment.md](deployment.md)), so only the parts that differ are rebuilt or restarted.

```sh
bun run rollback                  # the commit that was live before the last deploy
bun run rollback -- <commit>      # any earlier commit (from git log, or the server's HISTORY)
```

It pushes that commit to the production Git repository, moves the production checkout to it, and:

- **Frontend:** if it goes back to the build the last deploy replaced, that build is swapped back
  **without building** (seconds). Otherwise the older frontend is built beside the served one
  first, like any deploy.
- **Backend:** the API restarts on the older code only if the backend differs.
- **Checks:** the same smoke check as a deploy, then the SHAs and a status line.

Afterwards the status says `MISMATCH (the production checkout is not GitHub main)`. That is
expected: production is deliberately behind `main`. Fix the problem, `git push origin main`, and
`bun run deploy`; the status is `MATCH` again.

Running `bun run rollback` twice does not go further back; it returns to the same commit. To go
further back, name the commit (the server's `/opt/aichat/app-state/HISTORY` lists every deploy).

## The database

A rollback never touches the database. If the commit you leave ran a migration, the older code
runs on the newer schema, and the deploy says so (a warning). That is safe because every migration
is backward compatible ([deployment.md](deployment.md#migrations)). To undo a schema change, write a
new migration and deploy it. Never downgrade the production database by hand. Every migration was
preceded by a backup in `/var/backups/aichat`; restoring one loses everything written since, so it
is a last resort (header of `deploy/backup.sh`).

**Sign-in across a rollback past 2026-10-01 (Better Auth, migration 0012).** The older code runs on
the newer schema: the triggers keep `users.password_hash` and `email_verified_at` up to date in both
directions, so every password and verification still holds. The older web app reads its own cookie,
so everyone signs in again once; an account made with Google (no password) uses "forgot password".
While a deploy or rollback swaps the halves, sessions keep working: the API finds every session by
the SHA-256 of its token, whichever release wrote it. If a deploy stops after restarting the API but
with the old web build back (`STOP: the new frontend did not start`), roll back at once:
`bun run rollback`.

**Two-step sign-in across a rollback past 2026-10-02 (migration 0013).** The older release runs on
this schema, but it does not know two-step sign-in: until this release is deployed again, accounts
that turned it on sign in with their password or an email code alone. Their authenticator setup is
kept and applies again after the redeploy. The older release also runs on Next 14.2.35 (open
advisories): roll forward as soon as possible.

Students' files are database rows: a rollback keeps them (older code ignores the tables that hold
them), and deploying `main` again brings the File Library back. To stop only file processing, use
the kill switch instead of a rollback (`FILES_ENABLED=false`, [deployment.md](deployment.md#file-library-appfiles)).

## Automatic protection during a deploy

- **Frontend build fails:** users keep the previous build; nothing is restarted.
- **New frontend doesn't start:** the previous build is swapped back in and restarted
  automatically.
- **API fails its readiness check after a restart:** the deploy stops with `STOP:`; run
  `bun run rollback`.
- **First deploy (the cutover) fails:** the services of the old release layout are put back
  automatically.

## Emergency: without the scripts

Only if the deploy scripts themselves are broken. On the server:

```sh
cd /opt/aichat/app
git log --oneline -5                                   # pick a known-good commit
git reset --hard <commit> && printf 'commit=%s\n' "$(git rev-parse HEAD)" > RELEASE
systemctl restart aichat-api                           # if the backend differs
# the frontend: a build of that commit must be in place (.next-prev is the one before the last deploy)
systemctl stop aichat-web && mv frontend/apps/app/.next frontend/apps/app/.next-bad \
  && mv frontend/apps/app/.next-prev frontend/apps/app/.next && systemctl start aichat-web
```

Then fix the scripts, push, and deploy normally: the next deploy compares against the recorded
state and redoes whatever is needed.
