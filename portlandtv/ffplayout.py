"""ffplayout client: the only module that talks to ffplayout over the network.

Unverified against a live ffplayout 2.7.1: endpoints and field names follow
install.sh, which took them from ffplayout's Rust structs, not a running API.
"""
import json
import urllib.request

CHANNEL = 1


class Client:
    def __init__(self, url, user, password):
        self.url, self.user, self.password = url.rstrip("/"), user, password

    def _call(self, method, path, body=None, token=None):
        req = urllib.request.Request(self.url + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        if token:
            req.add_header("Authorization", "Bearer " + token)
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read()
        return json.loads(text) if text else None

    def _config(self):
        """-> (token, the channel's playout config). Logs in on every call: calls are rare."""
        token = self._call("POST", "/auth/login",
                           {"username": self.user, "password": self.password})["access"]
        return token, self._call("GET", f"/api/playout/config/{CHANNEL}", token=token)

    def output_size(self):
        """-> (width, height) ffplayout renders at, for the cards."""
        _, cfg = self._config()
        return cfg["processing"]["width"], cfg["processing"]["height"]  # unverified field names

    def set_day_start(self, hhmm):
        token, cfg = self._config()
        cfg["playlist"]["day_start"] = hhmm + ":00"
        self._call("PUT", f"/api/playout/config/{CHANNEL}", cfg, token)
        # unverified: ffplayout may only apply day_start after a restart (install.sh restarts it)


class Unconfigured:
    """Stands in when FFPLAYOUT_* aren't set: days still generate, the push fails visibly."""

    def output_size(self):
        return 1920, 1080  # shortcut: assumed size, cards rescale once a real client is set

    def set_day_start(self, hhmm):
        raise RuntimeError("ffplayout login not set (FFPLAYOUT_URL/USER/PASSWORD): "
                           "day_start not pushed")
