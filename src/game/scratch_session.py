"""Scratch board state: tile lifecycle, queue, partial resume, board identity."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from game.tile_space import (
    GAME_GPU_CHUNK,
    TILE_COUNT,
    tile_nonce_range,
)


class TileState(str, Enum):
    UNOPENED = "UNOPENED"
    QUEUED = "QUEUED"
    MINING = "MINING"
    COMPLETED = "COMPLETED"
    INTERRUPTED = "INTERRUPTED"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class BoardIdentity:
    board_id: str
    session_id: int
    job_id: str
    header_prefix: bytes
    extranonce2_hex: str
    prevhash: str
    ntime: str
    nbits: str
    generation: int

    def matches_snapshot(
        self,
        *,
        session_id: int,
        job_id: str,
        header_prefix: bytes,
        extranonce2_hex: str,
    ) -> bool:
        return (
            int(session_id) == int(self.session_id)
            and str(job_id) == str(self.job_id)
            and bytes(header_prefix) == bytes(self.header_prefix)
            and str(extranonce2_hex) == str(self.extranonce2_hex)
        )


@dataclass
class TileResult:
    tile_id: int
    state: TileState
    start_nonce: int
    end_nonce: int
    next_nonce: int
    hashes: int = 0
    best_difficulty: float | None = None
    best_hash_be_hex: str | None = None
    best_nonce: int | None = None
    share_candidates: int = 0
    accepted: int = 0
    rejected: int = 0
    processing_time_s: float = 0.0
    detail: str = ""


@dataclass
class TileWorkChunk:
    """One GPU micro-batch belonging to a board+tile."""

    board_id: str
    tile_id: int
    start_nonce: int
    count: int
    tile_end: int


@dataclass
class ScratchSession:
    board: BoardIdentity
    # Allow scratching an entire island without stalling on queue-full.
    max_queue: int = TILE_COUNT
    gpu_chunk: int = GAME_GPU_CHUNK
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _tiles: list[TileResult] = field(default_factory=list, repr=False)
    _queue: list[int] = field(default_factory=list, repr=False)
    _active_tile: int | None = None
    created_at: float = field(default_factory=time.time)
    hashing_time_s: float = 0.0
    select_wait_s: float = 0.0
    transition_time_s: float = 0.0

    def __post_init__(self) -> None:
        if not self._tiles:
            self._tiles = [
                TileResult(
                    tile_id=i,
                    state=TileState.UNOPENED,
                    start_nonce=tile_nonce_range(i)[0],
                    end_nonce=tile_nonce_range(i)[1],
                    next_nonce=tile_nonce_range(i)[0],
                )
                for i in range(TILE_COUNT)
            ]

    @staticmethod
    def new_board(
        *,
        session_id: int,
        job_id: str,
        header_prefix: bytes,
        extranonce2_hex: str,
        prevhash: str,
        ntime: str,
        nbits: str,
        generation: int,
        max_queue: int = TILE_COUNT,
        gpu_chunk: int = GAME_GPU_CHUNK,
    ) -> "ScratchSession":
        ident = BoardIdentity(
            board_id=str(uuid.uuid4()),
            session_id=int(session_id),
            job_id=str(job_id),
            header_prefix=bytes(header_prefix),
            extranonce2_hex=str(extranonce2_hex),
            prevhash=str(prevhash),
            ntime=str(ntime),
            nbits=str(nbits),
            generation=int(generation),
        )
        return ScratchSession(
            board=ident, max_queue=max_queue, gpu_chunk=int(gpu_chunk)
        )

    def tiles_revealed(self) -> int:
        with self._lock:
            return sum(1 for t in self._tiles if t.state == TileState.COMPLETED)

    def all_completed(self) -> bool:
        with self._lock:
            return all(t.state == TileState.COMPLETED for t in self._tiles)

    def snapshot_tiles(self) -> list[TileResult]:
        with self._lock:
            return [TileResult(**t.__dict__) for t in self._tiles]

    def get_tile(self, tile_id: int) -> TileResult:
        with self._lock:
            t = self._tiles[int(tile_id)]
            return TileResult(**t.__dict__)

    def enqueue(self, tile_id: int) -> tuple[bool, str]:
        """Queue an unopened/interrupted tile. Never re-queue COMPLETED."""
        tid = int(tile_id)
        with self._lock:
            if tid < 0 or tid >= TILE_COUNT:
                return False, "invalid tile"
            t = self._tiles[tid]
            if t.state == TileState.COMPLETED:
                return False, "already completed"
            if t.state == TileState.INVALIDATED:
                return False, "invalidated"
            if t.state in (TileState.QUEUED, TileState.MINING):
                return False, "already queued"
            if tid in self._queue:
                return False, "already queued"
            if len(self._queue) >= int(self.max_queue):
                return False, "queue full"
            if t.next_nonce >= t.end_nonce:
                t.state = TileState.COMPLETED
                return False, "already completed"
            t.state = TileState.QUEUED
            self._queue.append(tid)
            return True, "queued"

    def peek_queue(self) -> list[int]:
        with self._lock:
            return list(self._queue)

    def next_chunk(self) -> Optional[TileWorkChunk]:
        """Pop next GPU chunk for the head queue tile (or continue active)."""
        with self._lock:
            if self._active_tile is None:
                while self._queue:
                    tid = self._queue.pop(0)
                    t = self._tiles[tid]
                    if t.state in (TileState.INVALIDATED, TileState.COMPLETED):
                        continue
                    if t.next_nonce >= t.end_nonce:
                        t.state = TileState.COMPLETED
                        continue
                    self._active_tile = tid
                    t.state = TileState.MINING
                    break
            tid = self._active_tile
            if tid is None:
                return None
            t = self._tiles[tid]
            if t.state == TileState.INVALIDATED:
                self._active_tile = None
                return None
            remaining = t.end_nonce - t.next_nonce
            if remaining <= 0:
                t.state = TileState.COMPLETED
                self._active_tile = None
                return None
            take = min(int(self.gpu_chunk), remaining)
            return TileWorkChunk(
                board_id=self.board.board_id,
                tile_id=tid,
                start_nonce=int(t.next_nonce),
                count=take,
                tile_end=int(t.end_nonce),
            )

    def apply_chunk_progress(
        self,
        chunk: TileWorkChunk,
        *,
        scanned: int,
        processing_time_s: float = 0.0,
        best_difficulty: float | None = None,
        best_hash_be_hex: str | None = None,
        best_nonce: int | None = None,
        share_candidates: int = 0,
        interrupted: bool = False,
    ) -> TileResult:
        with self._lock:
            if chunk.board_id != self.board.board_id:
                # Stale board chunk — ignore
                return TileResult(
                    tile_id=chunk.tile_id,
                    state=TileState.INVALIDATED,
                    start_nonce=0,
                    end_nonce=0,
                    next_nonce=0,
                    detail="stale board",
                )
            t = self._tiles[chunk.tile_id]
            if t.state == TileState.INVALIDATED:
                return TileResult(**t.__dict__)
            scanned_i = max(0, int(scanned))
            # Advance only the contiguous prefix actually scanned from chunk.start
            advanced = min(scanned_i, chunk.count)
            expected_next = chunk.start_nonce + advanced
            if expected_next > t.next_nonce:
                t.next_nonce = min(expected_next, t.end_nonce)
            t.hashes += advanced
            t.processing_time_s += max(0.0, float(processing_time_s))
            self.hashing_time_s += max(0.0, float(processing_time_s))
            t.share_candidates += max(0, int(share_candidates))
            if best_difficulty is not None:
                if t.best_difficulty is None or float(best_difficulty) > float(
                    t.best_difficulty
                ):
                    t.best_difficulty = float(best_difficulty)
                    t.best_hash_be_hex = best_hash_be_hex
                    t.best_nonce = best_nonce
            if interrupted:
                if t.next_nonce >= t.end_nonce:
                    t.state = TileState.COMPLETED
                    self._active_tile = None
                else:
                    t.state = TileState.INTERRUPTED
                    self._active_tile = None
            elif t.next_nonce >= t.end_nonce:
                t.state = TileState.COMPLETED
                self._active_tile = None
            else:
                t.state = TileState.MINING
            return TileResult(**t.__dict__)

    def note_share_outcome(self, tile_id: int, *, accepted: bool) -> None:
        with self._lock:
            t = self._tiles[int(tile_id)]
            if accepted:
                t.accepted += 1
            else:
                t.rejected += 1

    def interrupt_active(self, reason: str = "") -> None:
        with self._lock:
            if self._active_tile is None:
                return
            t = self._tiles[self._active_tile]
            if t.state == TileState.MINING:
                t.state = TileState.INTERRUPTED
                if reason:
                    t.detail = reason
            self._active_tile = None

    def invalidate_board(self, reason: str = "job invalidated") -> None:
        with self._lock:
            self._queue.clear()
            self._active_tile = None
            for t in self._tiles:
                if t.state != TileState.COMPLETED:
                    t.state = TileState.INVALIDATED
                    t.detail = reason

    def metrics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "board_id": self.board.board_id,
                "job_id": self.board.job_id,
                "session_id": self.board.session_id,
                "extranonce2": self.board.extranonce2_hex,
                "prevhash": self.board.prevhash,
                "tiles_revealed": sum(
                    1 for t in self._tiles if t.state == TileState.COMPLETED
                ),
                "tiles_total": TILE_COUNT,
                "queue_len": len(self._queue),
                "hashing_time_s": self.hashing_time_s,
                "all_completed": all(
                    t.state == TileState.COMPLETED for t in self._tiles
                ),
            }
