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
12 тикера — сканираше ЖИВО пазара всеки run и оценяваше сигнала върху
каквото открие, вместо върху предварително избрани имена.

Добавена беше и 4-та day-trading "под $20" стратегия — същите 3 сигнала,
приложени върху по-евтини/по-волатилни акции, с отделен risk профил и
отделен лог.

После, по НОВА изрична молба (голям refactor), стана следното:
  1) blue-chip/ai-longterm/sp500-longterm ("нормалните компании") вече
     имат ЕДНАКВИ Stop-loss/Take-profit: -15% / +7% за трите. Watchlist-овете
     им са значително разширени (виж "ЛЕГАСИ СТРАТЕГИИ" по-долу) — идеята е
     ботът да има повече реални компании, сред които да намери такива,
     които съвпадат с критерия на всяка стратегия, вместо да гледа само
     шепа фиксирани имена.
  2) "penny" (легаси) и "под $20" (day-trading) стратегиите бяха ПРЕМАХНАТИ
     изцяло, заедно със старата "Спайк + pullback". На тяхно място има ЕДНА
     нова, по-добре обмислена стратегия — "Halt + Пробив" (виж по-долу) —
     за акции, скочили рязко (типично след спиране/възобновяване на
     търговията).
  3) Легаси стратегиите вече имат СВОЙ дневник ("legacy_log") с реални
     затворени сделки (символ, стратегия, вход/изход, П/З) — за разлика от
     day trading, тези позиции може да се затворят по всяко време (не само
     "днес"), затова дневникът се възстановява от ПЪЛНАТА поръчкова история,
     не само от днешната. Календарът на таблото вече показва обединено
     всичко, купено/продадено на даден ден — от коя да е стратегия — не
     само 3-те ротиращи се day-trade стратегии.

После, по НОВА изрична молба, стана следното:
  1) blue-chip/ai-longterm/sp500-longterm вече имат ПОДОБРЕНИ сигнали, не
     просто голи SMA пресичания: blue_chip_signal вече изисква и SMA(10) да
     се ПОКАЧВА (кръстът да не е вече отслабващ) и цената да не е прекалено
     разтеглена над SMA(30) (не гоним екстремно движение); golden_cross_signal
     (ai-longterm/sp500-longterm) вече изисква и текущата цена да е НАД
     SMA(50) (потвърждава РЕАЛЕН тренд сега, не само исторически кръст) и
     SMA(50) да се покачва. Виж blue_chip_signal/golden_cross_signal по-долу
     за пълни детайли.
  2) Halt + Пробив вече чете кандидатите си директно от Nasdaq Trader
     (get_nasdaq_halt_candidates — официалният безплатен feed за trading
     halts, филтриран само за волатилност-halt кодове), вместо от generic
     screener — по изрична молба на потребителя. Screener-ът остава като
     fallback, ако feed-ът е недостъпен. Риск параметрите също се смениха
     по изрична молба: Stop-loss -15% / Take-profit +10% (обърнато спрямо
     преди), макс. 2 позиции (не 3), и добавен таван HALT_MAX_PRICE = $20 —
     стратегията е за penny/евтини акции, не за каквото и да е скочило.

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
  SPIKE_STRATEGY_ENABLED     (опционално, ИЗКЛЮЧЕНО по подразбиране — контролира "Halt + Пробив", виж по-долу)

Изисква и пакета "cryptography" (виж стъпка "Install dependencies" в
trading-bot.yml) — единствената не-stdlib зависимост, само за AES.

=================== ЛЕГАСИ СТРАТЕГИИ (реактивирани, работят паралелно) ===================
blue-chip, ai-longterm и sp500-longterm отварят нови позиции (виж
LEGACY_STRATEGIES). За разлика от day trading, тук НЯМА принудително
затваряне — позицията се държи с дни/седмици, докато не удари собствения си
Stop-loss/Take-profit (управляван сървърно от Alpaca, -15% / +7% и за трите
— виж по-долу защо еднакви). Watchlist-овете им са значително разширени
спрямо преди, за да имат повече реални компании, сред които да намерят
такива, отговарящи на критерия на стратегията.

Сигналите вече НЕ са голи SMA пресичания — по изрична молба са подобрени с
допълнителни потвърждения (виж blue_chip_signal/golden_cross_signal):
  • blue-chip: SMA(10) > SMA(30) КАКТО ПРЕДИ, плюс SMA(10) да СЕ ПОКАЧВА
    (сравнена с преди BLUE_CHIP_TREND_LOOKBACK_DAYS дни — кръстът да не е
    вече отслабващ) и цената да не е с повече от BLUE_CHIP_MAX_EXTENSION_PCT
    над SMA(30) (да не гоним прекалено разтеглено движение).
  • ai-longterm/sp500-longterm: SMA(50) > SMA(200) ("златен кръст") КАКТО
    ПРЕДИ, плюс текущата цена да е НАД SMA(50) (потвърждава РЕАЛЕН тренд
    сега, не просто исторически кръст, от който цената вече се е върнала
    обратно) и SMA(50) да СЕ ПОКАЧВА (сравнена с преди
    GOLDEN_CROSS_TREND_LOOKBACK_DAYS дни).

Легаси сделките (влизане И реално затваряне, каквото и да е то) се пазят в
"legacy_log" — за разлика от day trading, тук затварянето не става от самия
бот в даден прозорец, а от Alpaca-ия bracket SL/TP по всяко време, затова
дневникът се възстановява от ПЪЛНАТА поръчкова история (виж
build_roundtrip_log/get_orders_since), не само от днешната.

=================== HALT + ПРОБИВ (опционална, РЪЧНО активирана) ===================
Замества старите "penny" (легаси) + "под $20" (day-trading) + "Спайк +
pullback" стратегии — консолидирани в ЕДНА, по-добре обмислена стратегия.
Гони акции, скочили рязко (+100%+ спрямо вчерашното затваряне) — най-честата
причина е новина/спиране-и-възобновяване на търговията (halt) при малки/
low-float компании. Купува едва след:
  1) лек pullback от дневния връх (не на самия връх, вижте HALT_PULLBACK_*),
  2) РАЗПОЗНАВАЕМ БИЧИ МОДЕЛ СВЕЩ около дъното на pullback-а — истинско
     разпознаване на chук/обърнат chук/поглъщане/харами/пронизваща
     линия/утринна звезда/трима бели войници и т.н. (виж каталога от
     is_hammer/is_bullish_engulfing/... функции и
     has_bullish_stabilization_candle точно преди halt_breakout_signal —
     каталогът е изпратен директно от потребителя), не просто число,
  3) ЧИСЛОВ ПРОБИВ обратно нагоре над локалния връх, образуван СЛЕД
     pullback-а (виж halt_breakout_signal + get_intraday_bars).
