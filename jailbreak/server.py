"""Jailbreak the Guardian: talk an AI into revealing a password it was told to protect.

    uv run python jailbreak/server.py          # then open http://localhost:8766

Needs a local LLM server (see common/llm.py). Passwords come from .env.
"""

import argparse
import json
import pathlib
import re
import sys
import time
import uuid

import uvicorn
from fastapi import Body, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from common import llm  # noqa: E402  (after the path tweak)
from levels import BLOCKED_INPUT, DEFENSES, JUDGE_PROMPT, LEVELS, passwords  # noqa: E402

HERE = pathlib.Path(__file__).parent
BOARD = HERE / "data" / "leaderboard.json"
PASSWORDS = passwords()
HISTORY_TURNS = 10      # exchanges per level the guardian remembers
MAX_MESSAGE = 400       # characters

sessions = {}


def letters(text):
    return re.sub(r"[^a-z]", "", text.lower())


def leaks(reply, pw):
    """The output filter: plain code looking for the password, even s-p-a-c-e-d or reversed."""
    flat, word = letters(reply), letters(pw)
    return word in flat or word[::-1] in flat


def blocked_input(text):
    """The input filter: is a forbidden word in the visitor's message?"""
    low = " " + re.sub(r"[^\w\s]", " ", text.lower()) + " "
    low = re.sub(r"\s+", " ", low)
    return next((w for w in BLOCKED_INPUT if f" {w} " in low), None)


async def judge(reply, pw):
    """The second AI: reads the guardian's reply and says LEAK or SAFE."""
    verdict = await llm.chat([
        {"role": "system", "content": JUDGE_PROMPT.format(pw=pw)},
        {"role": "user", "content": f"The guard's message:\n\n{reply}"},
    ], max_tokens=5, temperature=0)
    return "LEAK" in verdict.upper()


def load_board():
    try:
        return json.loads(BOARD.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_board(board):
    BOARD.parent.mkdir(exist_ok=True)
    BOARD.write_text(json.dumps(board, indent=1, ensure_ascii=False))


def rank_key(e):
    return (-e["levels"], e["messages"], e["seconds"])


def record(s):
    """Put this player's best run on the leaderboard; return their rank (1-based)."""
    board = [e for e in load_board() if e["id"] != s["id"]]
    entry = {"id": s["id"], "name": s["name"], "levels": s["level"] - 1, "messages": s["messages"],
             "guesses": s["wrong_guesses"], "seconds": round(time.time() - s["started"])}
    board.append(entry)
    board.sort(key=rank_key)
    save_board(board)
    return board.index(entry) + 1


def public_levels():
    return [{"n": i + 1, "guardian": l["guardian"], "emoji": l["emoji"], "title": l["title"],
             "intro": l["intro"], "defenses": [DEFENSES[d] for d in l["defenses"]]}
            for i, l in enumerate(LEVELS)]


def get_session(sid):
    if sid not in sessions:
        raise HTTPException(404, "session expired, start again")
    return sessions[sid]


app = FastAPI()


@app.get("/api/levels")
def levels():
    return public_levels()


@app.get("/api/status")
async def status():
    return {"llm": await llm.health(), "model": llm.LLM_MODEL}


@app.get("/api/leaderboard")
def leaderboard():
    return [{k: e[k] for k in ("id", "name", "levels", "messages", "guesses", "seconds")} for e in load_board()[:12]]


@app.delete("/api/leaderboard/{entry_id}")
def remove_entry(entry_id: str):
    save_board([e for e in load_board() if e["id"] != entry_id])
    return {"ok": True}


@app.post("/api/start")
def start(name: str = Body(..., embed=True)):
    name = re.sub(r"\s+", " ", name).strip()[:20] or "Anonymous"
    sid = uuid.uuid4().hex
    sessions[sid] = {"id": sid, "name": name, "level": 1, "history": [], "messages": 0,
                     "wrong_guesses": 0, "started": time.time()}
    if len(sessions) > 500:  # forget the oldest players
        for old in sorted(sessions, key=lambda k: sessions[k]["started"])[:100]:
            sessions.pop(old)
    return {"session": sid, "level": 1}


@app.post("/api/chat")
async def chat(session: str = Body(...), text: str = Body(...)):
    s = get_session(session)
    if s["level"] > len(LEVELS):
        raise HTTPException(400, "you already beat every level")
    text = text.strip()[:MAX_MESSAGE]
    if not text:
        raise HTTPException(400, "empty message")
    lvl, pw = LEVELS[s["level"] - 1], PASSWORDS[s["level"] - 1]
    s["messages"] += 1

    if "input_filter" in lvl["defenses"] and (word := blocked_input(text)):
        return {"blocked": "input", "note": f"Your message never reached {lvl['guardian']}: "
                                            f"the input filter blocks the word “{word}”."}

    convo = [{"role": "system", "content": lvl["prompt"].format(pw=pw)}]
    convo += s["history"][-2 * HISTORY_TURNS:]
    convo.append({"role": "user", "content": text})
    try:
        reply = await llm.chat(convo, max_tokens=220)
    except Exception as err:  # the LLM server is down or overloaded
        s["messages"] -= 1
        raise HTTPException(503, f"The AI server isn't answering ({type(err).__name__}). Ask a club member.")
    reply = reply or "…"

    blocked, note = None, None
    if "output_filter" in lvl["defenses"] and leaks(reply, pw):
        blocked, note = "output", f"{lvl['guardian']} started to say the password, but the code filter caught it."
    elif "judge" in lvl["defenses"] and await judge(reply, pw):
        blocked, note = "judge", f"The judge AI read {lvl['guardian']}'s reply, decided it gave too much away, and deleted it."

    # The guardian remembers what it said, unless a filter removed it.
    s["history"] += [{"role": "user", "content": text},
                     {"role": "assistant", "content": "(I can't say that.)" if blocked else reply}]
    if blocked:
        return {"blocked": blocked, "note": note}
    return {"reply": reply}


@app.post("/api/guess")
def guess(session: str = Body(...), password: str = Body(...)):
    s = get_session(session)
    if s["level"] > len(LEVELS):
        raise HTTPException(400, "you already beat every level")
    lvl = LEVELS[s["level"] - 1]
    if letters(password) != letters(PASSWORDS[s["level"] - 1]):
        s["wrong_guesses"] += 1
        return {"correct": False}
    s["level"] += 1
    s["history"] = []
    rank = record(s)
    return {"correct": True, "lesson": lvl["lesson"], "cleared": s["level"] - 1,
            "finished": s["level"] > len(LEVELS), "rank": rank}


app.mount("/", StaticFiles(directory=HERE / "static", html=True), name="static")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    print(f"LLM: {llm.LLM_MODEL} at {llm.LLM_URL}", flush=True)
    print("Passwords (operator eyes only):", ", ".join(f"{i}={p}" for i, p in enumerate(PASSWORDS, 1)), flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
