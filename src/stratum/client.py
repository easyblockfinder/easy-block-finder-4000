"""Solo CKPool Stratum V1 istemcisi."""

from __future__ import annotations

import json
import logging
import socket
import ssl
import threading
import time
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

DEFAULT_HOST = "stratum.ckpool.org"
DEFAULT_PORT = 3333
RECV_TIMEOUT = 30.0
RECONNECT_BASE = 2.0
RECONNECT_MAX = 60.0


class StratumClient:
    """
    mining.subscribe / authorize / notify / set_difficulty / submit.
    Worker name = Bitcoin payout address. No bundled default address.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        on_job: Optional[Callable[[list, bool], None]] = None,
        on_difficulty: Optional[Callable[[float], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_submit_result: Optional[Callable[[bool, str, Any], None]] = None,
        suggest_difficulty: Optional[float] = 1.0,
        password: str = "x",
        use_tls: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.on_job = on_job
        self.on_difficulty = on_difficulty
        self.on_status = on_status
        self.on_submit_result = on_submit_result
        self.suggest_difficulty = suggest_difficulty
        self.password = password or "x"
        # TLS always uses system trust store + hostname check. No insecure bypass.
        self.use_tls = bool(use_tls)

        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._msg_id = 0
        self._pending: dict[int, dict] = {}
        self._stop = threading.Event()
        self._reader: Optional[threading.Thread] = None
        self._watchdog: Optional[threading.Thread] = None

        self.extranonce1: str = ""
        self.extranonce2_size: int = 4
        self.difficulty: float = 1.0
        self.server_set_difficulty: Optional[float] = None
        self.authorized = False
        self.subscribed = False
        self.connected = False
        self.address: str = ""
        self._buffer = b""
        self._last_activity = 0.0
        # New session ID for each successful handshake
        self.session_id: int = 0
        # request id → submit log (request + response)
        self.submit_log: list[dict[str, Any]] = []
        # Raw stratum events (subscribe / notify / set_difficulty sequence)
        self.wire_log: list[dict[str, Any]] = []
        self.last_subscribe_raw: Any = None

    def _set_status(self, text: str) -> None:
        if self.on_status:
            self.on_status(text)

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def allocate_request_id(self) -> int:
        """Separate the ID before submission for Submit record mapping."""
        with self._lock:
            return self._next_id()

    def start(self, address: str) -> None:
        self.address = address.strip()
        if not self.address:
            raise ValueError("Bitcoin payout address required.")
        self._stop.clear()
        self._watchdog = threading.Thread(target=self._run_loop, name="stratum-loop", daemon=True)
        self._watchdog.start()

    def stop(self) -> None:
        self._stop.set()
        # First, cut job/diff/status — don't trigger zombie notify
        self.on_job = None
        self.on_difficulty = None
        self.on_status = None
        # on_submit_result duruyor: _close_socket in-flight share’lere outcome_unknown bildirir
        self._close_socket()
        self.on_submit_result = None
        if self._watchdog and self._watchdog.is_alive():
            self._watchdog.join(timeout=5)
        self.connected = False
        self.authorized = False
        self.subscribed = False

    def _close_socket(self) -> None:
        with self._lock:
            if self._sock:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
            self.connected = False
            pending_items = [
                (mid, p) for mid, p in self._pending.items() if p.get("is_submit")
            ]
            for mid, _ in pending_items:
                self._pending.pop(mid, None)
            session_id = self.session_id
        for mid, pending in pending_items:
            # Update submit_log
            for entry in self.submit_log:
                if entry.get("id") == mid and entry.get("ok") is None:
                    entry["ok"] = None
                    entry["time_recv"] = time.strftime("%H:%M:%S")
                    entry["response"] = {
                        "id": mid,
                        "result": None,
                        "error": None,
                        "outcome_unknown": True,
                    }
                    break
            if self.on_submit_result:
                try:
                    self.on_submit_result(
                        False,
                        "outcome_unknown: connection lost",
                        {
                            "id": mid,
                            "session_id": session_id,
                            "result": None,
                            "error": None,
                            "outcome_unknown": True,
                        },
                    )
                except Exception:
                    log.exception("submit unknown callback")
            pending["event"].set()
            log.info(
                "submit unknown session=%s id=%s reason=connection lost",
                session_id,
                mid,
            )

    def _run_loop(self) -> None:
        delay = RECONNECT_BASE
        while not self._stop.is_set():
            try:
                self._set_status(f"Connecting: {self.host}:{self.port}")
                self._connect_and_handshake()
                delay = RECONNECT_BASE
                if self._reader:
                    self._reader.join()
                if not self._stop.is_set():
                    raise ConnectionError("Stratum reader ended.")
            except Exception as exc:
                if self._stop.is_set():
                    break
                self.connected = False
                self.authorized = False
                self.subscribed = False
                self._set_status(f"Connection error: {exc}. {delay:.0f}s before retry…")
                self._close_socket()
                self._stop.wait(delay)
                delay = min(delay * 2, RECONNECT_MAX)

    def _ssl_context(self) -> ssl.SSLContext:
        """Verified TLS only — never disable hostname or cert checks."""
        return ssl.create_default_context()

    def _connect_and_handshake(self) -> None:
        raw = socket.create_connection((self.host, self.port), timeout=20)
        if self._stop.is_set():
            try:
                raw.close()
            except OSError:
                pass
            raise ConnectionError("Stratum stop — connection cancelled.")
        if self.use_tls:
            try:
                sock = self._ssl_context().wrap_socket(
                    raw, server_hostname=self.host
                )
            except ssl.SSLError as exc:
                try:
                    raw.close()
                except OSError:
                    pass
                raise ConnectionError(
                    f"TLS certificate verification failed for {self.host}: {exc}"
                ) from exc
            proto = "TLS"
        else:
            sock = raw
            proto = "TCP"
        sock.settimeout(RECV_TIMEOUT)
        with self._lock:
            self._sock = sock
            self._buffer = b""
            self.session_id += 1
            sid = self.session_id
        self.connected = True
        self._last_activity = time.time()
        self._set_status(f"{proto} connected: {self.host}:{self.port} (session={sid})")

        self._reader = threading.Thread(
            target=self._read_forever, name="stratum-reader", daemon=True
        )
        self._reader.start()

        from app_meta import APP_USER_AGENT

        sub = self._rpc("mining.subscribe", [APP_USER_AGENT])
        self._handle_subscribe_result(sub)
        self.subscribed = True
        self._set_status("Stratum subscribed.")

        auth = self._rpc("mining.authorize", [self.address, self.password])
        if auth is not True:
            raise RuntimeError(f"Authorization rejected: {auth}")
        self.authorized = True
        self._set_status(f"Authorized: {self.address[:12]}…")

        # CKPool: suggest_difficulty after authorize (server can clamp to mindiff)
        if self.suggest_difficulty is not None:
            try:
                self._rpc("mining.suggest_difficulty", [float(self.suggest_difficulty)])
                self._set_status(
                    f"mining.suggest_difficulty({self.suggest_difficulty}) sent; "
                    "effective difficulty is set only by mining.set_difficulty."
                )
            except Exception as exc:
                self._set_status(f"suggest_difficulty response ignored: {exc}")

    def _wire(self, kind: str, **payload: Any) -> None:
        entry = {"time": time.strftime("%H:%M:%S"), "kind": kind, **payload}
        self.wire_log.insert(0, entry)
        self.wire_log = self.wire_log[:200]
        log.info("stratum.wire %s %s", kind, {k: v for k, v in payload.items() if k != "raw"})

    def _handle_subscribe_result(self, result: Any) -> None:
        if not isinstance(result, (list, tuple)) or len(result) < 3:
            raise RuntimeError(f"Unexpected subscribe response: {result}")
        self.last_subscribe_raw = result
        self.extranonce1 = result[1]
        self.extranonce2_size = int(result[2])
        self._wire(
            "mining.subscribe.result",
            raw=result,
            extranonce1=self.extranonce1,
            extranonce2_size=self.extranonce2_size,
        )

    def _rpc(self, method: str, params: list) -> Any:
        event = threading.Event()
        holder: dict[str, Any] = {}
        with self._lock:
            msg_id = self._next_id()
            self._pending[msg_id] = {"event": event, "holder": holder}
            payload = {"id": msg_id, "method": method, "params": params}
            # Submit under the same lock as submit_share — avoid TCP/JSON race conditions
            sock = self._sock
            if sock is None:
                self._pending.pop(msg_id, None)
                raise RuntimeError("No socket.")
            sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        if not event.wait(timeout=30):
            with self._lock:
                self._pending.pop(msg_id, None)
            raise TimeoutError(f"RPC timeout: {method}")
        if "error" in holder and holder["error"]:
            raise RuntimeError(f"{method} hata: {holder['error']}")
        return holder.get("result")

    def submit_share(
        self,
        worker: str,
        job_id: str,
        extranonce2_hex: str,
        ntime_hex: str,
        nonce_hex: str,
        request_id: Optional[int] = None,
        expected_session_id: Optional[int] = None,
    ) -> int:
        """
        Async submit. Session check + send on the same socket under self._lock
        (connection churn is not covered by the controller lock alone).
        """
        if expected_session_id is None:
            raise ValueError("expected_session_id is required.")

        with self._lock:
            if int(self.session_id) != int(expected_session_id):
                raise RuntimeError(
                    f"session mismatch: expected={expected_session_id} "
                    f"current={self.session_id}"
                )
            sock = self._sock
            if sock is None or not self.connected:
                raise RuntimeError("no socket or not connected.")

            msg_id = int(request_id) if request_id is not None else self._next_id()
            session_id = int(self.session_id)
            payload = {
                "id": msg_id,
                "method": "mining.submit",
                "params": [worker, job_id, extranonce2_hex, ntime_hex, nonce_hex],
            }
            entry: dict[str, Any] = {
                "id": msg_id,
                "session_id": session_id,
                "request": payload,
                "response": None,
                "ok": None,
                "time_sent": time.strftime("%H:%M:%S"),
                "time_recv": None,
            }
            self.submit_log.insert(0, entry)
            self.submit_log = self.submit_log[:100]

            def _done(ok: bool, err: Any, result: Any) -> None:
                entry["time_recv"] = time.strftime("%H:%M:%S")
                entry["response"] = {"id": msg_id, "result": result, "error": err}
                entry["ok"] = ok
                if self.on_submit_result:
                    msg = "accepted" if ok else f"rejected: {err or result}"
                    self.on_submit_result(
                        ok,
                        msg,
                        {
                            "id": msg_id,
                            "session_id": session_id,
                            "result": result,
                            "error": err,
                            "request": payload,
                            "response": entry["response"],
                        },
                    )

            event = threading.Event()
            holder: dict[str, Any] = {"callback": _done}
            self._pending[msg_id] = {
                "event": event,
                "holder": holder,
                "is_submit": True,
            }
            # Send under the same lock — close/reconnect cannot intervene
            data = (json.dumps(payload) + "\n").encode("utf-8")
            sock.sendall(data)

        return msg_id

    def fail_pending_submits(self, reason: str) -> None:
        """Connection loss / session drop: Report errors to pending submits."""
        with self._lock:
            pending_items = [
                (mid, p) for mid, p in self._pending.items() if p.get("is_submit")
            ]
            for mid, _ in pending_items:
                self._pending.pop(mid, None)
            session_id = self.session_id
        for mid, pending in pending_items:
            holder = pending["holder"]
            cb = holder.get("callback")
            if cb:
                cb(False, reason, None)
            pending["event"].set()
            log.info("submit fail session=%s id=%s reason=%s", session_id, mid, reason)

    def _send(self, payload: dict) -> None:
        data = (json.dumps(payload) + "\n").encode("utf-8")
        with self._send_lock:
            sock = self._sock
            if not sock:
                raise RuntimeError("No socket.")
            sock.sendall(data)

    def _read_forever(self) -> None:
        while not self._stop.is_set():
            sock = self._sock
            if sock is None:
                break
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    break
                raise
            if not chunk:
                raise ConnectionError("Server closed the connection.")
            self._last_activity = time.time()
            self._buffer += chunk
            while b"\n" in self._buffer:
                line, self._buffer = self._buffer.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    log.warning("Invalid JSON: %s", line[:200])
                    continue
                self._dispatch(msg)

    def _dispatch(self, msg: dict) -> None:
        if "method" in msg and msg.get("id") is None:
            self._handle_notify_method(msg.get("method"), msg.get("params") or [])
            return

        msg_id = msg.get("id")
        if msg_id is None:
            return

        with self._lock:
            pending = self._pending.pop(msg_id, None)
        if not pending:
            return

        holder = pending["holder"]
        holder["result"] = msg.get("result")
        holder["error"] = msg.get("error")
        if pending.get("is_submit"):
            cb = holder.get("callback")
            # Accepted only if server result==True and no error
            ok = msg.get("error") is None and msg.get("result") is True
            if cb:
                cb(ok, msg.get("error"), msg.get("result"))
        pending["event"].set()

    def _handle_notify_method(self, method: Optional[str], params: list) -> None:
        if method == "mining.notify":
            clean = bool(params[8]) if len(params) > 8 else False
            self._wire(
                "mining.notify",
                job_id=params[0] if params else None,
                prevhash=params[1] if len(params) > 1 else None,
                version=params[5] if len(params) > 5 else None,
                nbits=params[6] if len(params) > 6 else None,
                ntime=params[7] if len(params) > 7 else None,
                clean_jobs=clean,
                merkle_branch_count=len(params[4]) if len(params) > 4 else 0,
                raw=params,
                difficulty_at_notify=self.difficulty,
            )
            if self.on_job:
                self.on_job(params, clean)
        elif method == "mining.set_difficulty":
            diff = float(params[0])
            self.difficulty = diff
            self.server_set_difficulty = diff
            self._wire("mining.set_difficulty", difficulty=diff, raw=params)
            if self.on_difficulty:
                self.on_difficulty(diff)
            self._set_status(f"Pool mining.set_difficulty: {diff}")
        elif method == "client.reconnect":
            self._set_status("Server requested reconnect.")
            self._close_socket()
        else:
            log.debug("Unhandled method: %s", method)
