FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
EXPOSE 18421
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "18421"]
