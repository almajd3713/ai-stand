# Human or Bot?

A Turing test. A visitor chats with two strangers at once for three minutes, then guesses which one is the human. One stranger is a club member typing on another laptop. The other is the local LLM playing a student. Sides are shuffled every round, and the start screen shows how often visitors get fooled.

## Run it

Needs the local LLM server (see [`jailbreak/README.md`](../jailbreak/README.md#run-it) and `.env.example`).

```bash
uv run python turing/server.py
```

- **Visitor screen:** http://localhost:8767 on the stand laptop.
- **Human player:** `http://<stand laptop's IP>:8767/human.html` on a club member's laptop, out of the visitor's sight. Find the IP with `ipconfig` (Windows) or `ip addr`. The server listens on all interfaces so the other laptop can reach it. Allow it through the firewall if Windows asks.

  If the server runs inside WSL, other machines can't reach it directly. Either run it on another laptop, or turn on WSL's mirrored networking (`networkingMode=mirrored` in `%UserProfile%\.wslconfig`).

The visitor can't start a round until the human player's page is open.

## How the bot passes for human

- **A persona:** a random student (name, age, subject, hobbies), from [`personas.py`](personas.py). Set `TURING_PLACE` in `.env` (for example `the University of Algiers`) so it claims to study where the visitors do.
- **A prompt that fights the model's natural voice:** short, lowercase, lazy, sarcastic, no lists, and *not* an encyclopedia ("idk, google it").
- **Code that removes the tells anyway:** long dashes, markdown, emoji, a third sentence. It also adds the occasional typo.
- **Human timing:** it waits to "read", shows the typing indicator, and "types" at 5–7 characters a second. Time spent generating counts toward that wait.
- **Language matching:** the visitor's language (French, Arabic script, Darija in Latin letters) is detected in code and the bot is told to answer in it.

Its Darija is still weak, because small models have seen little written Darija. That's a real tell, and worth pointing out after a round.

## Data

The fooled-rate stats are in `turing/data/stats.json` (gitignored). Delete the file to reset them.
