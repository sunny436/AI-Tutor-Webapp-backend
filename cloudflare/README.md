> **SUPERSEDED — 2026-08-20**
>
> Describes Windows paths, a PowerShell installer, and `start-all.ps1`. It documents 2 of the 4 tunnel hostnames and shows Convex as cloud-hosted; Convex is now self-hosted with two hostnames of its own. The token permission matrix and the shared-zone warning below are still correct and still matter.
>
> Production moved to the Ubuntu VM `10.1.30.37` on 19 Aug 2026.
> The authoritative description is [INFRASTRUCTURE.md](../INFRASTRUCTURE.md).
> Everything below is kept for history and may be wrong.

# Cloudflare edge

The application runs on the **company machine**. Cloudflare hosts nothing — it
provides DNS, TLS, a firewall, and a tunnel that lets the internet reach a
machine with no open ports and no public IP.

```
                        User
                          |
     Cloudflare  —  DNS · Universal SSL · WAF
                          |
                 Cloudflare Tunnel
        cloudflared makes an OUTBOUND connection.
        No inbound port is opened anywhere.
                          |
                  Company machine
            +-----------------------------+
            |  Next.js   127.0.0.1:3000   |
            |  FastAPI   127.0.0.1:4000   |
            +-----------------------------+
                    |               |
             Convex Cloud     Groq -> OpenRouter
```

| Public hostname | Serves | Local port |
|---|---|---|
| `ayur.namahos.com` | Next.js dashboard | 3000 |
| `ayur-api.namahos.com` | Python AI backend | 4000 |

The API needs its own hostname because the browser calls it directly and
cloudflared forwards the full request path without stripping a prefix — a single
host routing `/ai/*` would deliver `/ai/consult` to FastAPI, which has no such
route.

Both processes bind **127.0.0.1 only**. Nothing on the LAN can reach them; the
tunnel is the sole way in.

## Files here

| File | Committed | Contains |
|---|---|---|
| `.env` | **no** — git-ignored | the real API token and ids |
| `.env.example` | yes | the same keys with empty values |
| `config.yml` | yes | tunnel ingress rules. No secrets |
| `zones.mjs` | yes | lists the domains a token can see |

The tunnel's own credentials live in `%USERPROFILE%\.cloudflared\<tunnel-id>.json`
— deliberately outside the repository, so they cannot be committed by accident.

## Setting it up on a new machine

1. **Install cloudflared** (no administrator rights needed):

   ```powershell
   New-Item -ItemType Directory -Force "$env:USERPROFILE\.cloudflared\bin"
   Invoke-WebRequest -UseBasicParsing `
     -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" `
     -OutFile "$env:USERPROFILE\.cloudflared\bin\cloudflared.exe"
   ```

2. **Create the token.** Dashboard → My Profile → API Tokens → Create Custom
   Token, with exactly these permissions:

   | Type | Item | Level |
   |---|---|---|
   | Account | Cloudflare Tunnel | Edit |
   | Zone | DNS | Edit |
   | Zone | Zone | Read |
   | Zone | Zone Settings | Edit *(optional)* |

   Scope **Zone Resources** to the one domain. A token limited this way cannot
   reach billing, cannot buy anything, and cannot touch other domains on the
   account.

3. **Fill in `.env`** — copy `.env.example` to `.env` and paste the values. Never
   put a token in source, in a commit message, or in a chat.

4. **Confirm the token can see the domain:**

   ```bash
   node cloudflare/zones.mjs
   ```

5. **Create the tunnel and DNS records**, then start it:

   ```powershell
   & "$env:USERPROFILE\.cloudflared\bin\cloudflared.exe" `
       --config .\cloudflare\config.yml --no-autoupdate tunnel run
   ```

   In normal operation `scripts/production/start-all.ps1` does this for you.

## Notes worth keeping

**Do not use a broadly-scoped token.** The one first supplied for this project
carried account-wide write access including `Billing Write` and
`Workers Containers Write` — it could have created charges. It was used once to
mint the narrow token above and then removed from disk. Revoke any such token
once setup is done.

**Zone settings are shared.** `namahos.com` also carries the company's main
site, a Vercel deployment and production email (MX, SPF, DKIM, DMARC). Zone-wide
switches such as *Always Use HTTPS*, *SSL: Full (strict)* and *HSTS* apply to all
of them, so a change made for this app can break someone else's. The HTTP→HTTPS
redirect therefore lives in `apps/app/src/middleware.ts`, scoped to this app
alone, and the security headers are set by Next.js rather than at the edge.

**Everything used here is on the Free plan** — DNS, Universal SSL, Tunnel and the
free managed WAF ruleset. No paid feature was enabled.

**The `verbose` flag.** `AUTH_VERBOSE=1` makes the Convex Auth middleware log its
reasoning. It was how the sign-in redirect loop was diagnosed. Leave it off in
production; the output is noisy and includes token expiry details.
