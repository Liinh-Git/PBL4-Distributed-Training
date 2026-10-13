"""Small test-only TCP relay for reproducible slow-peer DTP scenarios."""

import contextlib
import socket
import threading


class SlowPeerProxy:
    def __init__(self, target_port: int):
        self.target_port = target_port
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.listener.settimeout(0.2)
        self.port = self.listener.getsockname()[1]
        self.stopping = threading.Event()
        self.sockets = []
        self.threads = []
        self.connections = 0
        self.delays = 0
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def _accept(self):
        while not self.stopping.is_set():
            try:
                client, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            try:
                upstream = socket.create_connection(("127.0.0.1", self.target_port), timeout=5)
                upstream.settimeout(None)
            except OSError:
                client.close()
                continue
            slow = self.connections == 0
            self.connections += 1
            self.sockets.extend([client, upstream])
            for source, target in [(client, upstream), (upstream, client)]:
                thread = threading.Thread(
                    target=self._relay, args=(source, target, slow), daemon=True
                )
                self.threads.append(thread)
                thread.start()

    def _relay(self, source, target, slow):
        try:
            while not self.stopping.is_set():
                data = source.recv(65536)
                if not data:
                    break
                if slow:
                    self.delays += 1
                    if self.stopping.wait(0.1 * (1 + self.delays % 3)):
                        break
                target.sendall(data)
        except OSError:
            pass
        finally:
            for sock in (source, target):
                with contextlib.suppress(OSError):
                    sock.shutdown(socket.SHUT_RDWR)

    def close(self):
        self.stopping.set()
        self.listener.close()
        for sock in self.sockets:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            sock.close()
        self.thread.join(2)
        for thread in self.threads:
            thread.join(2)
        if self.thread.is_alive() or any(t.is_alive() for t in self.threads):
            raise RuntimeError("Fault relay survived cleanup")
