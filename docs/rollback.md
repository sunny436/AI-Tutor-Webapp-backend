# Rollback

A rollback switches the frontend and the backend back **together**: both run from the one directory
`/opt/aichat/current` points at, so there is no way to roll back one without the other. The database
is never rolled back.

## Automatic

`deploy.sh` rolls back by itself when a release passes its trial checks but fails the live checks
after the switch. It points `current` back at the previous release, restarts both services, re-checks
them, and ends with `STOP: release <commit> failed its live checks; production is back on <previous>`.
A failure before the switch (build, migrations, trial copies) never touches production at all.

## Manual

From the repository root on a workstation:

```sh
bun run rollback                          # to the release that was live before this one
bun run rollback -- --to <commit>         # to any kept release (7+ characters of the commit)
bun run rollback -- --allow-older-schema  # see "Across a migration"
```

The host keeps three releases: the live one, the previous one and one more (see
`ls /opt/aichat/releases` and `/opt/aichat/releases/HISTORY`). The rollback checks web → API →
database on the live ports and that both services run the target release. If those checks fail, it
returns to the release it started from.

## Across a migration

If the release you are leaving ran a migration, the older code will run on the newer schema. That is
safe only when the migration was backward compatible, which is the rule for all migrations
([deployment.md](deployment.md#migrations)). So `rollback.sh` refuses by default and says why.
`--allow-older-schema` confirms it. To undo a schema change, write a new migration and deploy it.
Never downgrade the production database by hand.

## The first release on the old layout

On a host that still ran the two-checkout layout, there is no previous release. If the first
release fails its live checks, `release.sh` restores the unit files it replaced (kept as
`/etc/systemd/system/aichat-*.before-<time>`) and restarts the old layout. If you ever need to do
that by hand:

```sh
cd /etc/systemd/system
for f in aichat-*.before-<time>; do mv -f "$f" "${f%.before-<time>}"; done
rm -f /opt/aichat/current
systemctl daemon-reload && systemctl restart aichat-api aichat-web
```

## Emergency: without the scripts

If the scripts themselves are broken, on the host:

```sh
ls -1t /opt/aichat/releases                                  # pick a kept release
ln -sfn /opt/aichat/releases/<commit> /opt/aichat/current.next
mv -Tf /opt/aichat/current.next /opt/aichat/current          # atomic
systemctl restart aichat-api && systemctl restart aichat-web
bash /opt/aichat/current/deploy/infra-check.sh
```

Then record what you did in `/opt/aichat/releases/HISTORY`.
