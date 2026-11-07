FROM python:3.14-slim


# curl is required by the container and ECS health checks
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean


ARG PORT=8081
#ARG MP_HOST="0.0.0.0"  # MP_MCP_HOSTED=1 
ARG TRANSPORT="http"

ENV PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    MP_MCP_HOSTED=1 \
    MP_MCP_TRANSPORT=${TRANSPORT} \
    PORT=${PORT}

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
COPY pyproject.toml LICENSE README.md ./
COPY src ./src
RUN pip install --no-cache-dir .  

# Put the venv on PATH so `uvicorn` resolves without `uv run`.
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE ${PORT}


ENV AWS_REGION=us-east-2
# Settings reads MP_-prefixed vars; uvicorn requires a lowercase level
ENV MP_LOG_LEVEL=info

RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
    CMD curl -f http://localhost:${PORT}/health || exit 1

CMD ["mp-mcp"]

