"""
Kraken Data Fetcher & CSV Loaders (ENHANCED)
Oracle Project | Adversary v0
"""

import time
import json
import urllib.request
import urllib.error
from typing import List, Optional, Tuple
from signals import Candle5m, OracleTick


class KrakenFetcher:

    SPOT_URL = "https://api.kraken.com/0/public/OHLC"
    FUTURES_URL = "https://futures.kraken.com/api/charts/v1/spot/PI_XBTUSD/5m"
    SPOT_PAIR = "XXBTZUSD"
    CANDLE_INTERVAL = 5

    def __init__(self, use_futures: bool = False, max_retries: int = 3):
        self.use_futures = use_futures
        self.max_retries = max_retries

    def fetch_candles(self, hours: int = 28) -> List[Candle5m]:
        if self.use_futures:
            return self._fetch_futures(hours)
        return self._fetch_spot(hours)

    def _fetch_spot(self, hours: int) -> List[Candle5m]:
        since = int(time.time()) - (hours * 3600) - 300
        url = f"{self.SPOT_URL}?pair={self.SPOT_PAIR}&interval={self.CANDLE_INTERVAL}&since={since}"
        data = self._http_get(url)
        if data.get('error'):
            raise RuntimeError(f"Kraken API error: {data['error']}")
        result = data.get('result', {})
        candle_data = None
        for key in result:
            if key != 'last':
                candle_data = result[key]
                break
        if not candle_data:
            raise RuntimeError("No candle data in Kraken response")
        candles = []
        for row in candle_data:
            candles.append(Candle5m(
                timestamp=float(row[0]), open=float(row[1]), high=float(row[2]),
                low=float(row[3]), close=float(row[4]), vwap=float(row[5]),
                volume=float(row[6]), count=int(row[7]),
            ))
        candles.sort(key=lambda c: c.timestamp)
        return candles

    def _fetch_futures(self, hours: int) -> List[Candle5m]:
        to_ts = int(time.time())
        from_ts = to_ts - (hours * 3600)
        url = f"{self.FUTURES_URL}?from={from_ts}&to={to_ts}"
        data = self._http_get(url)
        raw = data.get('candles', [])
        if not raw:
            raise RuntimeError("No candle data from Kraken Futures API")
        candles = []
        for row in raw:
            candles.append(Candle5m(
                timestamp=float(row.get('time', 0)) / 1000.0,
                open=float(row.get('open', 0)), high=float(row.get('high', 0)),
                low=float(row.get('low', 0)), close=float(row.get('close', 0)),
                vwap=0.0, volume=float(row.get('volume', 0)),
            ))
        candles.sort(key=lambda c: c.timestamp)
        return candles

    def _http_get(self, url: str) -> dict:
        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(url, headers={
                    'User-Agent': 'OracleProject-AdversaryV0/1.0',
                    'Accept': 'application/json',
                })
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read().decode('utf-8'))
            except (urllib.error.URLError, urllib.error.HTTPError,
                    TimeoutError, ConnectionError) as e:
                if attempt == self.max_retries - 1:
                    raise RuntimeError(f"Kraken API failed after {self.max_retries} attempts: {e}")
                time.sleep(2 ** attempt)
        return {}


def load_candles_from_csv(filepath: str) -> List[Candle5m]:
    import csv
    candles = []
    with open(filepath, 'r') as f:
        for row in csv.DictReader(f):
            candles.append(Candle5m(
                timestamp=float(row.get('timestamp', row.get('time', 0))),
                open=float(row.get('open', 0)), high=float(row.get('high', 0)),
                low=float(row.get('low', 0)), close=float(row.get('close', 0)),
                vwap=float(row.get('vwap', 0)), volume=float(row.get('volume', 0)),
                count=int(row.get('count', 0)),
            ))
    candles.sort(key=lambda c: c.timestamp)
    return candles


def load_oracle_from_csv(filepath: str) -> List[OracleTick]:
    """
    Load Oracle posterior history. SWAP-POINT: oracle_cap formula.
    If oracle_cap column missing, uses: max(0.1, 1.0 - 0.8 * posterior)
    Replace with your PosteriorGov_piecewise mapping.
    """
    import csv
    ticks = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        has_cap = 'oracle_cap' in fields
        has_l1 = ('l1' in fields or 'l1_structural' in fields)
        has_l2 = ('l2' in fields or 'l2_context' in fields)
        for row in reader:
            ts = float(row['timestamp'])
            post = float(row['posterior'])
            cap = float(row['oracle_cap']) if has_cap and row.get('oracle_cap', '').strip() else max(0.1, 1.0 - 0.8 * post)
            l1 = None
            if has_l1:
                raw = row.get('l1', row.get('l1_structural', '')).strip()
                if raw:
                    l1 = float(raw)
            l2 = None
            if has_l2:
                raw = row.get('l2', row.get('l2_context', '')).strip()
                if raw:
                    l2 = float(raw)
            ticks.append(OracleTick(timestamp=ts, posterior=post, oracle_cap=cap,
                                    l1_structural=l1, l2_context=l2))
    ticks.sort(key=lambda t: t.timestamp)
    return ticks


def load_events_from_csv(filepath: str) -> List:
    import csv
    from backtest import Crash72Event
    events = []
    with open(filepath, 'r') as f:
        for row in csv.DictReader(f):
            events.append(Crash72Event(
                start_time=float(row['start_time']),
                end_time=float(row['end_time']),
                drawdown_pct=float(row['drawdown_pct']),
                label=row.get('label', ''),
            ))
    events.sort(key=lambda e: e.start_time)
    return events