Точно логиката "изчакай chук/поглъщане на дъното, после пробив нагоре", а
не просто "купи защото е зелено" — вече е РЕАЛНО разпознаване на свещи, не
приближение.

Позицията е ФИКСИРАНА сума в долари (HALT_POSITION_DOLLARS = $100), не % от
капитала — по изрична молба, за да е рискът на всяка отделна сделка малък и
предвидим, независимо от размера на акаунта. Stop-loss -15% / Take-profit
+10% (по изрична молба — лесно се сменят, виж константите), макс.
HALT_MAX_POSITIONS = 2 позиции едновременно ($200 общо). Цената се проверява
и срещу HALT_MAX_PRICE ($20 таван, по изрична молба) — стратегията е за
penny/евтини акции, не за каквото и да е скочило. За разлика от старата
"Спайк" версия, тук НЯМА принудително затваряне до края на деня — позицията
се държи докато не удари SL/TP, също като легаси стратегиите (realистично
за halt-плейове, които понякога продължават с дни).

Кандидатите ИДВАТ от Nasdaq Trader (get_nasdaq_halt_candidates —
rss.aspx?feed=tradehalts, официалният безплатен feed за trading halts на
ВСИЧКИ щатски борси, по изрична молба на потребителя), филтрирани само за
ВОЛАТИЛНОСТ-halt кодове (HALT_VOLATILITY_REASON_CODES — LUDP/LUDS/T5,
прескача регулаторни/новинарски halt-ове). FALLBACK: ако feed-ът е
временно недостъпен или няма активни волатилност-halt-ове в момента,
get_halt_candidates() пада назад към стария Alpaca screener (топ gainers +
most actives), за да не спре стратегията да работи изцяло.

