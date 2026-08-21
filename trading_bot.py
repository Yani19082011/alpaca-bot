#!/usr/bin/env python3
"""
Alpaca Paper Trading Bot — hourly runner, пет независими стратегии.

Изпълнява се от GitHub Actions (безплатен cron, пълен интернет достъп) —
не от Claude, защото Claude-облачните среди нямат мрежов достъп до Alpaca.

СТРАТЕГИЯ 1 — "blue-chip": SMA(10) > SMA(30) на ликвидни акции/ETF-и.
                 10% от equity, SL -3% / TP +6%, макс. 3 позиции.

СТРАТЕГИЯ 2 — "penny": 20-дневен breakout + volume spike на penny stocks
                 (<$5). 3% от equity, SL -10% / TP +20%, макс. 2 позиции.

СТРАТЕГИЯ 3 — "ai-longterm": дългосрочен тренд (SMA50 > SMA200, "златен
                 кръст") на watchlist от AI-сектора. BRACKET поръчка:
                 TP +20% / SL -20% (широк stop, катастрофична защита, не
                 обичайна търговска граница). 8% от equity, макс. 3 позиции.
                 (Забележка: без отделен earnings feed — Alpaca не дава
                 такива данни безплатно, а добавянето на трети API само
                 за това би усложнило нещата излишно. Сигналът е чисто
                 базиран на ценови тренд.)

СТРАТЕГИЯ 4 — "ai-daytrade": SAME AI watchlist, но intraday momentum
                 (цена > +1.5% спрямо днешния open, с потвърждение по
                 обем), само в прозореца 16:30–22:30 ч. българско време.
                 6% от equity, SL -2% / TP +4%, макс. 2 позиции.
                 ЗАДЪЛЖИТЕЛНО се затваря до края на прозореца (или ако
                 остават <20 мин. до затварянето на борсата) — никога не
                 се пренася за следващия ден. Позициите, отворени от тази
                 стратегия, се разпознават по client_order_id префикс
                 "ai-daytrade-", за да не се бъркат с "ai-longterm"
                 позиции в същия символ (двете стратегии споделят
                 watchlist, но никога не влизат в един и същ символ
                 едновременно — ако вече е държан от едната, другата го
                 прескача).

СТРАТЕГИЯ 5 — "sp500-longterm": диверсифицирана кошница от утвърдени
                 S&P 500 компании (различни сектори — финанси,
                 здравеопазване, потребление, енергетика, индустрия —
                 нарочно БЕЗ припокриване с другите watchlist-и), пак на
                 базата на "златен кръст" (SMA50 > SMA200). Мисълта е за
                 купи-и-държи за години, не за бърза търговия: BRACKET
                 поръчка TP +20% / SL -15% (широк stop, само
                 катастрофична защита). 6% от equity на позиция, макс. 5
                 едновременни позиции (до 30% от капитала разпределено
                 между сектори). По-широка диверсификация от
                 "ai-longterm", защото тук идеята е дългосрочен растеж на
                 целия пазар, не залог само на един сектор.

ВАЖНО за "проучвателния прозорец" (11:00–16:30 бг. време): това е преди
отварянето на американската борса, така че по това време скриптът и
без друго не прави нищо активно (пазарът е затворен → изход веднага).
Сигналите на всички стратегии вече се базират на последната ЗАТВОРЕНА
дневна свещ, която автоматично включва всичко случило се "през нощта"
— затова не добавям отделна pre-market "запомняща" фаза с ръчно пазено
състояние между run-овете (би изисквало ботът сам да прави git commit
обратно в repo-то — по-крехко и по-трудно за поддръжка, без реална
полза, защото free data feed-ът (IEX) и без друго няма надеждни
pre-market данни).

Всяка позиция се пуска като BRACKET (SL+TP) или OTO (само SL) поръчка —
Alpaca управлява изходите СЪРВЪРНО, денонощно, дори ботът да не се е
пуснал в конкретния час.

СТАТИЧНО ТАБЛО (docs/index.html, публикувано през GitHub Pages): при
всеки run скриптът записва docs/status.json (equity, позиции, поръчки) —
GitHub Actions го commit-ва обратно в repo-то (виж trading-bot.yml,
стъпка "Commit updated status snapshot"). Таблото чете този файл директно
от същия сайт — БЕЗ API ключове в браузъра и БЕЗ проблем с CORS (Alpaca
блокира директни browser заявки към paper-api.alpaca.markets).

ПАРОЛА / КРИПТИРАНЕ: ако DASHBOARD_PASSWORD е зададена, status.json се
записва криптиран (AES-256-GCM) — нечетим за никого без паролата, дори
ако отвори суровия файл директно на GitHub. Таблото пита за парола и
декриптира в браузъра (Web Crypto API), без паролата да напуска
компютъра на потребителя.

Изисква следните environment variables (GitHub Actions secrets):
  ALPACA_API_KEY_ID
  ALPACA_API_SECRET_KEY
  NTFY_TOPIC              (опционално — за push известия през ntfy.sh)
  DASHBOARD_PASSWORD      (опционално, но силно препоръчително — криптира status.json)

Изисква и пакета "cryptography" (виж стъпка "Install dependencies" в
trading-bot.yml) — единствената не-stdlib зависимост, само за AES.
"""
import os
import json
import sys
import base64
import hashlib
import traceback
from urllib import request, error
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

