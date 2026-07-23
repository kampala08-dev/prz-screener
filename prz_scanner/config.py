"""Configuration & parameters for the PRZ Buy Zone Scanner.

All parameters are ported/derived from the tested Pine Script "Harmonic PRZ
Scanner" (prz.pine). Where a value or concept has NO Pine equivalent it is
marked "[DEVIATION]" — see README.

Ground-truth note
------------------
This scanner ports the *actual* prz.pine file (the version tested on
TradingView), NOT the "v9 refD-convergence" algorithm described narratively in
prd_prz.md §4. In prz.pine each pattern's D point is a single fixed projection
of the XA leg (e.g. Gartley D = 0.786*XA), with a fixed half-width box, gated by
the BC-projection ratio. Validity comes from przStatus (touch/reversal/flip),
not from a "close never broke PRZ" test. See patterns.py for the 1:1 port.
"""

from dataclasses import dataclass, field
from typing import Dict, List


# ---------------------------------------------------------------------------
# Scan universe — ~640+ tickers, ordered by IDX liquidity/turnover ranking.
# Source: rank_600.md (2026-07-20). Update manually as needed.
# `.JK` suffix added automatically at fetch time.
# ---------------------------------------------------------------------------
UNIVERSE: List[str] = [
    # Rank 1-50 (Top liquidity)
    "TPIA", "BBCA", "BBRI", "BMRI", "DSSA", "AMMN", "BUMI", "TLKM", "ANTM", "BRPT",
    "ASII", "CUAN", "BREN", "BBNI", "PTRO", "BRMS", "DEWA", "AMRT", "MDKA", "EMAS",
    "TINS", "BUVA", "UNTR", "AADI", "BIPI", "RAJA", "INCO", "ADRO", "MAPI", "BNBR",
    "BULL", "MBMA", "ENRG", "MEDC", "INDF", "KLBF", "ITMG", "NCKL", "ESSA", "WIFI",
    "PGAS", "MINA", "INKP", "CDIA", "ADMR", "CPIN", "PTBA", "PSAB", "ARCI", "JPFA",
    # Rank 51-100
    "ASPR", "INDY", "SUPA", "PACK", "ISAT", "IMPC", "TKIM", "TCPI", "TOWR", "ICBP",
    "MSIN", "UNVR", "RATU", "RMKE", "PANI", "BUKA", "AKRA", "BRIS", "SMGR", "EMTK",
    "INET", "VKTR", "TAPG", "PWON", "SSIA", "KETR", "HRTA", "JSMR", "MIKA", "WBSA",
    "UVCR", "KOTA", "EXCL", "GULA", "JGLE", "BBTN", "GOTO", "AALI", "ARKO", "GGRM",
    "DMAS", "MARK", "PADI", "IRSX", "ESIP", "PGEO", "NZIA", "BDMN", "CYBR", "LSIP",
    # Rank 101-150
    "ELSA", "INTP", "BKSL", "CMNT", "OASA", "HMSP", "BSDE", "CTRA", "MTEL", "BFIN",
    "SIDO", "MYOR", "SSMS", "CMRY", "TRUE", "MAPA", "MPMX", "AYAM", "PNLF", "CBDK",
    "APIC", "DSNG", "CBRE", "PPRE", "HEAL", "GPSO", "SINI", "DEFI", "BAIK", "ACES",
    "SCMA", "LCKM", "MDIA", "SIMP", "HRUM", "ERAA", "ZATA", "HATM", "NICL", "DATA",
    "MMIX", "KIJA", "BNGA", "FILM", "DEWI", "BSML", "HUMI", "KEEN", "MIDI", "SMRA",
    # Rank 151-200
    "KPIG", "ARTO", "NISP", "LEAD", "BWPT", "FORE", "EPAC", "RSCH", "RGAS", "GTSI",
    "BANK", "STAA", "AUTO", "KUAS", "MBSS", "ASSA", "WMUU", "GRIA", "INDO", "GJTL",
    "DKFT", "OMED", "WEHA", "BJTM", "SRTG", "BSSR", "BTPS", "IATA", "MSJA", "COIN",
    "BBKP", "POWR", "PIPA", "BMTR", "ULTJ", "SMIL", "NATO", "NSSS", "AVIA", "VISI",
    "RLCO", "JARR", "RBMS", "MORA", "BBYB", "COCO", "PNBN", "FUJI", "MNCN", "YELO",
    # Rank 201-250
    "TOOL", "TRIN", "SDMU", "SOCI", "TBIG", "PSKT", "MEDS", "TOBA", "WIRG", "TOTL",
    "KJEN", "LPPF", "BELL", "SRSN", "CPRO", "DOOH", "SGER", "FORU", "DGWG", "CTTH",
    "WIIM", "NIKL", "KAQI", "PYFA", "DPUM", "LPKR", "STRK", "GIAA", "LAJU", "BIRD",
    "TUGU", "MLBI", "SMSM", "TPMA", "ELTY", "BJBR", "GPRA", "JATI", "KOCI", "TSPC",
    "KIOS", "NEST", "GMFI", "DFAM", "SNLK", "PKPK", "MGRO", "SMDR", "PADA", "UDNG",
    # Rank 251-300
    "RALS", "NRCA", "BEEF", "FUTR", "KRYA", "APLN", 
    "ALII", "MSKY", "OILS",
    "CLEO", "NTBK", "ASHA", "RMKO", "ARNA", "ICON", "DAAZ", "GZCO", "TMPO",
    "AHAP", "TBLA", "BEER", "NETV", "SOFA", "EURO", "MLPL", "MPOW", "KRAS",
    "TAMA", "LAPD", "BLUE", "ELPI", "LABA", "ERAL", 
    # Rank 301-350
    "RISE", "SLIS", "VICI", "BCIC", "MAIN", "FOLK", "SMLE", "MPPA",
    "KBLV", "MTDL", "DKHH", "MOLI",
    "LAND", "TRON", "FIRE", "FPNI", "TEBE", "MDIY", "JMAS", "PMUI", "PART", "PTPP",
    "ROTI", "KOKA", "APEX", "BSBK", "MLPT", "CHEK", "MEJA",
    "HOPE", "JAST", "BABY", "ASRI",
    # Rank 351-400
    "ASLI", "IKAN", "CHEM", "DOID", "CITA", "ELIT",
    # Rank 401-450
    "IMJS", "PTMP", "UANG", "BCIP", "TOSK", "BOAT",
    "CLPI", "IOTF", "RODA",
    # Rank 451-500
    "CITY", "VIVA","AISA",
    "NAIK", "NASI", "ISEA", "ERTX", "FWCT","WOOD", "MINE",
    # Rank 501-550
    "OPMS", "FAST", "BNII", "OBAT",
    # Rank 551-600
    "ENAK", "BVIC","PSAT", "KBLI",
    "CMNP", "AYLS", "BCAP", "POLU", "ESTA", "ECII", "LPPS", "MERI",
    # Rank 601-634
    "PICO", "RUIS", "GTRA", "SONA", "BTPN",
    # Extra tickers (added manually)
    "RANS", "BACH", "JELI", "PRDL", "EMMI", "JECX",
]


