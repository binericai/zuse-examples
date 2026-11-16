"""Routing accuracy on a public benchmark, with Claude for comparison.

MINDS-14 (PolyAI, CC BY 4.0): real customers calling an e-banking line, transcribed, in
9 European languages, 14 intents. We keep it out of Zuse's training data and use it only
for testing.

    python benchmark_minds14.py                 # Zuse: 100 calls per language, 900 calls, about $0.09
    python benchmark_minds14.py --claude        # also Claude Sonnet 5.5 (ANTHROPIC_API_KEY)
    python benchmark_minds14.py --bedrock       # the same Claude model through Amazon Bedrock (AWS credentials)

Prints accuracy, how accuracy depends on how sure Zuse is, and what each model cost.
"""

import argparse
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from zuse import HERE, MODEL, PRICE, ask_zuse, chance

LANGS = {"cs": "cs-CZ", "de": "de-DE", "en": "en-GB", "es": "es-ES", "fr": "fr-FR",
         "it": "it-IT", "nl": "nl-NL", "pl": "pl-PL", "pt": "pt-PT"}
CACHE = HERE / ".cache"


def fetch(config):
    """All transcriptions for one language, without the audio. Cached in .cache/ after the first run."""
    cached = CACHE / f"minds14-{config}.json"
    if cached.exists():
        d = json.loads(cached.read_text())
        return d["rows"], d["names"]
    rows, offset, names = [], 0, None
    while True:
        for attempt in range(8):
            r = requests.get("https://datasets-server.huggingface.co/rows", timeout=60, params={
                "dataset": "PolyAI/minds14", "config": config, "split": "train", "offset": offset, "length": 100})
            if r.status_code != 429 and r.status_code < 500:
                break
            time.sleep(5 * (attempt + 1))                # Hugging Face is busy: wait and retry
        r.raise_for_status()
        page = r.json()
        names = names or next(f for f in page["features"] if f["name"] == "intent_class")["type"]["names"]
        rows += [{"transcription": x["row"]["transcription"], "intent_class": x["row"]["intent_class"]}
                 for x in page["rows"] if x["row"]["transcription"]]
        offset += 100
        if offset >= page["num_rows_total"]:
            CACHE.mkdir(exist_ok=True)
            cached.write_text(json.dumps({"rows": rows, "names": names}, ensure_ascii=False))
            return rows, names


# --- Claude, for comparison -------------------------------------------------------------------
# The same task as a structured-output request: the answer must be one of the intents, and
# Claude says how sure it is (0-100), so it can have a "send it to a person" rule too. Thinking is off (the cheapest setting). Prices are Anthropic's list prices in USD per
# million tokens (input, output); the Batch API halves them if you can wait for the answers.
CLAUDE = {"Claude Sonnet 5.5": ("claude-sonnet-5-5", 2.00, 10.00, {"type": "between_tools"})}


def claude_client(bedrock):
    import anthropic
    if bedrock:
        return anthropic.AnthropicBedrock(aws_region=os.environ.get("AWS_REGION", "eu-central-1")), "eu.anthropic."
    return anthropic.Anthropic(), ""


