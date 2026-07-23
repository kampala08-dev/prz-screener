"""Multi-depth zigzag — 1:1 port of the Pine ZIGZAG D* blocks.

Pine uses `ta.pivothigh(high, depth, depth)` / `ta.pivotlow(low, depth, depth)`:
a bar is a pivot high iff its `high` is strictly greater than the `high` of the
`depth` bars to its LEFT and the `depth` bars to its RIGHT (symmetric window).
The pivot is only *confirmed* `depth` bars after it occurs (lookahead-safe delay)
— but since we scan on the last bar over a fully-formed history, we simply detect
all confirmed pivots by scanning bars whose right window fits within the data.

After detecting each raw pivot, Pine folds consecutive same-direction pivots into
one, keeping the more extreme (higher high / lower low). We replicate that exactly,
including the `time[depth]` bookkeeping (here: the integer bar index of the pivot).

[PRECISION] deviation from the raw Pine port (see _snap_to_extremes):
Symmetric-window pivots use a strict `>` test, so twin peaks/troughs within
`depth` bars of each other can disqualify one another, leaving the zigzag
anchored on a lesser swing (or missing the true extreme entirely). After the
Pine-faithful pivot pass we re-anchor each pivot to the TRUE extreme high/low
of its leg (the interval between its neighbouring opposite pivots), processed
left-to-right so bar ordering and high/low alternation are preserved. This
makes XABCD legs land exactly on the most extreme wick of each swing.
"""

from typing import List, Tuple
import numpy as np


# A zigzag point: (price, bar_index, is_high)
ZPoint = Tuple[float, int, bool]


def _pivot_high(high: np.ndarray, i: int, depth: int) -> bool:
    """True if bar i is a pivot high with symmetric window `depth`.

    Matches ta.pivothigh: high[i] must be >= all in left window and >= all in
    right window, and strictly greater than at least the immediate neighbours.
    ta.pivothigh treats the pivot as the strict local max; ties on either side
    disqualify it. We use strict > against both windows (Pine semantics).
    """
    hv = high[i]
    for j in range(i - depth, i):
        if high[j] >= hv:
            return False
    for j in range(i + 1, i + depth + 1):
        if high[j] >= hv:
            return False
    return True


def _pivot_low(low: np.ndarray, i: int, depth: int) -> bool:
    lv = low[i]
    for j in range(i - depth, i):
        if low[j] <= lv:
            return False
    for j in range(i + 1, i + depth + 1):
        if low[j] <= lv:
            return False
    return True


def compute_zigzag(high: np.ndarray, low: np.ndarray, depth: int,
                   max_points: int = 20, snap: bool = True) -> List[ZPoint]:
    """Return the zigzag pivot list for a given depth.

    Replicates Pine's per-depth array (p*p / p*b / p*t) capped at `max_points`
    (Pine keeps the last 20 via `while size > 20: shift`).

    `snap=True` ([PRECISION]) re-anchors each pivot to the true extreme of its
    leg after the Pine-faithful pass — see _snap_to_extremes.
    """
    n = len(high)
    pts: List[ZPoint] = []  # each: [price, bar_index, is_high]

    # Iterate bars left->right; a pivot at i is confirmable once i+depth < n.
    # Pine processes bars in order and the "current" pivot is reported at bar
    # i+depth (time[depth] = the pivot's own bar). Order of detection here is
    # by pivot bar-index ascending, matching Pine's temporal push order.
    for i in range(depth, n - depth):
        is_ph = _pivot_high(high, i, depth)
        is_pl = _pivot_low(low, i, depth)

        # A bar can't be both; if degenerate, prefer high (Pine evals ph first).
        if is_ph:
            _merge(pts, high[i], i, True)
        if is_pl:
            _merge(pts, low[i], i, False)

    # [PRECISION] snap before capping so every pivot still has real neighbours.
    if snap:
        pts = _snap_to_extremes(pts, high, low, n)

    # Keep only the last `max_points` (Pine: while size>20 shift from front).
    if len(pts) > max_points:
        pts = pts[-max_points:]
    return [(p[0], p[1], p[2]) for p in pts]


def _snap_to_extremes(pts: list, high: np.ndarray, low: np.ndarray,
                      n: int) -> list:
    """[PRECISION] Re-anchor each pivot to the true extreme of its leg.

    For pivot k the leg interval is (bar[k-1], bar[k+1]) exclusive — for the
    first pivot the interval starts at bar 0, for the last it runs to n-1 (so
    a still-developing extreme after the last confirmed pivot is captured).
    Processing is left-to-right and the left bound uses the ALREADY-SNAPPED
    bar of pivot k-1, which guarantees strictly increasing bar indices and
    preserved high/low alternation.
    """
    if not pts:
        return pts
    out = [list(p) for p in pts]
    for k in range(len(out)):
        left = out[k - 1][1] + 1 if k > 0 else 0
        right = out[k + 1][1] - 1 if k < len(out) - 1 else n - 1
        if right < left:
            continue
        price, bar, is_high = out[k]
        if is_high:
            j = left + int(np.argmax(high[left:right + 1]))
            if high[j] > price:
                out[k] = [float(high[j]), j, True]
        else:
            j = left + int(np.argmin(low[left:right + 1]))
            if low[j] < price:
                out[k] = [float(low[j]), j, False]
    return out


def _merge(pts: list, price: float, bar_idx: int, is_high: bool) -> None:
    """Fold consecutive same-direction pivots, keeping the more extreme one.

    Mirrors the Pine push/set logic:
      if last pivot same direction: replace only if new is more extreme
      else: push new pivot.
    """
    if pts:
        last = pts[-1]
        if last[2] == is_high:
            if is_high:
                if price > last[0]:
                    pts[-1] = [price, bar_idx, is_high]
            else:
                if price < last[0]:
                    pts[-1] = [price, bar_idx, is_high]
            return
    pts.append([price, bar_idx, is_high])