def _dedup_preserve(seq: List[str]) -> List[str]:
    seen = set()
    out = []
    for t in seq:
        u = t.strip().upper()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


UNIVERSE = _dedup_preserve(UNIVERSE)   # remove accidental duplicates (e.g. BRIS)

# Backwards-compat alias (Config default references this name).
LQ45 = UNIVERSE


@dataclass
class Config:
    # --- watchlist / data ---
    watchlist: List[str] = field(default_factory=lambda: list(LQ45))
    timeframe: str = "1d"          # "1d", "1wk", or "4h"
    period_daily: str = "2y"       # long enough for depth-20 zigzag
    period_weekly: str = "5y"      # ~260 weekly bars — plenty for all depths
    period_intraday: str = "60d"   # yfinance intraday history cap (~60d)

    # --- zigzag depths (Pine default-ON set: 3,5,8,12,20) ---
    # Pine also has 18 & 25 available but default OFF -> excluded here.
    depths: List[int] = field(default_factory=lambda: [3, 5, 8, 12, 20])

    # --- tolerances (Pine: tol1 strict=5, tol2 loose=10) ---
    tol_strict: float = 5.0
    tol_loose: float = 10.0
    enable_strict: bool = True
    enable_loose: bool = True

    # --- [BOOK] BC-projection gate (implied CD/BC vs book range) ---
    # Default ON: the gate now checks the *implied* CD/BC projection (the
    # Pine port gated bc/ab, which could never pass — dead code). Disable
    # with --no-strict-bc on the runners to loosen detection.
    strict_bc: bool = True

    # --- distance / validity (Pine) ---
    max_dist: float = 80.0         # Pine input default = 80%
    rev_bars: int = 5              # Pine "Reversal Confirm Bars"

    # --- pattern toggles (Pine: all ON) ---
    patterns_enabled: Dict[str, bool] = field(default_factory=lambda: {
        "Gartley": True, "Bat": True, "Butterfly": True,
        "Crab": True, "Shark": True,
    })

    # --- [DEVIATION] cross-stock scanner additions (no Pine equivalent) ---
    # BUY proximity: stock passes if close is inside PRZ, OR above PRZ within
    # proximity_pct heading down toward it. See scanner.py.
    proximity_pct: float = 3.0
    # prz_maxw: PRD asks 15% max PRZ width. Pine boxes are already narrow
    # (fixed ±3-5% of XA), so this is a light guard, applied on final box.
    prz_maxw: float = 15.0
    # [BOOK] confluence: a PRZ element (AB=CD completion, BC projection
    # level) joins the PRZ cluster if it lands within this % of the XA
    # anchor. Tighter -> stricter confluence requirement.
    prz_cluster_tol: float = 3.0
    # [DEVIATION] chart neatness: draw at most this many patterns per chart
    # (the nearest-to-price, highest-accuracy ones; best buy always shown).
    max_display: int = 2

    # --- output ---
    output_dir: str = "output"


