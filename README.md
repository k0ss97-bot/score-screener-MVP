# Automatic Score Screener MVP

Минимальный алерт-скринер по ТЗ: 1H OHLCV -> индикаторы -> поиск боковика 5-10 дней -> impulse/reversal score -> текстовый alert.

Это не торговый бот и не один индикатор. MVP специально сделан как прозрачная score-модель, чтобы thresholds можно было тестировать и менять.

## Что внутри

- `score_screener/indicators.py` - RSI, MACD histogram, Bollinger width, ATR%, MFI, ADX, EMA, relative volume, z-score.
- `score_screener/scanner.py` - поиск боковика, расчет фичей, impulse_score, reversal_score, классификация alert.
- `score_screener/data.py` - CSV loader, 4H/1D aggregation, synthetic demo candles, optional CCXT fetch adapter.
- `score_screener/storage.py` - SQLite schema для таблиц `symbols`, `candles_1h`, `features_1h`, `signals`.
- `tests/test_scanner.py` - smoke tests на synthetic breakout и exhaustion сценариях.

## Быстрый запуск

```bash
cd /Users/konstantingorskih/Documents/Codex/2026-07-07/files-mentioned-by-the-user-score/outputs/score_screener
python3 -m score_screener --demo
```

JSON-вывод:

```bash
python3 -m score_screener --demo --json
```

Тесты:

```bash
python3 -m unittest discover -s tests
```

## Telegram alerts

1. Создай бота через BotFather.
2. Узнай `chat_id` целевого чата/канала.
3. Скопируй env-шаблон:

```bash
cp .env.example .env
```

4. Заполни секреты в `.env`:

```text
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

5. Проверь отправку на demo:

```bash
python3 -m score_screener --demo --min-score 60 --telegram --send-all
```

Для hourly worker:

```bash
python3 -m score_screener \
  --csv data/universe_1h.csv \
  --min-score 60 \
  --telegram \
  --loop \
  --interval-minutes 60
```

По умолчанию используется `.screener_state.json`, чтобы не слать один и тот же alert повторно. Для повторной отправки добавь `--send-all`.

## CSV input

Ожидаемые колонки:

```text
timestamp,open,high,low,close,volume,quote_volume,symbol
```

Обязательные: `timestamp`, `open`, `high`, `low`, `close`, `volume`.

`timestamp` может быть ISO-строкой, Unix seconds или Unix milliseconds. `symbol` можно передать через CSV или параметром `--symbol`.

```bash
python3 -m score_screener --csv candles.csv --symbol ALGO/USDT --min-score 40
```

Если в CSV несколько символов с колонкой `symbol`, скринер сгруппирует их автоматически:

```bash
python3 -m score_screener --csv universe_1h.csv --min-score 60
```

## Scoring

Impulse score: 0-100.

- 0-40: нет интереса
- 40-60: watchlist
- 60-75: early
- 75-85: strong pre-breakout
- 85+: breakout/momentum, если цена подтвердила пробой или уже ушла в импульс

Reversal score считается отдельно. При `reversal_score >= 70` скринер также печатает `EXIT RISK`.

## Практическая настройка

Начни с ликвидных USDT-пар и 1H свечей за 60-120 дней. Для live-версии добавь расписание раз в час:

1. скачать/обновить 1H candles;
2. сохранить свечи в SQLite;
3. прогнать `scan_universe`;
4. отправить alert в Telegram/Discord только если score пересек threshold или changed state.

Thresholds находятся в `ScannerConfig`:

```python
ScannerConfig(
    min_base_days=5,
    max_base_days=10,
    base_range_pct=0.18,
    bb_width_percentile=30.0,
    atr_pct_percentile=35.0,
)
```

Перед live-алертами обязательно сделать historical validation: найти все боковики, разделить winners/controls, проверить признаки на T-72h/T-24h/T-4h/T-1h и только потом фиксировать thresholds.

## Hosting

Самый простой вариант для VPS:

```bash
cp .env.example .env
mkdir -p data runtime
# положи 1H CSV в data/universe_1h.csv
docker compose up -d --build
```

Для Render/Railway/Fly.io используй Dockerfile и worker command:

```bash
python -m score_screener --csv /app/data/universe_1h.csv --min-score 60 --telegram --loop --interval-minutes 60 --state-file /app/runtime/screener_state.json
```

Важно: `.env`, runtime state и реальные CSV исключены из git. Секреты добавляй через environment variables хостинга.

## GitHub commit

Папка уже подготовлена как корень репозитория. Команды:

```bash
cd /Users/konstantingorskih/Documents/Codex/2026-07-07/files-mentioned-by-the-user-score/outputs/score_screener
git init
git add .
git commit -m "Initial score screener MVP"
git branch -M main
git remote add origin git@github.com:<user>/<repo>.git
git push -u origin main
```
