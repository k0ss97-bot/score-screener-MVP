FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV SCREENER_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,ALGOUSDT
ENV SCREENER_MIN_SCORE=60
ENV SCREENER_INTERVAL_MINUTES=60
ENV SCREENER_BINANCE_LIMIT=1000

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY score_screener ./score_screener

CMD ["python", "-m", "score_screener", "--telegram", "--loop", "--state-file", "/app/runtime/screener_state.json"]
