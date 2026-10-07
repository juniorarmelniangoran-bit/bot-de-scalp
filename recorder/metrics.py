# recorder/metrics.py -- Journal par minute (JSONL) : debit moyen/max par seconde

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MinuteAgg:
    # Pour une minute UTC donnee — WS : messages par seconde + spread + deconnexions
    minute_key: str = ""  # ex "2026-10-05T14:03:00Z"
    total_messages: int = 0
    per_second_counts: dict[int, int] = field(default_factory=dict)  # sec -> count
    gaps: int = 0
    last_seq: int | None = None
    disconnects: int = 0
    # Pour le lag on suit seulement les variations : min/max/moy du lag instantane
    lag_min_ns: int | None = None
    lag_max_ns: int | None = None
    lag_sum_ns: int = 0
    lag_n: int = 0
    # Spread (offer - bid) : min/avg/max par minute
    spread_min: float | None = None
    spread_max: float | None = None
    spread_sum: float = 0.0
    spread_n: int = 0

    def add(self, sec: int, seq: int | None, ts_recv: int | None, wall_ns: int) -> None:
        self.total_messages += 1
        self.per_second_counts[sec] = self.per_second_counts.get(sec, 0) + 1
        if seq is not None:
            self.last_seq = seq
        if ts_recv is not None:
            lag = wall_ns - int(ts_recv)
            if self.lag_min_ns is None or lag < self.lag_min_ns:
                self.lag_min_ns = lag
            if self.lag_max_ns is None or lag > self.lag_max_ns:
                self.lag_max_ns = lag
            self.lag_sum_ns += lag
            self.lag_n += 1

    def add_tick(self, wall_ns: int, bid: float | None, offer: float | None) -> None:
        """Ajoute un tick WS au calcul du spread pour la minute."""
        key, sec = minute_key_from_wall_ns(wall_ns)
        # Si cle differente, on laisse l'appelant gerer ; ici on met juste a jour le spread
        self.add(sec=sec, seq=None, ts_recv=None, wall_ns=wall_ns)
        if bid is not None and offer is not None:
            spread = float(offer) - float(bid)
            if self.spread_min is None or spread < self.spread_min:
                self.spread_min = spread
            if self.spread_max is None or spread > self.spread_max:
                self.spread_max = spread
            self.spread_sum += spread
            self.spread_n += 1

    def to_line(self) -> dict:
        counts = list(self.per_second_counts.values())
        avg_per_s = (sum(counts) / len(counts)) if counts else 0.0
        max_per_s = max(counts) if counts else 0
        lag_avg = (self.lag_sum_ns / self.lag_n) if self.lag_n else None
        spread_avg = (self.spread_sum / self.spread_n) if self.spread_n else None
        return {
            "minute": self.minute_key,
            "messages": self.total_messages,
            "avg_per_second": avg_per_s,
            "max_per_second": max_per_s,
            "gaps": self.gaps,
            "disconnects": self.disconnects,
            "last_seq": self.last_seq,
            "lag_min_ns": self.lag_min_ns,
            "lag_max_ns": self.lag_max_ns,
            "lag_avg_ns": lag_avg,
            "spread_min": self.spread_min,
            "spread_avg": spread_avg,
            "spread_max": self.spread_max,
        }


def minute_key_from_wall_ns(wall_ns: int) -> tuple[str, int]:
    """Retourne (cle minute UTC ISO, seconde dans la minute 0-59)."""
    # wall_ns en nanosecondes UTC
    sec = int(wall_ns // 1_000_000_000)
    # gmtime pour UTC
    tm = time.gmtime(sec)
    key = time.strftime("%Y-%m-%dT%H:%M:00Z", tm)
    return key, tm.tm_sec


def append_minute_line(path: Path, agg: MinuteAgg) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(agg.to_line()) + "\n")
