"""Human or Bot? A Turing test: a visitor chats with two strangers and guesses which is the AI.

    uv run python turing/server.py

  visitor screen  http://localhost:8767/
  human player    http://<this laptop's IP>:8767/human.html   (on the club member's laptop)

One stranger is the bot (the local LLM, see common/llm.py). The other is a club
member typing on the human page. Which side is which is shuffled every round.
"""

import argparse
import asyncio
import json
import pathlib
import random
import sys
import time
import uuid

import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from common import llm  # noqa: E402
from personas import humanize, language_hint, new_persona, typing_seconds  # noqa: E402

HERE = pathlib.Path(__file__).parent
STATS = HERE / "data" / "stats.json"
IDLE_END = 600          # a round with no messages for this long was abandoned: end it
MAX_MESSAGE = 300

judges: set[WebSocket] = set()      # visitor screens (normally one)
humans: set[WebSocket] = set()      # club member screens (normally one)
round_ = None                        # the round being played, or None
bot_task: asyncio.Task | None = None


def load_stats():
    try:
        return json.loads(STATS.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"rounds": 0, "correct": 0}


def save_stats(s):
    STATS.parent.mkdir(exist_ok=True)
    STATS.write_text(json.dumps(s))


async def send(sockets, **msg):
    for ws in list(sockets):
        try:
            await ws.send_text(json.dumps(msg))
        except Exception:
            sockets.discard(ws)


async def status():
    await send(judges, type="status", human=bool(humans), llm=await llm.health(), stats=load_stats(),
               playing=round_ is not None)
    await send(humans, type="status", playing=round_ is not None, side=round_ and round_["human"])


async def start_round():
    global round_
    human = random.choice("AB")
    round_ = {"id": uuid.uuid4().hex, "human": human, "bot": "B" if human == "A" else "A",
              "persona": new_persona(), "history": [], "started": time.time(), "active": time.time(),
              "ended": False}
    await send(judges, type="round")
    await send(humans, type="round", side=human)


async def bot_reply(rnd, question):
    """Answer like a person: wait to 'read', show typing, then send."""
    try:
        t0 = time.time()
        convo = [{"role": "system", "content": rnd["persona"]["prompt"]}] + rnd["history"][-20:]
        if hint := language_hint(question):  # only in what the model sees, not the stored history
            convo[-1] = {"role": "user", "content": f"{convo[-1]['content']}\n\n({hint})"}
        reply = humanize(await llm.chat(convo, max_tokens=80, temperature=0.9))
        wait = typing_seconds(reply, question) - (time.time() - t0)  # generating counts as "reading"
        await asyncio.sleep(max(0.0, min(1.5, wait / 3)))            # reading before typing starts
        await send(judges, type="typing", who=rnd["bot"], on=True)
        await asyncio.sleep(max(0.5, wait - min(1.5, wait / 3)))
        if rnd is not round_ or rnd["ended"]:
            return
        rnd["history"].append({"role": "assistant", "content": reply})
        await send(judges, type="msg", who=rnd["bot"], text=reply)
        await send(judges, type="typing", who=rnd["bot"], on=False)
    except asyncio.CancelledError:
        await send(judges, type="typing", who=rnd["bot"], on=False)
        raise
    except Exception as err:
        print("bot failed:", repr(err), flush=True)
        await send(judges, type="typing", who=rnd["bot"], on=False)


async def visitor_says(to, text):
    global bot_task
    rnd = round_
    if not rnd or rnd["ended"] or to not in "AB" or not text:
        return
    rnd["active"] = time.time()
    if to == rnd["human"]:
        await send(humans, type="msg", who="visitor", text=text)
    else:
        rnd["history"].append({"role": "user", "content": text})
        if bot_task and not bot_task.done():  # several messages in a row: answer them all at once
            bot_task.cancel()
        bot_task = asyncio.create_task(bot_reply(rnd, text))


async def end_round(pick):
    global round_
    rnd = round_
    if not rnd or rnd["ended"]:
        return
    rnd["ended"] = True
    if bot_task and not bot_task.done():
        bot_task.cancel()
    stats = load_stats()
    correct = pick == rnd["human"] if pick in ("A", "B") else None
    if correct is not None:
        stats["rounds"] += 1
        stats["correct"] += int(correct)
        save_stats(stats)
    p = rnd["persona"]
    reveal = dict(type="reveal", human=rnd["human"], bot=rnd["bot"], pick=pick, correct=correct, stats=stats,
                  persona={k: p[k] for k in ("name", "age", "study", "likes")}, prompt=p["prompt"])
    await send(judges, **reveal)
    await send(humans, **reveal)
    round_ = None


async def heartbeat():
    while True:
        await asyncio.sleep(10)
        if round_ and time.time() - round_["active"] > IDLE_END:
            await end_round(None)  # abandoned
        await status()


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(heartbeat())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws/judge")
async def judge_ws(ws: WebSocket):
    await ws.accept()
    judges.add(ws)
    await status()
    try:
        while True:
            m = json.loads(await ws.receive_text())
            if m["type"] == "start":
                if not humans:
                    await send({ws}, type="error", text="The human player isn't connected yet. Ask a club member.")
                elif round_ is None:
                    await start_round()
            elif m["type"] == "say":
                await visitor_says(m.get("to"), str(m.get("text", "")).strip()[:MAX_MESSAGE])
            elif m["type"] == "typing" and round_ and m.get("to") == round_["human"]:
                await send(humans, type="typing", who="visitor", on=bool(m.get("on")))
            elif m["type"] == "vote":
                await end_round(m.get("pick"))
            elif m["type"] == "abort":
                await end_round(None)
            await status()
    except WebSocketDisconnect:
        judges.discard(ws)


@app.websocket("/ws/human")
async def human_ws(ws: WebSocket):
    await ws.accept()
    humans.add(ws)
    await status()
    if round_:
        await send({ws}, type="round", side=round_["human"])
    try:
        while True:
            m = json.loads(await ws.receive_text())
            if not round_ or round_["ended"]:
                continue
            if m["type"] == "say" and (text := str(m.get("text", "")).strip()[:MAX_MESSAGE]):
                round_["active"] = time.time()
                await send(judges, type="msg", who=round_["human"], text=text)
                await send(judges, type="typing", who=round_["human"], on=False)
            elif m["type"] == "typing":
                await send(judges, type="typing", who=round_["human"], on=bool(m.get("on")))
    except WebSocketDisconnect:
        humans.discard(ws)
        await status()


app.mount("/", StaticFiles(directory=HERE / "static", html=True), name="static")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--host", default="0.0.0.0", help="0.0.0.0 so the human player's laptop can connect")
    args = parser.parse_args()
    print(f"LLM: {llm.LLM_MODEL} at {llm.LLM_URL}", flush=True)
    print(f"visitor: http://localhost:{args.port}/   human player: http://<this-ip>:{args.port}/human.html", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