Изключена е по подразбиране; включва се само с GitHub Secret
SPIKE_STRATEGY_ENABLED = true (виж README.md — името на secret-а е останало
същото, за да не се налага нов).
"""
import os
import json
import sys
import base64
import hashlib
import traceback
import xml.etree.ElementTree as ET
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


# ==================== Легаси "swing/дългосрочни" стратегии — РЕАКТИВИРАНИ по молба ====================
# По-рано (при пивота към day trading) тези спряха да отварят нови позиции. По изрична молба
# сега пак работят — паралелно с day trading системите. За разлика от day trading, тук НЯМА
# принудително затваряне в края на деня — позицията се държи с дни/седмици, докато не удари
# собствения си Stop-loss/Take-profit (Alpaca го управлява сървърно, независимо от този код).
#
# По НОВА молба: SL/TP вече са ЕДНАКВИ за трите (-15% / +7%) — вместо всяка да има собствени
# нива — и watchlist-овете са значително разширени (от ~9-16 имена на ~18-36), за да има ботът
# повече реални компании, сред които да намери такива, отговарящи на критерия на стратегията
# (SMA кръст), вместо да гледа само шепа фиксирани имена. Всяка стратегия пази собствения си
# characteristic сигнал/сектор — просто с по-широк периметър за търсене:
#   blue-chip      — ликвидни мега/large-cap, бърз тренд сигнал SMA(10) > SMA(30)
#   ai-longterm    — AI/semis/cloud-infra сектор, "златен кръст" SMA(50) > SMA(200)
#   sp500-longterm — диверсифицирани value S&P 500 сектори, същия "златен кръст"
#
# "penny" (легаси) вече НЕ съществува като отделна легаси стратегия — обединена е в новата
# "Halt + Пробив" стратегия по-долу. "ai-daytrade" (старата 5-та) също НЕ е реактивирана —
# заменена е изцяло от 3-те ротиращи се day-trade стратегии по-горе.
BLUE_CHIP_WATCHLIST = [
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
    "NFLX", "ADBE", "CRM", "CSCO", "INTC", "IBM", "QCOM", "TXN", "INTU",
]
AI_LT_WATCHLIST = [
    "PLTR", "AMD", "AVGO", "SMCI", "CRWD", "SNOW", "ARM", "MRVL", "ANET", "MU", "ORCL",
    "TSM", "ASML", "LRCX", "AMAT", "KLAC", "DELL", "PANW", "FTNT", "DDOG", "NET", "ZS",
]
SP500_LT_WATCHLIST = [
    "JPM", "JNJ", "PG", "KO", "XOM", "CVX", "HD", "WMT", "UNH", "V", "MA", "DIS",
    "PEP", "COST", "MCD", "LLY", "BAC", "WFC", "GS", "MS", "ABBV", "MRK", "PFE",
    "ABT", "TMO", "NEE", "DUK", "SO", "CAT", "DE", "BA", "UPS", "LOW", "TGT", "SBUX", "NKE",
]

# Единни SL/TP за трите "нормални компании" стратегии по изрична молба.
LEGACY_STOP_LOSS_PCT = 0.15
LEGACY_TAKE_PROFIT_PCT = 0.07

BLUE_CHIP_POSITION_PCT, BLUE_CHIP_MAX_POSITIONS = 0.10, 3
AI_LT_POSITION_PCT, AI_LT_MAX_POSITIONS = 0.08, 3
SP500_LT_POSITION_PCT, SP500_LT_MAX_POSITIONS = 0.06, 5

GOLDEN_CROSS_FAST, GOLDEN_CROSS_SLOW = 50, 200   # SMA50 > SMA200 ("златен кръст")
GOLDEN_CROSS_TREND_LOOKBACK_DAYS = 10  # SMA(50) трябва да е по-висока, отколкото преди толкова дни -- потвърждава РЕАЛЕН, не отслабващ тренд
BLUE_CHIP_FAST, BLUE_CHIP_SLOW = 10, 30          # SMA(10) > SMA(30)
BLUE_CHIP_TREND_LOOKBACK_DAYS = 5      # SMA(10) трябва да е по-висока, отколкото преди толкова дни -- кръстът да не е вече отслабващ
BLUE_CHIP_MAX_EXTENSION_PCT = 0.08     # цената не може да е с повече от 8% над SMA(30) -- не гоним прекалено разтеглено движение

LEGACY_LOG_MAX_ENTRIES = 180   # пазим последните ~6 месеца затворени легаси сделки


# ==================== "Halt + Пробив" — опционална, РЪЧНО активирана стратегия ====================
# Заменя старите "penny" (легаси) + "под $20" (day-trading) + "Спайк + pullback" — консолидирани
# в ЕДНА стратегия, по изрична молба. Гони акции, скочили рязко (+100%+ спрямо вчерашното
# затваряне) — най-честата причина е новина/спиране-и-възобновяване на търговията (halt) при
# малки/low-float компании. Няма официален "тази акция е спряна" флаг в безплатните данни —
# заместваме идеята с ПРОВЕРИМ показател: рязък % скок + голям обем.
#
# За разлика от старата "Спайк" версия, тук влизаме едва след РАЗПОЗНАТ модел свещ + ЧИСЛОВ
# ПРОБИВ, не само pullback:
#   1) лек pullback от дневния връх (HALT_PULLBACK_MIN/MAX_PCT — не купуваме на самия връх),
#   2) РАЗПОЗНАВАЕМ бичи модел свещ около дъното (chук/поглъщане/утринна звезда и т.н. —
#      виж has_bullish_stabilization_candle точно преди halt_breakout_signal),
#   3) цената пробива обратно НАД локалния връх, образуван СЛЕД pullback-а (виж
#      halt_breakout_signal + get_intraday_bars — 5-минутни свещи, за да видим КЪДЕ точно е
#      бил pullback-ът и дали вече е пробит).
#
# ФИКСИРАНА позиция от HALT_POSITION_DOLLARS долара (не % от капитала) — по изрична молба, за
# да е рискът на всяка сделка малък и предвидим. Макс. HALT_MAX_POSITIONS позиции едновременно.
# Цената се проверява и срещу HALT_MAX_PRICE ($20 таван) — фокус върху penny/евтини акции.
# НЯМА принудително затваряне до края на деня (за разлика от старата Спайк версия) — държи се
# докато не удари SL/TP, също като легаси стратегиите (halt-плейове понякога продължават с дни).
#
# Кандидатите идват от Nasdaq Trader (get_nasdaq_halt_candidates — rss.aspx?feed=tradehalts,
# официалният безплатен feed за trading halts на всички щатски борси), филтрирани само за
# волатилност-halt кодове (HALT_VOLATILITY_REASON_CODES). Ако feed-ът е недостъпен или няма
# активни volatility halt-ове в момента, get_halt_candidates() пада назад към Alpaca screener-а
# (топ gainers + most active).
#
# ИЗКЛЮЧЕНА Е ПО ПОДРАЗБИРАНЕ. Включва се само с GitHub Secret SPIKE_STRATEGY_ENABLED = true
# (името на secret-а е останало същото нарочно, за да не се налага ново качване/secret).
HALT_ENABLED = os.environ.get("SPIKE_STRATEGY_ENABLED", "").strip().lower() in ("1", "true", "yes")
HALT_MIN_MOVE_PCT = 1.00          # поне +100% спрямо вчерашното затваряне
HALT_MAX_MOVE_PCT = 20.0          # таван — прескачаме съмнителни/грешни данни (напр. +2000%)
HALT_MIN_PRICE = 0.10             # истински penny/halt имена могат да са и под $1 (напр. $0.50-0.90)
HALT_MAX_PRICE = 20.0             # по изрична молба — фокус върху penny/евтини акции, не всичко, което е скочило
HALT_MIN_DOLLAR_VOLUME = 3_000_000
HALT_PULLBACK_MIN_PCT = 0.08      # поне -8% от дневния връх ("лек pullback", не купуваме на върха)
HALT_PULLBACK_MAX_PCT = 0.30      # не повече от -30% от върха (иначе е обрат, не pullback)
HALT_POSITION_DOLLARS = 100.0     # фиксирана сума на позиция, по изрична молба — не % от капитала
HALT_STOP_LOSS_PCT = 0.15         # -15% (по изрична молба)
HALT_TAKE_PROFIT_PCT = 0.10       # +10% (по изрична молба)
HALT_MAX_POSITIONS = 2            # по изрична молба — макс. 2 едновременни penny/halt позиции ($200 общо)
HALT_SCAN_TOP = 25                # колко имена да вземем, ако се стигне до fallback screener-а
HALT_INTRADAY_TIMEFRAME = "5Min"  # свещи за pullback+пробив анализа
HALT_INTRADAY_BARS = 48           # ~4 часа в 5-минутни свещи
HALT_LOG_MAX_ENTRIES = 180

# Официалният, безплатен Nasdaq Trader feed за trading halts (всички щатски
# борси, не само Nasdaq) — ОСНОВНИЯТ източник на кандидати за Halt + Пробив,
# по изрична молба на потребителя. Обикновен GET, без ключ/логин.
NASDAQ_HALTS_FEED_URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"
NASDAQ_NS = {"ndaq": "http://www.nasdaqtrader.com/"}
# Само ВОЛАТИЛНОСТ-свързани halt кодове (рязък скок/спад на цената) — точно
# сценария "$1 → $5, спряха я, пуснаха я пак". Изрично прескачаме
# регулаторни/новинарски halt-ове (T1/T2/H10/MWC0-3 и др.) — те не пасват на
# идеята на стратегията. Виж https://www.nasdaqtrader.com/trader.aspx?id=TradeHaltCodes
HALT_VOLATILITY_REASON_CODES = {"LUDP", "LUDS", "T5"}


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


def get_orders_since(days=120, limit=500):
    """Всички поръчки (не филтрирани по символ) от последните `days` дни —
    нужно за възстановяване на легаси/halt дневника (build_roundtrip_log),
    защото тези позиции може да се затворят по всяко време, не само 'днес'."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    return _get(f"{TRADING_BASE}/v2/orders?status=all&after={since}&limit={limit}")


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


