# recorder/companion.py -- Fichier compagnon 1 ligne/seconde + horloge SNTP simple

from __future__ import annotations

import json
import socket
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SecondBucket:
    count: int = 0
    first_seq: int | None = None
    last_seq: int | None = None
    first_ts_recv: int | None = None
    last_ts_recv: int | None = None

    def add(self, seq: int | None, ts_recv: int | None) -> None:
        self.count += 1
        if seq is not None:
            if self.first_seq is None:
                self.first_seq = seq
            self.last_seq = seq
        if ts_recv is not None:
            if self.first_ts_recv is None:
                self.first_ts_recv = ts_recv
            self.last_ts_recv = ts_recv


def companion_path_for_dbn(dbn_path: Path) -> Path:
    return dbn_path.with_suffix("") .parent / (dbn_path.stem + ".recv.jsonl")


def append_second_line(
    companion_path: Path,
    wall_ns: int,
    mono_ns: int,
    bucket: SecondBucket,
) -> None:
    line = {
        "wall_ns": wall_ns,
        "mono_ns": mono_ns,
        "count": bucket.count,
        "first_seq": bucket.first_seq,
        "last_seq": bucket.last_seq,
        "first_ts_recv": bucket.first_ts_recv,
        "last_ts_recv": bucket.last_ts_recv,
    }
    companion_path.parent.mkdir(parents=True, exist_ok=True)
    with open(companion_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


# --- Horloge : mesure d'ecart SNTP simple (stdlib only) ---

NTP_EPOCH_OFFSET = 2_208_988_800  # secondes entre 1900 et 1970

def sntp_offset_seconds(server: str = "time.windows.com", timeout: float = 3.0) -> float | None:
    """Retourne (t_serveur - t_local) en secondes, ou None si echec.

    Utilise UDP SNTP sans dependance. Ne corrige pas l'horloge, mesure seulement.
    """
    try:
        # Requete SNTP : LI=0, VN=3, Mode=3, puis zeros
        pkt = b"\x1b" + 47 * b"\x00"
        t0_mono = time.monotonic()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.sendto(pkt, (server, 123))
            data, _ = s.recvfrom(512)
        t1_mono = time.monotonic()
        if len(data) < 48:
            return None
        # Transmit timestamp du serveur a l'offset 40 (8 octets : sec + frac)
        sec, frac = struct.unpack("!II", data[40:48])
        server_sec = sec - NTP_EPOCH_OFFSET + frac / 2**32
        # On approxime t_local au milieu de l'aller-retour
        rtt = t1_mono - t0_mono
        local_sec = time.time() + rtt / 2.0 - rtt  # time.time() deja proche de t1
        # Plus simple : on compare server_sec a time.time() mesure juste apres recv
        # On utilise time.time() comme t_local
        return server_sec - time.time()
    except Exception:
        return None


def append_clock_offset(path: Path, wall_ns: int, offset_s: float | None, server: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"wall_ns": wall_ns, "server": server, "offset_s": offset_s}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
