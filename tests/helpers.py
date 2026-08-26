"""Shared test helpers: threaded TCP servers (plain + TLS)."""

import os
import socket
import ssl
import subprocess
import threading


class FakeServer:
    """Minimal threaded TCP server that handles each connection in a thread.

    `handler` is a callable(conn) that does the recv/send conversation.
    Pass an `ssl_context` to wrap accepted sockets in TLS (server side).
    """

    def __init__(self, handler, ssl_context=None, port=0):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(5)
        self.handler = handler
        self.ssl_context = ssl_context
        self._stop = False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            if self.ssl_context is not None:
                try:
                    conn = self.ssl_context.wrap_socket(conn, server_side=True)
                except Exception:
                    return
            self.handler(conn)
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def stop(self):
        self._stop = True
        try:
            self.sock.close()
        except Exception:
            pass


def make_self_signed_cert(tmpdir):
    """Generate a self-signed cert via openssl. Returns (cert, key) or (None, None)."""
    cert = os.path.join(str(tmpdir), "cert.pem")
    key = os.path.join(str(tmpdir), "key.pem")
    try:
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", key,
             "-out", cert, "-days", "1", "-nodes", "-subj", "/CN=localhost"],
            check=True, capture_output=True, timeout=30,
        )
        return cert, key
    except Exception:
        return None, None


def make_tls_server(handler, certfile, keyfile, port=0):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile, keyfile)
    return FakeServer(handler, ssl_context=ctx, port=port)
