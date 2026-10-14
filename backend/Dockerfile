FROM registry-1.docker.io/library/python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89
ARG APP_UID=1000
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements-runtime.lock /app/backend/requirements-runtime.lock
RUN python -m pip install --no-cache-dir -r backend/requirements-runtime.lock
COPY backend /app/backend
COPY schemas /app/schemas
COPY migrations /app/migrations
COPY docs/research /app/docs/research
COPY artifacts/benchmark /app/artifacts/benchmark
COPY artifacts/experiments /app/artifacts/experiments
RUN python -m pip install --no-cache-dir --no-deps -e /app/backend && useradd --uid ${APP_UID} --create-home depscope
RUN mkdir -p /app/data/runtime && chown -R ${APP_UID} /app/data
USER ${APP_UID}
EXPOSE 8000
CMD ["python","-m","uvicorn","depscope.runtime.main:app","--host","0.0.0.0","--port","8000"]