API_KEY = os.environ.get("ALPACA_API_KEY_ID", "")
API_SECRET = os.environ.get("ALPACA_API_SECRET_KEY", "")

# ntfy.sh — безплатни push известия без акаунт/токен. "Темата" действа
# като таен адрес — четем я САМО от GitHub Secret (не е записана тук в
# кода), защото repo-то е public и всеки текст тук би бил видим за всички.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

# Парола за криптиране на docs/status.json — четем я САМО от GitHub Secret.
# Ако е зададена, status.json се записва криптиран (AES-256-GCM) и е
# нечетим за всеки, който няма паролата — дори ако отвори файла директно.
# Таблото (docs/index.html) го декриптира в браузъра с Web Crypto API,
# използвайки SHA-256 от същата парола като ключ (виж unlockWith() там).
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

TRADING_BASE = "https://paper-api.alpaca.markets"
DATA_BASE = "https://data.alpaca.markets"
SOFIA_TZ = ZoneInfo("Europe/Sofia")

# Пътят, в който се записва JSON снимка на текущото състояние — GitHub
# Actions я commit-ва обратно в repo-то, а статичното табло в docs/index.html
# (публикувано през GitHub Pages) я чете директно като обикновен файл от
# СЪЩИЯ сайт. Така таблото никога няма нужда от API ключове в браузъра и
# няма проблем с CORS (Alpaca блокира директни заявки от браузър).
STATUS_PATH = "docs/status.json"

# ==================== СТРАТЕГИЯ 1: blue-chip ====================
WATCHLIST = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
MAX_POSITIONS = 3
POSITION_PCT = 0.10
STOP_LOSS_PCT = 0.03
TAKE_PROFIT_PCT = 0.06
SMA_SHORT = 10
SMA_LONG = 30

# ==================== СТРАТЕГИЯ 2: penny stocks ====================
PENNY_WATCHLIST = [
    "HTZ", "PLUG", "UWMC", "OPEN", "NIO", "AMC",
    "BTBT", "HIVE", "SPCE", "LAC", "EOSE", "BBAI",
]
PENNY_MIN_PRICE = 0.50
PENNY_MAX_PRICE = 5.00
PENNY_MIN_AVG_DOLLAR_VOLUME = 2_000_000
PENNY_MAX_POSITIONS = 2
PENNY_POSITION_PCT = 0.03
PENNY_STOP_LOSS_PCT = 0.10
PENNY_TAKE_PROFIT_PCT = 0.20
PENNY_BREAKOUT_LOOKBACK = 20
PENNY_VOLUME_MULT = 1.5

# ==================== СТРАТЕГИЯ 3 и 4: AI сектор ====================
# Watchlist проверен август 2026 г. (реални, борсово листнати тикери,
# отделни от blue-chip и penny списъците по-горе).
AI_WATCHLIST = ["PLTR", "AMD", "AVGO", "SMCI", "CRWD", "SNOW", "ARM", "MRVL", "ANET", "MU", "ORCL"]

# -- 3a: ai-longterm --
AI_LT_SMA_FAST = 50
AI_LT_SMA_SLOW = 200
AI_LT_BARS_LIMIT = 220
AI_LT_MAX_POSITIONS = 3
AI_LT_POSITION_PCT = 0.08
AI_LT_STOP_LOSS_PCT = 0.20   # катастрофична защита, не обичаен trading stop
AI_LT_TAKE_PROFIT_PCT = 0.20  # взима печалбата на +20% вместо да чака безкрайно

