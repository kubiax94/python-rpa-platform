# Frontend

This directory contains the Next.js operator UI for the project.

## Commands

Run from this directory:

```powershell
npm install
npm run dev
npm run build
npm run start
npm run lint
```

## Environment Variables

- `NEXT_PUBLIC_API_URL` - base HTTP URL for the FastAPI server.
- `NEXT_PUBLIC_WS_URL` - optional WebSocket URL override.

If these are not set, some hooks fall back to local hardcoded defaults.

## Notes

- Guacamole frontend integration uses `guacamole-common-js`.
- The frontend should communicate only with the FastAPI server, not directly with the agent.

For the full project overview, architecture, deployment flow, and backend API summary, see the root `README.md`.
