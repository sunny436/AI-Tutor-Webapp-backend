# Provisioning history

`deploy/` holds the numbered shell scripts used to build the original Linux VM, in the
order they were run — host setup, self-hosted Convex, auth, the backend adapter, jobs,
multi-tenancy, HTTPS via Caddy then Cloudflare, rate limiting, and the UI increments.

**These are a record, not tooling.** 55 of the 61 scripts hardcode the VM's address
(`10.1.30.14`) and install path (`/opt/myos`), and they assume a Debian host with Docker.
None of them will run as-is on another machine.

They are kept because the numbered sequence is the clearest explanation of how the
production environment was assembled and why certain settings exist. Read them; don't
execute them.

For running the project locally, see [../START.md](../START.md).
