# Test a Bedrock API key

Use an existing Python 3.9+ environment. From the repository directory:

```sh
cd AWS-API
# Only if you need a new Python environment:
# python3 -m venv .venv-aws && . .venv-aws/bin/activate
python -m pip install -r requirements-aws-test.txt

# Create the private key file only if it does not exist.
umask 077
[ -f aws-api-test.env ] || cp aws-api-test.env.example aws-api-test.env
chmod 600 aws-api-test.env
# Edit aws-api-test.env: replace the key placeholder; keep AWS_PROFILE unset.

. ./aws-api-test.env
python aws-api-test.py
```

Defaults: `us-west-2`, `anthropic.claude-haiku-4-5`, workspace `default`.
Success prints `PASS` and `AWS API test OK` (exit code 0).
One billable request; keep the Git-ignored key file private.
If it fails, check key expiry, model access, region, workspace, and network access.

## Bedrock models

Prices are USD per 1 million tokens, Standard US geographic/regional inference, uncached input, prompts up to 100K input tokens (checked October 26, 2026). Sources: [AWS pricing](https://aws.amazon.com/bedrock/pricing/) and the linked model documentation. Global routing, caching, batch processing, and longer contexts can change the rates.

| Model (AWS documentation) | Base model ID | Input / 1M tokens | Output / 1M tokens |
| --- | --- | ---: | ---: |
| [Claude Haiku 5.5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-5-5.html) | `anthropic.claude-haiku-5-5` | $0.11 | $0.55 |
| [Claude Sonnet 5.5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-5-5.html) | `anthropic.claude-sonnet-5-5` | $2.20 | $11.00 |
| [Claude Opus 5.5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-5-5.html) | `anthropic.claude-opus-5-5` | $4.40 | $22.00 |
| [Claude Fable 5.1](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-fable-5-1.html) | `anthropic.claude-fable-5-1` | $11.00 | $55.00 |
| [GPT-6.1 Sol](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-1-sol.html) | `openai.gpt-6.1-sol` | $2.20 | $11.00 |
| [GPT-6 Sol](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-sol.html) | `openai.gpt-6-sol` | $2.20 | $11.00 |
| [GPT-6 Astra](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-astra.html) | `openai.gpt-6-astra` | $11.00 | $55.00 |
| [GPT-6 Luna](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-luna.html) | `openai.gpt-6-luna` | $0.11 | $0.55 |
| [Nova 2 Lite](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-2-lite.html) | `amazon.nova-2-lite-v1:0` | $0.33 | $2.75 |
| [Nova Pro](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-pro.html) | `amazon.nova-pro-v1:0` | $0.80 | $3.20 |
| [Nova Lite](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-lite.html) | `amazon.nova-lite-v1:0` | $0.06 | $0.24 |

This test uses Anthropic's Mantle client, with the Claude base IDs above:

```sh
python aws-api-test.py --model anthropic.claude-haiku-5-5
```

OpenAI and Nova require a different client/API. On `bedrock-runtime`, US cross-region inference uses `us.` before these IDs (for example, `us.amazon.nova-2-lite-v1:0`). Base IDs on Mantle have no routing prefix. Availability depends on region and account access; see each model's documentation.
