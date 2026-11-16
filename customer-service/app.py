"""The five examples in your browser, one tab each.

    python app.py                  # opens http://127.0.0.1:8400 (or the next free port)
    python app.py --no-browser

The page talks to this small local server, and only the server calls Zuse, so your API key
never reaches the browser. It listens on 127.0.0.1 only and refuses requests from other
websites, so nothing else can spend your key through it.
"""

import argparse
import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Server(ThreadingHTTPServer):
    allow_reuse_address = False      # never share a port with another program
    daemon_threads = True

import bot_handover
import check_replies
import refunds
import route_tickets
import survey_comments
from zuse import HERE, MODEL, PRICE, get_key, load_samples

# Each tab: the module, its samples, a title, one line saying what it does, and whether you can type your own.
EXAMPLES = {
    "routing": (route_tickets, "Route tickets", "Zuse reads a ticket in any language and picks the team.", True),
    "handover": (bot_handover, "Bot handover", "After every customer message, should a person take over from the bot?", False),
    "quality": (check_replies, "Check replies", "Is the agent's reply good, worth coaching, or must it be stopped?", False),
    "refunds": (refunds, "Refunds", "Does the request meet the refund policy?", False),
    "feedback": (survey_comments, "Survey comments", "Which topics is the customer talking about?", True),
}


def show(key, s):
    """The sample as the page draws it: who says what, with an English translation."""
    if key == "handover":
        return [{"who": "Customer" if t["who"] == "customer" else "Bot", "text": t["text"], "en": t.get("en")} for t in s["turns"]]
    if key == "quality":
        return [{"who": "Customer", "text": s["customer"], "en": s.get("customer_en")},
                {"who": "Agent's reply", "text": s["reply"], "en": s.get("reply_en")}]
    if key == "refunds":
        o = s["order"]
        order = f"{o['item']}, €{o['price']}, delivered {o['days']} days ago, photo: {'yes' if o.get('photo') else 'no'}"
        return [{"who": "Refund policy", "text": refunds.POLICY},
                {"who": "Order", "text": order + (f". {o['note']}" if o.get("note") else "")},
                {"who": "Customer", "text": s["message"], "en": s.get("message_en")}]
    who = f"Comment, {s['stars']} of 5 stars" if s.get("stars") else "Customer"
    return [{"who": who, "text": s["text"], "en": s.get("en")}]


def describe():
    out = []
    for key, (mod, title, lede, own) in EXAMPLES.items():
        out.append({"key": key, "title": title, "lede": lede, "own": own, "file": mod.__name__ + ".py",
                    "sure": mod.SURE, "rule": mod.RULE, "decisions": mod.DECISIONS, "questions": mod.QUESTIONS,
                    "samples": [{"id": s["id"], "title": s["title"], "lang": s.get("lang"), "demo": s.get("demo"),
                                 "show": show(key, s)} for s in load_samples(key)]})
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "zuse-examples"

    def log_message(self, *args):
        pass

    def _local(self):
        # Blocks DNS rebinding: another site pointing its own name at 127.0.0.1.
        return (self.headers.get("Host") or "").rsplit(":", 1)[0] in ("127.0.0.1", "localhost")

    def _send(self, status, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._local():
            return self._send(403, {"error": "Open the page at http://127.0.0.1."})
        if self.path == "/":
            return self._send(200, (HERE / "web" / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/examples":
            return self._send(200, {"model": MODEL, "price": PRICE, "examples": describe()})
        self._send(404, {"error": "Not found."})

    def do_POST(self):
        # The custom header forces a CORS preflight, which this server never approves,
        # so other websites can't post here from your browser.
        if not self._local() or self.headers.get("X-Zuse-Example") != "1" or self.path != "/api/run":
            return self._send(403, {"error": "Requests must come from the examples page."})
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 100_000)))
            mod, *_, own = EXAMPLES[body["example"]]
            if body.get("text"):
                if not own or len(body["text"]) > 10_000:
                    raise ValueError
                item = {"text": body["text"]}
            else:
                item = next(s for s in load_samples(body["example"]) if s["id"] == body["id"])
        except (ValueError, KeyError, TypeError, StopIteration):
            return self._send(400, {"error": "Pick a sample, or write a message under 10,000 characters."})
        try:
            r = mod.handle(item)
        except Exception as e:                           # bad key, no network, ...
            return self._send(502, {"error": str(e)})
        r["request"] = {"model": MODEL, "state": r["text"], "questions": mod.QUESTIONS} if r["text"] else None
        r["label"] = mod.DECISIONS.get(r["decision"], r["decision"])
        r["expect"] = item.get("expect")
        return self._send(200, r)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8400)
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()
    get_key()                                            # asks for it if there is none yet
    for port in range(args.port, args.port + 20):        # the first free port
        try:
            server = Server(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    else:
        sys.exit(f"Ports {args.port}-{args.port + 19} are all in use. Try: python app.py --port 9000")
    url = f"http://127.0.0.1:{port}"
    print(f"Zuse examples on {url}   Ctrl+C to stop", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
