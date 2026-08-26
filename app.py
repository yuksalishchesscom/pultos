import socket
import threading

import webview

from backend import create_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    app = create_app()
    port = _free_port()

    server_thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True),
        daemon=True,
    )
    server_thread.start()

    webview.create_window(
        "PultOS",
        f"http://127.0.0.1:{port}/",
        width=430,
        height=780,
        resizable=True,
    )
    webview.start(gui="qt")


if __name__ == "__main__":
    main()
