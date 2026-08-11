#!/usr/bin/env python3
"""
Alpaca Paper Trading Bot — hourly runner, две независими стратегии.

Изпълнява се от GitHub Actions (безплатен cron, пълен интернет достъп) —
не от Claude, защото Claude-облачните среди нямат мрежов достъп до Alpaca.

СТРАТЕГИЯ 1 — "blue-chip" (ликвидни акции/ETF-и):
  - Сигнал: SMA(10) > SMA(30) на дневни свещи (краткосрочен моментум над
    дългосрочния тренд).
  - Позиция = 10% от equity. Stop-loss -3% / Take-profit +6%.
  - Максимум 3 едновременни позиции от този watchlist.

СТРАТЕГИЯ 2 — "penny" (penny stocks, под $5/акция):
  - Много по-волатилен клас акции — по-малка позиция на сделка, по-широки
    stop/take-profit нива (движенията са по-резки), плюс филтър за
    ликвидност, за да не се хващаме в напълно неликвидни книжа.
  - Сигнал: пробив над най-високото затваряне от последните 20 дни
    ("20-day breakout"), потвърден с обем над 1.5x средния за периода
    ("volume spike") — класически подход за волатилни малки капитализации,
    по-подходящ от обикновена SMA за тази категория (SMA изостава твърде
    много при резки движения).
  - Ценови филтър: цената трябва да е между PENNY_MIN_PRICE и
    PENNY_MAX_PRICE — прилага се на всяко пускане, така че дори watchlist-ът
    да остарее (акция е излязла извън penny диапазона или е делистната),
    ботът просто я прескача, вместо да гърми.
  - Позиция = 3% от equity. Stop-loss -10% / Take-profit +20%.
  - Максимум 2 едновременни позиции от този watchlist.

Всяка позиция (и от двете стратегии) се пуска като BRACKET order —
Alpaca управлява stop-loss/take-profit СЪРВЪРНО, денонощно, дори ботът
да не се е пуснал в конкретния час.

Ако пазарът е затворен, скриптът излиза веднага (евтин run).

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

# ==================== СТРАТЕГИЯ 1: blue-chip ====================
WATCHLIST = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
MAX_POSITIONS = 3
POSITION_PCT = 0.10        # 10% от equity на нова позиция
STOP_LOSS_PCT = 0.03       # -3%
TAKE_PROFIT_PCT = 0.06     # +6%
SMA_SHORT = 10
SMA_LONG = 30

# ==================== СТРАТЕГИЯ 2: penny stocks ====================
# Стартов watchlist (август 2026) — провери/обнови периодично, penny
# stocks сменят статус (цена, делистване) много по-бързо от blue-chip.
# Ценовият филтър по-долу пази бота дори списъкът да остарее.
PENNY_WATCHLIST = [
    "HTZ", "PLUG", "UWMC", "OPEN", "NIO", "AMC",
    "BTBT", "HIVE", "SPCE", "LAC", "EOSE", "BBAI",
]
PENNY_MIN_PRICE = 0.50
PENNY_MAX_PRICE = 5.00
PENNY_MIN_AVG_DOLLAR_VOLUME = 2_000_000   # избягва напълно неликвидни книжа
PENNY_MAX_POSITIONS = 2
PENNY_POSITION_PCT = 0.03      # 3% от equity — доста по-малко от blue-chip
PENNY_STOP_LOSS_PCT = 0.10     # -10% (по-волатилни, по-широк stop)
PENNY_TAKE_PROFIT_PCT = 0.20   # +20%
PENNY_BREAKOUT_LOOKBACK = 20
PENNY_VOLUME_MULT = 1.5


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


def place_bracket_buy(symbol, qty, entry_price, stop_loss_pct, take_profit_pct):
    take_profit = round(entry_price * (1 + take_profit_pct), 2)
    stop_loss = round(entry_price * (1 - stop_loss_pct), 2)
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


# ---------------- Сигнали ----------------

def blue_chip_signal(bars):
    """SMA(10) > SMA(30) — краткосрочен моментум над дългосрочния тренд."""
    closes = [b["c"] for b in bars]
    short = sma(closes, SMA_SHORT)
    long_ = sma(closes, SMA_LONG)
    return short is not None and long_ is not None and short > long_


def penny_signal(bars):
    """20-дневен breakout + volume spike, с ценови и ликвиден филтър."""
    if len(bars) < PENNY_BREAKOUT_LOOKBACK + 1:
        return False
    closes = [b["c"] for b in bars]
    volumes = [b["v"] for b in bars]
    last_close = closes[-1]

    if last_close < PENNY_MIN_PRICE or last_close > PENNY_MAX_PRICE:
        return False  # излязла е извън penny диапазона (или грешен символ)

    prior_closes = closes[-(PENNY_BREAKOUT_LOOKBACK + 1):-1]
    prior_volumes = volumes[-(PENNY_BREAKOUT_LOOKBACK + 1):-1]
    prior_high = max(prior_closes)
    avg_volume = sum(prior_volumes) / len(prior_volumes)
    avg_price = sum(prior_closes) / len(prior_closes)
    avg_dollar_volume = avg_volume * avg_price

    if avg_dollar_volume < PENNY_MIN_AVG_DOLLAR_VOLUME:
        return False  # твърде неликвидна

    today_volume = volumes[-1]
    breakout = last_close > prior_high
    volume_spike = avg_volume > 0 and today_volume > avg_volume * PENNY_VOLUME_MULT
    return breakout and volume_spike


# ---------------- Стратегии ----------------

STRATEGIES = [
    {
        "label": "blue-chip",
        "watchlist": WATCHLIST,
        "max_positions": MAX_POSITIONS,
        "position_pct": POSITION_PCT,
        "stop_loss_pct": STOP_LOSS_PCT,
        "take_profit_pct": TAKE_PROFIT_PCT,
        "signal_fn": blue_chip_signal,
    },
    {
        "label": "penny",
        "watchlist": PENNY_WATCHLIST,
        "max_positions": PENNY_MAX_POSITIONS,
        "position_pct": PENNY_POSITION_PCT,
        "stop_loss_pct": PENNY_STOP_LOSS_PCT,
        "take_profit_pct": PENNY_TAKE_PROFIT_PCT,
        "signal_fn": penny_signal,
    },
]


def run_strategy(strategy, equity, held_symbols, traded_today):
    """Изпълнява една стратегия и връща (list от направени сделки, list от грешки)."""
    watchlist = strategy["watchlist"]
    held_in_strategy = held_symbols & set(watchlist)
    slots_free = strategy["max_positions"] - len(held_in_strategy)

    trades_made = []
    errors = []
    if slots_free <= 0:
        return trades_made, errors

    for symbol in watchlist:
        if len(trades_made) >= slots_free:
            break
        if symbol in held_symbols or symbol in traded_today:
            continue
        try:
            bars = get_daily_bars(symbol)
        except error.HTTPError as e:
            errors.append(f"[{strategy['label']}] {symbol}: грешка при данни ({e.read().decode()[:200]})")
            continue

        if not bars or not strategy["signal_fn"](bars):
            continue

        last_price = bars[-1]["c"]
        budget = equity * strategy["position_pct"]
        qty = int(budget // last_price)
        if qty < 1:
            continue
        try:
            place_bracket_buy(
                symbol, qty, last_price,
                strategy["stop_loss_pct"], strategy["take_profit_pct"],
            )
            trades_made.append((strategy["label"], symbol, qty, last_price,
                                 strategy["stop_loss_pct"], strategy["take_profit_pct"]))
            print(
                f"[{strategy['label']}] КУПЕНО: {qty} x {symbol} @ ~{last_price:.2f} "
                f"(SL -{strategy['stop_loss_pct']*100:.0f}% / TP +{strategy['take_profit_pct']*100:.0f}%)"
            )
        except error.HTTPError as e:
            errors.append(f"[{strategy['label']}] {symbol}: грешка при поръчка ({e.read().decode()[:200]})")

    return trades_made, errors


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

    print(f"Equity: {equity:.2f} | Отворени позиции: {len(positions)}")

    today_orders = get_today_orders()
    traded_today = {o["symbol"] for o in today_orders}

    all_trades = []
    all_errors = []
    for strategy in STRATEGIES:
        trades, errors = run_strategy(strategy, equity, held_symbols, traded_today)
        all_trades.extend(trades)
        all_errors.extend(errors)
        # обновяваме held_symbols веднага, за да не се пресичат бюджетите
        held_symbols |= {t[1] for t in trades}

    if all_trades:
        lines = [f"🤖 Alpaca бот — {len(all_trades)} нова сделка(и):"]
        for label, symbol, qty, price, sl, tp in all_trades:
            lines.append(
                f"  • [{label}] КУПЕНО {qty} x {symbol} @ ~{price:.2f} "
                f"(SL -{sl*100:.0f}% / TP +{tp*100:.0f}%)"
            )
        lines.append(f"Equity: ${equity:,.2f}")
        send_notification("\n".join(lines))
    if all_errors:
        send_notification("⚠️ Alpaca бот — грешки:\n" + "\n".join(all_errors))

    if not all_trades and not all_errors:
        print("Няма нови сигнали този час (нито blue-chip, нито penny).")


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
