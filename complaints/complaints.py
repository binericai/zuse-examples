"""Sort real customer complaints by product, and check every answer against the truth.

The US Consumer Financial Protection Bureau publishes the complaints it receives, in the
customers' own words (public domain, 1.7 million with text). Each complaint says which product
it is about, as filed by the customer, so we know the right answer. This script reads an equal
number of complaints for each product, asks Zuse which product each one is about, and scores it.
With --bedrock or --claude it does the same with Claude Sonnet 5.5 and compares
accuracy and cost.

    python complaints.py                  # Zuse, 30 complaints per product (270)
    python complaints.py --claude         # also Claude, with ANTHROPIC_API_KEY
    python complaints.py --bedrock        # also Claude, through Amazon Bedrock (AWS credentials)
"""

import argparse
import json
import os
import random
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent

# --- Your Zuse API key, from .env in this folder or the repo root -----------------------------
for env in (HERE / ".env", HERE.parent / ".env"):
    if env.exists():
        for line in env.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
ENV_FILE = HERE.parent / ".env"
MODEL = os.environ.get("ZUSE_MODEL", "zuse-27b")
KEY = ""
# Two sizes: zuse-9b is the cheaper one, zuse-27b a little more accurate. Set ZUSE_MODEL in .env.
ZUSE_PRICE = {"zuse-9b": 0.12, "zuse-27b": 0.75}.get(MODEL, 0.75)   # USD per million input tokens; no output

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


# --- The question: this is the whole "prompt" ---------------------------------------------------
TASK = "Which financial product is this consumer complaint about?"
PRODUCTS = {
    "credit_report": "Credit reports, credit scores or credit repair services",
    "debt_collection": "Debt collection: a collector or agency chasing a debt",
    "bank_account": "A checking or savings account",
    "credit_card": "A credit card or prepaid card",
    "mortgage": "A mortgage",
    "student_loan": "A student loan",
    "vehicle_loan": "A car or other vehicle loan or lease",
    "personal_loan": "A payday loan, title loan or personal loan",
    "money_transfer": "Money transfers, virtual currency or money services",
}
QUESTIONS = {"product": {"type": "choice", "instructions": TASK, "criteria": PRODUCTS}}
SURE = 0.90                                          # act automatically at this probability or above


def ask_zuse(text):
    """One request per complaint. Retries when the service is busy."""
    for attempt in range(4):
        t0 = time.time()
        r = requests.post(os.environ.get("BINERIC_BASE_URL", "https://api.bineric.com").rstrip("/") + "/v1/zuse", timeout=60,
                          headers={"Authorization": f"Bearer {KEY}"},
                          json={"model": MODEL, "state": text, "questions": QUESTIONS})
        if r.status_code in (429, 502, 503, 504) and attempt < 3:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        res = r.json()
        a = res["answers"]["product"]
        # How sure Zuse is: the probability of the product it chose.
        return a["choice"], a["probabilities"][a["choice"]], res["usage"]["input_tokens"], 0, time.time() - t0


# --- The same job with Claude, for comparison ----------------------------------------------------
# A structured-output request: the answer must be one of the products, plus how sure Claude says
# it is (0-100). Thinking is off, the cheapest setting. Anthropic list prices, USD per million
# tokens (input, output); the Batch API halves them if you can wait.
CLAUDE = {"Claude Sonnet 5.5": ("claude-sonnet-5-5", 2.00, 10.00, {"type": "between_tools"})}


def ask_claude(client, model, thinking, text):
    schema = {"type": "object", "properties": {"product": {"type": "string", "enum": list(PRODUCTS)},
                                               "sure": {"type": "integer"}},
              "required": ["product", "sure"], "additionalProperties": False}
    system = (TASK + " Pick one of the products below, and say how sure you are that it is right, from 0 to 100."
              "\n\nThe products:\n" + "\n".join(f"- {k}: {v}" for k, v in PRODUCTS.items()))
    t0 = time.time()
    r = client.messages.create(model=model, max_tokens=200, thinking=thinking, system=system,
                               messages=[{"role": "user", "content": text}],
                               output_config={"format": {"type": "json_schema", "schema": schema}})
    out = json.loads(r.content[-1].text) if r.stop_reason == "end_turn" else {"product": None, "sure": 0}
    return out["product"], out["sure"] / 100, r.usage.input_tokens, r.usage.output_tokens, time.time() - t0


# --- The data -----------------------------------------------------------------------------------
# The CFPB database as Parquet files on Hugging Face. We read a few random chunks of 1,000
# complaints, not the whole 900 MB. The CFPB renamed some products over the years; GROUP maps
# the old and new names onto the nine products above.
PARQUET = ("https://huggingface.co/datasets/BEE-spoke-data/consumer-finance-complaints/"
           "resolve/refs%2Fconvert%2Fparquet/has-text/train/{:04d}.parquet")
GROUP = {
    "Credit reporting, credit repair services, or other personal consumer reports": "credit_report",
    "Credit reporting or other personal consumer reports": "credit_report",
    "Credit reporting": "credit_report",
    "Debt collection": "debt_collection",
    "Checking or savings account": "bank_account",
    "Bank account or service": "bank_account",
    "Credit card or prepaid card": "credit_card",
    "Credit card": "credit_card",
    "Prepaid card": "credit_card",
    "Mortgage": "mortgage",
    "Student loan": "student_loan",
    "Vehicle loan or lease": "vehicle_loan",
    "Payday loan, title loan, or personal loan": "personal_loan",
    "Payday loan, title loan, personal loan, or advance loan": "personal_loan",
    "Payday loan": "personal_loan",
    "Consumer Loan": "personal_loan",
    "Money transfer, virtual currency, or money service": "money_transfer",
    "Money transfers": "money_transfer",
    "Virtual currency": "money_transfer",
}


