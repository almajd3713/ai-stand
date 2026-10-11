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
PLAYERS = HERE / "data" / "players.json"
PASSWORDS = passwords()
HISTORY_TURNS = 10      # exchanges per level the guardian remembers
MAX_MESSAGE = 400       # characters
IDLE_CAP = 120          # seconds: a longer pause between actions doesn't count as playing time


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


# ---------------------------------------------------------------- players
# A player is their name: typing the same name again resumes their game,
# even after the server restarts.

def player_key(name):
    return re.sub(r"\s+", " ", name).strip().casefold()


def load_players():
    try:
        return json.loads(PLAYERS.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_players():
    PLAYERS.parent.mkdir(exist_ok=True)
    tmp = PLAYERS.with_suffix(".tmp")
    tmp.write_text(json.dumps(players, ensure_ascii=False))
    tmp.replace(PLAYERS)


def played(p):
    """Add the time since the player's last action, but not long breaks."""
    now = time.time()
    p["seconds"] += min(now - p["last"], IDLE_CAP)
    p["last"] = now


players = load_players()   # player key -> progress
sessions = {}              # session token -> player key


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
             "guesses": s["wrong_guesses"], "seconds": round(s["seconds"])}
    board.append(entry)
    board.sort(key=rank_key)
    save_board(board)
    return board.index(entry) + 1


def public_levels():
    return [{"n": i + 1, "guardian": l["guardian"], "emoji": l["emoji"], "title": l["title"],
             "intro": l["intro"], "defenses": [DEFENSES[d] for d in l["defenses"]]}
            for i, l in enumerate(LEVELS)]


def get_session(sid):
    if sessions.get(sid) not in players:
        raise HTTPException(404, "session expired, type your name again to continue")
    return players[sessions[sid]]


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
    """Operator: remove a player (rude names happen), from the board and from saved progress."""
    save_board([e for e in load_board() if e["id"] != entry_id])
    if players.pop(entry_id, None):
        save_players()
    return {"ok": True}


@app.post("/api/start")
def start(name: str = Body(...), resume: bool = Body(False)):
    """A new name starts a game. A known name first gets asked "is this you?", then resumes."""
    name = re.sub(r"\s+", " ", name).strip()[:20] or "Anonymous"
    key = player_key(name)
    p = players.get(key)
    if p and not resume:
        return {"existing": {"name": p["name"], "level": p["level"], "messages": p["messages"],
                             "finished": p["level"] > len(LEVELS)}}
    if p and p["level"] > len(LEVELS):
        raise HTTPException(400, "this player already beat every guardian")
    if not p:
        p = players[key] = {"id": key, "name": name, "level": 1, "history": [], "messages": 0,
                            "wrong_guesses": 0, "seconds": 0.0, "last": time.time()}
    p["last"] = time.time()  # the break since their last visit doesn't count
    save_players()
    sid = uuid.uuid4().hex
    sessions[sid] = key
    return {"session": sid, "name": p["name"], "level": p["level"], "messages": p["messages"],
            "wrong": p["wrong_guesses"], "seconds": round(p["seconds"]), "history": p["history"]}


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
    played(s)

    if "input_filter" in lvl["defenses"] and (word := blocked_input(text)):
        save_players()
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
    s["history"] = s["history"][-2 * HISTORY_TURNS:]
    save_players()
    if blocked:
        return {"blocked": blocked, "note": note}
    return {"reply": reply}


@app.post("/api/guess")
def guess(session: str = Body(...), password: str = Body(...)):
    s = get_session(session)
    if s["level"] > len(LEVELS):
        raise HTTPException(400, "you already beat every level")
    lvl = LEVELS[s["level"] - 1]
    played(s)
    if letters(password) != letters(PASSWORDS[s["level"] - 1]):
        s["wrong_guesses"] += 1
        save_players()
        return {"correct": False}
    s["level"] += 1
    s["history"] = []
    save_players()
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
