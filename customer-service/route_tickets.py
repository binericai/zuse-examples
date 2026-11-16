"""Route support tickets to the right team, in any language.

Zuse reads each ticket and picks a team. Your rules send the ticket there only when Zuse is
at least 90% sure; otherwise a person decides. Data requests and legal threats get their own
route, because they have deadlines and risks of their own.

    python route_tickets.py                                  # try the sample tickets
    python route_tickets.py "Hei, dere har trukket meg to ganger!"   # try your own
"""

import sys

from zuse import ask_zuse, chance, try_samples

# 1. What Zuse is asked. The ticket itself can be in any language.
QUESTIONS = {
    "team": {
        "type": "choice",
        "instructions": "Which support team should handle this ticket?",
        "criteria": {
            "billing": "Payments, invoices, charges and refunds of money",
            "delivery": "Shipping, tracking, late, lost or wrongly delivered parcels",
            "returns": "Returning, exchanging or reporting damaged or faulty products",
            "technical": "The website, app or checkout is not working",
            "account": "Login, account settings, membership and personal data",
            "other": "None of these: thanks, spam, unclear or unrelated messages",
        },
    },
    "data_request": {"type": "noul", "instructions":
        "Is the customer asking to see, export or delete the personal data the company holds about them?"},
    "legal_threat": {"type": "noul", "instructions":
        "Does the customer mention a lawyer, legal action or a complaint to a consumer authority?"},
}

# 2. Your rules.
SURE = 0.90          # route automatically only when Zuse is at least this sure of the team
RULE = f"A ticket goes straight to a team only when Zuse is at least {SURE:.0%} sure of the team; otherwise a person decides."

DECISIONS = {"billing": "Billing", "delivery": "Delivery", "returns": "Returns", "technical": "Technical",
             "account": "Account", "other": "Other", "privacy": "Privacy team", "team lead": "Team lead",
             "person": "A person decides"}


def decide(answers):
    team = answers["team"]
    if answers["data_request"]["noul"] >= 0.5:
        return "privacy", "A request about their personal data: GDPR gives you one month to answer."
    if answers["legal_threat"]["noul"] >= 0.5:
        return "team lead", "The customer mentions a lawyer or a consumer authority."
    if chance(team) >= SURE:
        return team["choice"], f"Zuse is {chance(team):.0%} sure."
    return "person", f"Maybe {DECISIONS[team['choice']]}, but Zuse is only {chance(team):.0%} sure."


# 3. Putting it together: one request per ticket.
def handle(ticket):
    response = ask_zuse(ticket["text"], QUESTIONS)
    decision, reason = decide(response["answers"])
    return {"decision": decision, "reason": reason, "tokens": response["usage"]["input_tokens"],
            "text": ticket["text"], "response": response}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        r = handle({"text": " ".join(sys.argv[1:])})
        print(f"{DECISIONS[r['decision']]}: {r['reason']}")
    else:
        try_samples("routing", handle)
