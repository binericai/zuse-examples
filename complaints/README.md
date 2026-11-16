# Complaints

Sort real customer complaints by product, check every answer against the truth, and see what
the same job costs with Zuse and with Claude.

The US Consumer Financial Protection Bureau publishes the complaints it receives, in the
customers' own words: 1.7 million with text, public domain. Each one records which product it
is about, so every answer can be checked. [`complaints.py`](complaints.py) is one file you can
read top to bottom: the question, the call, the data download and the scoring.

```bash
cd complaints
python complaints.py              # Zuse, 30 complaints for each of 9 products
python complaints.py --claude     # also Claude Sonnet 5.5 (needs ANTHROPIC_API_KEY)
python complaints.py --bedrock    # the same Claude model through Amazon Bedrock
```

It downloads only a few chunks of the database (about 4 seconds each), not all 900 MB, and
caches them in `.cache/`. Every answer, with Zuse's probability, is saved in `results/`.
It needs `pip install -r ../requirements-benchmarks.txt`. Add `ZUSE_MODEL=zuse-9b` in front to run the 9B.

## Results

270 complaints, 30 for each product, 15 Nov 2026:

| | Right | Input / output tokens per complaint | Cost per million complaints | Median time |
|---|---|---|---|---|
| Zuse 9B (`zuse-9b`) | 75.2% | 405 / 0 | **$49** | 2.0 s |
| Zuse 27B (`zuse-27b`) | 78.5% | 405 / 0 | $304 | 1.7 s |
| Claude Sonnet 5.5 | 80.4% | 940 / 17 | $2,046 ($1,023 batch) | 0.5 s |

The full output and every answer are in [`results/`](results/).

Zuse 27B right, per product: credit reports 100%, student loans 90%, mortgages 87%, bank
accounts 83%, money transfers 80%, credit cards 77%, debt collection 77%, vehicle loans 70%,
payday and personal loans 43%.

What to know when you read these numbers:

- **The labels are noisy.** The product is the one the customer picked when they filed the
  complaint, and many complaints touch two products (a debt collector chasing a credit card
  debt, for example). No model gets close to 100%; compare the models with each other.
- **Claude needs more input tokens** for the same complaint: the instructions and the
  structured-output format add about 500 tokens. Zuse has no output tokens.
- **Claude's "how sure"** is what it says when asked for a number from 0 to 100. Zuse's is the
  probability it gives the product.
- Claude ran with thinking off and structured output, at Anthropic's list prices; with
  thinking on it would cost more. Times are with 8 requests at once.
- 270 complaints is a small test: a difference of a few points can be chance. Run it with
  `--per-product 100` for a firmer answer.

## Make it yours

Change `PRODUCTS` to your own categories and `TASK` to your question, and point `download()`
at your own data. Keep the scoring: it is how you find out whether a threshold is safe before
you automate anything.

## Data licence

CFPB Consumer Complaint Database, public domain (US government work), read from the
[BEE-spoke-data/consumer-finance-complaints](https://huggingface.co/datasets/BEE-spoke-data/consumer-finance-complaints)
copy on Hugging Face (CC0). Nothing from the dataset is stored in this repository.
