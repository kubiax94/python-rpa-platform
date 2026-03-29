# my-orciestra

Monorepo for orchestrating Windows VM agents from a FastAPI control plane with a Next.js frontend and optional Apache Guacamole remote access.

Architecture details and flow diagrams live in `docs/ARCHITECTURE.md`.

## What This Project Does

- Runs a Windows service agent on managed machines.
- Keeps agent state, telemetry, tasks, and deployments in the FastAPI server.
- Exposes a web UI for operators.
- Prepares deployment artifacts and bootstrap scripts for new agents.
- Optionally bridges agents to Apache Guacamole for remote desktop access inside the same app.

## Architecture

The repository is split into four main layers:

- `frontend/` - Next.js operator UI.
- `vm_agent_server/src/` - FastAPI control plane, HTTP API, WebSocket orchestration, task and deployment logic.
- `vm_agent/src/` - Windows agent service, process management, telemetry, screenshot and window helpers.
- `shared/` - shared protocol and event models used across server, agent, and frontend flows.

Communication boundaries:

- Frontend talks only to the FastAPI server.
- Agents talk only to the FastAPI server.
- Guacamole is treated as a remote desktop transport layer, not as the orchestration core.

## Repository Layout

```text
my-orciestra/
|- frontend/                 Next.js UI
|- vm_agent_server/src/      FastAPI server and orchestration
|- vm_agent/src/             Windows service agent
|- shared/                   Shared models and protocol
|- artifacts/                Generated deployment payloads
|- logs/                     Task logs and runtime output
|- deploy.ps1                Local build/copy workflow for agent payloads
|- agent_service.spec        PyInstaller spec for Windows service bundle
```

Important files:

- `vm_agent_server/src/server.py` - FastAPI entry point and WebSocket surface.
- `vm_agent_server/src/api/routers/` - HTTP API routers for tasks, deployments, and Guacamole.
- `vm_agent_server/src/task_models.py` - unified task model.
- `vm_agent_server/src/task_service.py` - task orchestration and pipeline progression.
- `vm_agent_server/src/deployment_service.py` - deployment preparation flow.
- `vm_agent/src/service/agent_service.py` - Windows service entry point.
- `deploy.ps1` - copies built artifacts to the target share.

## Main Concepts

### Tasks

The server uses one extensible task model and routes execution by task kind.

- `TaskSpec` is the common task shape.
- `AgentTaskSpec` represents agent-executed work.
- `DeploymentTaskSpec` represents server-side deployment preparation work.
- `TaskDispatcher` resolves handlers by task kind.
- `TaskService` persists tasks and dispatches them.

This structure makes it possible to add new task kinds without redesigning the storage model.

### Deployments

Deployment preparation is server-driven:

- a deployment record is created,
- a bootstrap token is issued,
- build artifacts and install scripts are produced,
- the operator can install manually or through RDP on the target machine.

This matches the current preference that the server should not store or use personal admin credentials for remote automated installs.

### Guacamole

Guacamole support is optional and layered on top of the existing app.

- FastAPI exposes Guacamole-related HTTP endpoints.
- The frontend can request session data from FastAPI.
- Guacamole provides remote connection transport only.

Task execution, telemetry, and lifecycle still stay in the server-agent path.

## Prerequisites

- Windows development machine.
- Python virtual environment available at `env\Scripts\python.exe`.
- Node.js for the frontend.
- Access to the target VM share if you use `deploy.ps1`.
- Optional Apache Guacamole instance if you want embedded remote access.

## Setup

### Python

This repo already assumes a local virtual environment at:

```powershell
env\Scripts\python.exe
```

Core Python dependencies are declared in `pyproject.toml`.

### Frontend

Install frontend dependencies from `frontend/`:

```powershell
Set-Location frontend
npm install
```

## Running The Project

### Start the FastAPI server

From the repository root:

```powershell
env\Scripts\python.exe -m vm_agent_server.src.server
```

### Start the frontend

From `frontend/`:

```powershell
npm run dev
```

### Build the Windows service bundle

From the repository root:

```powershell
env\Scripts\python.exe -m PyInstaller --clean agent_service.spec
```

Do not rely on `pyinstaller` from `PATH`. This repo expects the build to run from the local virtual environment.

### Copy payloads to the VM share

From the repository root:

```powershell
.\deploy.ps1
```

Useful switches:

- `-SkipBuild` skips the PyInstaller step.
- `-ArtifactsOnly` copies only `artifacts/`.

## Configuration

### Frontend environment variables

- `NEXT_PUBLIC_API_URL` - base HTTP URL for the FastAPI server.
- `NEXT_PUBLIC_WS_URL` - frontend WebSocket URL override.

If not set, the frontend falls back to hardcoded local defaults from the React hooks.

### Server environment variables

Deployment and server behavior:

