#!/usr/bin/env python3
"""
Alpaca Paper Trading Bot — hourly momentum runner.

Изпълнява се от GitHub Actions (безплатен cron, пълен интернет достъп) —
не от Claude, защото Claude-облачните среди нямат мрежов достъп до Alpaca.

Стратегия (проста, обяснима, с вграден risk management):
  - Watchlist от ликвидни акции/ETF-и.
  - Сигнал за покупка: SMA(10) > SMA(30) на дневни свещи (краткосрочен
    моментум над дългосрочния) и няма вече отворена позиция/поръчка
    по символа днес.
  - Всяка нова позиция се пуска като BRACKET order: market buy +
    take-profit (+6%) + stop-loss (-3%), които Alpaca управлява
    СЪРВЪРНО — т.е. защитата действа денонощно, дори ботът да не се
    е пуснал в конкретния час.
  - Лимит от MAX_POSITIONS едновременни позиции, position sizing —
    фиксиран % от equity на позиция.
  - Ако пазарът е затворен, скриптът излиза веднага (евтин run).

Изисква следните environment variables (GitHub Actions secrets):
  ALPACA_API_KEY_ID
  ALPACA_API_SECRET_KEY
  NTFY_TOPIC              (опционално — за push известия през ntfy.sh)

Използва само Python stdlib (urllib) — не изисква pip install.
"""
import os
import json
import sys
import traceback
from urllib import request, error
from datetime import datetime, timedelta, timezone

API_KEY = os.environ.get("ALPACA_API_KEY_ID", "")
API_SECRET = os.environ.get("ALPACA_API_SECRET_KEY", "")

# ntfy.sh — безплатни push известия без акаунт/токен. "Темата" действа
# като таен адрес — никой друг не я знае, затова е достатъчно уникална.
# Абонирай се в ntfy app (или ntfy.sh в браузъра на телефона) за тази тема:
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "yani-alpaca-10543be3")

TRADING_BASE = "https://paper-api.alpaca.markets"
DATA_BASE = "https://data.alpaca.markets"

# ---- Настройки на стратегията (променяй свободно) ----
WATCHLIST = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
MAX_POSITIONS = 3
POSITION_PCT = 0.10        # 10% от equity на нова позиция
STOP_LOSS_PCT = 0.03       # -3%
TAKE_PROFIT_PCT = 0.06     # +6%
SMA_SHORT = 10
SMA_LONG = 30


# ---------------- ntfy.sh известия ----------------

def send_notification(text):
    """Праща push известие през ntfy.sh. Никога не гърми run-а, ако се провали."""
    if not NTFY_TOPIC:
        return
    try:
        url = f"https://ntfy.sh/{NTFY_TOPIC}"
        req = request.Request(
            url, data=text.encode("utf-8"), headers={"Content-Type": "text/plain; charset=utf-8"}, method="POST"
        )
        with request.urlopen(req, timeout=15) as resp:
            resp.read()
    except Exception as e:
        print(f"[ntfy] Неуспешно изпращане: {e}")


# ---------------- Alpaca REST helpers ----------------

def _headers():
    return {
        "APCA-API-KEY-ID": API_KEY,
        "APCA-API-SECRET-KEY": API_SECRET,
        "Content-Type": "application/json",
    }


def _get(url):
    req = request.Request(url, headers=_headers())
    with request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def _post(url, payload):
    data = json.dumps(payload).encode()
    req = request.Request(url, data=data, headers=_headers(), method="POST")
    with request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def get_clock():
    return _get(f"{TRADING_BASE}/v2/clock")


def get_account():
    return _get(f"{TRADING_BASE}/v2/account")


def get_positions():
    return _get(f"{TRADING_BASE}/v2/positions")


def get_today_orders():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _get(f"{TRADING_BASE}/v2/orders?status=all&after={today}T00:00:00Z&limit=200")


