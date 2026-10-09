FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLOWTWIN_HOME=/app
WORKDIR /app
COPY pyproject.toml requirements.txt ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && useradd --no-log-init --create-home --uid 10001 flowtwin \
    && mkdir -p /app/data/raw /app/data/processed /app/artifacts /app/reports/generated \
    && chown -R flowtwin:flowtwin /app
USER flowtwin
EXPOSE 8000
CMD ["flowtwin", "serve", "--host", "0.0.0.0", "--port", "8000"]