def get_intraday_bars(symbol, timeframe=None, limit=None):
    """Кратка вътрешнодневна серия (по подразбиране ~4 часа в 5-минутни свещи)
    — нужна на halt_breakout_signal, за да открие КЪДЕ точно през деня е бил
    pullback-ът и дали цената вече го е пробила обратно нагоре. Дневният
    snapshot (open/high/low/close) не дава тази информация."""
    tf = timeframe or HALT_INTRADAY_TIMEFRAME
    lim = limit or HALT_INTRADAY_BARS
    data = _get(f"{DATA_BASE}/v2/stocks/{symbol}/bars?timeframe={tf}&limit={lim}&feed=iex&adjustment=raw")
    return data.get("bars", []) if isinstance(data, dict) else []


def get_market_movers(top=20):
    """Screener endpoint — топ 'gainers' в момента (най-близкото до 'халт/скочи рязко',
    достъпно без официален halt флаг). Ако endpoint-ът не е наличен на текущия план/
    акаунт (403/404/друга грешка), просто връщаме празен списък — ботът продължава
    нормално, само halt сканирането пропуска този run."""
    try:
        data = _get(f"{DATA_BASE}/v1beta1/screener/stocks/movers?top={top}")
    except error.HTTPError as e:
        print(f"[halt] Screener endpoint недостъпен (HTTP {e.code}) — прескачам market-wide сканиране този run.")
        return []
    except Exception as e:
        print(f"[halt] Неуспешно четене на movers: {e}")
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
    halt-сканирането (get_halt_candidates), за да намери каквото реално се
    търгува активно днес, вместо фиксиран списък. Същото graceful-degrade
    поведение като get_market_movers — при недостъпен endpoint връщаме []."""
    try:
        data = _get(f"{DATA_BASE}/v1beta1/screener/stocks/most-actives?top={top}&by=volume")
    except error.HTTPError as e:
        print(f"[halt] Screener (most-actives) недостъпен (HTTP {e.code}) — прескачам живото сканиране този run.")
        return []
    except Exception as e:
        print(f"[halt] Неуспешно четене на most-actives: {e}")
        return []
    actives = data.get("most_actives", []) if isinstance(data, dict) else []
    symbols = []
    for a in actives:
        sym = a.get("symbol") if isinstance(a, dict) else None
        if sym:
            symbols.append(sym)
    return symbols


def get_nasdaq_halt_candidates():
    """ОСНОВЕН източник на halt кандидати — директно от Nasdaq Trader
    (rss.aspx?feed=tradehalts), официалният безплатен feed за trading
    halts на ВСИЧКИ щатски борси (не само Nasdaq), по изрична молба на
    потребителя. Филтрира само за ВОЛАТИЛНОСТ-свързани halt кодове
    (HALT_VOLATILITY_REASON_CODES) — прескача регулаторни/новинарски.
    При грешка/недостъпност връща [] тихо, без да чупи run-а — вика се
    от get_halt_candidates(), който тогава пада назад към screener-а."""
    try:
        req = request.Request(NASDAQ_HALTS_FEED_URL, headers={"User-Agent": "Mozilla/5.0 (alpaca-bot)"})
        with request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
    except Exception as e:
        print(f"[halt] Nasdaq halts feed недостъпен: {e}")
        return []

    seen, symbols = set(), []
    for item in root.findall(".//item"):
        reason = (item.findtext("ndaq:ReasonCode", "", NASDAQ_NS) or "").strip()
        if reason not in HALT_VOLATILITY_REASON_CODES:
            continue
        symbol = (item.findtext("ndaq:IssueSymbol", "", NASDAQ_NS) or "").strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)
    return symbols[:HALT_SCAN_TOP]


def get_halt_candidates():
    """ОСНОВЕН път: реалния списък HALT-нати компании от Nasdaq Trader (виж
    get_nasdaq_halt_candidates) — точно източникът, който потребителят
    поиска. FALLBACK: ако feed-ът е временно недостъпен ИЛИ в момента няма
    активни волатилност-halt-ове (напълно нормално — не всеки час има
    такива), пада назад към комбинация от 'топ gainers' + 'most actives'
    screener-ите, за да не спре стратегията да работи изцяло."""
    symbols = get_nasdaq_halt_candidates()
    if symbols:
        return symbols

    seen, candidates = set(), []
    for sym in get_market_movers(top=HALT_SCAN_TOP) + get_most_active_symbols(top=HALT_SCAN_TOP):
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
    Връща (trades, realized_pl_total, closed_count). Ползва се от
    build_daytrade_trades (единствената intraday стратегия — легаси/halt
    ползват отделния build_roundtrip_trades по-долу, тъй като не се
    затварят в рамките на деня)."""
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


def _load_previous_log_field(field_name):
    """Общ хелпър — чете (и декриптира, ако трябва) ПРЕДИШНИЯ status.json,
    само за да извади един лог масив по име. Ползва се от legacy_log и
    halt_log — за да продължат историята си между run-овете."""
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


def load_previous_legacy_log():
    return _load_previous_log_field("legacy_log")


def load_previous_halt_log():
    return _load_previous_log_field("halt_log")


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