# -- 3b: ai-daytrade --
AI_DT_MAX_POSITIONS = 2
AI_DT_POSITION_PCT = 0.06
AI_DT_STOP_LOSS_PCT = 0.02
AI_DT_TAKE_PROFIT_PCT = 0.04
AI_DT_MOMENTUM_THRESHOLD = 0.015     # +1.5% спрямо днешния open
AI_DT_MIN_DOLLAR_VOLUME = 10_000_000  # оборот в $ до момента днес
AI_DT_WINDOW_START_MIN = 16 * 60 + 30   # 16:30 бг. време
AI_DT_WINDOW_END_MIN = 22 * 60 + 30     # 22:30 бг. време
AI_DT_FORCE_CLOSE_BUFFER_MIN = 20       # затваря се 20 мин. преди края

# ==================== СТРАТЕГИЯ 5: sp500-longterm ====================
# Диверсифицирана кошница от S&P 500 компании, различни сектори,
# нарочно БЕЗ припокриване с WATCHLIST / PENNY_WATCHLIST / AI_WATCHLIST.
SP500_WATCHLIST = [
    "JPM", "JNJ", "PG", "KO", "XOM", "CVX", "HD", "WMT",
    "UNH", "V", "MA", "DIS", "PEP", "COST", "MCD", "LLY",
]
SP500_LT_SMA_FAST = 50
SP500_LT_SMA_SLOW = 200
SP500_LT_BARS_LIMIT = 220
SP500_LT_MAX_POSITIONS = 5
SP500_LT_POSITION_PCT = 0.06
SP500_LT_STOP_LOSS_PCT = 0.15   # катастрофична защита, не обичаен trading stop
SP500_LT_TAKE_PROFIT_PCT = 0.20  # взима печалбата на +20% вместо да чака безкрайно

# ==================== Начален баланс (за "P/L общо от старта") ====================
# Alpaca paper trading акаунтите тръгват по подразбиране с $100,000.
# Ако си нулирал/презаредил акаунта с друга сума, смени числото тук.
STARTING_BALANCE = 100_000.0


# ---------------- ntfy.sh известия ----------------

def send_notification(text):
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


def _delete(url):
    req = request.Request(url, headers=_headers(), method="DELETE")
    with request.urlopen(req, timeout=20) as resp:
        return resp.status


def get_clock():
    return _get(f"{TRADING_BASE}/v2/clock")


def get_account():
    return _get(f"{TRADING_BASE}/v2/account")


def get_positions():
    return _get(f"{TRADING_BASE}/v2/positions")


def get_today_orders():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _get(f"{TRADING_BASE}/v2/orders?status=all&after={today}T00:00:00Z&limit=200")


def get_orders_for_symbol_today(symbol):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _get(f"{TRADING_BASE}/v2/orders?status=all&symbols={symbol}&after={today}T00:00:00Z&limit=50")


def get_open_orders_for_symbol(symbol):
    return _get(f"{TRADING_BASE}/v2/orders?status=open&symbols={symbol}&limit=50")


def cancel_order(order_id):
    return _delete(f"{TRADING_BASE}/v2/orders/{order_id}")


def close_position_market(symbol):
    return _delete(f"{TRADING_BASE}/v2/positions/{symbol}")


def get_daily_bars(symbol, limit=40):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=limit * 2)  # буфер за уикенди/празници
    url = (
        f"{DATA_BASE}/v2/stocks/{symbol}/bars"
        f"?timeframe=1Day&start={start.strftime('%Y-%m-%d')}"
        f"&end={end.strftime('%Y-%m-%d')}&limit={limit}&feed=iex"
    )
    return _get(url).get("bars", [])


def get_snapshot(symbol):
    return _get(f"{DATA_BASE}/v2/stocks/{symbol}/snapshot?feed=iex")


def parse_alpaca_ts(ts):
    """Alpaca връща наносекундна точност (напр. ...104594476-04:00) —
    Python поддържа макс. 6 цифри (микросекунди), затова подрязваме."""
    if "." in ts:
        head, rest = ts.split(".", 1)
        frac, offset = rest, ""
        for i, ch in enumerate(rest):
            if ch in "+-Z":
                frac, offset = rest[:i], rest[i:]
                break
        frac = frac[:6].ljust(6, "0")
        ts = f"{head}.{frac}{offset}"
    return datetime.fromisoformat(ts)


def sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def place_entry_order(symbol, qty, entry_price, stop_loss_pct, take_profit_pct, client_order_id=None):
    """BRACKET (SL+TP), или OTO (само SL) ако take_profit_pct е None."""
    stop_loss = round(entry_price * (1 - stop_loss_pct), 2)
    payload = {
        "symbol": symbol,
        "qty": str(qty),
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
    }
    if take_profit_pct is not None:
        take_profit = round(entry_price * (1 + take_profit_pct), 2)
        payload["order_class"] = "bracket"
        payload["take_profit"] = {"limit_price": str(take_profit)}
        payload["stop_loss"] = {"stop_price": str(stop_loss)}
    else:
        payload["order_class"] = "oto"
        payload["stop_loss"] = {"stop_price": str(stop_loss)}
    if client_order_id:
        payload["client_order_id"] = client_order_id[:128]
    return _post(f"{TRADING_BASE}/v2/orders", payload)


# ---------------- Status snapshot (за статичното табло) ----------------

def _safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _encrypt_json(obj, password):
    """AES-256-GCM криптиране на JSON обект с ключ = SHA-256(password).
    Връща base64 низ (nonce + ciphertext+tag), декриптируем в браузъра
    със същия ключ извод чрез Web Crypto SubtleCrypto (виж docs/index.html)."""
    plaintext = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    key = hashlib.sha256(password.encode("utf-8")).digest()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def write_status_snapshot(clock, account, positions, orders):
    """Записва компактна JSON снимка в STATUS_PATH — commit-ва се обратно в
    repo-то от workflow-а, за да може docs/index.html (GitHub Pages) да я
    прочете директно, без API ключове и без CORS проблем."""
    try:
        equity_val = _safe_float(account.get("equity"))
        last_equity_val = _safe_float(account.get("last_equity"))

        day_pl = None
        day_pl_pct = None
        if equity_val is not None and last_equity_val:
            day_pl = equity_val - last_equity_val
            day_pl_pct = day_pl / last_equity_val

        total_pl = None
        total_pl_pct = None
        if equity_val is not None:
            total_pl = equity_val - STARTING_BALANCE
            total_pl_pct = total_pl / STARTING_BALANCE

        status = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "market_open": bool(clock.get("is_open")),
            "next_open": clock.get("next_open"),
            "next_close": clock.get("next_close"),
            "account": {
                "equity": account.get("equity"),
                "cash": account.get("cash"),
                "buying_power": account.get("buying_power"),
                "portfolio_value": account.get("portfolio_value"),
                "last_equity": account.get("last_equity"),
                "day_pl": day_pl,
                "day_pl_pct": day_pl_pct,
                "total_pl": total_pl,
                "total_pl_pct": total_pl_pct,
            },
            "positions": [
                {
                    "symbol": p.get("symbol"),
                    "qty": p.get("qty"),
                    "avg_entry_price": p.get("avg_entry_price"),
                    "current_price": p.get("current_price"),
                    "unrealized_pl": p.get("unrealized_pl"),
                    "unrealized_plpc": p.get("unrealized_plpc"),
                    "side": p.get("side"),
                }
                for p in positions
            ],
            "orders": [
                {
                    "symbol": o.get("symbol"),
                    "side": o.get("side"),
                    "qty": o.get("qty"),
                    "status": o.get("status"),
                    "filled_avg_price": o.get("filled_avg_price"),
                    "client_order_id": o.get("client_order_id"),
                    "submitted_at": o.get("submitted_at"),
                }
                for o in orders
            ],
        }
        if DASHBOARD_PASSWORD:
            payload = {"enc": _encrypt_json(status, DASHBOARD_PASSWORD)}
        else:
            print(
                "[status] ПРЕДУПРЕЖДЕНИЕ: DASHBOARD_PASSWORD не е зададена — "
                "status.json се пише БЕЗ криптиране (четим е от всеки)."
            )
            payload = status

        status_dir = os.path.dirname(STATUS_PATH)
        if status_dir:
            os.makedirs(status_dir, exist_ok=True)
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[status] Неуспешен запис на snapshot: {e}")


# ---------------- Сигнали ----------------

def blue_chip_signal(bars):
    closes = [b["c"] for b in bars]
    short = sma(closes, SMA_SHORT)
    long_ = sma(closes, SMA_LONG)
    return short is not None and long_ is not None and short > long_


