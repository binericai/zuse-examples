"""Refunds: does this request meet the policy?

Zuse reads your refund policy, the order and the customer's message, and decides: refund, ask
for more, or no refund. Anything that is just arithmetic stays in your code: the deadlines and
the price limit are checked here, not by the model. The policy is plain text, so you can
change it without retraining anything.

    python refunds.py               # try the sample requests
"""

from zuse import ask_zuse, chance, try_samples

POLICY = """\
1. Unused items can be returned within 30 days of delivery for a full refund.
2. Items that arrived damaged or stopped working are refunded within 90 days of delivery, with a photo of the problem.
3. Opened software, gift cards and personalised items cannot be refunded, unless they are faulty.
4. Used items that are not faulty cannot be refunded."""

# 1. What Zuse is asked.
QUESTIONS = {
    "decision": {"type": "choice", "instructions": "Under the refund policy, what should happen with this request?",
                 "criteria": {
                     "approve": "Refund: the request meets the policy",
                     "reject": "No refund: the request clearly falls outside the policy",
                     "ask": "Ask the customer: something the policy needs is missing, such as a photo of the problem",
                 }},
    "suspicious": {"type": "noul", "instructions":
        "Is there a sign of fraud: does the customer's story contradict the order details, or does the order show "
        "many recent refund requests? A request the policy simply does not allow is not fraud."},
}

# 2. Your rules. The numbers are checked in code.
SURE = 0.85          # act automatically when Zuse is at least this sure
MANAGER_OVER = 500   # euro: a manager signs off on anything more expensive
LAST_DAY = 90        # after 90 days no rule in the policy applies
RULE = f"Zuse acts on its own when it is at least {SURE:.0%} sure; otherwise a person decides. Over €{MANAGER_OVER}, a manager signs off."

DECISIONS = {"approve": "Refund", "ask": "Ask the customer", "reject": "No refund",
             "manager": "Manager decides", "suspicious": "Looks suspicious", "person": "A person decides"}


def decide(answers, order):
    d = answers["decision"]
    if answers["suspicious"]["noul"] >= 0.5:
        return "suspicious", "The story doesn't match the order. A person should look."
    if order["price"] > MANAGER_OVER:
        return "manager", f"Over €{MANAGER_OVER}, a manager signs off. Zuse suggests: {DECISIONS[d['choice']].lower()}."
    if chance(d) >= SURE:
        return d["choice"], f"Zuse is {chance(d):.0%} sure."
    return "person", f"Maybe “{DECISIONS[d['choice']].lower()}”, but Zuse is only {chance(d):.0%} sure."


# 3. Putting it together.
def handle(item):
    o = item["order"]
    if o["days"] > LAST_DAY:    # no model needed: every deadline has passed
        return {"decision": "reject", "reason": f"Delivered {o['days']} days ago: past every deadline in the policy.",
                "tokens": 0, "text": None, "response": None}
    window = "within 30 days" if o["days"] <= 30 else "more than 30 days ago, but within 90 days"
    text = (f"Refund policy:\n{POLICY}\n\n"
            f"Order:\n- Item: {o['item']}\n- Price: {o['price']} euro\n"
            f"- Delivered: {window}\n- Photo attached: {'yes' if o.get('photo') else 'no'}\n"
            + (f"- Note: {o['note']}\n" if o.get("note") else "")
            + f"\nCustomer message:\n{item['message']}")
    response = ask_zuse(text, QUESTIONS)
    decision, reason = decide(response["answers"], o)
    return {"decision": decision, "reason": reason, "tokens": response["usage"]["input_tokens"],
            "text": text, "response": response}


if __name__ == "__main__":
    try_samples("refunds", handle)