def build_roundtrip_trades(all_orders, prefix_label_map):
    """Възстановява ЗАТВОРЕНИ (купено+продадено) сделки за не-intraday
    стратегии (легаси/halt) от ПЪЛНАТА поръчкова история (не само днешната
    — тези позиции може да стоят седмици). За разлика от
    _build_trades_by_coid_prefix (за day trading, само 'днес'), тук всяка
    сделка пази коя точно стратегия я е отворила и датата, на която РЕАЛНО
    се е затворила (не 'днес') — затварянето става само от Alpaca-ия
    bracket SL/TP, по всяко време. `prefix_label_map` е {ключ: етикет},
    напр. {"blue-chip": "Blue-chip", ...} — символ се приписва на стратегия
    по client_order_id префикса на КУПУВАЩАТА поръчка; продаващата поръчка
    НЕ носи същия coid (Alpaca генерира нов за bracket изходите), затова се
    съпоставя само по символ, хронологично — същия принцип като
    _build_trades_by_coid_prefix."""
    orders_sorted = sorted(
        (o for o in all_orders if o.get("status") == "filled"),
        key=lambda o: o.get("filled_at") or o.get("submitted_at") or "",
    )
    open_buys = {}
    closed = []
    for o in orders_sorted:
        coid = o.get("client_order_id") or ""
        symbol = o.get("symbol")
        side = o.get("side")
        price = _safe_float(o.get("filled_avg_price"))
        qty = _safe_float(o.get("qty"))
        if not symbol or not price or not qty:
            continue

        if side == "buy":
            strategy_key = None
            for key in prefix_label_map:
                if coid.startswith(f"{key}-"):
                    strategy_key = key
                    break
            if strategy_key:
                open_buys[symbol] = {
                    "strategy_key": strategy_key,
                    "strategy_label": prefix_label_map[strategy_key],
                    "price": price,
                    "qty": qty,
                }
        elif side == "sell" and symbol in open_buys:
            buy = open_buys.pop(symbol)
            filled_at = o.get("filled_at") or o.get("submitted_at") or ""
            closed_date = filled_at[:10] if filled_at else None
            if not closed_date:
                continue
            matched_qty = min(qty, buy["qty"])
            pl = (price - buy["price"]) * matched_qty
            closed.append({
                "date": closed_date,
                "symbol": symbol,
                "strategy": buy["strategy_key"],
                "strategy_label": buy["strategy_label"],
                "entry_price": round(buy["price"], 2),
                "exit_price": round(price, 2),
                "qty": matched_qty,
                "pl": round(pl, 2),
            })
    return closed


def build_roundtrip_log(all_orders, previous_log, prefix_label_map, max_entries):
    """Прекомпютва ВСИЧКИ затворени сделки от `all_orders` (get_orders_since)
    и презаписва деня им в `previous_log` — идемпотентно и self-healing:
    ако предишен run е пропуснал нещо (напр. поради временна грешка), този
    run пак ще го хване, стига поръчката да е в прозореца на get_orders_since."""
    closed_trades = build_roundtrip_trades(all_orders, prefix_label_map)
    by_date = {}
    for t in closed_trades:
        by_date.setdefault(t["date"], []).append(t)
    log = previous_log
    for date_str, trades in by_date.items():
        realized_pl = sum(t["pl"] for t in trades)
        log = _upsert_simple_log(log, date_str, trades, realized_pl, len(trades), max_entries)
    return log


# ---------------- Status snapshot (за статичното табло) ----------------

def write_status_snapshot(clock, account, positions, orders, daytrade_log=None, today_strategy=None, legacy_log=None, halt_log=None):
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
            "halt_strategy_enabled": HALT_ENABLED,
            "legacy_log": legacy_log or [],
            "halt_log": halt_log or [],
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
    """SMA(50) > SMA(200) — "златен кръст", класически дългосрочен uptrend сигнал
    (ai-longterm и sp500-longterm). ПОДОБРЕН по изрична молба спрямо голото
    пресичане — изисква и:
      1) текущата цена да е НАД SMA(50) — потвърждава, че сме РЕАЛНО в
         тренд СЕГА, не просто, че кръстът е станал исторически, а цената
         междувременно е паднала обратно под него;
      2) SMA(50) да СЕ ПОКАЧВА спрямо преди GOLDEN_CROSS_TREND_LOOKBACK_DAYS
         дни — потвърждава сила на тренда, не отслабващ/плосък кръст."""
    closes = [b.get("c") for b in bars if b.get("c") is not None]
    fast_sma = sma(closes, GOLDEN_CROSS_FAST)
    slow_sma = sma(closes, GOLDEN_CROSS_SLOW)
    if fast_sma is None or slow_sma is None:
        return False
    if fast_sma <= slow_sma:
        return False
    price = closes[-1] if closes else None
    if not price or price <= fast_sma:
        return False
    fast_sma_prev = sma(closes[:-GOLDEN_CROSS_TREND_LOOKBACK_DAYS], GOLDEN_CROSS_FAST)
    if fast_sma_prev is None or fast_sma <= fast_sma_prev:
        return False
    return True


def blue_chip_signal(bars):
    """SMA(10) > SMA(30) — по-кратък/по-отзивчив кръст за ликвидните
    блу-чипове. ПОДОБРЕН по изрична молба спрямо голото пресичане —
    изисква и:
      1) SMA(10) да СЕ ПОКАЧВА спрямо преди BLUE_CHIP_TREND_LOOKBACK_DAYS
         дни — потвърждава РЕАЛЕН тренд, не кръст, който вече губи сила;
      2) цената да не е с повече от BLUE_CHIP_MAX_EXTENSION_PCT над SMA(30)
         — избягва купуване на прекалено разтеглено/екстремно движение."""
    closes = [b.get("c") for b in bars if b.get("c") is not None]
    fast_sma = sma(closes, BLUE_CHIP_FAST)
    slow_sma = sma(closes, BLUE_CHIP_SLOW)
    if fast_sma is None or slow_sma is None:
        return False
    if fast_sma <= slow_sma:
        return False
    fast_sma_prev = sma(closes[:-BLUE_CHIP_TREND_LOOKBACK_DAYS], BLUE_CHIP_FAST)
    if fast_sma_prev is None or fast_sma <= fast_sma_prev:
        return False
    price = closes[-1] if closes else None
    if not price or not slow_sma:
        return False
    extension = (price - slow_sma) / slow_sma
    if extension > BLUE_CHIP_MAX_EXTENSION_PCT:
        return False
    return True


def legacy_signal(strategy_key, bars, snapshot):
    if strategy_key == "blue-chip":
        return blue_chip_signal(bars)
    if strategy_key in ("ai-longterm", "sp500-longterm"):
        return golden_cross_signal(bars)
    return False


LEGACY_STRATEGIES = [
    {"key": "blue-chip", "label": "Blue-chip", "watchlist": BLUE_CHIP_WATCHLIST,
     "position_pct": BLUE_CHIP_POSITION_PCT, "stop_loss_pct": LEGACY_STOP_LOSS_PCT,
     "take_profit_pct": LEGACY_TAKE_PROFIT_PCT, "max_positions": BLUE_CHIP_MAX_POSITIONS,
     "needs_snapshot": False},
    {"key": "ai-longterm", "label": "AI дългосрочно", "watchlist": AI_LT_WATCHLIST,
     "position_pct": AI_LT_POSITION_PCT, "stop_loss_pct": LEGACY_STOP_LOSS_PCT,
     "take_profit_pct": LEGACY_TAKE_PROFIT_PCT, "max_positions": AI_LT_MAX_POSITIONS,
     "needs_snapshot": False},
    {"key": "sp500-longterm", "label": "S&P 500 дългосрочно", "watchlist": SP500_LT_WATCHLIST,
     "position_pct": SP500_LT_POSITION_PCT, "stop_loss_pct": LEGACY_STOP_LOSS_PCT,
     "take_profit_pct": LEGACY_TAKE_PROFIT_PCT, "max_positions": SP500_LT_MAX_POSITIONS,
     "needs_snapshot": False},
]