def download(per_product, seed):
    cache = HERE / ".cache" / f"complaints-{per_product}-{seed}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    import fsspec
    import pyarrow.parquet as pq
    rng, pools = random.Random(seed), defaultdict(list)
    print(f"Downloading complaints until there are {per_product} for each product...", file=sys.stderr)
    while min((len(pools[p]) for p in PRODUCTS), default=0) < per_product:
        f = pq.ParquetFile(fsspec.open(PARQUET.format(rng.randrange(3)), block_size=2**20).open())
        chunk = f.read_row_group(rng.randrange(f.num_row_groups),
                                 columns=["Complaint ID", "Product", "Consumer complaint narrative"]).to_pylist()
        for x in rng.sample(chunk, 100):                      # 100 from each chunk, for spread
            product = GROUP.get(x["Product"])
            if product and x["Consumer complaint narrative"] and len(pools[product]) < per_product:
                pools[product].append({"id": x["Complaint ID"], "product": product,
                                       "text": x["Consumer complaint narrative"]})
    out = [c for p in PRODUCTS for c in pools[p]]
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps(out))
    return out


def score(name, complaints, results, pin, pout):
    n = len(results)
    right = sum(r[0] == c["product"] for c, r in zip(complaints, results))
    auto = [(c, r) for c, r in zip(complaints, results) if r[1] >= SURE]
    auto_right = sum(r[0] == c["product"] for c, r in auto)
    cost = (sum(r[2] for r in results) * pin + sum(r[3] for r in results) * pout) / 1e6
    return {"name": name, "right": right / n, "auto": len(auto) / n, "auto_right": auto_right / max(1, len(auto)),
            "per_million": cost / n * 1e6, "seconds": sorted(r[4] for r in results)[n // 2],
            "tokens_in": sum(r[2] for r in results) / n, "tokens_out": sum(r[3] for r in results) / n}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--per-product", type=int, default=30)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--claude", action="store_true", help="compare with Claude (needs ANTHROPIC_API_KEY)")
    p.add_argument("--bedrock", action="store_true", help="compare with Claude on Amazon Bedrock")
    args = p.parse_args()
    global KEY
    KEY = get_key()

    complaints = download(args.per_product, args.seed)
    texts = [c["text"] for c in complaints]
    with ThreadPoolExecutor(max_workers=8) as pool:
        z = list(pool.map(ask_zuse, texts))
    rows = [score(f"Zuse ({MODEL})", complaints, z, ZUSE_PRICE, 0)]

    if args.claude or args.bedrock:
        import anthropic
        client = (anthropic.AnthropicBedrock(aws_region=os.environ.get("AWS_REGION", "eu-central-1"))
                  if args.bedrock else anthropic.Anthropic())
        prefix = "eu.anthropic." if args.bedrock else ""
        for name, (model, pin, pout, thinking) in CLAUDE.items():
            with ThreadPoolExecutor(max_workers=8) as pool:
                c = list(pool.map(lambda t: ask_claude(client, prefix + model, thinking, t), texts))
            rows.append(score(name, complaints, c, pin, pout))

    n = len(complaints)
    lines = [f"{n} real complaints from the CFPB database, {args.per_product} for each of {len(PRODUCTS)} products\n"]
    lines.append("Zuse, right per product")
    for prod in PRODUCTS:
        mine = [(c, r) for c, r in zip(complaints, z) if c["product"] == prod]
        lines.append(f"  {PRODUCTS[prod][:52]:<54}{sum(r[0] == prod for c, r in mine) / len(mine):>6.0%}")
    lines.append(f"\n{'':<20}{'right':>7}{f'at {SURE:.0%} sure: automatic, right':>31}"
                 f"{'tokens in/out':>15}{'per million':>13}{'batch API':>11}{'median time':>13}")
    for r in rows:
        batch = f"${r['per_million'] / 2:,.0f}" if r["name"].startswith("Claude") else ""
        auto = f"{r['auto']:.0%}, {r['auto_right']:.1%}"
        tokens = f"{r['tokens_in']:.0f} / {r['tokens_out']:.0f}"
        cost, secs = f"${r['per_million']:,.0f}", f"{r['seconds']:.2f} s"
        lines.append(f"{r['name']:<20}{r['right']:>7.1%}{auto:>31}{tokens:>15}{cost:>13}{batch:>11}{secs:>13}")
    if len(rows) > 1:
        lines.append("Claude: thinking off, structured output, Anthropic list prices. Its 'how sure' is what it says, not a probability.")
    print("\n".join(lines))
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / f"results-{MODEL}.txt").write_text("\n".join(lines) + "\n")
    with open(HERE / "results" / f"answers-{MODEL}.jsonl", "w") as f:
        for c, r in zip(complaints, z):
            f.write(json.dumps({"id": c["id"], "product": c["product"], "zuse": r[0], "sure": round(r[1], 4)}) + "\n")


if __name__ == "__main__":
    main()
