"""A small Zuse client (one HTTP call) and a helper that tries an example on its samples."""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent

# Your API key, from .env in this folder or the repo root (see .env.example).
for env in (HERE / ".env", HERE.parent / ".env"):
    if env.exists():
        for line in env.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
ENV_FILE = HERE.parent / ".env"
MODEL = os.environ.get("ZUSE_MODEL", "zuse-27b")
URL = os.environ.get("BINERIC_BASE_URL", "https://api.bineric.com").rstrip("/") + "/v1/zuse"
# Two sizes. zuse-9b is the cheaper one; zuse-27b is a little more accurate. Set ZUSE_MODEL in .env.
PRICES = {"zuse-9b": 0.12, "zuse-27b": 0.75}   # USD per million input tokens. Zuse has no output tokens.
PRICE = PRICES.get(MODEL, 0.75)

session = requests.Session()

GET_KEY = """You need a Zuse API key. Get one in a minute:
  1. Sign up at https://bineric.com/platform
  2. Open "API keys" in the dashboard and click "Generate Key"
  3. Paste it below (it is saved to .env in this repo, which git ignores)"""


def get_key():
    """The API key from .env or the environment; if there is none, ask for it once and save it to .env."""
    key = os.environ.get("BINERIC_API_KEY", "")
    if key and key != "paste-your-key-here":
        return key
    if not sys.stdin.isatty():
        sys.exit(GET_KEY.split("\n  3.")[0] + "\n  3. Put it in .env as BINERIC_API_KEY=your-key")
    import getpass
    print(GET_KEY)
    key = getpass.getpass("API key: ").strip()
    if not key:
        sys.exit("No key entered.")
    env = ENV_FILE
    gap = "\n" if env.exists() and not env.read_text().endswith("\n") else ""
    with open(env, "a") as f:
        f.write(f"{gap}BINERIC_API_KEY={key}\n")
    os.environ["BINERIC_API_KEY"] = key
    print(f"Saved to {env}.\n")
    return key


def ask_zuse(text, questions):
    """Send one text and all the questions about it. Returns Zuse's full response."""
    key = get_key()
    body = {"model": MODEL, "state": text, "questions": questions}
    for attempt in range(4):
        r = session.post(URL, json=body, timeout=60, headers={"Authorization": f"Bearer {key}"})
        if r.status_code in (429, 502, 503, 504) and attempt < 3:
            time.sleep(2 ** attempt)                     # busy: wait and try again
            continue
        if r.status_code != 200:
            raise RuntimeError(f"Zuse API error {r.status_code}: {r.text[:300]}")
        return r.json()


def chance(answer):
    """How likely Zuse's answer is to be right: the probability of the option it chose.

    (The API also returns `confidence`, the same thing rescaled so that 0 means "can't tell
    the options apart". We use the plain probability because it is easier to read.)
    """
    return answer["probabilities"][answer["choice"]]


# --- Trying an example on its samples ---------------------------------------------------------

def load_samples(name):
    path = HERE / "samples" / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def try_samples(name, handle):
    """Run handle() on every sample in samples/<name>.jsonl and compare with the expected answer.

    A "person" decision where something else was expected means Zuse wasn't sure enough and left
    it to a person: not wrong, just not automatic.
    """
    samples = load_samples(name)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(handle, samples))
    right = wrong = unsure = 0
    for s, r in zip(samples, results):
        expect = s["expect"] if isinstance(s["expect"], list) else [s["expect"]]
        if r["decision"] in expect:
            right, mark = right + 1, "right"
        elif r["decision"] == "person":
            unsure, mark = unsure + 1, "not sure: to a person"
        else:
            wrong, mark = wrong + 1, f"WRONG (expected {' or '.join(expect)})"
        print(f"{s['id']:<4} {s['title'][:34]:<34} {r['decision']:<12} {mark:<26} {r['reason']}")
    tokens = sum(r["tokens"] for r in results)
    n = len(samples)
    print(f"\n{n} cases: {right} right, {wrong} wrong, {unsure} left to a person because Zuse wasn't sure enough.")
    print(f"{tokens:,} input tokens = ${tokens * PRICE / 1e6:.4f}, about ${tokens * PRICE / n / 1e3:.2f} per 1,000.")
