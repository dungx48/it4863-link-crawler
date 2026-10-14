FROM python:3.13-slim-bookworm AS dependencies

ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --only-binary=:all: -r requirements.txt

FROM python:3.13-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --gid 10001 crawler \
    && useradd --uid 10001 --gid crawler --no-create-home crawler \
    && mkdir -p /app/output /app/.cache/httpcache \
    && chown -R crawler:crawler /app
COPY --from=dependencies /opt/venv /opt/venv
COPY config.py scrapy.cfg ./
COPY crawler/ ./crawler/
USER 10001:10001
ENTRYPOINT ["python", "-m", "scrapy"]
CMD ["crawl", "hust", "-a", "max_pages=2500", "-s", "DEPTH_LIMIT=4"]
