from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from game.scratch_session import ScratchSession, TileState  # noqa: E402
from game.tile_space import TILE_NONCE_COUNT  # noqa: E402


def _board(**kw):
    base = dict(
        session_id=1,
        job_id="j1",
        header_prefix=b"\x00" * 76,
        extranonce2_hex="00000000",
        prevhash="aa" * 32,
        ntime="1d00ffff",
        nbits="1d00ffff",
        generation=1,
        gpu_chunk=1000,
        max_queue=3,
    )
    base.update(kw)
    return ScratchSession.new_board(**base)


def test_enqueue_and_no_double():
    s = _board()
    ok, _ = s.enqueue(0)
    assert ok
    ok2, msg = s.enqueue(0)
    assert not ok2
    assert "queued" in msg or "already" in msg


def test_completed_not_recomputed():
    s = _board(gpu_chunk=TILE_NONCE_COUNT)
    assert s.enqueue(0)[0]
    chunk = s.next_chunk()
    assert chunk is not None
    assert chunk.count == TILE_NONCE_COUNT
    res = s.apply_chunk_progress(chunk, scanned=TILE_NONCE_COUNT)
    assert res.state == TileState.COMPLETED
    ok, msg = s.enqueue(0)
    assert not ok
    assert "completed" in msg


def test_partial_resume():
    s = _board(gpu_chunk=100)
    assert s.enqueue(5)[0]
    c1 = s.next_chunk()
    assert c1 is not None and c1.start_nonce == tile_start(5)
    s.apply_chunk_progress(c1, scanned=100, interrupted=True)
    t = s.get_tile(5)
    assert t.state == TileState.INTERRUPTED
    assert t.next_nonce == tile_start(5) + 100
    assert s.enqueue(5)[0]
    c2 = s.next_chunk()
    assert c2 is not None
    assert c2.start_nonce == tile_start(5) + 100


def tile_start(tid: int) -> int:
    return tid * TILE_NONCE_COUNT


def test_queue_limit():
    s = _board(max_queue=2)
    assert s.enqueue(0)[0]
    assert s.enqueue(1)[0]
    ok, msg = s.enqueue(2)
    assert not ok
    assert "queue" in msg


def test_invalidate_drops_queue_and_marks():
    s = _board()
    s.enqueue(0)
    s.enqueue(1)
    s.invalidate_board("clean")
    assert s.peek_queue() == []
    assert s.get_tile(0).state == TileState.INVALIDATED
    assert s.get_tile(1).state == TileState.INVALIDATED


def test_stale_board_chunk_ignored():
    s = _board()
    s.enqueue(0)
    chunk = s.next_chunk()
    assert chunk is not None
    # Forge wrong board id
    bad = type(chunk)(
        board_id="other",
        tile_id=chunk.tile_id,
        start_nonce=chunk.start_nonce,
        count=chunk.count,
        tile_end=chunk.tile_end,
    )
    res = s.apply_chunk_progress(bad, scanned=chunk.count)
    assert res.state == TileState.INVALIDATED
    # Original tile still mining / not fully advanced by stale
    t = s.get_tile(0)
    assert t.next_nonce == chunk.start_nonce