LEGACY_PREFIX_LABELS = {s["key"]: s["label"] for s in LEGACY_STRATEGIES}
HALT_PREFIX_LABELS = {"halt": "Halt + Пробив 💥"}


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
    само върху watchlist. Важно за 'halt': кандидатите идват от живо
    сканиране (get_halt_candidates), различно всеки run, затова позиция,
    купена вчера от символ, който днес вече не е сред 'топ' кандидатите,
    пак трябва да се преброи."""
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


# ---------------- Разпознаване на свещи (candlestick patterns) — по изрична молба ----------------
# Каталог от бичи ("купи") модели, изпратен директно от потребителя, за да потвърждава
# halt_breakout_signal, че дъното на pullback-а РЕАЛНО е стабилизация, а не просто число
# (виж has_bullish_stabilization_candle по-долу). Всяка функция работи върху обикновен
# {"o","h","l","c"} бар и връща True/False — чисти, лесни за тестване.
#
# Само БИЧИ/стабилизиращи модели (стратегията само купува, никога не шортва):
#   • Единични: Чук (Hammer), Обърнат чук (Inverted Hammer), Водно конче (Dragonfly Doji),
#     Бичо Марубозу (Bullish Marubozu).
#   • Двойни: Бичо поглъщане (Bullish Engulfing), Биче Харами (Bullish Harami),
#     Пронизваща линия (Piercing Line).
#   • Тройни: Утринна звезда (Morning Star), Трима бели войници (Three White Soldiers).

def _candle_parts(bar):
    o, h, l, c = bar.get("o"), bar.get("h"), bar.get("l"), bar.get("c")
    if o is None or h is None or l is None or c is None:
        return None
    full_range = h - l
    if full_range <= 0:
        return None
    body = abs(c - o)
    body_top = max(o, c)
    body_bottom = min(o, c)
    upper_wick = h - body_top
    lower_wick = body_bottom - l
    return {"o": o, "h": h, "l": l, "c": c, "range": full_range, "body": body,
            "upper_wick": upper_wick, "lower_wick": lower_wick}


def is_hammer(bar):
    """Чук: малко тяло в горната част + дълга долна сянка (поне 2x тялото),
    почти без горна сянка. Появява се на дъното на низходящо движение —
    силен бичи сигнал."""
    p = _candle_parts(bar)
    if p is None or p["body"] <= 0:
        return False
    return p["lower_wick"] >= 2 * p["body"] and p["upper_wick"] <= p["body"] * 0.3


def is_inverted_hammer(bar):
    """Обърнат чук: малко тяло в долната част + дълга горна сянка (поне 2x
    тялото), почти без долна сянка. На дъното на низходящ тренд — купувачите
    са опитали, срещнали са съпротива, но присъствието им е сигнал."""
    p = _candle_parts(bar)
    if p is None or p["body"] <= 0:
        return False
    return p["upper_wick"] >= 2 * p["body"] and p["lower_wick"] <= p["body"] * 0.3


def is_dragonfly_doji(bar):
    """Водно конче (Dragonfly Doji): тялото е практически нулево, дълга
    долна сянка, почти без горна — бичи характер, подобно на чука."""
    p = _candle_parts(bar)
    if p is None:
        return False
    if p["body"] > p["range"] * 0.05:
        return False
    return p["upper_wick"] <= p["range"] * 0.1


def is_bullish_marubozu(bar):
    """Бичо Марубозу: голямо плътно бичо тяло, почти без сенки в двата
    края — отваря се на дъното, затваря се на върха. Агресивно купуване."""
    p = _candle_parts(bar)
    if p is None or bar.get("c") <= bar.get("o"):
        return False
    return p["upper_wick"] <= p["range"] * 0.05 and p["lower_wick"] <= p["range"] * 0.05


def is_bullish_engulfing(prev_bar, bar):
    """Бичо поглъщане: малка мечa свещ, последвана от голяма бича свещ,
    чието тяло напълно поглъща тялото на предната."""
    po, pc = prev_bar.get("o"), prev_bar.get("c")
    o, c = bar.get("o"), bar.get("c")
    if None in (po, pc, o, c):
        return False
    if pc >= po or c <= o:
        return False
    return o <= pc and c >= po


def is_bullish_harami(prev_bar, bar):
    """Биче Харами: голяма мечa свещ, последвана от малка бича свещ, чието
    тяло се събира изцяло в границите на тялото на предната — сигнал за
    спиране на спада."""
    po, pc = prev_bar.get("o"), prev_bar.get("c")
    o, c = bar.get("o"), bar.get("c")
    if None in (po, pc, o, c):
        return False
    if pc >= po or c <= o:
        return False
    return o >= pc and c <= po


def is_piercing_line(prev_bar, bar):
    """Пронизваща линия: дълга мечa свещ, последвана от бича свещ, която се
    отваря под дъното ѝ, но затваря над средата (50%) на тялото ѝ."""
    po, pc = prev_bar.get("o"), prev_bar.get("c")
    o, c = bar.get("o"), bar.get("c")
    if None in (po, pc, o, c):
        return False
    if pc >= po or c <= o:
        return False
    midpoint = (po + pc) / 2
    return o < pc and midpoint < c < po


def is_morning_star(bar1, bar2, bar3):
    """Утринна звезда: дълга мечa свещ, малка неопределена свещ
    (нерешителност), после дълга бича свещ, затваряща дълбоко в тялото на
    първата — класически сигнал за дъно."""
    vals = [bar1.get("o"), bar1.get("c"), bar2.get("o"), bar2.get("c"), bar3.get("o"), bar3.get("c")]
    if any(v is None for v in vals):
        return False
    o1, c1, o2, c2, o3, c3 = vals
    if c1 >= o1 or c3 <= o3:
        return False
    body1 = abs(c1 - o1)
    body2 = abs(c2 - o2)
    if body1 <= 0 or body2 > body1 * 0.5:
        return False
    midpoint1 = (o1 + c1) / 2
    return c3 > midpoint1


def is_three_white_soldiers(bar1, bar2, bar3):
    """Трима бели войници: три последователни дълги бичи свещи, всяка
    затваряща и отваряща по-високо от предната — силен знак за продължение
    на възходящото движение."""
    bars = [bar1, bar2, bar3]
    for b in bars:
        o, c = b.get("o"), b.get("c")
        if o is None or c is None or c <= o:
            return False
    return (bar2["c"] > bar1["c"] and bar3["c"] > bar2["c"]
            and bar2["o"] > bar1["o"] and bar3["o"] > bar2["o"])


def has_bullish_stabilization_candle(bars, idx):
    """Проверява дали свещта на позиция `idx` (сама или в комбинация с
    непосредствено предходните 1-2 свещи) образува познат бичи модел от
    каталога по-горе. Ползва се от halt_breakout_signal, за да потвърди, че
    дъното на pullback-а е РЕАЛНА стабилизация (не просто число), точно
    както при живия анализ (чакай hammer/поглъщане/утринна звезда, после
    пробив)."""
    if idx < 0 or idx >= len(bars):
        return False
    bar = bars[idx]
    if is_hammer(bar) or is_inverted_hammer(bar) or is_dragonfly_doji(bar) or is_bullish_marubozu(bar):
        return True
    if idx >= 1:
        prev = bars[idx - 1]
        if is_bullish_engulfing(prev, bar) or is_bullish_harami(prev, bar) or is_piercing_line(prev, bar):
            return True
    if idx >= 2:
        if is_morning_star(bars[idx - 2], bars[idx - 1], bar) or is_three_white_soldiers(bars[idx - 2], bars[idx - 1], bar):
            return True
    return False


# ---------------- "Halt + Пробив" — сигнал и вход (swing, БЕЗ принудително затваряне) ----------------

def halt_breakout_signal(snapshot, intraday_bars):
    """Halt + Пробив: изисква (1) вече станал рязък % скок спрямо вчерашното
    затваряне (заместител на официалния "halt" флаг, който липсва в
    безплатните данни), (2) pullback от дневния връх в разумни граници
    (не купуваме на самия връх, но и не купуваме след пълен обрат надолу),
    (3) РАЗПОЗНАВАЕМ бичи модел свещ (chук/поглъщане/утринна звезда и т.н.
    — виж has_bullish_stabilization_candle) около дъното на pullback-а, за
    да потвърди, че е РЕАЛНА стабилизация, не просто число, и (4) реален
    ПРОБИВ нагоре над локалния връх, образуван СЛЕД дъното (5-минутни
    свещи) — тоест не влизаме само защото цената е паднала, а чак когато
    видим и позната свещ на дъното, и реален пробив нагоре след нея (точно
    логиката от живия анализ на FNGR: чакаме hammer/стабилизация, после
    пробив). Цената се проверява и срещу HALT_MAX_PRICE (под $20, по
    изрична молба) — стратегията е за penny/евтини акции, не за каквото и
    да е скочило."""
    try:
        price = snapshot["latestTrade"]["p"]
        today_high = snapshot["dailyBar"]["h"]
        today_volume = snapshot["dailyBar"]["v"]
        prev_close = snapshot["prevDailyBar"]["c"]
    except (KeyError, TypeError):
        return False
    if not price or not today_high or not prev_close:
        return False
    if price < HALT_MIN_PRICE or price > HALT_MAX_PRICE:
        return False

    move_from_prev_close = (price - prev_close) / prev_close
    if not (HALT_MIN_MOVE_PCT <= move_from_prev_close <= HALT_MAX_MOVE_PCT):
        return False

    dollar_volume = today_volume * price
    if dollar_volume < HALT_MIN_DOLLAR_VOLUME:
        return False

    if not intraday_bars or len(intraday_bars) < 4:
        return False  # твърде малко свещи за надежден pullback+пробив анализ

    # 1) дневен връх измежду наличните интрадей свещи
    peak_idx = max(range(len(intraday_bars)), key=lambda i: intraday_bars[i].get("h") or 0)
    peak_price = intraday_bars[peak_idx].get("h") or 0
    if not peak_price:
        return False

    bars_after_peak = intraday_bars[peak_idx + 1:]
    if len(bars_after_peak) < 2:
        return False  # още няма достатъчно свещи СЛЕД върха — чакаме

    # 2) дъно на pullback-а СЛЕД върха
    low_idx = min(range(len(bars_after_peak)), key=lambda i: bars_after_peak[i].get("l") if bars_after_peak[i].get("l") is not None else float("inf"))
    pullback_low = bars_after_peak[low_idx].get("l")
    if pullback_low is None:
        return False

    pullback_pct = (peak_price - pullback_low) / peak_price
    if not (HALT_PULLBACK_MIN_PCT <= pullback_pct <= HALT_PULLBACK_MAX_PCT):
        return False

    # 2.5) Изисква разпознаваем БИЧИ модел свещ около дъното на pullback-а —
    # проверяваме дъното и следващите 2 свещи (позволява на 2-3-свещни
    # модели като поглъщане/утринна звезда да завършат точно на дъното).
    # Числовият пробив по-долу НЕ е достатъчен сам по себе си — потребителят
    # изрично поиска реално потвърждение от формата на свещите, не само от
    # числата.
    stabilization_confirmed = any(
        has_bullish_stabilization_candle(bars_after_peak, low_idx + offset)
        for offset in range(3)
        if low_idx + offset < len(bars_after_peak)
    )
    if not stabilization_confirmed:
        return False

    # 3) локален връх, образуван СЛЕД дъното на pullback-а (стабилизацията)
    bars_after_low = bars_after_peak[low_idx + 1:]
    if not bars_after_low:
        return False  # нямаме нито една свещ след дъното — все още чакаме стабилизация
    local_high_after_low = max((b.get("h") or 0) for b in bars_after_low)
    if not local_high_after_low:
        return False

    # ПРОБИВ: текущата цена трябва реално да пробие над този локален връх
    return price > local_high_after_low


def run_halt_entries(equity, held_symbols, traded_today, today_str):
    """Кандидатите идват от get_halt_candidates() — реалния Nasdaq Trader
    halt feed, с fallback към общ screener (виж докстринга на
    get_halt_candidates по-горе). Позицията е ФИКСИРАНА сума в долари
    (HALT_POSITION_DOLLARS), не % от капитала — по изрична молба.
    Swing-style: НЕ се затваря принудително в края на деня."""
    trades_made, errors = [], []
    slots_free = HALT_MAX_POSITIONS - count_open_legacy_positions(held_symbols, "halt-")
    if slots_free <= 0:
        return trades_made, errors

    candidates = get_halt_candidates()
    for symbol in candidates:
        if len(trades_made) >= slots_free:
            break
        if symbol in held_symbols or symbol in traded_today:
            continue  # вече държан/търгуван днес (от друга стратегия или другаде) — прескачаме
        try:
            snap = get_snapshot(symbol)
        except error.HTTPError as e:
            errors.append(f"[halt] {symbol}: грешка при snapshot ({e.read().decode()[:150]})")
            continue
        try:
            bars = get_intraday_bars(symbol)
        except error.HTTPError as e:
            errors.append(f"[halt] {symbol}: грешка при интрадей данни ({e.read().decode()[:150]})")
            continue
        if not halt_breakout_signal(snap, bars):
            continue
        try:
            current_price = snap["latestTrade"]["p"]
        except (KeyError, TypeError):
            continue
        if not current_price:
            continue
        qty = int(HALT_POSITION_DOLLARS // current_price)
        if qty < 1:
            continue
        coid = f"halt-{symbol}-{today_str}"
        try:
            place_entry_order(symbol, qty, current_price, HALT_STOP_LOSS_PCT, HALT_TAKE_PROFIT_PCT, client_order_id=coid)
            trades_made.append(("Halt + Пробив 💥", symbol, qty, current_price, HALT_STOP_LOSS_PCT, HALT_TAKE_PROFIT_PCT))
            print(
                f"[halt] КУПЕНО: {qty} x {symbol} @ ~{current_price:.2f} "
                f"(SL -{HALT_STOP_LOSS_PCT*100:.0f}% / TP +{HALT_TAKE_PROFIT_PCT*100:.0f}%, "
                f"${HALT_POSITION_DOLLARS:.0f} фиксирано) — държи се докато не удари SL/TP (не е intraday)"
            )
        except error.HTTPError as e:
            errors.append(f"[halt] {symbol}: грешка при поръчка ({e.read().decode()[:150]})")

    return trades_made, errors


# ---------------- Main ----------------

def run():
    if not API_KEY or not API_SECRET:
        raise RuntimeError("Липсват ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY.")

    clock = get_clock()
    account = get_account()
    positions = get_positions()
    today_orders = get_today_orders()
    daytrade_log = load_previous_daytrade_log()
    legacy_log = load_previous_legacy_log()
    halt_log = load_previous_halt_log()

    # Легаси/Halt логовете се преизчисляват НАПЪЛНО от реалната поръчкова
    # история (не само от днешните поръчки) при всеки run — самокоригират
    # се, ако затварящ SL/TP fill е станал между два последователни run-а
    # (виж build_roundtrip_log/build_roundtrip_trades по-горе).
    try:
        orders_since = get_orders_since()
        legacy_log = build_roundtrip_log(orders_since, legacy_log, LEGACY_PREFIX_LABELS, LEGACY_LOG_MAX_ENTRIES)
        halt_log = build_roundtrip_log(orders_since, halt_log, HALT_PREFIX_LABELS, HALT_LOG_MAX_ENTRIES)
    except error.HTTPError as e:
        print(f"[legacy/halt log] Неуспешно обновяване: {e}")

    now = parse_alpaca_ts(clock["timestamp"])
    sofia_now = now.astimezone(SOFIA_TZ)
    active_strategy = todays_strategy(sofia_now)
    active_strategy_info = {"key": active_strategy["key"], "label": active_strategy["label"]}

    write_status_snapshot(
        clock, account, positions, today_orders,
        daytrade_log=daytrade_log, today_strategy=active_strategy_info, legacy_log=legacy_log, halt_log=halt_log,
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
        f"halt: {'вкл.' if HALT_ENABLED else 'изкл.'}"
    )

    all_trades, all_errors = [], []

    # 1) Задължително първо: затваряме просрочени day-trade позиции от днес.
    #    Легаси swing стратегиите и Halt+Пробив НЕ се пипат тук — те се
    #    държат докато не ударят своя SL/TP (виж стъпки 2-4 по-долу).
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

    # 2) Нови входове по активната днешна стратегия — само в прозореца (day trading).
    if in_window and not should_force_close:
        trades, errors = run_daytrade_entries(active_strategy, equity, held_symbols, traded_today, today_str)
        all_trades.extend(trades)
        all_errors.extend(errors)
        held_symbols |= {t[1] for t in trades}

    # 3) Легаси swing стратегии (blue-chip/ai-longterm/sp500-longterm) — НЕ са
    #    intraday, работят докато пазарът е отворен, независимо от day-trading прозореца.
    #    Никога не се затварят принудително — държат се докато не ударят своя SL/TP.
    for strategy in LEGACY_STRATEGIES:
        trades, errors = run_legacy_entries(strategy, equity, held_symbols, traded_today, today_str)
        all_trades.extend(trades)
        all_errors.extend(errors)
        held_symbols |= {t[1] for t in trades}

    # 4) Halt + Пробив — също swing-style (без принудително затваряне),
    #    работи докато пазарът е отворен, ако е включена (SPIKE_STRATEGY_ENABLED secret).
    if HALT_ENABLED:
        halt_trades, halt_errors = run_halt_entries(equity, held_symbols, traded_today, today_str)
        all_trades.extend(halt_trades)
        all_errors.extend(halt_errors)
        held_symbols |= {t[1] for t in halt_trades}

    # Финална снимка — след сделките/затварянията и с обновения дневник.
    if all_trades or should_force_close:
        try:
            write_status_snapshot(
                clock, get_account(), get_positions(), get_today_orders(),
                daytrade_log=daytrade_log, today_strategy=active_strategy_info,
                legacy_log=legacy_log, halt_log=halt_log,
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
