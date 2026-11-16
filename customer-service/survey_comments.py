"""Survey comments: what are customers talking about?

One comment can be about several things, so each topic is its own yes/no question. Zuse
answers all of them in one request, in any language.

    python survey_comments.py       # try the sample comments
"""

from zuse import ask_zuse, try_samples

# 1. What Zuse is asked: one yes/no question per topic.
TOPICS = {
    "delivery": "delivery, shipping or how long the order took to arrive",
    "product": "the products themselves: their quality, the range on offer, or whether they match the description",
    "price": "price, cost or value for money",
    "service": "the customer service team or how they were treated by staff",
    "website": "the website, the app or the checkout",
    "returns": "returning an item or getting a refund",
}
QUESTIONS = {topic: {"type": "noul", "instructions": f"Does the comment talk about {what}?"}
             for topic, what in TOPICS.items()}

# 2. Your rules.
SURE = 0.5           # count a topic when Zuse thinks it's more likely than not
RULE = f"A topic counts when Zuse is at least {SURE:.0%} sure the comment talks about it."

DECISIONS = {"none": "Nothing specific"}   # otherwise the decision is the list of topics


def decide(answers):
    topics = [t for t in TOPICS if answers[t]["noul"] >= SURE]
    if not topics:
        return "none", "No topic stands out."
    return " + ".join(sorted(topics)), ", ".join(f"{t} {answers[t]['noul']:.0%}" for t in topics)


# 3. Putting it together: one request per comment.
def handle(comment):
    text = (f"Star rating: {comment['stars']} of 5\n" if comment.get("stars") else "") + f"Comment: {comment['text']}"
    response = ask_zuse(text, QUESTIONS)
    decision, reason = decide(response["answers"])
    return {"decision": decision, "reason": reason, "tokens": response["usage"]["input_tokens"],
            "text": text, "response": response}


if __name__ == "__main__":
    try_samples("feedback", handle)
