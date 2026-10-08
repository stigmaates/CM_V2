"""Measure completed Telegram polls separately from message arrival or process life."""

import json

from telegram.ext import Application
from telegram.request import HTTPXRequest


class ObservedPollingRequest(HTTPXRequest):
    def __init__(self, heartbeat, **kwargs):
        self.heartbeat = heartbeat
        super().__init__(**kwargs)

    async def do_request(self, url, method, **kwargs):
        polling = url.rsplit("/", 1)[-1].lower() == "getupdates"
        try:
            result = await super().do_request(url, method, **kwargs)
        except Exception as exc:
            if polling:
                self.heartbeat.poll_error(type(exc).__name__)
            raise
        if polling:
            try:
                ok = result[0] == 200 and json.loads(result[1]).get("ok") is True
            except (ValueError, AttributeError):
                ok = False
            if ok:
                self.heartbeat.poll_success()
            else:
                self.heartbeat.poll_error("HTTP_" + str(result[0]))
        return result


class ObservedApplication(Application):
    def __init__(self, heartbeat, **kwargs):
        super().__init__(**kwargs)
        self.heartbeat = heartbeat

    async def process_update(self, update):
        self.heartbeat.handler_started()
        try:
            return await super().process_update(update)
        finally:
            self.heartbeat.handler_finished()
