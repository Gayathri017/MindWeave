FROM python:3.11-slim AS base

# No compiler toolchain needed at runtime -- all deps ship prebuilt wheels
# for this exact Python/platform combo. Keeping the image slim reduces
# attack surface and avoids the exact build failure we hit on Render's
# native runtime (falling back to source builds on an unexpected version).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as a non-root user -- if the process is ever compromised (e.g. via a
# dependency vuln), it can't write outside its own workdir or touch
# anything requiring elevated privileges.
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PORT=8000
EXPOSE 8000

# `exec` replaces the shell process with uvicorn (PID 1), so SIGTERM from
# Render on shutdown/redeploy reaches uvicorn directly for a graceful exit
# instead of being swallowed by an intermediate shell.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
