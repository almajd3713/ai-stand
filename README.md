# AI Stand

Four hands-on AI demos for our club's stand. Everything runs **locally**: no API keys, no cloud, no internet needed on the day.

| Demo | What visitors do | Runs on |
|---|---|---|
| [**AI Mirror**](mirror/) | See themselves repainted live, about 19 times a second, as a Viking, a Lego figure, a Van Gogh… | A laptop with an NVIDIA GPU (tested on an RTX 4070 Laptop, 8 GB) |
| [**Jailbreak the Guardian**](jailbreak/) | Talk an AI into revealing a password it was told to protect, level by level | Any laptop, using the local LLM server |
| [**Invisibility Cloak**](cloak/) | Hold up a printed patch and watch a person detector stop seeing them | Any laptop with a webcam (CPU is enough) |
| [**Human or Bot?**](turing/) | Chat with two strangers and guess which one is an AI | Two laptops (visitor + a club member), using the local LLM server |

## Setup

Uses [uv](https://docs.astral.sh/uv/). From the repo root:

```bash
uv sync
```

The first run downloads the model weights (about 2.5 GB for the mirror) from Hugging Face. Do it at home, not at the venue.

The chat games need a local LLM server, which on the day is the Mac running Ollama. Copy `.env.example` to `.env` and fill it in. `.env` holds the jailbreak passwords and is gitignored, so it never reaches GitHub.

See each demo's folder for how to run it.

## On the day

| Machine | Runs | Command |
|---|---|---|
| Gaming laptop (RTX 4070) | AI Mirror | `uv run python mirror/server.py`, then http://localhost:8765 |
| Mac (M3 Pro) | The LLM server for both chat games | `OLLAMA_HOST=0.0.0.0 ollama serve` (with `qwen3.5:9b` pulled) |
| Laptop 1 | Jailbreak the Guardian | `uv run python jailbreak/server.py`, then http://localhost:8766 |
| Laptop 2 | Invisibility Cloak | `uv run python cloak/server.py`, then http://localhost:8768 |
| Laptop 3 + a club member's laptop | Human or Bot? | `uv run python turing/server.py`. Visitor: http://localhost:8767. Human: `http://<laptop 3 IP>:8767/human.html` |

Checklist:

- [ ] Bring a router. All laptops join its network; it doesn't need internet. Note the Mac's IP and put it in each laptop's `.env` as `LLM_URL=http://<mac-ip>:11434`.
- [ ] `.env` on the jailbreak laptop has the six passwords (`JB_PASSWORD_1` … `6`).
- [ ] Every laptop has run `uv sync` and started its demo once at home, so all models are already downloaded.
- [ ] Gaming laptop: plugged in, Best performance mode, nothing else using the GPU (close VS Code; stop k3s and other GPU jobs).
- [ ] The printed patch and control are glued to cardboard.
- [ ] Each demo's README has an "operating it" section. Skim them.
