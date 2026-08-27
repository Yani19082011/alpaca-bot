#!/usr/bin/env python3
"""
Alpaca Paper Trading Bot — hourly runner, ЕКСПЕРИМЕНТ с 3 ротиращи се
day-trading стратегии.

Изпълнява се от GitHub Actions (безплатен cron, пълен интернет достъп) —
не от Claude, защото Claude-облачните среди нямат мрежов достъп до Alpaca.

=================== ИСТОРИЯ НА ПРОМЕНИТЕ (най-новото най-долу) ===================
По-рано ботът въртеше 5 различни стратегии едновременно (blue-chip, penny,
ai-longterm, ai-daytrade, sp500-longterm). После, по изрично желание, беше
преминат към САМО day trading (3 ротиращи се стратегии, виж по-долу).

После, по НОВА изрична молба, 4-те легаси стратегии (blue-chip, penny,
ai-longterm, sp500-longterm) бяха РЕАКТИВИРАНИ — сега пак отварят нови
позиции, паралелно с day trading системите (виж "ЛЕГАСИ СТРАТЕГИИ" по-долу).
Старата 5-та ("ai-daytrade") НЕ е реактивирана — заменена е изцяло от
по-добре обмислените 3 ротиращи се стратегии.

После, по изрична молба, "penny" престана да ползва фиксиран watchlist от
12 тикера — сега сканира ЖИВО пазара всеки run (виж "PENNY: ЖИВО СКАНИРАНЕ"
по-долу) и оценява сигнала върху каквото открие, вместо върху предварително
избрани имена.

Добавена е и 4-та day-trading "под $20" стратегия (виж по-долу) — същите 3
сигнала, приложени върху по-евтини/по-волатилни акции, с отделен risk
профил и отделен лог.

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
  NTFY_TOPIC                 (опционално — за push известия през ntfy.sh)
  DASHBOARD_PASSWORD         (опционално, но силно препоръчително — криптира status.json)
  SPIKE_STRATEGY_ENABLED     (опционално, ИЗКЛЮЧЕНО по подразбиране — виж "СПАЙК + PULLBACK" по-долу)

Изисква и пакета "cryptography" (виж стъпка "Install dependencies" в
trading-bot.yml) — единствената не-stdlib зависимост, само за AES.

=================== "ПОД $20" DAY TRADING (винаги активна) ===================
Същите 3 сигнала (momentum/reversal/breakout — каквато е "днешната" активна
ротационна стратегия) се прилагат и върху watchlist от по-евтини, по-волатилни
акции (CHEAP_WATCHLIST) — отделен капиталов "джоб", отделни (по-широки) risk
параметри, отделен лог ("cheap_log"), за да не разваля честното сравнение на
трите горе. Same day-trading прозорец и принудително затваряне. ВАЖНО: списъкът
е избран по историческа цена под $20, но кодът ВИНАГИ проверява живата цена
(CHEAP_MAX_PRICE) от snapshot-а преди да купи — тикер над $20 се прескача
автоматично, без грешка.

=================== ЛЕГАСИ СТРАТЕГИИ (реактивирани, работят паралелно) ===================
blue-chip, penny, ai-longterm и sp500-longterm пак отварят нови позиции (виж
LEGACY_STRATEGIES). За разлика от day trading, тук НЯМА принудително
затваряне — позицията се държи с дни/седмици, докато не удари собствения си
Stop-loss/Take-profit (управляван сървърно от Alpaca). blue-chip, ai-longterm
и sp500-longterm пазят същите фиксирани watchlist-ове както преди пивота към
day trading (виж README.md).

=================== PENNY: ЖИВО СКАНИРАНЕ (без фиксиран watchlist) ===================
По изрична молба "penny" вече НЕ е ограничена до предварително избрани 12
тикера — на всеки run сама открива кандидати чрез Alpaca-ия market-wide
screener (get_penny_candidates): комбинация от "топ gainers" (движение) и
"most actives" (обем), т.е. каквото реално се движи/търгува в момента, а не
статичен списък. Тъй като по този начин кандидатите могат да са буквално
кои да е акции, PENNY_MAX_PRICE (<$5) и минимален дневен обем в долари
(PENNY_MIN_DOLLAR_VOLUME) се проверяват ЖИВО за всеки кандидат, преди
сигналът изобщо да се оцени — това е същият принцип на самокорекция, който
CHEAP_MAX_PRICE ползва за "под $20" добавката. Ако screener endpoint-ите не
са достъпни на текущия план/акаунт, сканирането просто се пропуска този
run, без грешка (същото поведение като при "Спайк + pullback"). Отворени
penny позиции се броят по client_order_id префикс ("penny-"), НЕ по
членство в watchlist — иначе позиция, купена от кандидат, който вече не е
"топ" на следващия run, би "изчезнала" от преброяването.

=================== СПАЙК + PULLBACK (опционална, РЪЧНО активирана) ===================
Отделна, много по-рискова 4-та стратегия — НЕ участва в честното сравнение
на трите по-горе. Гони акции, скочили рязко (+100%+ за деня спрямо вчера)
— най-честата причина е новина/спиране-и-възобновяване на търговия (halt)
при малки/low-float компании. Купува едва след лек pullback от дневния
връх + индикатор, че pullback-ът спира. Пълните детайли и рисковете са в
коментарите над SPIKE_* константите по-долу — прочети ги, преди да я
включиш. Изключена е по подразбиране; включва се само с GitHub Secret
SPIKE_STRATEGY_ENABLED = true (виж README.md).
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


# ==================== "Под $20" day trading — 4-та добавка към ротацията ====================
# По изрична молба: същите 3 сигнала (momentum/reversal/breakout, каквато е "днешната"
# активна стратегия) се прилагат и върху по-евтини, по-волатилни акции — отделен "капиталов
# джоб", отделни risk параметри, отделен лог (за да не разваля честното сравнение по-горе).
#
# ВАЖНО за списъка по-долу: избрани са ликвидни, познати имена, които ИСТОРИЧЕСКИ са се
# търгували под $20 — но не мога да гарантирам, че точно днес всяко от тях е под $20 (борсите
# се движат, а познанията ми са отпреди повече от година). Затова кодът винаги проверява
# ЖИВАТА цена от snapshot-а (CHEAP_MAX_PRICE) преди да купи — ако някой тикер вече е над $20,
# просто се прескача автоматично, без грешка.
CHEAP_WATCHLIST = [
    "SOFI", "F", "SIRI", "PBR", "VALE", "GOLD", "KGC", "CCL", "WBD", "SNAP",
    "IQ", "GRAB", "BBD", "RIG", "SWN",
]
CHEAP_MAX_PRICE = 20.0
CHEAP_MAX_POSITIONS = 2
CHEAP_POSITION_PCT = 0.05
CHEAP_STOP_LOSS_PCT = 0.03
CHEAP_TAKE_PROFIT_PCT = 0.06
CHEAP_MIN_DOLLAR_VOLUME = 5_000_000
CHEAP_LOG_MAX_ENTRIES = 180


# ==================== Легаси "swing/дългосрочни" стратегии — РЕАКТИВИРАНИ по молба ====================
# По-рано (при пивота към day trading) тези 4 спряха да отварят нови позиции. По изрична
# молба сега пак работят — паралелно с day trading системите. За разлика от day trading,
# тук НЯМА принудително затваряне в края на деня — позицията се държи с дни/седмици, докато
# не удари собствения си Stop-loss/Take-profit (Alpaca го управлява сървърно, независимо от
# този код). Списъците и параметрите са същите, които бяха документирани в README.md.
#
# "ai-daytrade" (старата 5-та стратегия) НЕ е реактивирана — тя беше буквално заменена от
# по-добре обмислените 3 ротиращи се day-trade стратегии по-горе, връщането ѝ би било просто
# по-груба версия на нещо, което вече правим по-добре.
BLUE_CHIP_WATCHLIST = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
# "penny" няма повече фиксиран watchlist — виж get_penny_candidates() и
# докстринга "PENNY: ЖИВО СКАНИРАНЕ" по-горе.
AI_LT_WATCHLIST = ["PLTR", "AMD", "AVGO", "SMCI", "CRWD", "SNOW", "ARM", "MRVL", "ANET", "MU", "ORCL"]
SP500_LT_WATCHLIST = ["JPM", "JNJ", "PG", "KO", "XOM", "CVX", "HD", "WMT", "UNH", "V", "MA", "DIS", "PEP", "COST", "MCD", "LLY"]

BLUE_CHIP_POSITION_PCT, BLUE_CHIP_STOP_LOSS_PCT, BLUE_CHIP_TAKE_PROFIT_PCT, BLUE_CHIP_MAX_POSITIONS = 0.10, 0.03, 0.06, 3
PENNY_POSITION_PCT, PENNY_STOP_LOSS_PCT, PENNY_TAKE_PROFIT_PCT, PENNY_MAX_POSITIONS = 0.03, 0.10, 0.20, 2
AI_LT_POSITION_PCT, AI_LT_STOP_LOSS_PCT, AI_LT_TAKE_PROFIT_PCT, AI_LT_MAX_POSITIONS = 0.08, 0.20, 0.20, 3
SP500_LT_POSITION_PCT, SP500_LT_STOP_LOSS_PCT, SP500_LT_TAKE_PROFIT_PCT, SP500_LT_MAX_POSITIONS = 0.06, 0.15, 0.20, 5

PENNY_BREAKOUT_LOOKBACK_DAYS = 20   # "20-дневен breakout"
PENNY_VOLUME_MULTIPLIER = 1.5       # днешният обем трябва да е поне 1.5x средния за периода
PENNY_MAX_PRICE = 5.0               # "penny stock" прагът — проверява се ЖИВО от snapshot-а
PENNY_MIN_DOLLAR_VOLUME = 1_000_000 # минимална дневна ликвидност в долари, за да не купуваме "мъртви" тикери
PENNY_CANDIDATE_SCAN_TOP = 25       # колко имена да вземем от всеки screener endpoint (movers/most-actives)
GOLDEN_CROSS_FAST, GOLDEN_CROSS_SLOW = 50, 200   # SMA50 > SMA200 ("златен кръст")
BLUE_CHIP_FAST, BLUE_CHIP_SLOW = 10, 30          # SMA(10) > SMA(30)


# ==================== "Спайк + pullback" — опортюнистична, РЪЧНО активирана стратегия ====================
# ВНИМАНИЕ, прочети преди да я включиш: гони акции, скочили рязко (+100%+ за деня) — най-честата
# причина за такъв скок е новина/спиране-и-възобновяване на търговията (halt) при малки/low-float
# компании, или т.нар. "late trend day" резки нови. Няма официален "тази акция е спряна" флаг в
# безплатните данни, които ботът ползва — затова заместваме идеята с ПРОВЕРИМ показател: рязък %
# скок спрямо вчерашното затваряне + голям обем. Купуваме едва след лек pullback от дневния връх
# (не купуваме на самия връх), и само след индикатор, че pullback-ът спира (цената вече се е
# отдръпнала над дъното му) — same логика като "Отскок" стратегията по-горе, приложена тук.
#
# ТОВА Е ОТДЕЛНА, МНОГО ПО-РИСКОВА СТРАТЕГИЯ от трите ротационни — затова НЕ участва в честното
# им сравнение (отделен лог, отделен client_order_id префикс "spike-") и има СВОИ, по-широки risk
# параметри (по-малка позиция, по-широк Stop-loss/Take-profit — волатилността тук е несравнимо
# по-висока, тесните -2%/+4% нива на другите 3 биха я извадили от позицията почти веднага от
# нормален шум).
#
# ИЗКЛЮЧЕНА Е ПО ПОДРАЗБИРАНЕ. Включва се само с GitHub Secret SPIKE_STRATEGY_ENABLED = true —
# без да се пипа никакъв код повторно. Ползва Alpaca screener endpoint-а "movers" (топ gainers) —
# той може да НЕ е наличен на всеки план/акаунт; ако не е достъпен, ботът просто пропуска
# сканирането този run (не гърми), продължава нормално с другите 3 стратегии.
SPIKE_ENABLED = os.environ.get("SPIKE_STRATEGY_ENABLED", "").strip().lower() in ("1", "true", "yes")
SPIKE_MIN_MOVE_PCT = 1.00          # поне +100% спрямо вчерашното затваряне
SPIKE_MAX_MOVE_PCT = 20.0          # таван — прескачаме съмнителни/грешни данни (напр. +2000%)
SPIKE_MIN_PRICE = 1.00             # без под-доларови тикери (обикновено нетъргуеми/шум)
SPIKE_MIN_DOLLAR_VOLUME = 3_000_000
SPIKE_PULLBACK_MIN_PCT = 0.08      # поне -8% от дневния връх ("лек pullback", не купуваме на върха)
SPIKE_PULLBACK_MAX_PCT = 0.30      # не повече от -30% от върха (иначе е обрат, не pullback)
SPIKE_CUSHION_ABOVE_LOW_PCT = 0.03 # цената трябва да е поне 3% над дъното на pullback-а (спира да пада)
SPIKE_POSITION_PCT = 0.03          # 3% от капитала — наполовина на другите стратегии
SPIKE_STOP_LOSS_PCT = 0.10         # -10% (много по-широк от -2% — тук е нормално да люлее силно)
SPIKE_TAKE_PROFIT_PCT = 0.20       # +20%
SPIKE_MAX_POSITIONS = 1            # максимум 1 отворена спайк-позиция едновременно
SPIKE_SCAN_TOP = 20                # колко "most active gainers" да провери от screener-а
SPIKE_LOG_MAX_ENTRIES = 180


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


def get_recent_orders_for_symbol(symbol, limit=50):
    """За разлика от get_orders_for_symbol_today — НЕ филтрира по дата. Нужно е
    за легаси (не-intraday) стратегиите, чиито позиции може да са отворени
    преди дни/седмици — за да разпознаем на коя стратегия принадлежи дадена
    вече отворена позиция, трябва да видим и старите ѝ поръчки, не само днешните."""
    return _get(f"{TRADING_BASE}/v2/orders?status=all&symbols={symbol}&limit={limit}")


def get_open_orders_for_symbol(symbol):
    return _get(f"{TRADING_BASE}/v2/orders?status=open&symbols={symbol}&limit=50")


def cancel_order(order_id):
    return _delete(f"{TRADING_BASE}/v2/orders/{order_id}")


def close_position_market(symbol):
    return _delete(f"{TRADING_BASE}/v2/positions/{symbol}")


def get_snapshot(symbol):
    return _get(f"{DATA_BASE}/v2/stocks/{symbol}/snapshot?feed=iex")


def get_daily_bars(symbol, limit=210):
    """Дневни свещи (за SMA изчисления при легаси стратегиите). limit=210 дава
    достатъчен буфер за SMA(200) дори при почивни дни/дупки в данните."""
    data = _get(f"{DATA_BASE}/v2/stocks/{symbol}/bars?timeframe=1Day&limit={limit}&feed=iex&adjustment=raw")
    return data.get("bars", []) if isinstance(data, dict) else []


def get_market_movers(top=20):
    """Screener endpoint — топ 'gainers' в момента (най-близкото до 'халт/скочи рязко',
    достъпно без официален halt флаг). Ако endpoint-ът не е наличен на текущия план/
    акаунт (403/404/друга грешка), просто връщаме празен списък — ботът продължава
    нормално, само spike сканирането пропуска този run."""
    try:
        data = _get(f"{DATA_BASE}/v1beta1/screener/stocks/movers?top={top}")
    except error.HTTPError as e:
        print(f"[spike] Screener endpoint недостъпен (HTTP {e.code}) — прескачам market-wide сканиране този run.")
        return []
    except Exception as e:
        print(f"[spike] Неуспешно четене на movers: {e}")
        return []
    gainers = data.get("gainers", []) if isinstance(data, dict) else []
    symbols = []
    for g in gainers:
        sym = g.get("symbol") if isinstance(g, dict) else None
        if sym:
            symbols.append(sym)
    return symbols


def get_most_active_symbols(top=25):
    """Screener endpoint — топ 'most active' по обем в момента. Ползва се от
    penny-сканирането (get_penny_candidates), за да намери каквото реално се
    търгува активно днес, вместо фиксиран списък. Същото graceful-degrade
    поведение като get_market_movers — при недостъпен endpoint връщаме []."""
    try:
        data = _get(f"{DATA_BASE}/v1beta1/screener/stocks/most-actives?top={top}&by=volume")
    except error.HTTPError as e:
        print(f"[penny] Screener (most-actives) недостъпен (HTTP {e.code}) — прескачам живото сканиране този run.")
        return []
    except Exception as e:
        print(f"[penny] Неуспешно четене на most-actives: {e}")
        return []
    actives = data.get("most_actives", []) if isinstance(data, dict) else []
    symbols = []
    for a in actives:
        sym = a.get("symbol") if isinstance(a, dict) else None
        if sym:
            symbols.append(sym)
    return symbols


def get_penny_candidates():
    """Комбинира 'топ gainers' + 'most actives' в един дедупликиран списък
    кандидати за живото penny-сканиране — каквото реално се движи/търгува в
    момента на пазара, вместо фиксирани 12 тикера. Ако и двата screener
    endpoint-а са недостъпни, връща [] и penny сканирането просто се
    пропуска този run (без грешка) — същия принцип като при спайк
    стратегията."""
    seen, candidates = set(), []
    for sym in get_market_movers(top=PENNY_CANDIDATE_SCAN_TOP) + get_most_active_symbols(top=PENNY_CANDIDATE_SCAN_TOP):
        if sym not in seen:
            seen.add(sym)
            candidates.append(sym)
    return candidates


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


def _build_trades_by_coid_prefix(today_orders, prefix):
    """Общ хелпър: възстановява РЕАЛНИТЕ покупки/продажби за деня директно
    от поръчките в Alpaca (а не от моментна снимка на unrealized_pl) — така
    хващаме коректно и случаите, в които Stop-loss/Take-profit се е
    задействал сам по средата на деня (преди принудителното затваряне).
    Връща (trades, realized_pl_total, closed_count). Ползва се и от
    build_daytrade_trades, и от build_spike_trades."""
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


def build_daytrade_trades(today_orders, active_strategy_key):
    return _build_trades_by_coid_prefix(today_orders, f"daytrade-{active_strategy_key}-")


def build_spike_trades(today_orders):
    return _build_trades_by_coid_prefix(today_orders, "spike-")


def build_cheap_trades(today_orders):
    return _build_trades_by_coid_prefix(today_orders, "cheap-")


def _load_previous_log_field(field_name):
    """Общ хелпър — чете (и декриптира, ако трябва) ПРЕДИШНИЯ status.json,
    само за да извади един лог масив по име. Ползва се и от spike_log, и от
    cheap_log — за да продължат историята си между run-овете."""
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
        return raw.get(field_name, []) if isinstance(raw, dict) else []
    except Exception as e:
        print(f"[{field_name}] Неуспешно четене на предишен log: {e}")
        return []


def load_previous_spike_log():
    return _load_previous_log_field("spike_log")


def load_previous_cheap_log():
    return _load_previous_log_field("cheap_log")


def _upsert_simple_log(log, date_str, trades, realized_pl, trades_closed, max_entries):
    entry = {
        "date": date_str,
        "realized_pl": round(realized_pl, 2),
        "trades_closed": trades_closed,
        "trades": trades or [],
    }
    log = [e for e in log if e.get("date") != date_str]
    log.append(entry)
    log.sort(key=lambda e: e.get("date", ""))
    return log[-max_entries:]


def upsert_spike_log(log, date_str, trades, realized_pl, trades_closed):
    return _upsert_simple_log(log, date_str, trades, realized_pl, trades_closed, SPIKE_LOG_MAX_ENTRIES)


def upsert_cheap_log(log, date_str, trades, realized_pl, trades_closed):
    return _upsert_simple_log(log, date_str, trades, realized_pl, trades_closed, CHEAP_LOG_MAX_ENTRIES)


# ---------------- Status snapshot (за статичното табло) ----------------

def write_status_snapshot(clock, account, positions, orders, daytrade_log=None, today_strategy=None, spike_log=None, cheap_log=None):
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
            "spike_strategy_enabled": SPIKE_ENABLED,
            "spike_log": spike_log or [],
            "cheap_log": cheap_log or [],
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


# ---------------- Легаси сигнали (SMA / breakout — реактивирани стратегии) ----------------

def sma(closes, period):
    """Проста пълзяща средна на последните `period` стойности (най-новата — последна)."""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def golden_cross_signal(bars):
    """SMA(50) > SMA(200) — "златен кръст", класически дългосрочен uptrend сигнал.
    Ползва се от ai-longterm и sp500-longterm."""
    closes = [b.get("c") for b in bars if b.get("c") is not None]
    fast_sma = sma(closes, GOLDEN_CROSS_FAST)
    slow_sma = sma(closes, GOLDEN_CROSS_SLOW)
    if fast_sma is None or slow_sma is None:
        return False
    return fast_sma > slow_sma


def blue_chip_signal(bars):
    """SMA(10) > SMA(30) — по-кратък/по-отзивчив кръст за ликвидните блу-чипове."""
    closes = [b.get("c") for b in bars if b.get("c") is not None]
    fast_sma = sma(closes, BLUE_CHIP_FAST)
    slow_sma = sma(closes, BLUE_CHIP_SLOW)
    if fast_sma is None or slow_sma is None:
        return False
    return fast_sma > slow_sma


def penny_signal(bars, snapshot):
    """20-дневен breakout (текущата цена пробива над 20-дневния максимум) +
    обем-потвърждение (днешният обем е поне 1.5x средния за периода).
    Кандидатите идват от живо сканиране (get_penny_candidates), не от
    фиксиран watchlist, затова тук ЖИВО се проверяват и PENNY_MAX_PRICE
    (<$5) и минимална дневна ликвидност (PENNY_MIN_DOLLAR_VOLUME) —
    иначе screener-ът би могъл да предложи каквото и да е, не само
    истински penny stocks."""
    if len(bars) < PENNY_BREAKOUT_LOOKBACK_DAYS:
        return False
    recent = bars[-PENNY_BREAKOUT_LOOKBACK_DAYS:]
    highs = [b.get("h") for b in recent if b.get("h") is not None]
    volumes = [b.get("v") for b in recent if b.get("v") is not None]
    if not highs or not volumes:
        return False
    try:
        price = snapshot["latestTrade"]["p"]
        today_volume = snapshot["dailyBar"]["v"]
    except (KeyError, TypeError):
        return False
    if not price or price > PENNY_MAX_PRICE:
        return False  # вече не е "penny" — прескачаме тихо
    if today_volume * price < PENNY_MIN_DOLLAR_VOLUME:
        return False  # твърде неликвидно
    breakout_level = max(highs)
    avg_volume = sum(volumes) / len(volumes)
    return price > breakout_level and avg_volume > 0 and today_volume > avg_volume * PENNY_VOLUME_MULTIPLIER


def legacy_signal(strategy_key, bars, snapshot):
    if strategy_key == "blue-chip":
        return blue_chip_signal(bars)
    if strategy_key == "penny":
        return penny_signal(bars, snapshot)
    if strategy_key in ("ai-longterm", "sp500-longterm"):
        return golden_cross_signal(bars)
    return False


LEGACY_STRATEGIES = [
    {"key": "blue-chip", "label": "Blue-chip", "watchlist": BLUE_CHIP_WATCHLIST,
     "position_pct": BLUE_CHIP_POSITION_PCT, "stop_loss_pct": BLUE_CHIP_STOP_LOSS_PCT,
     "take_profit_pct": BLUE_CHIP_TAKE_PROFIT_PCT, "max_positions": BLUE_CHIP_MAX_POSITIONS,
     "needs_snapshot": False},
    # "watchlist": None — penny няма фиксиран списък, кандидатите идват ЖИВО
    # всеки run от get_penny_candidates() (виж run_legacy_entries по-долу).
    {"key": "penny", "label": "Penny stocks", "watchlist": None,
     "position_pct": PENNY_POSITION_PCT, "stop_loss_pct": PENNY_STOP_LOSS_PCT,
     "take_profit_pct": PENNY_TAKE_PROFIT_PCT, "max_positions": PENNY_MAX_POSITIONS,
     "needs_snapshot": True},
    {"key": "ai-longterm", "label": "AI дългосрочно", "watchlist": AI_LT_WATCHLIST,
     "position_pct": AI_LT_POSITION_PCT, "stop_loss_pct": AI_LT_STOP_LOSS_PCT,
     "take_profit_pct": AI_LT_TAKE_PROFIT_PCT, "max_positions": AI_LT_MAX_POSITIONS,
     "needs_snapshot": False},
    {"key": "sp500-longterm", "label": "S&P 500 дългосрочно", "watchlist": SP500_LT_WATCHLIST,
     "position_pct": SP500_LT_POSITION_PCT, "stop_loss_pct": SP500_LT_STOP_LOSS_PCT,
     "take_profit_pct": SP500_LT_TAKE_PROFIT_PCT, "max_positions": SP500_LT_MAX_POSITIONS,
     "needs_snapshot": False},
]


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


# ---------------- Легаси стратегии: вход (БЕЗ принудително затваряне — swing, не intraday) ----------------

def count_open_legacy_positions(held_symbols, prefix):
    """Брои по client_order_id префикс, върху ВСИЧКИ държани символи — НЕ
    само върху watchlist. Важно за 'penny': кандидатите идват от живо
    сканиране, различно всеки run, затова позиция, купена вчера от символ,
    който днес вече не е сред 'топ' кандидатите, пак трябва да се преброи."""
    count = 0
    for symbol in held_symbols:
        try:
            orders = get_recent_orders_for_symbol(symbol)
        except error.HTTPError:
            continue
        if any(o.get("client_order_id", "").startswith(prefix) and o.get("status") == "filled" for o in orders):
            count += 1
    return count


def run_legacy_entries(strategy, equity, held_symbols, traded_today, today_str):
    trades_made, errors = [], []
    prefix = f"{strategy['key']}-"
    slots_free = strategy["max_positions"] - count_open_legacy_positions(held_symbols, prefix)
    if slots_free <= 0:
        return trades_made, errors

    if strategy["watchlist"] is None:
        # "penny" — живо сканиране вместо фиксиран watchlist (виж докстринга
        # "PENNY: ЖИВО СКАНИРАНЕ" горе). Ако screener-ите са недостъпни,
        # get_penny_candidates() връща [] и цикълът просто не прави нищо
        # този run — без грешка.
        candidate_symbols = get_penny_candidates()
    else:
        candidate_symbols = strategy["watchlist"]

    for symbol in candidate_symbols:
        if len(trades_made) >= slots_free:
            break
        if symbol in held_symbols or symbol in traded_today:
            continue  # вече държан/търгуван днес (от друга стратегия или другаде) — прескачаме
        try:
            bars = get_daily_bars(symbol)
        except error.HTTPError as e:
            errors.append(f"[{strategy['key']}] {symbol}: грешка при исторически данни ({e.read().decode()[:150]})")
            continue

        snap = None
        if strategy["needs_snapshot"]:
            try:
                snap = get_snapshot(symbol)
            except error.HTTPError as e:
                errors.append(f"[{strategy['key']}] {symbol}: грешка при snapshot ({e.read().decode()[:150]})")
                continue

        if not legacy_signal(strategy["key"], bars, snap):
            continue

        try:
            current_price = snap["latestTrade"]["p"] if snap else bars[-1]["c"]
        except (KeyError, TypeError, IndexError):
            continue
        if not current_price:
            continue

        budget = equity * strategy["position_pct"]
        qty = int(budget // current_price)
        if qty < 1:
            continue
        coid = f"{prefix}{symbol}-{today_str}"
        try:
            place_entry_order(symbol, qty, current_price, strategy["stop_loss_pct"], strategy["take_profit_pct"], client_order_id=coid)
            trades_made.append((strategy["label"], symbol, qty, current_price, strategy["stop_loss_pct"], strategy["take_profit_pct"]))
            print(
                f"[{strategy['key']}] КУПЕНО: {qty} x {symbol} @ ~{current_price:.2f} "
                f"(SL -{strategy['stop_loss_pct']*100:.0f}% / TP +{strategy['take_profit_pct']*100:.0f}%) — "
                f"държи се докато не удари SL/TP (не е intraday)"
            )
        except error.HTTPError as e:
            errors.append(f"[{strategy['key']}] {symbol}: грешка при поръчка ({e.read().decode()[:150]})")

    return trades_made, errors


# ---------------- "Под $20" day trading — вход и принудително затваряне ----------------

def count_open_cheap_positions(held_symbols):
    count = 0
    for symbol in held_symbols & set(CHEAP_WATCHLIST):
        try:
            orders = get_orders_for_symbol_today(symbol)
        except error.HTTPError:
            continue
        if any(o.get("client_order_id", "").startswith("cheap-") and o.get("status") == "filled" for o in orders):
            count += 1
    return count


def run_cheap_entries(strategy, equity, held_symbols, traded_today, today_str):
    """Прилага същия сигнал като "днешната" ротационна стратегия (momentum/
    reversal/breakout), но върху watchlist от по-евтини акции + собствени,
    по-широки risk параметри. CHEAP_MAX_PRICE се проверява ЖИВО от snapshot-а
    — ако тикер вече не е под $20, просто се прескача, без грешка."""
    trades_made, errors = [], []
    slots_free = CHEAP_MAX_POSITIONS - count_open_cheap_positions(held_symbols)
    if slots_free <= 0:
        return trades_made, errors

    for symbol in CHEAP_WATCHLIST:
        if len(trades_made) >= slots_free:
            break
        if symbol in held_symbols or symbol in traded_today:
            continue
        try:
            snap = get_snapshot(symbol)
        except error.HTTPError as e:
            errors.append(f"[cheap] {symbol}: грешка при snapshot ({e.read().decode()[:150]})")
            continue
        try:
            current_price = snap["latestTrade"]["p"]
        except (KeyError, TypeError):
            continue
        if not current_price or current_price > CHEAP_MAX_PRICE:
            continue  # вече не е "под $20" — прескачаме тихо
        try:
            today_volume = snap["dailyBar"]["v"]
        except (KeyError, TypeError):
            continue
        if today_volume * current_price < CHEAP_MIN_DOLLAR_VOLUME:
            continue
        if not strategy["signal_fn"](snap):
            continue
        budget = equity * CHEAP_POSITION_PCT
        qty = int(budget // current_price)
        if qty < 1:
            continue
        coid = f"cheap-{symbol}-{today_str}"
        try:
            place_entry_order(symbol, qty, current_price, CHEAP_STOP_LOSS_PCT, CHEAP_TAKE_PROFIT_PCT, client_order_id=coid)
            trades_made.append(("Под $20 💵", symbol, qty, current_price, CHEAP_STOP_LOSS_PCT, CHEAP_TAKE_PROFIT_PCT))
            print(
                f"[cheap] КУПЕНО: {qty} x {symbol} @ ~{current_price:.2f} "
                f"(SL -{CHEAP_STOP_LOSS_PCT*100:.0f}% / TP +{CHEAP_TAKE_PROFIT_PCT*100:.0f}%) "
                f"— ще се затвори до края на прозореца"
            )
        except error.HTTPError as e:
            errors.append(f"[cheap] {symbol}: грешка при поръчка ({e.read().decode()[:150]})")

    return trades_made, errors


def force_close_cheap_positions(held_symbols, positions_by_symbol):
    closed, errors = [], []
    for symbol in held_symbols & set(CHEAP_WATCHLIST):
        try:
            orders = get_orders_for_symbol_today(symbol)
        except error.HTTPError as e:
            errors.append(f"[cheap] {symbol}: грешка при проверка ({e.read().decode()[:150]})")
            continue
        is_cheap = any(
            o.get("client_order_id", "").startswith("cheap-") and o.get("status") == "filled"
            for o in orders
        )
        if not is_cheap:
            continue
        try:
            for o in get_open_orders_for_symbol(symbol):
                try:
                    cancel_order(o["id"])
                except error.HTTPError:
                    pass
            close_position_market(symbol)
            closed.append(symbol)
            print(f"[cheap] ЗАТВОРЕНО {symbol} (край на дневния прозорец)")
        except error.HTTPError as e:
            errors.append(f"[cheap] {symbol}: грешка при затваряне ({e.read().decode()[:150]})")
    return closed, errors


# ---------------- "Спайк + pullback" — сигнал и вход/изход ----------------

def spike_pullback_signal(snapshot):
    """Опортюнистичен сигнал: рязък % скок спрямо вчерашното затваряне
    (заместител на "халт/resume", защото няма официален halt флаг в
    безплатните данни) + лек pullback от дневния връх (не купуваме на
    самия връх) + индикатор, че pullback-ът спира (cushion над дъното му
    — същата логика като "Отскок" стратегията) + прилична ликвидност."""
    try:
        price = snapshot["latestTrade"]["p"]
        today_high = snapshot["dailyBar"]["h"]
        today_low = snapshot["dailyBar"]["l"]
        today_volume = snapshot["dailyBar"]["v"]
        prev_close = snapshot["prevDailyBar"]["c"]
    except (KeyError, TypeError):
        return False
    if not price or not today_high or not today_low or not prev_close:
        return False
    if price < SPIKE_MIN_PRICE:
        return False

    move_from_prev_close = (price - prev_close) / prev_close
    if not (SPIKE_MIN_MOVE_PCT <= move_from_prev_close <= SPIKE_MAX_MOVE_PCT):
        return False

    pullback_from_high = (today_high - price) / today_high
    if not (SPIKE_PULLBACK_MIN_PCT <= pullback_from_high <= SPIKE_PULLBACK_MAX_PCT):
        return False

    cushion_above_low = (price - today_low) / today_low
    if cushion_above_low < SPIKE_CUSHION_ABOVE_LOW_PCT:
        return False

    dollar_volume = today_volume * price
    if dollar_volume < SPIKE_MIN_DOLLAR_VOLUME:
        return False

    return True


def count_open_spike_positions(held_symbols):
    count = 0
    for symbol in held_symbols:
        try:
            orders = get_orders_for_symbol_today(symbol)
        except error.HTTPError:
            continue
        if any(o.get("client_order_id", "").startswith("spike-") and o.get("status") == "filled" for o in orders):
            count += 1
    return count


def run_spike_entries(equity, held_symbols, traded_today, today_str):
    """Сканира текущите "most active gainers" (Alpaca screener) за
    кандидати за spike-pullback сигнала. Ако screener endpoint-ът не е
    наличен на текущия план, get_market_movers връща празен списък и
    просто не се търгува нищо тук този run — без грешка."""
    trades_made, errors = [], []
    slots_free = SPIKE_MAX_POSITIONS - count_open_spike_positions(held_symbols)
    if slots_free <= 0:
        return trades_made, errors

    candidates = get_market_movers(SPIKE_SCAN_TOP)
    for symbol in candidates:
        if len(trades_made) >= slots_free:
            break
        if symbol in held_symbols or symbol in traded_today:
            continue  # вече държан/търгуван днес (от друга стратегия или другаде) — прескачаме
        try:
            snap = get_snapshot(symbol)
        except error.HTTPError as e:
            errors.append(f"[spike] {symbol}: грешка при snapshot ({e.read().decode()[:150]})")
            continue
        if not spike_pullback_signal(snap):
            continue
        current_price = snap["latestTrade"]["p"]
        budget = equity * SPIKE_POSITION_PCT
        qty = int(budget // current_price)
        if qty < 1:
            continue
        coid = f"spike-{symbol}-{today_str}"
        try:
            place_entry_order(symbol, qty, current_price, SPIKE_STOP_LOSS_PCT, SPIKE_TAKE_PROFIT_PCT, client_order_id=coid)
            trades_made.append(("Спайк+pullback 💥", symbol, qty, current_price, SPIKE_STOP_LOSS_PCT, SPIKE_TAKE_PROFIT_PCT))
            print(
                f"[spike] КУПЕНО: {qty} x {symbol} @ ~{current_price:.2f} "
                f"(SL -{SPIKE_STOP_LOSS_PCT*100:.0f}% / TP +{SPIKE_TAKE_PROFIT_PCT*100:.0f}%) "
                f"— ще се затвори до края на прозореца"
            )
        except error.HTTPError as e:
            errors.append(f"[spike] {symbol}: грешка при поръчка ({e.read().decode()[:150]})")

    return trades_made, errors


def force_close_spike_positions(held_symbols, positions_by_symbol):
    """Затваря всички отворени днешни spike позиции — задължително до
    края на дневния прозорец, също като другите 3 стратегии (никога не
    се държи позиция за нощта)."""
    closed, errors = [], []
    for symbol in list(held_symbols):
        try:
            orders = get_orders_for_symbol_today(symbol)
        except error.HTTPError as e:
            errors.append(f"[spike] {symbol}: грешка при проверка ({e.read().decode()[:150]})")
            continue
        is_spike = any(
            o.get("client_order_id", "").startswith("spike-") and o.get("status") == "filled"
            for o in orders
        )
        if not is_spike:
            continue
        try:
            for o in get_open_orders_for_symbol(symbol):
                try:
                    cancel_order(o["id"])
                except error.HTTPError:
                    pass
            close_position_market(symbol)
            closed.append(symbol)
            print(f"[spike] ЗАТВОРЕНО {symbol} (край на дневния прозорец)")
        except error.HTTPError as e:
            errors.append(f"[spike] {symbol}: грешка при затваряне ({e.read().decode()[:150]})")
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
    spike_log = load_previous_spike_log()
    cheap_log = load_previous_cheap_log()

    now = parse_alpaca_ts(clock["timestamp"])
    sofia_now = now.astimezone(SOFIA_TZ)
    active_strategy = todays_strategy(sofia_now)
    active_strategy_info = {"key": active_strategy["key"], "label": active_strategy["label"]}

    write_status_snapshot(
        clock, account, positions, today_orders,
        daytrade_log=daytrade_log, today_strategy=active_strategy_info, spike_log=spike_log, cheap_log=cheap_log,
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
        f"стратегия днес: {active_strategy['label']} | window: {in_window} | force-close: {should_force_close} | "
        f"spike: {'вкл.' if SPIKE_ENABLED else 'изкл.'}"
    )

    all_trades, all_errors = [], []

    # 1) Задължително първо: затваряме просрочени day-trade (и "под $20", и ако е
    #    включена — spike) позиции от днес. Легаси swing стратегиите НЕ се пипат тук.
    if should_force_close:
        closed, errs = force_close_daytrade_positions(held_symbols, positions_by_symbol)
        for s in closed:
            all_trades.append(("daytrade-CLOSE", s, None, None, None, None))
        all_errors.extend(errs)
        held_symbols -= set(closed)

        cheap_closed, cheap_close_errs = force_close_cheap_positions(held_symbols, positions_by_symbol)
        for s in cheap_closed:
            all_trades.append(("cheap-CLOSE", s, None, None, None, None))
        all_errors.extend(cheap_close_errs)
        held_symbols -= set(cheap_closed)

        if SPIKE_ENABLED:
            spike_closed, spike_close_errs = force_close_spike_positions(held_symbols, positions_by_symbol)
            for s in spike_closed:
                all_trades.append(("spike-CLOSE", s, None, None, None, None))
            all_errors.extend(spike_close_errs)
            held_symbols -= set(spike_closed)

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

        cheap_trades_today, cheap_pl, cheap_closed_count = build_cheap_trades(fresh_orders)
        if cheap_trades_today:
            cheap_log = upsert_cheap_log(cheap_log, today_str, cheap_trades_today, cheap_pl, cheap_closed_count)

        if SPIKE_ENABLED:
            spike_trades_today, spike_pl, spike_closed_count = build_spike_trades(fresh_orders)
            if spike_trades_today:
                spike_log = upsert_spike_log(spike_log, today_str, spike_trades_today, spike_pl, spike_closed_count)

    # 2) Нови входове по активната днешна стратегия — само в прозореца (day trading).
    if in_window and not should_force_close:
        trades, errors = run_daytrade_entries(active_strategy, equity, held_symbols, traded_today, today_str)
        all_trades.extend(trades)
        all_errors.extend(errors)
        held_symbols |= {t[1] for t in trades}

        cheap_trades, cheap_errors = run_cheap_entries(active_strategy, equity, held_symbols, traded_today, today_str)
        all_trades.extend(cheap_trades)
        all_errors.extend(cheap_errors)
        held_symbols |= {t[1] for t in cheap_trades}

        if SPIKE_ENABLED:
            spike_trades, spike_errors = run_spike_entries(equity, held_symbols, traded_today, today_str)
            all_trades.extend(spike_trades)
            all_errors.extend(spike_errors)
            held_symbols |= {t[1] for t in spike_trades}

    # 3) Легаси swing стратегии (blue-chip/penny/ai-longterm/sp500-longterm) — НЕ са
    #    intraday, работят докато пазарът е отворен, независимо от day-trading прозореца.
    #    Никога не се затварят принудително — държат се докато не ударят своя SL/TP.
    for strategy in LEGACY_STRATEGIES:
        trades, errors = run_legacy_entries(strategy, equity, held_symbols, traded_today, today_str)
        all_trades.extend(trades)
        all_errors.extend(errors)
        held_symbols |= {t[1] for t in trades}

    # Финална снимка — след сделките/затварянията и с обновения дневник.
    if all_trades or should_force_close:
        try:
            write_status_snapshot(
                clock, get_account(), get_positions(), get_today_orders(),
                daytrade_log=daytrade_log, today_strategy=active_strategy_info,
                spike_log=spike_log, cheap_log=cheap_log,
            )
        except error.HTTPError as e:
            print(f"[status] Неуспешно финално обновяване: {e}")

    if all_trades:
        lines = [f"🤖 Alpaca бот — {len(all_trades)} събитие(я) [{active_strategy['label']}]:"]
        for label, symbol, qty, price, sl, tp in all_trades:
            if label in ("daytrade-CLOSE", "spike-CLOSE", "cheap-CLOSE"):
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
