"""Bot handover: should a person take over this chat now?

A chatbot answers first. After every customer message, Zuse reads the chat so far and your
rules decide whether a person takes over. Because Zuse reads the whole chat each time, it
notices frustration building up over several messages, not just one angry line.

    python bot_handover.py          # try the sample chats
"""

from zuse import ask_zuse, try_samples

# 1. What Zuse is asked after each customer message.
QUESTIONS = {
    "asked": {"type": "noul", "instructions": "Has the customer asked to talk to a human, a person or a real agent?"},
    "sensitive": {"type": "noul", "instructions":
        "Is this a sensitive situation a bot should not handle, such as fraud, a stolen card, a safety risk, "
        "a death in the family or a customer in a vulnerable situation?"},
    "needs_person": {"type": "noul", "instructions":
        "Should a human support agent take over this chat now, instead of the bot? Yes if the customer is getting "
        "frustrated, or the bot is going in circles or not understanding them."},
}

# 2. Your rules.
SURE = 0.70          # hand over when Zuse is at least this sure a person is needed
RULE = f"A person takes over when Zuse is at least {SURE:.0%} sure one is needed, and at once if it's sensitive or the customer asks."

DECISIONS = {"person": "A person takes over", "bot": "The bot carries on"}


def decide(answers):
    if answers["sensitive"]["noul"] >= 0.5:
        return "person", "This is sensitive. A bot should not handle it."
    if answers["asked"]["noul"] >= 0.5:
        return "person", "The customer asked for a person."
    p = answers["needs_person"]["noul"]
    if p >= SURE:
        return "person", f"Zuse is {p:.0%} sure a person should take over."
    return "bot", f"Zuse is {p:.0%} sure a person is needed, below your {SURE:.0%}."


# 3. Putting it together: ask after every customer message, stop at the first handover.
def transcript(turns):
    return "\n".join(f"{'Customer' if t['who'] == 'customer' else 'Bot'}: {t['text']}" for t in turns)


def handle(chat):
    turns, tokens, n = chat["turns"], 0, 0
    for i, turn in enumerate(turns):
        if turn["who"] != "customer":
            continue
        n += 1
        text = transcript(turns[: i + 1])
        response = ask_zuse(text, QUESTIONS)
        tokens += response["usage"]["input_tokens"]
        decision, reason = decide(response["answers"])
        if decision == "person":
            break
    return {"decision": decision, "reason": f"After customer message {n}: {reason}", "tokens": tokens,
            "text": text, "response": response}


if __name__ == "__main__":
    try_samples("handover", handle)