def penny_signal(bars):
    if len(bars) < PENNY_BREAKOUT_LOOKBACK + 1:
        return False
    closes = [b["c"] for b in bars]
    volumes = [b["v"] for b in bars]
    last_close = closes[-1]
    if last_close < PENNY_MIN_PRICE or last_close > PENNY_MAX_PRICE:
        return False
    prior_closes = closes[-(PENNY_BREAKOUT_LOOKBACK + 1):-1]
    prior_volumes = volumes[-(PENNY_BREAKOUT_LOOKBACK + 1):-1]
    prior_high = max(prior_closes)
    avg_volume = sum(prior_volumes) / len(prior_volumes)
    avg_price = sum(prior_closes) / len(prior_closes)
    if avg_volume * avg_price < PENNY_MIN_AVG_DOLLAR_VOLUME:
        return False
    today_volume = volumes[-1]
    breakout = last_close > prior_high
    volume_spike = avg_volume > 0 and today_volume > avg_volume * PENNY_VOLUME_MULT
    return breakout and volume_spike


def golden_cross_signal(bars, sma_fast=AI_LT_SMA_FAST, sma_slow=AI_LT_SMA_SLOW):
    """SMA(fast) > SMA(slow) ('златен кръст') и цената над SMA(fast) —
    потвърден дългосрочен тренд. Използва се и от "ai-longterm", и от
    "sp500-longterm" (по подразбиране 50/200, еднакво за двете)."""
    closes = [b["c"] for b in bars]
    fast = sma(closes, sma_fast)
    slow = sma(closes, sma_slow)
    if fast is None or slow is None:
        return False
    return fast > slow and closes[-1] > fast


def ai_daytrade_signal(snapshot):
    try:
        current_price = snapshot["latestTrade"]["p"]
        today_open = snapshot["dailyBar"]["o"]
        today_volume = snapshot["dailyBar"]["v"]
    except (KeyError, TypeError):
        return False
    if not today_open or not current_price:
        return False
    momentum = (current_price - today_open) / today_open
    dollar_volume_so_far = today_volume * current_price
    return momentum > AI_DT_MOMENTUM_THRESHOLD and dollar_volume_so_far > AI_DT_MIN_DOLLAR_VOLUME


# ---------------- Стратегии (bar-based: blue-chip / penny / ai-longterm) ----------------

STRATEGIES = [
    {
        "label": "blue-chip", "watchlist": WATCHLIST, "max_positions": MAX_POSITIONS,
        "position_pct": POSITION_PCT, "stop_loss_pct": STOP_LOSS_PCT,
        "take_profit_pct": TAKE_PROFIT_PCT, "signal_fn": blue_chip_signal, "bars_limit": 40,
    },
    {
        "label": "penny", "watchlist": PENNY_WATCHLIST, "max_positions": PENNY_MAX_POSITIONS,
        "position_pct": PENNY_POSITION_PCT, "stop_loss_pct": PENNY_STOP_LOSS_PCT,
        "take_profit_pct": PENNY_TAKE_PROFIT_PCT, "signal_fn": penny_signal, "bars_limit": 40,
    },
    {
        "label": "ai-longterm", "watchlist": AI_WATCHLIST, "max_positions": AI_LT_MAX_POSITIONS,
        "position_pct": AI_LT_POSITION_PCT, "stop_loss_pct": AI_LT_STOP_LOSS_PCT,
        "take_profit_pct": AI_LT_TAKE_PROFIT_PCT, "signal_fn": golden_cross_signal, "bars_limit": AI_LT_BARS_LIMIT,
    },
    {
        "label": "sp500-longterm", "watchlist": SP500_WATCHLIST, "max_positions": SP500_LT_MAX_POSITIONS,
        "position_pct": SP500_LT_POSITION_PCT, "stop_loss_pct": SP500_LT_STOP_LOSS_PCT,
        "take_profit_pct": SP500_LT_TAKE_PROFIT_PCT, "signal_fn": golden_cross_signal, "bars_limit": SP500_LT_BARS_LIMIT,
    },
]


