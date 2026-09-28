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
