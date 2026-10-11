# Human or Bot?

A Turing test. A visitor chats with two strangers at once, then guesses which one is the human. There's no time limit: the visitor can vote whenever they like, and the club decides when a round should end. A timer counting up shows how long the round has been going. One stranger is a club member typing on another laptop. The other is the local LLM playing a student. Sides are shuffled every round, and the start screen shows how often visitors get fooled.

## Run it

Needs the local LLM server (see [`jailbreak/README.md`](../jailbreak/README.md#run-it) and `.env.example`).

```bash
uv run python turing/server.py
```

- **Visitor screen:** http://localhost:8767 on the stand laptop.
- **Human player:** `http://<stand laptop's IP>:8767/human.html` on a club member's laptop, out of the visitor's sight. Find the IP with `ipconfig` (Windows) or `ip addr`. The server listens on all interfaces so the other laptop can reach it. Allow it through the firewall if Windows asks.

  **If the server runs inside WSL**, two things are needed:

  1. Mirrored networking, so WSL shares the PC's IP address: `networkingMode=mirrored` under `[wsl2]` in `%UserProfile%\.wslconfig`, then `wsl --shutdown`.
  2. A firewall opening. WSL's Hyper-V firewall blocks all incoming connections by default. Run `./stand.sh firewall` once and approve the Windows admin prompt. It opens port 8767 only. `./stand.sh firewall close` removes the rule. The script behind it is [`tools/open-ports.ps1`](../tools/open-ports.ps1).

  `./stand.sh turing` prints the exact address for the other PC. Both PCs must be on the same network. Some university and café Wi-Fi networks block device-to-device traffic. If it still can't connect, use your own router or a phone hotspot.

The visitor can't start a round until the human player's page is open. A round with no messages for 10 minutes ends by itself.

## How the bot passes for human

- **A persona:** a random student (name, age, subject, hobbies), from [`personas.py`](personas.py). Set `TURING_PLACE` in `.env` (for example `the University of Algiers`) so it claims to study where the visitors do.
- **A prompt that fights the model's natural voice:** short, lowercase, lazy, sarcastic, no lists, and *not* an encyclopedia ("idk, google it").
- **Code that removes the tells anyway:** long dashes, markdown, emoji, a third sentence. It also adds the occasional typo.
- **Human timing:** it waits to "read", shows the typing indicator, and "types" at 5–7 characters a second. Time spent generating counts toward that wait.
- **Language matching:** the visitor's language (French, Arabic script, Darija in Latin letters) is detected in code and the bot is told to answer in it.

Its Darija is still weak, because small models have seen little written Darija. That's a real tell, and worth pointing out after a round.

## Data

The fooled-rate stats are in `turing/data/stats.json` (gitignored). Delete the file to reset them.
