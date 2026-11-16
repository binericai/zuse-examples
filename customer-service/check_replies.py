"""Check agent replies: review every answer an agent sends, not a small sample.

Zuse reads the customer's message and the agent's reply together and checks the reply
against a short rubric. Good replies pass, weak ones go to a team lead for coaching, and a
reply that breaks a rule is stopped before it is sent.

    python check_replies.py         # try the sample replies
"""

from zuse import ask_zuse, try_samples

# 1. What Zuse is asked about each reply.
QUESTIONS = {
    "answers_it": {"type": "noul", "instructions":
        "Does the agent's reply deal with what the customer actually asked or complained about?"},
    "rude": {"type": "noul", "instructions":
        "Is the reply rude or cold, or does the agent blame the customer or talk down to them?"},
    "overpromise": {"type": "noul", "instructions":
        "Does the agent offer compensation or a discount, or guarantee something the company does not control, "
        "such as 'I guarantee it arrives tomorrow'? Normal information about a refund, a replacement or a "
        "delivery estimate does not count."},
    "breaks_rule": {"type": "noul", "instructions":
        "Does the agent ask for a password, a full card number or a security code, "
        "or reveal another customer's personal information?"},
}

# 2. Your rules.
SURE = 0.80          # pass a reply when Zuse is at least this sure it answers the question
RULE = f"A reply passes only when Zuse is at least {SURE:.0%} sure it answers the question; otherwise a person checks it."

DECISIONS = {"good": "Good reply", "coach": "Coach the agent", "stop": "Stop: breaks a rule",
             "person": "A person checks"}


def decide(answers):
    if answers["breaks_rule"]["noul"] >= 0.5:
        return "stop", "It asks for a password or card details, or shares another customer's data."
    problems = [name for key, name in (("rude", "sounds rude or blames the customer"),
                                       ("overpromise", "promises too much")) if answers[key]["noul"] >= 0.5]
    p = answers["answers_it"]["noul"]
    if p < 0.5:
        problems.insert(0, "doesn't answer the question")
    if problems:
        return "coach", "Worth a word with the agent: " + ", ".join(problems) + "."
    if p >= SURE:
        return "good", f"Zuse is {p:.0%} sure it answers the question, and found nothing to fix."
    return "person", f"Nothing wrong found, but Zuse is only {p:.0%} sure it answers the question."


# 3. Putting it together: one request per reply.
def handle(item):
    text = f"Customer message:\n{item['customer']}\n\nAgent reply:\n{item['reply']}"
    response = ask_zuse(text, QUESTIONS)
    decision, reason = decide(response["answers"])
    return {"decision": decision, "reason": reason, "tokens": response["usage"]["input_tokens"],
            "text": text, "response": response}


if __name__ == "__main__":
    try_samples("quality", handle)
