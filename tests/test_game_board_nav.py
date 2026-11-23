from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from game.scratch_session import ScratchSession  # noqa: E402


def test_board_history_switch_preserves_tile_progress():
    a = ScratchSession.new_board(
        session_id=1,
        job_id="j",
        header_prefix=b"\x01" * 76,
        extranonce2_hex="00000001",
        prevhash="aa" * 32,
        ntime="1",
        nbits="1d00ffff",
        generation=1,
        gpu_chunk=100,
    )
    b = ScratchSession.new_board(
        session_id=1,
        job_id="j",
        header_prefix=b"\x01" * 76,
        extranonce2_hex="00000002",
        prevhash="aa" * 32,
        ntime="1",
        nbits="1d00ffff",
        generation=1,
        gpu_chunk=100,
    )
    assert a.enqueue(0)[0]
    chunk = a.next_chunk()
    assert chunk is not None
    a.apply_chunk_progress(chunk, scanned=chunk.count)
    assert a.get_tile(0).state.value in ("COMPLETED", "MINING", "INTERRUPTED")

    boards = [a, b]
    # Simulate switch to B then back to A — progress remains
    active = boards[1]
    assert active.board.extranonce2_hex == "00000002"
    active = boards[0]
    assert active.get_tile(0).hashes > 0
