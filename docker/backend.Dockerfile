FROM python:3.13-slim AS source

ARG REPO_URL=https://github.com/kubiax94/python-rpa-platform.git
ARG REPO_REF=

RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src

RUN git init /src/repo && \
    git -C /src/repo remote add origin "${REPO_URL}" && \
    git -C /src/repo config core.sparseCheckout true && \
    git -C /src/repo sparse-checkout init --cone && \
    git -C /src/repo sparse-checkout set shared vm_agent_server && \
    if [ -n "${REPO_REF}" ]; then git -C /src/repo fetch --depth 1 origin "${REPO_REF}"; else git -C /src/repo fetch --depth 1 origin; fi && \
    git -C /src/repo checkout FETCH_HEAD

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN python -m pip install --upgrade pip && \
    python -m pip install --no-cache-dir \
        "aiosqlite>=0.21" \
        "fastapi>=0.115" \
        "pydantic>=2.0" \
        "pyee>=13.0.0" \
        "uvicorn[standard]>=0.34" \
        "websockets>=15.0"

COPY --from=source /src/repo/shared /app/shared
COPY --from=source /src/repo/vm_agent_server /app/vm_agent_server

WORKDIR /data

EXPOSE 8765

CMD ["python", "-m", "vm_agent_server.src.server"]