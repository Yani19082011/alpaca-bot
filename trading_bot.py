#!/usr/bin/env python3
"""
Alpaca Paper Trading Bot — hourly runner, ЕКСПЕРИМЕНТ с 3 ротиращи се
day-trading стратегии.

Изпълнява се от GitHub Actions (безплатен cron, пълен интернет достъп) —
не от Claude, защото Claude-облачните среди нямат мрежов достъп до Alpaca.

=================== ЗАЩО СЕ ПРОМЕНИ БОТЪТ ===================
По-рано ботът въртеше 5 различни стратегии едновременно (blue-chip, penny,
ai-longterm, ai-daytrade, sp500-longterm). Сега, по изрично желание, ботът
търгува САМО intraday (day trading) — никога не държи позиция за нощта.

Старите 4 дългосрочни/средносрочни стратегии (blue-chip, penny, ai-longterm,
sp500-longterm) вече НЕ отварят нови позиции. Позициите, които вече бяха
отворени от тях преди тази промяна, НЕ се пипат — просто си стоят с
техните оригинални stop-loss/take-profit поръчки (Alpaca ги управлява
сървърно, независимо от този код) и ще се затворят сами, когато цената
удари единия праг. Таблото продължава да ги показва с оригиналните им
означения, докато не се затворят.

=================== 3-ДНЕВЕН ЕКСПЕРИМЕНТ ===================
За да разберем коя day-trading идея работи най-добре, ботът РОТИРА между
3 различни сигнала — по един активен на ден (детерминирано по датата, не
по случаен избор, за да е едно и също цял ден дори ботът да се пуска
многократно):

  🚀 momentum  — купува СИЛА: цена > +1.5% спрямо днешния open + обем
                 потвърждение. Залага на продължение на движението.

  🔄 reversal  — купува СЛАБОСТ, която спира да пада: цена е поне -1.5%
                 от open (истинска слабост), но вече не прави нови дъна
                 (малко над днешния минимум) + обем. Залага на отскок —
                 обратна теза на momentum.

  📈 breakout  — купува ПРОБИВ: цената е на/близо до дневния максимум,
                 при условие че самият връх вече е забележимо над open
                 (не е плосък ден) + обем. Залага на продължение след
                 пробив на съпротива.

Умишлено ВСИЧКИ параметри за риск (позиция %, stop-loss, take-profit,
брой позиции, прозорец) са ЕДНАКВИ за трите — единствената разлика е
СИГНАЛЪТ за вход. Това прави сравнението честно: ако една стратегия
изкара по-добър резултат, причината е сигналът, не различен риск профил.

Всеки ден ботът записва резултата (реализирана печалба/загуба от
затворените тази стратегия позиции) в docs/status.json → "daytrade_log",
което се пази между run-овете (файлът се чете и допълва, не се
презаписва от нулата всеки път) — така след 3+ дни има реална статистика
за сравнение, видима директно на таблото.

За всеки ден в "daytrade_log" се пази и списък "trades" с реалните
покупки/продажби (символ, кол-во, цена, П/З) — таблото го показва в
календар (по 1 клетка на ден, оцветена според резултата), а с клик на
конкретен ден се вижда точно какво е купил/продал ботът тогава. Тези
сделки НЕ се вземат от моментна снимка при затварянето, а се
възстановяват от реалната поръчкова история в Alpaca (виж
build_daytrade_trades) — това хваща коректно и случаите, в които
Stop-loss/Take-profit се е задействал сам по средата на деня, преди
принудителното затваряне в края на прозореца.

Прозорец: 16:30–22:30 ч. българско време. ЗАДЪЛЖИТЕЛНО се затваря всичко
до края на прозореца (или ако остават <20 мин. до затварянето на
борсата) — никога не се пренася за следващия ден. Позициите се
разпознават по client_order_id префикс "daytrade-{стратегия}-".

СТАТИЧНО ТАБЛО (docs/index.html, публикувано през GitHub Pages): при
всеки run скриптът записва docs/status.json (equity, позиции, поръчки,
активна стратегия днес, дневник от резултати) — GitHub Actions го
commit-ва обратно в repo-то (виж trading-bot.yml, стъпка "Commit updated
status snapshot"). Таблото чете този файл директно от същия сайт — БЕЗ
API ключове в браузъра и БЕЗ проблем с CORS (Alpaca блокира директни
browser заявки към paper-api.alpaca.markets).

ПАРОЛА / КРИПТИРАНЕ: ако DASHBOARD_PASSWORD е зададена, status.json се
записва криптиран (AES-256-GCM) — нечетим за никого без паролата, дори
ако отвори суровия файл директно на GitHub. Таблото пита за парола и
декриптира в браузъра (Web Crypto API), без паролата да напуска
компютъра на потребителя. Ботът и декриптира предишния файл (за да
продължи "daytrade_log" историята между run-овете), и криптира новия.

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

# ==================== Начален баланс (за "P/L общо от старта") ====================
# Alpaca paper trading акаунтите тръгват по подразбиране с $100,000.
# Ако си нулирал/презаредил акаунта с друга сума, смени числото тук.
STARTING_BALANCE = 100_000.0

# ==================== Day trading watchlist (споделен от трите стратегии) ====================
# Ликвидни, достатъчно волатилни имена — блу-чипове/ETF-и + AI/tech сектор.
DAYTRADE_WATCHLIST = [
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
    "PLTR", "AMD", "AVGO", "SMCI", "CRWD", "SNOW", "ARM", "MRVL", "ANET", "MU", "ORCL",
]

# ==================== Общи риск параметри (ЕДНАКВИ за трите — честно сравнение) ====================
DT_MAX_POSITIONS = 2
DT_POSITION_PCT = 0.06
DT_STOP_LOSS_PCT = 0.02
DT_TAKE_PROFIT_PCT = 0.04
DT_MIN_DOLLAR_VOLUME = 10_000_000       # оборот в $ до момента днес
DT_WINDOW_START_MIN = 16 * 60 + 30      # 16:30 бг. време
DT_WINDOW_END_MIN = 22 * 60 + 30        # 22:30 бг. време
DT_FORCE_CLOSE_BUFFER_MIN = 20          # затваря се 20 мин. преди края

# ==================== Параметри на сигналите ====================
DT_MOMENTUM_THRESHOLD = 0.015   # ±1.5% спрямо днешния open (ползва се от momentum И reversal)
DT_REVERSAL_CUSHION = 0.003     # цената трябва да е поне 0.3% над дневния минимум (не "прясно" дъно)
DT_BREAKOUT_MIN_RANGE = 0.005   # дневният връх трябва да е поне +0.5% над open (не е плосък ден)
DT_BREAKOUT_MARGIN = 0.002      # цената трябва да е до 0.2% от дневния връх, за да се брои "на върха"

DAYTRADE_LOG_MAX_ENTRIES = 180   # пазим последните ~6 месеца дневни резултати (за календара на таблото)


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


def place_entry_order(symbol, qty, entry_price, stop_loss_pct, take_profit_pct, client_order_id=None):
    """BRACKET (SL+TP) поръчка."""
    stop_loss = round(entry_price * (1 - stop_loss_pct), 2)
    take_profit = round(entry_price * (1 + take_profit_pct), 2)
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
    if client_order_id:
        payload["client_order_id"] = client_order_id[:128]
    return _post(f"{TRADING_BASE}/v2/orders", payload)


# ---------------- Криптиране/декриптиране (за status.json) ----------------

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


def _decrypt_json(enc_b64, password):
    """Обратното на _encrypt_json — ползва се, за да прочетем "daytrade_log"
    от ПРЕДИШНИЯ status.json (криптиран) и да продължим историята му."""
    raw = base64.b64decode(enc_b64)
    nonce, ciphertext = raw[:12], raw[12:]
    key = hashlib.sha256(password.encode("utf-8")).digest()
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return json.loads(plaintext.decode("utf-8"))


# ---------------- Дневник на 3-дневния експеримент ----------------

def load_previous_daytrade_log():
    """Чете (и декриптира, ако трябва) ПРЕДИШНИЯ status.json, само за да
    извади daytrade_log масива — за да продължи историята между run-овете
    (иначе всеки run презаписва файла от нулата и губим миналите дни)."""
    try:
        with open(STATUS_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return []
    try:
        if isinstance(raw, dict) and "enc" in raw:
            if not DASHBOARD_PASSWORD:
                return []
            raw = _decrypt_json(raw["enc"], DASHBOARD_PASSWORD)
        return raw.get("daytrade_log", []) if isinstance(raw, dict) else []
    except Exception as e:
        print(f"[daytrade_log] Неуспешно четене на предишен log: {e}")
        return []


def upsert_daytrade_log(log, date_str, strategy_key, strategy_label, realized_pl, trades_closed, trades=None):
    """Добавя/обновява записа за дадена дата (ако вече има запис за същия
    ден — презаписва го, вместо да дублира). "trades" е списък с реалните
    покупки/продажби от деня — показва се в календара на таблото, като
    цъкнеш на конкретен ден."""
    entry = {
        "date": date_str,
        "strategy": strategy_key,
        "strategy_label": strategy_label,
        "realized_pl": round(realized_pl, 2),
        "trades_closed": trades_closed,
        "trades": trades or [],
    }
    log = [e for e in log if e.get("date") != date_str]
    log.append(entry)
    log.sort(key=lambda e: e.get("date", ""))
    return log[-DAYTRADE_LOG_MAX_ENTRIES:]


def build_daytrade_trades(today_orders, active_strategy_key):
    """Възстановява РЕАЛНИТЕ покупки/продажби за деня директно от
    поръчките в Alpaca (а не от моментна снимка на unrealized_pl) — така
    хващаме коректно и случаите, в които Stop-loss/Take-profit се е
    задействал сам по средата на деня (преди принудителното затваряне).
    Връща (trades, realized_pl_total, closed_count)."""
    prefix = f"daytrade-{active_strategy_key}-"
    buys = {}
    for o in today_orders:
        coid = o.get("client_order_id") or ""
        if not coid.startswith(prefix):
            continue
        if o.get("side") != "buy" or o.get("status") != "filled":
            continue
        symbol = o.get("symbol")
        price = _safe_float(o.get("filled_avg_price"))
        qty = _safe_float(o.get("qty"))
        if symbol and price and qty:
            buys[symbol] = {"qty": qty, "price": price}

    trades = []
    realized_pl_total = 0.0
    closed_count = 0
    for symbol, buy in buys.items():
        trades.append({"type": "buy", "symbol": symbol, "qty": buy["qty"], "price": round(buy["price"], 2)})
        sell_price, sell_qty = None, 0.0
        for o in today_orders:
            if o.get("symbol") != symbol or o.get("side") != "sell" or o.get("status") != "filled":
                continue
            p = _safe_float(o.get("filled_avg_price"))
            q = _safe_float(o.get("qty"))
            if p and q:
                sell_price = p
                sell_qty += q
        if sell_price is not None and sell_qty > 0:
            pl = (sell_price - buy["price"]) * sell_qty
            trades.append({"type": "sell", "symbol": symbol, "qty": sell_qty, "price": round(sell_price, 2), "pl": round(pl, 2)})
            realized_pl_total += pl
            closed_count += 1

    trades.sort(key=lambda t: (t["symbol"], t["type"]))
    return trades, round(realized_pl_total, 2), closed_count


# ---------------- Status snapshot (за статичното табло) ----------------

def write_status_snapshot(clock, account, positions, orders, daytrade_log=None, today_strategy=None):
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
            "daytrade_today_strategy": today_strategy,
            "daytrade_log": daytrade_log or [],
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


# ---------------- Трите day-trading сигнала ----------------

def momentum_signal(snapshot):
    """🚀 Купува СИЛА: цена > +1.5% спрямо днешния open, с обем-потвърждение.
    Залага на продължение на движението (следва тренда)."""
    try:
        price = snapshot["latestTrade"]["p"]
        today_open = snapshot["dailyBar"]["o"]
        today_volume = snapshot["dailyBar"]["v"]
    except (KeyError, TypeError):
        return False
    if not today_open or not price:
        return False
    momentum = (price - today_open) / today_open
    dollar_volume = today_volume * price
    return momentum > DT_MOMENTUM_THRESHOLD and dollar_volume > DT_MIN_DOLLAR_VOLUME


def reversal_signal(snapshot):
    """🔄 Купува СЛАБОСТ, която спира да пада: цената е поне -1.5% от open
    (истинска слабост), но вече не прави нови дъна (малко над днешния
    минимум) + обем. Залага на отскок — обратна теза на momentum."""
    try:
        price = snapshot["latestTrade"]["p"]
        today_open = snapshot["dailyBar"]["o"]
        today_low = snapshot["dailyBar"]["l"]
        today_volume = snapshot["dailyBar"]["v"]
    except (KeyError, TypeError):
        return False
    if not today_open or not price or not today_low:
        return False
    drop_from_open = (price - today_open) / today_open
    cushion_above_low = (price - today_low) / today_low
    dollar_volume = today_volume * price
    return (
        drop_from_open < -DT_MOMENTUM_THRESHOLD
        and cushion_above_low > DT_REVERSAL_CUSHION
        and dollar_volume > DT_MIN_DOLLAR_VOLUME
    )


def breakout_signal(snapshot):
    """📈 Купува ПРОБИВ: цената е на/близо до дневния максимум, при
    условие че самият връх вече е забележимо над open (не е плосък ден)
    + обем. Залага на продължение след пробив на съпротива."""
    try:
        price = snapshot["latestTrade"]["p"]
        today_open = snapshot["dailyBar"]["o"]
        today_high = snapshot["dailyBar"]["h"]
        today_volume = snapshot["dailyBar"]["v"]
    except (KeyError, TypeError):
        return False
    if not today_open or not price or not today_high:
        return False
    high_move = (today_high - today_open) / today_open
    near_high = price >= today_high * (1 - DT_BREAKOUT_MARGIN)
    dollar_volume = today_volume * price
    return high_move > DT_BREAKOUT_MIN_RANGE and near_high and dollar_volume > DT_MIN_DOLLAR_VOLUME


DAYTRADE_STRATEGIES = [
    {"key": "momentum", "label": "Моментум 🚀", "signal_fn": momentum_signal},
    {"key": "reversal", "label": "Отскок 🔄", "signal_fn": reversal_signal},
    {"key": "breakout", "label": "Пробив 📈", "signal_fn": breakout_signal},
]


def todays_strategy(sofia_now):
    """Детерминирана ротация по календарна дата (не по случаен избор) —
    така активната стратегия е една и съща цял ден, дори ботът да се
    пуска многократно."""
    idx = sofia_now.toordinal() % len(DAYTRADE_STRATEGIES)
    return DAYTRADE_STRATEGIES[idx]


# ---------------- Day trading: вход и принудително затваряне ----------------

def count_open_daytrade_positions(held_symbols):
    count = 0
    for symbol in held_symbols & set(DAYTRADE_WATCHLIST):
        try:
            orders = get_orders_for_symbol_today(symbol)
        except error.HTTPError:
            continue
        if any(o.get("client_order_id", "").startswith("daytrade-") and o.get("status") == "filled" for o in orders):
            count += 1
    return count


def run_daytrade_entries(strategy, equity, held_symbols, traded_today, today_str):
    trades_made, errors = [], []
    dt_open_count = count_open_daytrade_positions(held_symbols)
    slots_free = DT_MAX_POSITIONS - dt_open_count
    if slots_free <= 0:
        return trades_made, errors

    for symbol in DAYTRADE_WATCHLIST:
        if len(trades_made) >= slots_free:
            break
        if symbol in held_symbols or symbol in traded_today:
            continue  # вече държан (от стар/легаси позиция или другаде) — прескачаме
        try:
            snap = get_snapshot(symbol)
        except error.HTTPError as e:
            errors.append(f"[{strategy['key']}] {symbol}: грешка при snapshot ({e.read().decode()[:150]})")
            continue
        if not strategy["signal_fn"](snap):
            continue
        current_price = snap["latestTrade"]["p"]
        budget = equity * DT_POSITION_PCT
        qty = int(budget // current_price)
        if qty < 1:
            continue
        coid = f"daytrade-{strategy['key']}-{symbol}-{today_str}"
        try:
            place_entry_order(symbol, qty, current_price, DT_STOP_LOSS_PCT, DT_TAKE_PROFIT_PCT, client_order_id=coid)
            trades_made.append((strategy["label"], symbol, qty, current_price, DT_STOP_LOSS_PCT, DT_TAKE_PROFIT_PCT))
            print(
                f"[{strategy['label']}] КУПЕНО: {qty} x {symbol} @ ~{current_price:.2f} "
                f"(SL -{DT_STOP_LOSS_PCT*100:.0f}% / TP +{DT_TAKE_PROFIT_PCT*100:.0f}%) "
                f"— ще се затвори до края на прозореца"
            )
        except error.HTTPError as e:
            errors.append(f"[{strategy['key']}] {symbol}: грешка при поръчка ({e.read().decode()[:150]})")

    return trades_made, errors


def force_close_daytrade_positions(held_symbols, positions_by_symbol):
    """Затваря всички отворени днешни day-trade позиции. Реализираната
    П/З за деня НЕ се смята тук — смята се отделно, от реалните fill-ове
    на поръчките (виж build_daytrade_trades), защото е по-точна (хваща и
    SL/TP, които са се задействали сами по-рано през деня)."""
    closed, errors = [], []
    for symbol in held_symbols & set(DAYTRADE_WATCHLIST):
        try:
            orders = get_orders_for_symbol_today(symbol)
        except error.HTTPError as e:
            errors.append(f"[daytrade] {symbol}: грешка при проверка ({e.read().decode()[:150]})")
            continue
        is_daytrade = any(
            o.get("client_order_id", "").startswith("daytrade-") and o.get("status") == "filled"
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
            print(f"[daytrade] ЗАТВОРЕНО {symbol} (край на дневния прозорец)")
        except error.HTTPError as e:
            errors.append(f"[daytrade] {symbol}: грешка при затваряне ({e.read().decode()[:150]})")
    return closed, errors


# ---------------- Main ----------------

def run():
    if not API_KEY or not API_SECRET:
        raise RuntimeError("Липсват ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY.")

    clock = get_clock()
    account = get_account()
    positions = get_positions()
    today_orders = get_today_orders()
    daytrade_log = load_previous_daytrade_log()

    now = parse_alpaca_ts(clock["timestamp"])
    sofia_now = now.astimezone(SOFIA_TZ)
    active_strategy = todays_strategy(sofia_now)
    active_strategy_info = {"key": active_strategy["key"], "label": active_strategy["label"]}

    write_status_snapshot(
        clock, account, positions, today_orders,
        daytrade_log=daytrade_log, today_strategy=active_strategy_info,
    )

    if not clock.get("is_open"):
        print(f"Пазарът е затворен (next open: {clock.get('next_open')}). Нищо за правене.")
        return

    next_close = parse_alpaca_ts(clock["next_close"])
    minutes_to_close = (next_close - now).total_seconds() / 60.0

    sofia_minutes = sofia_now.hour * 60 + sofia_now.minute
    in_window = DT_WINDOW_START_MIN <= sofia_minutes <= DT_WINDOW_END_MIN
    near_window_end = sofia_minutes >= (DT_WINDOW_END_MIN - DT_FORCE_CLOSE_BUFFER_MIN)
    near_market_close = minutes_to_close <= DT_FORCE_CLOSE_BUFFER_MIN
    should_force_close = near_window_end or near_market_close

    today_str = now.strftime("%Y-%m-%d")
    equity = float(account["equity"])
    held_symbols = {p["symbol"] for p in positions}
    positions_by_symbol = {p["symbol"]: p for p in positions}
    traded_today = {o["symbol"] for o in today_orders}

    print(
        f"Equity: {equity:.2f} | Позиции: {len(positions)} | Sofia {sofia_now.strftime('%H:%M')} | "
        f"стратегия днес: {active_strategy['label']} | window: {in_window} | force-close: {should_force_close}"
    )

    all_trades, all_errors = [], []

    # 1) Задължително първо: затваряме просрочени day-trade позиции от днес.
    if should_force_close:
        closed, errs = force_close_daytrade_positions(held_symbols, positions_by_symbol)
        for s in closed:
            all_trades.append(("daytrade-CLOSE", s, None, None, None, None))
        all_errors.extend(errs)
        held_symbols -= set(closed)

        # Пресмятаме реалните покупки/продажби на деня от прясната поръчкова
        # история (не от снимка отпреди затварянето) — по-точно.
        try:
            fresh_orders = get_today_orders()
        except error.HTTPError:
            fresh_orders = today_orders
        day_trades, day_realized_pl, day_closed_count = build_daytrade_trades(
            fresh_orders, active_strategy["key"],
        )
        daytrade_log = upsert_daytrade_log(
            daytrade_log, today_str, active_strategy["key"], active_strategy["label"],
            day_realized_pl, day_closed_count, day_trades,
        )

    # 2) Нови входове по активната днешна стратегия — само в прозореца.
    if in_window and not should_force_close:
        trades, errors = run_daytrade_entries(active_strategy, equity, held_symbols, traded_today, today_str)
        all_trades.extend(trades)
        all_errors.extend(errors)
        held_symbols |= {t[1] for t in trades}

    # Финална снимка — след сделките/затварянията и с обновения дневник.
    if all_trades or should_force_close:
        try:
            write_status_snapshot(
                clock, get_account(), get_positions(), get_today_orders(),
                daytrade_log=daytrade_log, today_strategy=active_strategy_info,
            )
        except error.HTTPError as e:
            print(f"[status] Неуспешно финално обновяване: {e}")

    if all_trades:
        lines = [f"🤖 Alpaca бот — {len(all_trades)} събитие(я) [{active_strategy['label']}]:"]
        for label, symbol, qty, price, sl, tp in all_trades:
            if label == "daytrade-CLOSE":
                lines.append(f"  • ЗАТВОРЕНО {symbol} (край на дневния прозорец)")
            else:
                lines.append(f"  • [{label}] КУПЕНО {qty} x {symbol} @ ~{price:.2f} (SL -{sl*100:.0f}% / TP +{tp*100:.0f}%)")
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
