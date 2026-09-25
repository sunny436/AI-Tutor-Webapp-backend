# Rollback

> **AI Tutor is released as one application. Frontend and backend are never independently
> deployed to production.** That holds for rollbacks too.

A rollback switches the frontend and the backend back **together**, to one earlier release: both
run from the one directory `/opt/aichat/current` points at, so there is no way to roll back one
without the other. The database is never rolled back.

## Automatic

A deploy rolls back by itself when a release passes its trial checks but fails the live checks
after the switch (the web → API → database chain, or any process not running the new release). It
switches back to the previous release in the same order as a deploy, proves the invariant again,
and ends with `STOP: release <commit> failed its live checks; production is back on <previous>`.
A failure before the switch (checks, build, migrations, trial copies) never touches production.

## Manual

From the repository root on a workstation:

```sh
bun run rollback                          # to the release that was live before this one
bun run rollback -- --to <commit>         # to any kept release (7 to 40 hex characters)
bun run rollback -- --allow-older-schema  # see "Across a migration"
```

It asks you to type `rollback`, then runs on the host as a detached systemd unit
(`aichat-rollback-<time>`), so a lost SSH connection cannot leave it half done. It:

1. picks the target from `/opt/aichat/releases/LIVE-STACK`, the ordered list of releases that were
   live: a second `bun run rollback` goes further back, never forward to the release you just left;
2. checks the target was fully built, and that its files still match its commit;
3. applies the migration guard below;
4. switches: stop web → `current` → target → restart API → start web, with the target's own units;
5. proves pointer = API release = web release = every process's release, plus web → API → database.
   If that fails, it returns to the release it started from.

Afterwards, `bun run status` must end with `INVARIANT OK`. The host keeps the last three live
releases plus the live and previous one (`ls /opt/aichat/releases`, `/opt/aichat/releases/HISTORY`).
To go back to an older commit that is no longer kept, deploy it: `bun run deploy -- --ref <commit>
--older` (it must still be on `main` with successful CI).

## Across a migration

If the release you are leaving ran a migration, the older code will run on the newer schema. That is
safe only when the migration was backward compatible, which is the rule for all migrations
([deployment.md](deployment.md#migrations)). So the rollback refuses by default and says why;
`--allow-older-schema` confirms it. To undo a schema change, write a new migration and deploy it.
Never downgrade the production database by hand. Every migration was preceded by a backup in
`/var/backups/aichat` (the file is named in `HISTORY`); restoring one loses everything written since,
so it is a last resort (header of `deploy/backup.sh`).

## The first release on the old layout

On a host that still ran the two-checkout layout, there is no previous release. If the first
release fails its live checks, the deploy restores the unit files it replaced (kept as
`/etc/systemd/system/aichat-*.before-<time>`) and restarts the old layout.

Production made that move on 2026-09-25 (units saved as `aichat-*.before-20260925052156`; the old
checkouts are still in place). Until a second release has been deployed there, `bun run rollback`
has no earlier release, and going back to the old layout is the manual restore below. If you ever
need it:

```sh
cd /etc/systemd/system
for f in aichat-*.before-<time>; do mv -f "$f" "${f%.before-<time>}"; done
rm -f /opt/aichat/current
systemctl daemon-reload && systemctl restart aichat-api aichat-web
```

## Emergency: without the scripts

Only if the scripts themselves are broken. On the host, keep the order (web down first, so the two
halves never run different releases):

```sh
ls -1t /opt/aichat/releases                                  # pick a kept, built release
systemctl stop aichat-web
ln -sfn /opt/aichat/releases/<commit> /opt/aichat/current.next
mv -Tf /opt/aichat/current.next /opt/aichat/current          # atomic
systemctl restart aichat-api && systemctl start aichat-web
bash /opt/aichat/current/deploy/server/status.sh             # must end with INVARIANT OK
```

Then record what you did in `/opt/aichat/releases/HISTORY`, and push the commit onto
`/opt/aichat/releases/LIVE-STACK` so the next rollback starts from the right place.
