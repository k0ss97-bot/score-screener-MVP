FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV SCREENER_EXCHANGE=bybit
ENV SCREENER_BYBIT_CATEGORY=spot
ENV SCREENER_QUOTE=USDT
ENV SCREENER_MIN_SCORE=60
ENV SCREENER_INTERVAL_MINUTES=60
ENV SCREENER_KLINE_LIMIT=1000
ENV SCREENER_MAX_SYMBOLS=0
ENV SCREENER_REQUEST_DELAY_SECONDS=0.05

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN mkdir -p /app/runtime

COPY pyproject.toml README.md ./
COPY score_screener ./score_screener

CMD ["python", "-m", "score_screener", "--telegram", "--loop", "--state-file", "/app/runtime/screener_state.json"]
