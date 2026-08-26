import json
import queue
import threading

from flask import Blueprint, Response, session

from . import relay_client, social_client

events_bp = Blueprint("events", __name__, url_prefix="/api")


@events_bp.route("/events")
def events():
    if not session.get("authed"):
        return Response(status=401)

    def stream():
        shared: "queue.Queue" = queue.Queue()
        relay_q = relay_client.subscribe()
        social_q = social_client.subscribe()
        stop = threading.Event()

        def pump(src):
            while not stop.is_set():
                try:
                    item = src.get(timeout=1)
                except queue.Empty:
                    continue
                shared.put(item)

        threading.Thread(target=pump, args=(relay_q,), daemon=True).start()
        threading.Thread(target=pump, args=(social_q,), daemon=True).start()

        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    event = shared.get(timeout=25)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield ": ping\n\n"
        finally:
            stop.set()
            relay_client.unsubscribe(relay_q)
            social_client.unsubscribe(social_q)

    return Response(stream(), mimetype="text/event-stream")