- `VM_AGENT_REPO_URL` - overrides detected Git remote for deployment preparation.
- `VM_AGENT_ARTIFACT_SHARE_ROOT` - overrides artifact share root.
- `VM_AGENT_SERVER_WS_URL` - explicit public WebSocket URL used in bootstrap/install flows.
- `VM_AGENT_SERVER_PUBLIC_URL` - explicit public base URL used by server-generated links.
- `VM_AGENT_SERVER_SUPPRESS_GUAC_TUNNEL_ACCESS_LOGS` - controls noisy Guacamole tunnel access logs.
- `VM_AGENT_BOOTSTRAP_RECOVERY_WINDOW_SECONDS` - recovery window for bootstrap token handling.
- `VM_AGENT_JWT_SECRET` - signing secret for agent runtime JWTs.
- `VM_AGENT_JWT_ISSUER` - issuer claim for agent runtime JWTs.
- `VM_AGENT_JWT_TTL_SECONDS` - optional JWT lifetime for agent runtime tokens. Leave empty for non-expiring tokens.

Guacamole:

- `GUACAMOLE_BASE_URL`
- `GUACAMOLE_SERVER_BASE_URL`
- `GUACAMOLE_AUTH_USERNAME`
- `GUACAMOLE_AUTH_PASSWORD`
- `GUACAMOLE_AUTH_PROVIDER`
- `GUACAMOLE_CONNECTION_TYPE`
- `GUACAMOLE_CONNECTION_MAP_JSON`
- `GUACAMOLE_CONNECTION_MAP_FILE`
- `GUACAMOLE_DEFAULT_CONNECTION_MODE`
- `GUACAMOLE_ALLOW_EMBED`
- `GUACAMOLE_DISPLAY_MODE`
- `GUACAMOLE_DISPLAY_WIDTH`
- `GUACAMOLE_DISPLAY_HEIGHT`
- `GUACAMOLE_DISPLAY_DPI`

### Agent runtime configuration

The agent reads runtime bootstrap data from `agent.bootstrap.json` and allows environment overrides:

- `VM_AGENT_SERVER_URL`
- `VM_AGENT_ACCESS_TOKEN`
- `VM_AGENT_BOOTSTRAP_TOKEN`
- `VM_AGENT_ID`

Legacy compatibility:

- old configs using `secret` are still read and normalized to `access_token`,
- old env override `VM_AGENT_SECRET` is still accepted as a fallback, but new usage should prefer `VM_AGENT_ACCESS_TOKEN`.

The runtime config loader lives in `vm_agent/src/config/bootstrap_config.py`.

## HTTP API Overview

The HTTP API is organized by router under `vm_agent_server/src/api/routers/`.

### Tasks

- `POST /api/tasks`
- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `POST /api/tasks/{task_id}/cancel`
- `GET /api/tasks/{task_id}/log`
- `GET /api/tasks/{task_id}/log/raw`

### Pipelines

- `POST /api/pipelines`
- `GET /api/pipelines`
- `GET /api/pipelines/{pipeline_id}`
- `POST /api/pipelines/{pipeline_id}/run`
- `GET /api/pipeline-runs/{run_id}`

### Deployments

- `POST /api/deployments/prepare`
- `GET /api/deployments/config`
- `GET /api/deployments`
- `GET /api/deployments/{deployment_id}`
- `GET /api/deployments/{deployment_id}/installer`

### Audit

- `GET /api/audit`

### Guacamole

- `GET /api/guacamole/config`
- `GET /api/guacamole/connections`
- `GET /api/agents/{agent_id}/guacamole`
- `GET /api/agents/{agent_id}/guacamole/diagnostics`
- `POST /api/agents/{agent_id}/guacamole/session`
- `DELETE /api/guacamole/session/{auth_token}`
- `GET|POST /api/guacamole/tunnel`
- `WS /api/guacamole/websocket-tunnel`

## Data And Generated Files

The repository may contain local runtime databases and generated artifacts during development:

- `agents.db`
- `tasks.db`
- `telemetry.db`
- `artifacts/deployments/`
- `logs/tasks/`

Treat these as local runtime state, not as source code.

## Testing

Current validated server-side test command:

```powershell
env\Scripts\python.exe -m unittest discover -s vm_agent_server/tests -t . -v
```

Current coverage includes:

- task router tests,
- deployment router tests,
- task dispatcher tests,
- task service pipeline tests.

There is no broader verified backend test harness in the repo today.

## Development Notes

- Keep Windows-specific service and desktop interaction code inside `vm_agent/`.
- Keep HTTP, WebSocket, deployment, task, and telemetry APIs inside `vm_agent_server/`.
- Preserve schema compatibility in `shared/` when changing network events.
- Do not remove Pillow/PIL collection from `agent_service.spec`; screenshot capture depends on it.
- Do not reintroduce periodic background window resolution in heartbeats; that has already caused CPU spikes.

## Current Gaps

- Root-level documentation was added after several architectural refactors, so some internal modules still rely on code reading rather than dedicated docs.
- Guacamole router tests are not yet present.
- Frontend README previously came from the default Next.js template and has been reduced to a pointer to this document.

## Recommended Next Docs

If you want to extend documentation further, the most useful follow-ups would be:

- deployment operator runbook,
- API contracts with example payloads,
- agent bootstrap/install walkthrough,
- frontend feature map.