"""Active mining operation, fixed WorkBatch snapshot, and nonce/extranonce management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .bitcoin import (
    bits_to_target,
    build_block_header,
    build_coinbase,
    build_merkle_root,
    extranonce2_bytes,
    header_hash,
    midstate_from_header,
    nonce_to_submit_hex,
    rebuild_header_from_submit,
    share_target_from_difficulty,
    verify_header_against_targets,
)
from .search_strategy import (
    SearchStrategy,
    affine_from_seed,
    batch_nonce_base,
    seed_fingerprint,
    seed_material,
)


@dataclass(frozen=True)
class JobSnapshot:
    """
    Immutable job copy for GPU batch / share submission.
    header_prefix + midstate + targets travel together; live job buffer is not used.
    """

    job_id: str
    prevhash: str
    coinb1: str
    coinb2: str
    merkle_branches: tuple[str, ...]
    version: str
    nbits: str
    ntime: str
    extranonce1: str
    extranonce2_size: int
    extranonce2_hex: str
    difficulty: float
    generation: int
    diff_at_notify: float
    header_prefix: bytes  # 76 bayt
    midstate: bytes  # 32 bayt
    merkle_root: bytes
    share_target_value: int
    network_target_value: int
    # If true, mining.submit is prohibited for this snapshot (overridden with clean_jobs=true)
    submit_forbidden: bool = False
    # clean=true / increasing epoch at session change — all old batches are invalid
    validity_epoch: int = 0
    session_id: int = 0

    def share_target(self) -> int:
        return self.share_target_value

    def network_target(self) -> int:
        return self.network_target_value

    def is_submittable(self, current_epoch: int, current_session: int) -> bool:
        if self.submit_forbidden:
            return False
        if self.validity_epoch != current_epoch:
            return False
        if self.session_id != current_session:
            return False
        return True

    def rebuild_from_submit(self, nonce: int) -> dict:
        return rebuild_header_from_submit(
            version_hex=self.version,
            prevhash_hex=self.prevhash,
            coinb1_hex=self.coinb1,
            coinb2_hex=self.coinb2,
            merkle_branches=self.merkle_branches,
            extranonce1_hex=self.extranonce1,
            extranonce2_hex=self.extranonce2_hex,
            ntime_hex=self.ntime,
            nbits_hex=self.nbits,
            nonce_hex=nonce_to_submit_hex(nonce),
        )

    def header_for_nonce(self, nonce: int) -> bytes:
        return self.header_prefix + (nonce & 0xFFFFFFFF).to_bytes(4, "little")

    def verify_nonce(self, nonce: int) -> Optional[dict]:
        """Verify only with this snapshot — do not look at the live MiningJob buffer."""
        if self.submit_forbidden:
            return None
        rebuilt = self.rebuild_from_submit(nonce)
        expected = self.header_for_nonce(nonce)
        if rebuilt["header"] != expected:
            return None
        result = verify_header_against_targets(
            rebuilt["header"], self.share_target_value, self.network_target_value
        )
        # The result that achieves the network goal is not filtered out by the share filter.
        if not result["meets_share"] and not result["meets_network"]:
            return None
        submit_nonce = nonce_to_submit_hex(nonce)
        if submit_nonce != rebuilt["nonce_submit_hex"] or rebuilt["nonce"] != nonce:
            return None
        return {
            "nonce": nonce,
            "nonce_hex": submit_nonce,
            "extranonce2": self.extranonce2_hex,
            "ntime": self.ntime,
            "job_id": self.job_id,
            "generation": self.generation,
            "difficulty": self.difficulty,
            "diff_at_notify": self.diff_at_notify,
            "share_target": self.share_target_value,
            "network_target": self.network_target_value,
            "header": rebuilt["header"],
            "hash_hex": rebuilt["hash_be_hex"],
            "hash_be_hex": rebuilt["hash_be_hex"],
            "hash_le_hex": rebuilt["hash_le_hex"],
            "merkle_root_hex": rebuilt["merkle_root"].hex(),
            "snapshot": self,
            "rebuild": rebuilt,
            "buffer_header_match": True,
            **result,
        }


@dataclass(frozen=True)
class WorkBatch:
    """allocate_batch result: logical scan window + immutable snapshot."""

    snapshot: JobSnapshot
    start_nonce: int  # GPU nonce_base (strategy-dependent)
    count: int
    logical_start: int = 0
    strategy: str = "sequential"
    affine_a: int = 1
    affine_b: int = 0
    seed_fp: str = ""

    @property
    def job_id(self) -> str:
        return self.snapshot.job_id

    @property
    def validity_epoch(self) -> int:
        return self.snapshot.validity_epoch

    @property
    def session_id(self) -> int:
        return self.snapshot.session_id

    def header80(self) -> bytes:
        # Kernel overwrites nonce; midstate/tail come from current header prefix.
        return self.snapshot.header_for_nonce(0)

    def is_submittable(self, current_epoch: int, current_session: int) -> bool:
        return self.snapshot.is_submittable(current_epoch, current_session)


@dataclass
class MiningJob:
    job_id: str
    prevhash: str
    coinb1: str
    coinb2: str
    merkle_branches: list[str]
    version: str
    nbits: str
    ntime: str
    clean_jobs: bool
    extranonce1: str
    extranonce2_size: int
    difficulty: float
    diff_at_notify: float = 0.0

    extranonce2: int = 0
    nonce: int = 0  # logical cursor in [0, 2^32)
    generation: int = 0
    # superseded: clean=false — yeni tahsis yok, in-flight submit OK
    superseded: bool = False
    # invalidated: clean=true / session dropped — in-flight submit prohibited
    invalidated: bool = False
    search_strategy: SearchStrategy = SearchStrategy.SEQUENTIAL
    _strategy_seed_fp: str = field(default="", repr=False)
    _affine_a: int = field(default=1, repr=False)
    _affine_b: int = field(default=0, repr=False)

    _merkle_root: bytes = field(default=b"", repr=False)
    _header_prefix: bytes = field(default=b"", repr=False)
    _midstate: bytes = field(default=b"", repr=False)
    _midstate_key: bytes = field(default=b"", repr=False)
    _tail: bytes = field(default=b"", repr=False)
    _needs_extranonce_bump: bool = field(default=False, repr=False)

    @property
    def revoked(self) -> bool:
        """Retroactive: no new allocation can be made."""
        return self.superseded or self.invalidated

    @revoked.setter
    def revoked(self, value: bool) -> None:
        if value:
            self.invalidated = True
        else:
            self.invalidated = False
            self.superseded = False

    def network_target(self) -> int:
        return bits_to_target(self.nbits)

    def share_target(self) -> int:
        return share_target_from_difficulty(self.difficulty)

    def accept_new_work(self) -> bool:
        return not self.superseded and not self.invalidated

    def submit_allowed(self) -> bool:
        return not self.invalidated

    def snapshot(
        self,
        *,
        validity_epoch: int = 0,
        session_id: int = 0,
    ) -> JobSnapshot:
        if len(self._header_prefix) != 76 or len(self._midstate) != 32:
            self.rebuild_work()
        return JobSnapshot(
            job_id=self.job_id,
            prevhash=self.prevhash,
            coinb1=self.coinb1,
            coinb2=self.coinb2,
            merkle_branches=tuple(self.merkle_branches),
            version=self.version,
            nbits=self.nbits,
            ntime=self.ntime,
            extranonce1=self.extranonce1,
            extranonce2_size=self.extranonce2_size,
            extranonce2_hex=self.extranonce2_hex(),
            difficulty=float(self.difficulty),
            generation=self.generation,
            diff_at_notify=float(self.diff_at_notify or self.difficulty),
            header_prefix=bytes(self._header_prefix),
            midstate=bytes(self._midstate),
            merkle_root=bytes(self._merkle_root),
            share_target_value=self.share_target(),
            network_target_value=self.network_target(),
            submit_forbidden=self.invalidated,
            validity_epoch=int(validity_epoch),
            session_id=int(session_id),
        )

    def rebuild_work(self) -> None:
        en2 = extranonce2_bytes(self.extranonce2, self.extranonce2_size)
        coinbase = build_coinbase(self.coinb1, self.extranonce1, en2, self.coinb2)
        self._merkle_root = build_merkle_root(coinbase, self.merkle_branches)
        header = build_block_header(
            self.version,
            self.prevhash,
            self._merkle_root,
            self.ntime,
            self.nbits,
            0,
        )
        self._header_prefix = header[:76]
        self._tail = header[64:76]
        key = header[:64]
        if key != self._midstate_key or not self._midstate:
            self._midstate = midstate_from_header(header)
            self._midstate_key = key

    def extranonce2_hex(self) -> str:
        return extranonce2_bytes(self.extranonce2, self.extranonce2_size).hex()

    def configure_search_strategy(
        self,
        strategy: SearchStrategy | str,
        *,
        work_family_id: str = "",
        session_salt: str = "",
    ) -> None:
        """Bind strategy + seed for this job (call on create / after en2 bump)."""
        if isinstance(strategy, str):
            strategy = SearchStrategy(strategy)
        self.search_strategy = strategy
        seed = seed_material(
            work_family_id=work_family_id or self.job_id,
            extranonce2_hex=self.extranonce2_hex(),
            strategy=strategy,
            session_salt=session_salt,
        )
        self._strategy_seed_fp = seed_fingerprint(seed)
        if strategy is SearchStrategy.RANDOMIZED:
            aff = affine_from_seed(seed)
            self._affine_a = int(aff.a)
            self._affine_b = int(aff.b)
        else:
            self._affine_a = 1
            self._affine_b = 0

    def allocate_batch(
        self,
        count: int,
        *,
        validity_epoch: int = 0,
        session_id: int = 0,
        work_family_id: str = "",
    ) -> Optional[WorkBatch]:
        """
        Logical cursor allocate + immutable snapshot.
        Final 2^32 logical slice uses the OLD extranonce/header; bump next allocate.
        """
        if not self.accept_new_work():
            return None
        if self._needs_extranonce_bump:
            self._bump_extranonce2(work_family_id=work_family_id)
            self._needs_extranonce_bump = False
            self.nonce = 0

        start = int(self.nonce) & 0xFFFFFFFF
        space = 0x100000000 - start
        if space <= 0:
            self._bump_extranonce2(work_family_id=work_family_id)
            start = 0
            space = 0x100000000

        take = min(int(count), space)
        if take <= 0:
            return None

        snap = self.snapshot(validity_epoch=validity_epoch, session_id=session_id)
        base = batch_nonce_base(start, self.search_strategy)
        batch = WorkBatch(
            snapshot=snap,
            start_nonce=int(base),
            count=take,
            logical_start=start,
            strategy=self.search_strategy.value,
            affine_a=int(self._affine_a),
            affine_b=int(self._affine_b),
            seed_fp=str(self._strategy_seed_fp),
        )
        nxt = start + take
        if nxt >= 0x100000000:
            self.nonce = 0
            self._needs_extranonce_bump = True
        else:
            self.nonce = nxt
        return batch

    def advance_nonce_range(self, count: int) -> tuple[int, int]:
        """Backfill wrapper — uses allocate_batch."""
        batch = self.allocate_batch(count)
        if batch is None:
            return 0, 0
        return batch.start_nonce, batch.count

    def bump_extranonce2(self, *, work_family_id: str = "") -> None:
        """Advance extranonce2 and rebuild coinbase/Merkle/midstate (Game Mode boards)."""
        self._bump_extranonce2(work_family_id=work_family_id)

    def _bump_extranonce2(self, *, work_family_id: str = "") -> None:
        limit = 1 << (8 * self.extranonce2_size)
        self.extranonce2 = (self.extranonce2 + 1) % limit
        self.rebuild_work()
        # Refresh affine seed for new extranonce2 (same strategy)
        self.configure_search_strategy(
            self.search_strategy,
            work_family_id=work_family_id or self.job_id,
        )

    def header_for_nonce(self, nonce: int) -> bytes:
        return self._header_prefix + nonce.to_bytes(4, "little")

    def cpu_scan(self, start_nonce: int, count: int) -> list[dict]:
        hits: list[dict] = []
        snap = self.snapshot()
        for n in range(start_nonce, start_nonce + count):
            if self.invalidated:
                break
            verified = snap.verify_nonce(n)
            if verified:
                hits.append(verified)
        return hits

    def verify_candidate(
        self,
        nonce: int,
        snapshot: Optional[JobSnapshot] = None,
    ) -> Optional[dict]:
        snap = snapshot or self.snapshot()
        # snap.submit_forbidden if the live job is invalidated and the snap comes from the previously valid job
        # snap looks at its own flag; snap.submit_forbidden remains False in superseded.
        return snap.verify_nonce(nonce)

    def mark_superseded(self) -> None:
        """clean_jobs=false: yeni tahsis yok, mevcut snapshot submit OK."""
        self.superseded = True

    def mark_invalidated(self) -> None:
        """clean_jobs=true / session loss: submit prohibited."""
        self.invalidated = True


def job_from_notify(
    params: list,
    extranonce1: str,
    extranonce2_size: int,
    difficulty: float,
    generation: int,
) -> MiningJob:
    diff = float(difficulty)
    job = MiningJob(
        job_id=params[0],
        prevhash=params[1],
        coinb1=params[2],
        coinb2=params[3],
        merkle_branches=list(params[4]),
        version=params[5],
        nbits=params[6],
        ntime=params[7],
        clean_jobs=bool(params[8]),
        extranonce1=extranonce1,
        extranonce2_size=extranonce2_size,
        difficulty=diff,
        diff_at_notify=diff,
        generation=generation,
    )
    job.rebuild_work()
    return job