def ask_claude(client, model, thinking, text, options, task):
    schema = {"type": "object", "properties": {"answer": {"type": "string", "enum": list(options)},
                                               "sure": {"type": "integer"}},
              "required": ["answer", "sure"], "additionalProperties": False}
    system = (task + " Pick one of the options below, and say how sure you are that it is right, from 0 to 100."
              "\n\nThe options:\n" + "\n".join(f"- {k}: {v}" for k, v in options.items()))
    t0 = time.time()
    r = client.messages.create(model=model, max_tokens=200, thinking=thinking, system=system,
                               messages=[{"role": "user", "content": text}],
                               output_config={"format": {"type": "json_schema", "schema": schema}})
    out = json.loads(r.content[-1].text) if r.stop_reason == "end_turn" else {"answer": None, "sure": 0}
    return out["answer"], r.usage.input_tokens, r.usage.output_tokens, time.time() - t0, out["sure"] / 100


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--per-lang", type=int, default=100)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--claude", action="store_true", help="compare with Claude (needs ANTHROPIC_API_KEY)")
    p.add_argument("--bedrock", action="store_true", help="compare with Claude on Amazon Bedrock")
    args = p.parse_args()

    rng = random.Random(args.seed)
    items = []
    for lang, config in LANGS.items():
        rows, names = fetch(config)
        for row in rng.sample(rows, min(args.per_lang, len(rows))):
            items.append((lang, row["transcription"], names[row["intent_class"]]))
    options = {n: n.replace("_", " ") for n in names}
    task = "What is the customer calling the bank about?"
    question = {"intent": {"type": "choice", "instructions": task, "criteria": options}}
    n = len(items)
    lines = [f"MINDS-14: {n} calls in {len(LANGS)} languages, {len(names)} intents\n"]

    def zuse(item):
        t0 = time.time()
        res = ask_zuse(item[1], question)
        a = res["answers"]["intent"]
        return a["choice"], chance(a), res["usage"]["input_tokens"], time.time() - t0

    with ThreadPoolExecutor(max_workers=8) as pool:
        z = list(pool.map(zuse, items))

    # Accuracy by language
    lines.append(f"{'language':<10}{'calls':>6}{'Zuse right':>12}")
    for lang in LANGS:
        mine = [(it, o) for it, o in zip(items, z) if it[0] == lang]
        lines.append(f"{lang:<10}{len(mine):>6}{sum(o[0] == it[2] for it, o in mine) / len(mine):>12.1%}")
    lines.append(f"{'all':<10}{n:>6}{sum(o[0] == it[2] for it, o in zip(items, z)) / n:>12.1%}\n")

    # Is Zuse's probability honest? Group the answers by how sure Zuse was, and count how many were right.
    lines.append("How sure Zuse was, and how often it was right")
    lines.append(f"{'Zuse said':<14}{'calls':>6}{'right':>8}")
    for lo, hi in ((0, .5), (.5, .7), (.7, .9), (.9, .97), (.97, .99), (.99, 1.01)):
        group = [(it, o) for it, o in zip(items, z) if lo <= o[1] < hi]
        if group:
            label = f"{lo:.0%}-{min(hi, 1):.0%}"
            lines.append(f"{label:<14}{len(group):>6}{sum(o[0] == it[2] for it, o in group) / len(group):>8.1%}")
    lines.append("")
    lines.append("If you route automatically only when Zuse is sure, and send the rest to a person")
    lines.append(f"{'at least':<10}{'automatic':>11}{'right':>8}{'mistakes per 1,000 calls':>27}")
    for sure in (0.5, 0.8, 0.9, 0.95, 0.99):
        auto = [(it, o) for it, o in zip(items, z) if o[1] >= sure]
        right = sum(o[0] == it[2] for it, o in auto)
        lines.append(f"{sure:<10.0%}{len(auto) / n:>11.1%}{right / len(auto):>8.1%}{(len(auto) - right) / n * 1000:>27.0f}")

    # Cost and the comparison
    def at(results, sure_of, bar=0.9):
        """Share handled automatically at this bar, and how many of those were right."""
        auto = [(it, o) for it, o in zip(items, results) if sure_of(o) >= bar]
        return len(auto) / n, (sum(o[0] == it[2] for it, o in auto) / len(auto) if auto else 0)

    rows = [(f"Zuse ({MODEL})", sum(o[0] == it[2] for it, o in zip(items, z)) / n,
             sum(o[2] for o in z) * PRICE / 1e6, sorted(o[3] for o in z)[n // 2], at(z, lambda o: o[1]))]
    if args.claude or args.bedrock:
        client, prefix = claude_client(args.bedrock)
        for name, (model, pin, pout, thinking) in CLAUDE.items():
            with ThreadPoolExecutor(max_workers=8) as pool:
                c = list(pool.map(lambda it: ask_claude(client, prefix + model, thinking, it[1], options, task), items))
            cost = (sum(o[1] for o in c) * pin + sum(o[2] for o in c) * pout) / 1e6
            rows.append((name, sum(o[0] == it[2] for it, o in zip(items, c)) / n, cost, sorted(o[3] for o in c)[n // 2],
                         at(c, lambda o: o[4])))
            lines.append(f"\n{name}, by how sure it said it was")
            lines.append(f"{'it said':<14}{'calls':>6}{'right':>8}")
            for lo, hi in ((0, .7), (.7, .9), (.9, .97), (.97, .99), (.99, 1.01)):
                group = [(it, o) for it, o in zip(items, c) if lo <= o[4] < hi]
                if group:
                    lines.append(f"{f'{lo:.0%}-{min(hi, 1):.0%}':<14}{len(group):>6}"
                                 f"{sum(o[0] == it[2] for it, o in group) / len(group):>8.1%}")
    lines.append(f"\n{'':<20}{'right':>7}{'at 90% sure: automatic, right':>31}{'per 1,000 calls':>17}{'batch API':>11}{'median time':>13}")
    for name, acc, cost, sec, (auto, auto_right) in rows:
        batch = f"${cost / n * 500:.3f}" if name.startswith("Claude") else ""
        lines.append(f"{name:<20}{acc:>7.1%}{f'{auto:.0%}, {auto_right:.1%}':>31}{f'${cost / n * 1000:.3f}':>17}{batch:>11}{f'{sec:.2f} s':>13}")
    if len(rows) > 1:
        lines.append("Claude: thinking off, structured output, Anthropic list prices. Its 'how sure' is what it says, not a probability.")

    print("\n".join(lines))
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / f"minds14-{MODEL}.txt").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
