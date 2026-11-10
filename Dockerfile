FROM python:3.14-slim


# curl is required by the container and ECS health checks
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get clean


ARG PORT=8081
ARG TRANSPORT="http"

ENV PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    MP_MCP_HOSTED=1 \
    MP_MCP_TRANSPORT=${TRANSPORT} \
    PORT=${PORT}

WORKDIR /app

COPY pyproject.toml LICENSE README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

EXPOSE ${PORT}


RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
    CMD curl -f http://localhost:${PORT}/health || exit 1

CMD ["mp-mcp"]

