# Caddy Setup

This project works well behind Caddy when you want one HTTPS origin for:

- the Next.js frontend,
- the FastAPI backend,
- frontend WebSocket traffic,
- optional local Guacamole web access,
- Microsoft Entra redirect callbacks.

Caddy is only a reverse proxy and TLS terminator here. It does not run Guacamole containers and it does not replace Docker, Tomcat, or your Linux-side Nginx setup.

## Why Caddy Here

Microsoft Entra requires HTTPS redirect URIs for normal web applications. The callback used by this app is fixed to:

`/api/users/callback/microsoft`

So if you expose the app as:

`https://orciestra.lab.local`

then the redirect URI to register in Entra is:

`https://orciestra.lab.local/api/users/callback/microsoft`

## Topology

- Caddy listens on `443`
- Next.js listens on `127.0.0.1:3000`
- FastAPI listens on `127.0.0.1:8765`
- optional: Guacamole listens on `127.0.0.1:8088`
- Browser talks only to `https://orciestra.lab.local`

If your Guacamole already runs remotely behind Nginx, keep that deployment as-is. Point FastAPI at it with `GUACAMOLE_BASE_URL`, and do not proxy `/guacamole/*` through local Caddy unless you explicitly want that extra hop.

## Included Example

See [Caddyfile.example](c:/Users/Kubiaxx/Documents/Programowanie/DevOPS/my-orciestra/Caddyfile.example).

If you just want to run the default lab setup immediately, use:

- [Caddyfile](c:/Users/Kubiaxx/Documents/Programowanie/DevOPS/my-orciestra/Caddyfile)
- [run-caddy.ps1](c:/Users/Kubiaxx/Documents/Programowanie/DevOPS/my-orciestra/run-caddy.ps1)
- [start-local.ps1](c:/Users/Kubiaxx/Documents/Programowanie/DevOPS/my-orciestra/start-local.ps1)
- [stop-local.ps1](c:/Users/Kubiaxx/Documents/Programowanie/DevOPS/my-orciestra/stop-local.ps1)
- [set-entra-client-secret.ps1](c:/Users/Kubiaxx/Documents/Programowanie/DevOPS/my-orciestra/set-entra-client-secret.ps1)

The example routes:

- optionally `/guacamole/*` to the local Guacamole web app
- `/api/*` to FastAPI
- `/frontend` to FastAPI WebSocket
- `/ws` to FastAPI agent WebSocket endpoint
- everything else to Next.js

This keeps TLS termination only in Caddy. Next.js and FastAPI can remain on plain local HTTP behind the proxy. Guacamole can be local too, but it does not have to be.

## Recommended Environment

Set these before starting the backend:

```powershell
$env:VM_AGENT_SERVER_PUBLIC_URL = "https://orciestra.lab.local"
$env:VM_AGENT_LOCAL_ADMIN_USERNAME = "admin"
$env:VM_AGENT_LOCAL_ADMIN_PASSWORD = "strong-password"
$env:GUACAMOLE_BASE_URL = "http://127.0.0.1:8088/guacamole"
```

For a remote Guacamole behind Linux Nginx, use its real public or internal URL instead, for example:

```powershell
$env:GUACAMOLE_BASE_URL = "https://guac.example.internal/guacamole"
```

For the frontend, you can leave `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL` unset when using Caddy. The frontend will use the current browser origin automatically.

## Hosts Entry

Add a local hosts entry on the machine that opens the dashboard:

```text
192.168.1.10 orciestra.lab.local
```

If operators use multiple workstations, add the same name in internal DNS instead of editing every hosts file.

If you just want to inspect the setup locally and skip host mapping entirely, run Caddy on `localhost` instead.

## Running The Stack

1. Start the backend on `127.0.0.1:8765`
2. Start the frontend on `127.0.0.1:3000`
3. If you use local Guacamole, start it on `127.0.0.1:8088`
4. Run Caddy with the example file

Example PowerShell flow:

