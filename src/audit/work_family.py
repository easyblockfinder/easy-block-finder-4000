"""Job-id-independent work family fingerprint for duplicate-notify detection."""

from __future__ import annotations

import hashlib
from typing import Any, Iterable


def work_family_id(
    *,
    prevhash: str,
    coinb1: str,
    coinb2: str,
    merkle_branches: Iterable[str],
    version: str,
    nbits: str,
    ntime: str,
    extranonce1: str,
    extranonce2_size: int,
) -> str:
    parts = [
        (prevhash or "").lower().strip(),
        (coinb1 or "").lower().strip(),
        (coinb2 or "").lower().strip(),
        "|".join((b or "").lower().strip() for b in merkle_branches),
        (version or "").lower().strip(),
        (nbits or "").lower().strip(),
        (ntime or "").lower().strip(),
        (extranonce1 or "").lower().strip(),
        str(int(extranonce2_size)),
    ]
    blob = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]


def family_from_job(job: Any) -> str:
    return work_family_id(
        prevhash=job.prevhash,
        coinb1=job.coinb1,
        coinb2=job.coinb2,
        merkle_branches=job.merkle_branches,
        version=job.version,
        nbits=job.nbits,
        ntime=job.ntime,
        extranonce1=job.extranonce1,
        extranonce2_size=job.extranonce2_size,
    )
