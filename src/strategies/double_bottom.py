from __future__ import annotations

import pandas as pd

from src.strategies.base import Strategy, hits_from_mask, strategy_features

_TROUGH_WINDOW = 5
_MIN_TROUGH_GAP = 5
_MAX_BOTTOM_DEVIATION = 0.03
_FRESH_BREAKOUT_DAYS = 5


def _detect_double_bottom(frame: pd.DataFrame) -> bool:
    """在单只股票最近 60 根日K中检测双底颈线突破。

    参考口径：相邻两个局部低点（邻域 ±5 根）间隔 >= 5 根且谷值差 <= 3%，
    颈线取两谷之间最高价，要求收盘站上颈线且突破发生在最近 5 日内。
    """
    if len(frame) < _MIN_TROUGH_GAP * 2 + 2:
        return False
    low = frame["low"].to_numpy(dtype=float)
    high = frame["high"].to_numpy(dtype=float)
    close = frame["close"].to_numpy(dtype=float)
    size = len(frame)

    troughs: list[int] = []
    for index in range(_TROUGH_WINDOW, size - _TROUGH_WINDOW):
        neighborhood = low[index - _TROUGH_WINDOW : index + _TROUGH_WINDOW + 1]
        if low[index] > neighborhood.min():
            continue
        # 平台期连续多根同为低点时只保留第一根，避免同一段底重复计数
        if troughs and index - troughs[-1] <= _TROUGH_WINDOW:
            continue
        troughs.append(index)
    if len(troughs) < 2:
        return False

    first, second = troughs[-2], troughs[-1]
    if second - first < _MIN_TROUGH_GAP:
        return False
    bottom_floor = min(low[first], low[second])
    if abs(low[first] - low[second]) / bottom_floor > _MAX_BOTTOM_DEVIATION:
        return False

    neckline = float(high[first : second + 1].max())
    if not close[-1] > neckline:
        return False
    breakout_index = next(
        (index for index in range(second + 1, size) if close[index] > neckline),
        None,
    )
    return breakout_index is not None and size - 1 - breakout_index < _FRESH_BREAKOUT_DAYS


class DoubleBottomStrategy(Strategy):
    key = "double_bottom"
    name = "双底颈线突破"
    family = "pattern"
    description = "两个相近低点构筑双底后，近期放量站稳颈线之上"
    score = 35

    def evaluate(self, daily, report_date, factors, features=None) -> pd.DataFrame:
        latest = strategy_features(daily, report_date, factors, features)
        history = daily[daily["trade_date"] <= report_date].sort_values(["code", "trade_date"])
        history = history[history["code"].isin(set(latest["code"]))]
        window = history.groupby("code", sort=False).tail(60)
        hit_codes = set()
        if not latest.empty and not window.empty:
            pool = set(latest["code"])
            hit_codes = {
                code
                for code, frame in window.groupby("code", sort=False)
                if code in pool and _detect_double_bottom(frame)
            }
        mask = latest["code"].isin(hit_codes)
        return hits_from_mask(
            latest, mask, self.name, self.score, "双底形态完成且突破颈线", key=self.key, family=self.family
        )
