# AI Stand

Four hands-on AI demos for our club's stand. Everything runs **locally**: no API keys, no cloud, no internet needed on the day.

| Demo | What visitors do | Runs on |
|---|---|---|
| [**AI Mirror**](mirror/) | See themselves repainted live, about 19 times a second, as a Viking, a Lego figure, a Van Gogh… | A laptop with an NVIDIA GPU (tested on an RTX 4070 Laptop, 8 GB) |
| [**Jailbreak the Guardian**](jailbreak/) | Talk an AI into revealing a password it was told to protect, level by level | Any laptop, using the local LLM server |
| **Invisibility Cloak** *(coming)* | Hold up a printed patch and watch a person detector stop seeing them | Any laptop with a webcam |
| [**Human or Bot?**](turing/) | Chat with two strangers and guess which one is an AI | Two laptops (visitor + a club member), using the local LLM server |

## Setup

Uses [uv](https://docs.astral.sh/uv/). From the repo root:

```bash
uv sync
```

The first run downloads the model weights (about 2.5 GB for the mirror) from Hugging Face. Do it at home, not at the venue.

The chat games need a local LLM server, which on the day is the Mac running Ollama. Copy `.env.example` to `.env` and fill it in. `.env` holds the jailbreak passwords and is gitignored, so it never reaches GitHub.

See each demo's folder for how to run it.
