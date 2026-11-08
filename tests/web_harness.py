"""Seam 2 harness: a browser-ish Flask test client over a Channel's service."""
from html.parser import HTMLParser

import yaml

from portlandtv.web import create_app


class _Form(HTMLParser):
    """Field values as the browser would post them: inputs and selected options."""

    def __init__(self):
        super().__init__()
        self.fields, self._select, self._first = {}, None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input" and "name" in a:
            self.fields[a["name"]] = a.get("value", "")
        elif tag == "select":
            self._select, self._first = a["name"], True
        elif tag == "option" and self._select:
            if self._first or "selected" in a:
                self.fields[self._select] = a.get("value", "")
            self._first = False

    def handle_endtag(self, tag):
        if tag == "select":
            self._select = None


class Browser:
    def __init__(self, channel):
        self.channel = channel
        self.client = create_app(channel.service).test_client()
        self.html = None

    def get(self):
        r = self.client.get("/")
        assert r.status_code == 200, r.status_code
        self.html = r.get_data(as_text=True)
        return self.html

    def fields(self):
        p = _Form()
        p.feed(self.html)
        return p.fields

    def submit(self, action="save", changes=None):
        """Post the current page's form with `changes` applied; keeps the result page."""
        data = {**self.fields(), **(changes or {}), "action": action}
        r = self.client.post("/", data=data, follow_redirects=True)
        self.html = r.get_data(as_text=True)
        return r

    def yaml(self):
        with open(self.channel.config_path) as f:
            return yaml.safe_load(f)
