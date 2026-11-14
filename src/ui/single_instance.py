"""Ensure only one Easy Block Finder 4000 process owns the UI."""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from app_meta import APP_SHORT, APP_VERSION

# Stable IPC name (not tied to user-visible branding changes)
SERVER_NAME = f"{APP_SHORT}-v{APP_VERSION}-single-instance"
_RAISE_MSG = b"RAISE\n"


class SingleInstanceGuard(QObject):
    """
    First process listens on a local socket.
    Second process sends RAISE and exits — primary shows/activates its window.
    """

    activated = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server: QLocalServer | None = None

    def ensure_primary(self) -> bool:
        """
        Return True if this process is the primary instance.
        Return False after notifying an already-running primary (caller should exit).
        """
        if self._notify_existing():
            return False

        QLocalServer.removeServer(SERVER_NAME)
        server = QLocalServer(self)
        if not server.listen(SERVER_NAME):
            server.close()
            # Race: another instance took the name — notify and yield
            self._notify_existing()
            return False

        server.newConnection.connect(self._on_new_connection)
        self._server = server
        return True

    def _notify_existing(self) -> bool:
        sock = QLocalSocket()
        sock.connectToServer(SERVER_NAME)
        if not sock.waitForConnected(500):
            sock.abort()
            return False
        sock.write(_RAISE_MSG)
        sock.flush()
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            sock.waitForDisconnected(500)
        return True

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            client = self._server.nextPendingConnection()
            if client is None:
                continue
            if client.bytesAvailable() == 0:
                client.waitForReadyRead(300)
            try:
                client.readAll()
            except Exception:
                pass
            client.disconnectFromServer()
            client.deleteLater()
            self.activated.emit()

    def close(self) -> None:
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(SERVER_NAME)
            self._server = None