def run_strategy(strategy, equity, held_symbols, traded_today, today_str):
    watchlist = strategy["watchlist"]
    held_in_strategy = held_symbols & set(watchlist)
    slots_free = strategy["max_positions"] - len(held_in_strategy)
    trades_made, errors = [], []
    if slots_free <= 0:
        return trades_made, errors

    for symbol in watchlist:
        if len(trades_made) >= slots_free:
            break
        if symbol in held_symbols or symbol in traded_today:
            continue
        try:
            bars = get_daily_bars(symbol, limit=strategy.get("bars_limit", 40))
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
        coid = f"{strategy['label']}-{symbol}-{today_str}"
        try:
            place_entry_order(
                symbol, qty, last_price, strategy["stop_loss_pct"], strategy["take_profit_pct"],
                client_order_id=coid,
            )
            trades_made.append((strategy["label"], symbol, qty, last_price,
                                 strategy["stop_loss_pct"], strategy["take_profit_pct"]))
            tp = strategy["take_profit_pct"]
            tp_str = f"+{tp*100:.0f}%" if tp is not None else "без TP (виси до SL)"
            print(
                f"[{strategy['label']}] КУПЕНО: {qty} x {symbol} @ ~{last_price:.2f} "
                f"(SL -{strategy['stop_loss_pct']*100:.0f}% / TP {tp_str})"
            )
        except error.HTTPError as e:
            errors.append(f"[{strategy['label']}] {symbol}: грешка при поръчка ({e.read().decode()[:200]})")

    return trades_made, errors


# ---------------- ai-daytrade: вход и принудително затваряне ----------------

def count_open_ai_daytrade_positions(held_symbols):
    count = 0
    for symbol in held_symbols & set(AI_WATCHLIST):
        try:
            orders = get_orders_for_symbol_today(symbol)
        except error.HTTPError:
            continue
        if any(o.get("client_order_id", "").startswith("ai-daytrade-") and o.get("status") == "filled" for o in orders):
            count += 1
    return count