def get_daily_bars(symbol, limit=40):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=limit * 2)  # буфер за уикенди/празници
    url = (
        f"{DATA_BASE}/v2/stocks/{symbol}/bars"
        f"?timeframe=1Day&start={start.strftime('%Y-%m-%d')}"
        f"&end={end.strftime('%Y-%m-%d')}&limit={limit}&feed=iex"
    )
    return _get(url).get("bars", [])


def sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def place_bracket_buy(symbol, qty, entry_price):
    take_profit = round(entry_price * (1 + TAKE_PROFIT_PCT), 2)
    stop_loss = round(entry_price * (1 - STOP_LOSS_PCT), 2)
    payload = {
        "symbol": symbol,
        "qty": str(qty),
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
        "order_class": "bracket",
        "take_profit": {"limit_price": str(take_profit)},
        "stop_loss": {"stop_price": str(stop_loss)},
    }
    return _post(f"{TRADING_BASE}/v2/orders", payload)


# ---------------- Main ----------------

def run():
    if not API_KEY or not API_SECRET:
        raise RuntimeError("Липсват ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY.")

    clock = get_clock()
    if not clock.get("is_open"):
        print(f"Пазарът е затворен (next open: {clock.get('next_open')}). Нищо за правене.")
        return  # тихо излизане - не спамим известието всеки затворен час

    account = get_account()
    equity = float(account["equity"])
    positions = get_positions()
    held_symbols = {p["symbol"] for p in positions}

    print(f"Equity: {equity:.2f} | Отворени позиции: {len(positions)}/{MAX_POSITIONS}")

    if len(positions) >= MAX_POSITIONS:
        print("Лимитът от позиции е достигнат. Stop-loss/take-profit вече са активни в Alpaca.")
        return

    today_orders = get_today_orders()
    traded_today = {o["symbol"] for o in today_orders}

    trades_made = []
    errors = []
    for symbol in WATCHLIST:
        if len(positions) + len(trades_made) >= MAX_POSITIONS:
            break
        if symbol in held_symbols or symbol in traded_today:
            continue
        try:
            bars = get_daily_bars(symbol)
        except error.HTTPError as e:
            errors.append(f"{symbol}: грешка при данни ({e.read().decode()[:200]})")
            continue
        closes = [b["c"] for b in bars]
        short = sma(closes, SMA_SHORT)
        long_ = sma(closes, SMA_LONG)
        if short is None or long_ is None:
            continue
        if short > long_:
            last_price = closes[-1]
            budget = equity * POSITION_PCT
            qty = int(budget // last_price)
            if qty < 1:
                continue
            try:
                place_bracket_buy(symbol, qty, last_price)
                trades_made.append((symbol, qty, last_price))
                print(
                    f"КУПЕНО: {qty} x {symbol} @ ~{last_price:.2f} "
                    f"(SL -{STOP_LOSS_PCT*100:.0f}% / TP +{TAKE_PROFIT_PCT*100:.0f}%)"
                )
            except error.HTTPError as e:
                errors.append(f"{symbol}: грешка при поръчка ({e.read().decode()[:200]})")

    # Известие само ако наистина се е случило нещо (сделка или грешка) —
    # не спамим известието при всеки тих час без сигнали.
    if trades_made:
        lines = [f"🤖 Alpaca бот — {len(trades_made)} нова сделка(и):"]
        for symbol, qty, price in trades_made:
            lines.append(f"  • КУПЕНО {qty} x {symbol} @ ~{price:.2f} (SL -3% / TP +6%)")
        lines.append(f"Equity: ${equity:,.2f}")
        send_notification("\n".join(lines))
    if errors:
        send_notification("⚠️ Alpaca бот — грешки:\n" + "\n".join(errors))

    if not trades_made and not errors:
        print("Няма нови сигнали този час.")


def main():
    try:
        run()
    except Exception:
        tb = traceback.format_exc()
        print(tb)
        send_notification(f"🔴 Alpaca бот — run завърши с грешка:\n{tb[-800:]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