```powershell
Push-Location c:\Users\Kubiaxx\Documents\Programowanie\DevOPS\my-orciestra

$env:VM_AGENT_SERVER_PUBLIC_URL = "https://orciestra.lab.local"
$env:GUACAMOLE_BASE_URL = "http://127.0.0.1:8088/guacamole"

Start-Process powershell -ArgumentList '-NoExit', '-Command', 'Push-Location frontend; npm run start'
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'c:/Users/Kubiaxx/Documents/Programowanie/DevOPS/my-orciestra/env/Scripts/python.exe -m vm_agent_server.src.server'

caddy run --config .\Caddyfile.example
```

Or use the helper script:

```powershell
Push-Location c:\Users\Kubiaxx\Documents\Programowanie\DevOPS\my-orciestra
.\run-caddy.ps1
```

Or start the whole local stack in one step:

```powershell
Push-Location c:\Users\Kubiaxx\Documents\Programowanie\DevOPS\my-orciestra
.\start-local.ps1 -OpenBrowser
```

If Guacamole is external, start the same stack like this:

```powershell
Push-Location c:\Users\Kubiaxx\Documents\Programowanie\DevOPS\my-orciestra
.\start-local.ps1 -Hostname localhost -GuacamoleBaseUrl "https://guac.example.internal/guacamole" -DisableGuacamoleProxy -OpenBrowser
```

That launcher:

- starts Next.js on a fixed local port `3000`,
- starts FastAPI on `8765` if it is not already running,
- starts Caddy for the selected hostname,
- refuses to silently let the frontend drift to `3001` or another port.

To stop the local stack again:

```powershell
Push-Location c:\Users\Kubiaxx\Documents\Programowanie\DevOPS\my-orciestra
.\stop-local.ps1
```

To also stop a local Guacamole process on `8088` when it belongs to a common Java/Tomcat runtime:

```powershell
.\stop-local.ps1 -IncludeGuacamole
```

For a no-mapping local preview:

```powershell
Push-Location c:\Users\Kubiaxx\Documents\Programowanie\DevOPS\my-orciestra
.\start-local.ps1 -Hostname localhost -OpenBrowser
```

That is useful when you want to see the full Caddy flow without touching `hosts` or internal DNS.

When you are ready to move from `localhost` to the real Entra-facing hostname, use the same launcher with a different host:

```powershell
.\start-local.ps1 -Hostname orciestra.lab.local
```

Then register the matching redirect URI in Entra:

`https://orciestra.lab.local/api/users/callback/microsoft`

If Entra returns `AADSTS7000218` or another `invalid_client` error, the stored app registration secret is missing or wrong. You can update only the persisted secret with:

```powershell
Push-Location c:\Users\Kubiaxx\Documents\Programowanie\DevOPS\my-orciestra
.\set-entra-client-secret.ps1
```

That script updates `identity.azure.client_secret` in [server_settings.db](c:/Users/Kubiaxx/Documents/Programowanie/DevOPS/my-orciestra/server_settings.db), creates a backup first, and then you should restart the backend.

To override the host or ports:

```powershell
.\run-caddy.ps1 -Hostname orciestra.kubiax.local -FrontendPort 3000 -BackendPort 8765 -GuacamolePort 8088
```

If Guacamole is external and you do not want a local `/guacamole/*` route at all:

```powershell
.\run-caddy.ps1 -Hostname orciestra.kubiax.local -DisableGuacamoleProxy
```

## Entra Registration

Register this exact web redirect URI:

`https://orciestra.lab.local/api/users/callback/microsoft`

For strictly local testing, you can also use:

`https://localhost/api/users/callback/microsoft`

Do not register the old LAN HTTP callback such as:

`http://192.168.1.10:8765/api/users/callback/microsoft`

That form is not accepted by Entra for a web app because it is non-HTTPS and not localhost.

## Certificates

The example uses `local_certs`, which is good for a lab or private network.

You do not need separate certificates for Next.js, FastAPI, or Guacamole in this layout. Only Caddy presents HTTPS to the browser.

For broader internal use, prefer one of these:

- a certificate from your internal CA,
- a real DNS name with publicly trusted TLS,
- or a company PKI-issued cert.

## Notes

- Caddy handles WebSocket upgrade automatically.
- The app still uses the existing backend bridge for Guacamole session minting and tunnel control; the `/guacamole/*` route is optional and only useful when you also want the upstream Guacamole web app available through the same Caddy origin.
- If you later run Next.js and FastAPI as Windows services, Caddy can stay as the single public entrypoint.