def run_ai_daytrade_entries(equity, held_symbols, traded_today, today_str):
    trades_made, errors = [], []
    dt_open_count = count_open_ai_daytrade_positions(held_symbols)
    slots_free = AI_DT_MAX_POSITIONS - dt_open_count
    if slots_free <= 0:
        return trades_made, errors

    for symbol in AI_WATCHLIST:
        if len(trades_made) >= slots_free:
            break
        if symbol in held_symbols or symbol in traded_today:
            continue  # вече държан (от ai-longterm или другаде) - прескачаме, за да не се смесят
        try:
            snap = get_snapshot(symbol)
        except error.HTTPError as e:
            errors.append(f"[ai-daytrade] {symbol}: грешка при snapshot ({e.read().decode()[:150]})")
            continue
        if not ai_daytrade_signal(snap):
            continue
        current_price = snap["latestTrade"]["p"]
        budget = equity * AI_DT_POSITION_PCT
        qty = int(budget // current_price)
        if qty < 1:
            continue
        coid = f"ai-daytrade-{symbol}-{today_str}"
        try:
            place_entry_order(symbol, qty, current_price, AI_DT_STOP_LOSS_PCT, AI_DT_TAKE_PROFIT_PCT, client_order_id=coid)
            trades_made.append(("ai-daytrade", symbol, qty, current_price, AI_DT_STOP_LOSS_PCT, AI_DT_TAKE_PROFIT_PCT))
            print(
                f"[ai-daytrade] КУПЕНО: {qty} x {symbol} @ ~{current_price:.2f} "
                f"(SL -{AI_DT_STOP_LOSS_PCT*100:.0f}% / TP +{AI_DT_TAKE_PROFIT_PCT*100:.0f}%) "
                f"— ще се затвори до края на прозореца"
            )
        except error.HTTPError as e:
            errors.append(f"[ai-daytrade] {symbol}: грешка при поръчка ({e.read().decode()[:150]})")

    return trades_made, errors


def force_close_ai_daytrade_positions(held_symbols):
    closed, errors = [], []
    for symbol in held_symbols & set(AI_WATCHLIST):
        try:
            orders = get_orders_for_symbol_today(symbol)
        except error.HTTPError as e:
            errors.append(f"[ai-daytrade] {symbol}: грешка при проверка ({e.read().decode()[:150]})")
            continue
        is_daytrade = any(
            o.get("client_order_id", "").startswith("ai-daytrade-") and o.get("status") == "filled"
            for o in orders
        )
        if not is_daytrade:
            continue
        try:
            for o in get_open_orders_for_symbol(symbol):
                try:
                    cancel_order(o["id"])
                except error.HTTPError:
                    pass  # може вече да е отменена от OCO-своя близнак — ОК
            close_position_market(symbol)
            closed.append(symbol)
            print(f"[ai-daytrade] ЗАТВОРЕНО {symbol} (край на дневния прозорец / borsa)")
        except error.HTTPError as e:
            errors.append(f"[ai-daytrade] {symbol}: грешка при затваряне ({e.read().decode()[:150]})")
    return closed, errors


# ---------------- Main ----------------

def run():
    if not API_KEY or not API_SECRET:
        raise RuntimeError("Липсват ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY.")

    clock = get_clock()
    account = get_account()
    positions = get_positions()
    today_orders = get_today_orders()
    write_status_snapshot(clock, account, positions, today_orders)

    if not clock.get("is_open"):
        print(f"Пазарът е затворен (next open: {clock.get('next_open')}). Нищо за правене.")
        return

    now = parse_alpaca_ts(clock["timestamp"])
    next_close = parse_alpaca_ts(clock["next_close"])
    minutes_to_close = (next_close - now).total_seconds() / 60.0

    sofia_now = now.astimezone(SOFIA_TZ)
    sofia_minutes = sofia_now.hour * 60 + sofia_now.minute
    in_daytrade_window = AI_DT_WINDOW_START_MIN <= sofia_minutes <= AI_DT_WINDOW_END_MIN
    near_window_end = sofia_minutes >= (AI_DT_WINDOW_END_MIN - AI_DT_FORCE_CLOSE_BUFFER_MIN)
    near_market_close = minutes_to_close <= AI_DT_FORCE_CLOSE_BUFFER_MIN
    should_force_close = near_window_end or near_market_close

    today_str = now.strftime("%Y-%m-%d")

    equity = float(account["equity"])
    held_symbols = {p["symbol"] for p in positions}
    traded_today = {o["symbol"] for o in today_orders}

    print(
        f"Equity: {equity:.2f} | Позиции: {len(positions)} | "
        f"Sofia {sofia_now.strftime('%H:%M')} | daytrade window: {in_daytrade_window} | "
        f"force-close: {should_force_close}"
    )

    all_trades, all_errors = [], []

    # 1) Задължително първо: затваряме просрочени ai-daytrade позиции.
    if should_force_close:
        closed, errs = force_close_ai_daytrade_positions(held_symbols)
        for s in closed:
            all_trades.append(("ai-daytrade-CLOSE", s, None, None, None, None))
        all_errors.extend(errs)
        held_symbols -= set(closed)

    # 2) Bar-based стратегии: blue-chip, penny, ai-longterm.
    for strategy in STRATEGIES:
        trades, errors = run_strategy(strategy, equity, held_symbols, traded_today, today_str)
        all_trades.extend(trades)
        all_errors.extend(errors)
        held_symbols |= {t[1] for t in trades}

    # 3) ai-daytrade нови входове — само в прозореца и не точно преди затваряне.
    if in_daytrade_window and not should_force_close:
        trades, errors = run_ai_daytrade_entries(equity, held_symbols, traded_today, today_str)
        all_trades.extend(trades)
        all_errors.extend(errors)
        held_symbols |= {t[1] for t in trades}

    # Финална снимка — след като сделките (ако е имало) вече са изпълнени,
    # за да показва таблото актуалното състояние, не това отпреди тях.
    if all_trades:
        try:
            write_status_snapshot(clock, get_account(), get_positions(), get_today_orders())
        except error.HTTPError as e:
            print(f"[status] Неуспешно финално обновяване: {e}")

    if all_trades:
        lines = [f"🤖 Alpaca бот — {len(all_trades)} събитие(я):"]
        for label, symbol, qty, price, sl, tp in all_trades:
            if label == "ai-daytrade-CLOSE":
                lines.append(f"  • [ai-daytrade] ЗАТВОРЕНО {symbol} (край на дневния прозорец)")
            else:
                tp_str = f"+{tp*100:.0f}%" if tp is not None else "без TP"
                lines.append(f"  • [{label}] КУПЕНО {qty} x {symbol} @ ~{price:.2f} (SL -{sl*100:.0f}% / TP {tp_str})")
        lines.append(f"Equity: ${equity:,.2f}")
        send_notification("\n".join(lines))
    if all_errors:
        send_notification("⚠️ Alpaca бот — грешки:\n" + "\n".join(all_errors))
    if not all_trades and not all_errors:
        print("Няма нови сигнали/действия този час.")


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
