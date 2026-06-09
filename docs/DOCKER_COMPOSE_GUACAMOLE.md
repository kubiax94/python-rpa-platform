# Docker Compose Stack

This stack is meant to sit behind your own reverse proxy, for example Nginx on Proxmox, in front of:

- the Next.js frontend,
- the FastAPI backend,
- Apache Guacamole,
- `guacd`,
- PostgreSQL for Guacamole.

The compose file exposes frontend, backend, and Guacamole directly on host ports. Your external Nginx should route them into one browser origin.

## Topology

- `http://localhost:3000` -> Next.js frontend
- `http://localhost:8765` -> FastAPI backend
- `http://localhost:8080/guacamole` -> Guacamole web app

Recommended Nginx routing:

- `/` -> frontend on port `3000`
- `/api/*`, `/frontend`, `/ws` -> backend on port `8765`
- `/guacamole/*` -> Guacamole on port `8080`

## Start

From the repo root:

```powershell
docker compose up --build -d
```

Open:

```text
http://localhost:3000
```

## Start On Another Machine From GitHub

You do not need to copy the repo manually.

This compose setup can now build the frontend and backend by cloning the app repo during image build. By default it uses:

- `APP_REPO_URL=https://github.com/kubiax94/python-rpa-platform.git`
- `APP_REPO_REF` unset, which means the repo default branch

The recommended flow is:

```powershell
git clone <your-repo-url>
cd my-orciestra
docker compose up --build -d
```

If you want one command that clones or updates the repo and then starts the stack, use [start-docker-from-github.ps1](c:/Users/Kubiaxx/Documents/Programowanie/DevOPS/my-orciestra/start-docker-from-github.ps1):

```powershell
.\start-docker-from-github.ps1 -RepoUrl <your-repo-url>
```

Optional switches:

- `-CheckoutRoot C:\deployments` chooses where the repo should live on that machine
- `-Ref some-branch` is optional and only needed if you want a non-default branch
- `-NoBuild` skips `--build` on `docker compose up`
- `-NoStart` only clones or updates the repo

Why not put the GitHub URL directly into the Dockerfiles:

You can put Git clone inside the Dockerfiles, and this stack now does that for frontend and backend.

The exact syntax is:

```powershell
git clone https://github.com/kubiax94/python-rpa-platform.git
```

Not:

```powershell
git clone https://github.com/kubiax94/python-rpa-platform@vm_agent_server
```

If you want to override the repo or branch at build time:

```powershell
$env:APP_REPO_URL = "https://github.com/kubiax94/python-rpa-platform.git"
docker compose up --build -d
```

Only set `APP_REPO_REF` if you actually want a non-default branch or tag.

Tradeoff: frontend and backend each clone the repo during build, which is less efficient than using a checked-out repo as a shared build context, but it does remove the need to manually copy source files to another machine.

## Stop

```powershell
docker compose down
```

To remove containers only:

```powershell
docker compose down
```

To also remove persisted state, delete `docker-data/` after shutdown.

## Important Environment Variables

You can override these on the command line or through a local `.env` file:

- `FRONTEND_PORT` default `3000`
- `BACKEND_PORT` default `8765`
- `GUACAMOLE_PORT` default `8080`
- `VM_AGENT_SERVER_PUBLIC_URL` should be your external Nginx origin, for example `https://orciestra.example.internal`
- `GUACAMOLE_AUTH_USERNAME` default `guacadmin`
- `GUACAMOLE_AUTH_PASSWORD` default `guacadmin`
- `GUACAMOLE_AUTH_PROVIDER` default `postgresql`
- `GUACAMOLE_DB_NAME` default `guacamole_db`
- `GUACAMOLE_DB_USER` default `guacamole_user`
- `GUACAMOLE_DB_PASSWORD` default `guacamole_password`

Example:

```powershell
$env:FRONTEND_PORT = "3000"
$env:BACKEND_PORT = "8765"
$env:GUACAMOLE_PORT = "8080"
$env:VM_AGENT_SERVER_PUBLIC_URL = "https://orciestra.example.internal"
$env:GUACAMOLE_AUTH_PASSWORD = "change-me-now"
docker compose up --build -d
```

## Persistence

Backend runtime state stays in the workspace-local bind mount under `docker-data/`:

- `docker-data/backend/` -> backend SQLite files and task logs

Guacamole runtime state uses Docker named volumes instead of workspace bind mounts:

- `guac_db` -> Guacamole PostgreSQL data
- `guac_recordings` -> Guacamole recordings
- `guac_drive` -> Guacamole drive mount

Deployment artifacts remain mounted to `artifacts/` so files created by the backend stay visible in the repo.

This avoids host UID/GID and filesystem ACL mismatches when the Guacamole containers run as their internal service users, which is a common source of `Permission denied` errors with bind mounts on client machines.

## Notes

- This stack is for the frontend + backend + Guacamole path only. It does not package the Windows agent.
- The backend now supports container-friendly path overrides for SQLite databases and task logs.
- The compose file assumes Guacamole database auth through PostgreSQL and points FastAPI at `http://guacamole:8080/guacamole`.
- The Caddy config in `docker/caddy/Caddyfile` is no longer required for this compose setup.