FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY score_screener ./score_screener

CMD ["python", "-m", "score_screener", "--demo", "--min-score", "60"]