def ticker_to_yf(code: str) -> str:
    """BBCA -> BBCA.JK"""
    code = code.strip().upper()
    return code if code.endswith(".JK") else f"{code}.JK"


def h4_config() -> "Config":
    """Pre-configured Config for H4 (4-hour) timeframe scans.

    Key differences from the Daily default:
    - timeframe  : '4h'  — fetches 60m from yfinance then resamples to 4H
    - depths     : [3, 5, 8, 12]  — depth 20 is dropped because yfinance
                   intraday history is capped at ~60 days ≈ 90 H4 candles;
                   a depth-20 pivot needs 40 bars of confirmation window,
                   which leaves too few pivots to find meaningful patterns.
    - output_dir : 'output/h4'  — keeps H4 results separate from daily output.
    """
    return Config(
        timeframe="4h",
        depths=[3, 5, 8, 12],
        output_dir="output/h4",
        period_intraday="60d",
    )


def daily_config() -> "Config":
    """Pre-configured Config for Daily (1d) timeframe scans (convenience alias)."""
    return Config(
        timeframe="1d",
        output_dir="output/daily",
    )


def weekly_config() -> "Config":
    """Pre-configured Config for Weekly (1wk) timeframe scans.

    Key differences from the Daily default:
    - timeframe    : '1wk' — native yfinance weekly interval, no resampling.
    - period_weekly: '5y'  — ~260 weekly candles; enough for all depths incl. 20.
    - depths       : [3, 5, 8, 12, 20]  — same as Daily (more history available).
    - output_dir   : 'output/weekly' — keeps Weekly results separate.

    Weekly PRZ patterns are longer-term signals (weeks/months horizon) compared
    to Daily (days/weeks) and H4 (hours/days).
    """
    return Config(
        timeframe="1wk",
        depths=[3, 5, 8, 12, 20],
        output_dir="output/weekly",
        period_weekly="5y",
    )
