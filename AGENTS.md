# Project Guidelines

## Architecture

- This workspace has four active layers: `frontend/` for the Next.js UI, `vm_agent_server/src/` for the FastAPI control plane, `vm_agent/src/` for the Windows agent service, and `shared/` for protocol and event models.
- Keep the existing boundary intact: frontend talks only to the server, and agents talk only to the server. Do not add direct frontend-to-agent flows.
- Treat the FastAPI server as the orchestration boundary for new features. If a new UI action needs backend support, add the API or WebSocket handling in `vm_agent_server/src/server.py` and keep transport/event schemas in `shared/`.
- For Apache Guacamole integration, keep a single UI in `frontend/` and use Guacamole only for remote connection management and streaming. Task execution, telemetry, process monitoring, and agent lifecycle stay in the existing server-agent path.
- When adding Guacamole support, prefer a thin bridge in the server that maps app agents or VMs to Guacamole connections or sessions. Avoid pushing orchestration logic into Guacamole.

## Build And Run

- Use `env\Scripts\python.exe` for Python commands in this repo.
- Run the FastAPI server with `env\Scripts\python.exe -m vm_agent_server.src.server`.
- Build the Windows service bundle with `env\Scripts\python.exe -m PyInstaller --clean agent_service.spec`.
- Deploy to the target VM with `.\deploy.ps1`.
- Frontend commands run from `frontend/`: `npm run dev`, `npm run build`, `npm run start`, `npm run lint`.
- There is no verified automated backend test command in the repo today. Do not invent one; validate changes with targeted runs.

## Conventions

- Keep Windows-specific service, session, and process-launch code inside `vm_agent/`. Keep HTTP, WebSocket, task, and telemetry APIs inside `vm_agent_server/`.
- Preserve schema compatibility when adding or changing events. Update shared protocol models first, then update both the server and agent handling.
- Do not remove Pillow or PIL collection from `agent_service.spec`; screenshot capture depends on Pillow being bundled into the PyInstaller executable.
- Keep window enumeration and refresh work on-demand. Do not reintroduce periodic background resolution in heartbeats because it can spawn helper processes and spike CPU usage.
- Prefer minimal, focused changes. This repository already contains generated artifacts and deployment files, so avoid broad cleanup unless explicitly requested.

## Key Files

- `vm_agent_server/src/server.py`: primary FastAPI entry point, WebSocket routing, and API surface.
- `vm_agent/src/service/agent_service.py`: Windows service entry point for the packaged agent.
- `shared/network/events/example_event.py`: shared event contracts used across server, agent, and frontend flows.
- `agent_service.spec`: PyInstaller packaging config for the Windows service binary.
- `deploy.ps1`: source of truth for the current VM deployment workflow.

## Guacamole Direction

- The preferred product direction is a unified app interface in the Next.js frontend with Guacamole embedded as a remote desktop transport layer.
- A good first increment is to add server endpoints for creating or resolving Guacamole sessions, then expose that session inside a dedicated frontend view or panel.
- Keep agent identity and Guacamole connection identity explicitly mapped in the server. That mapping should be owned by the app, not inferred ad hoc in the frontend.