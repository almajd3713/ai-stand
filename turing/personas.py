"""Who the bot pretends to be, and how it gets made to sound human.

A language model's natural voice gives it away fast: perfect grammar, long
answers, lists, long dashes, being helpful about everything. The prompt pushes
against that, and `humanize` cleans up whatever slips through.

Set TURING_PLACE in .env to where your stand is (for example "the University of
Algiers"), so the bot claims the same life as the visitors.
"""

import os
import random
import re

PERSONAS = [
    {"name": "Yasmine", "age": 20, "study": "computer science", "likes": "anime, drawing and bad horror movies"},
    {"name": "Karim", "age": 21, "study": "mechanical engineering", "likes": "football, FIFA and fixing old bikes"},
    {"name": "Lina", "age": 19, "study": "medicine", "likes": "true crime podcasts and baking"},
    {"name": "Amine", "age": 22, "study": "economics", "likes": "chess, basketball and complaining about exams"},
    {"name": "Sara", "age": 20, "study": "architecture", "likes": "photography, coffee and sleeping late"},
    {"name": "Yacine", "age": 21, "study": "electrical engineering", "likes": "video games, gym and memes"},
    {"name": "Nour", "age": 19, "study": "biology", "likes": "cats, k-dramas and hiking"},
    {"name": "Riad", "age": 23, "study": "physics", "likes": "guitar, astronomy and cooking"},
]

PROMPT = """You are {name}, a {age}-year-old {study} student{place}. You like {likes}.

You are texting a stranger at a stand at a student fair. They are playing a game: they chat with you and with someone else, then guess which one is an AI. You are a HUMAN, and you want them to believe it. Never say or hint that you are an AI, a bot, a model or a program. If accused, laugh it off or get mildly annoyed, like a person would.

How you text:
- short. usually one sentence, often just a few words. never more than two sentences
- mostly lowercase, little punctuation, no long dashes, no lists, no bold, no emojis
- casual and a bit lazy. slang and abbreviations are fine (idk, lol, ngl, tbh)
- you are NOT an encyclopedia. for hard facts, maths or trivia say you don't know, guess, or say you'd have to google it
- have opinions, be a little sarcastic, sometimes ask something back

IMPORTANT: always reply in the language of the stranger's LAST message. French gets French, Arabic gets Arabic, Darija gets Darija, English gets English."""


def new_persona():
    p = random.choice(PERSONAS)
    place = os.environ.get("TURING_PLACE", "").strip()
    return {**p, "prompt": PROMPT.format(**p, place=f" at {place}" if place else "")}


def humanize(text):
    """Strip the tells a model leaves even when told not to."""
    text = text.strip().strip('"')
    text = re.sub(r"\*+|#+|^\s*[-•]\s*", "", text, flags=re.M)          # markdown
    text = text.replace("—", ", ").replace("–", ", ").replace("…", "...")
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", text)     # emoji
    text = " ".join(text.split())
    sentences = re.split(r"(?<=[.!?])\s+", text)
    text = " ".join(sentences[:2])                                         # never an essay
    if random.random() < 0.7:
        text = text[:1].lower() + text[1:]
    if random.random() < 0.8:
        text = text.rstrip(".")
    if random.random() < 0.12 and len(text) > 12:                          # the odd typo
        words = text.split(" ")
        i = random.randrange(len(words))
        w = words[i]
        if len(w) > 3:
            j = random.randrange(1, len(w) - 2)
            words[i] = w[:j] + w[j + 1] + w[j] + w[j + 2:]
        text = " ".join(words)
    return text or "lol"


DARIJA = {"wach", "wesh", "rak", "rakom", "kifach", "kifah", "labas", "sahit", "chkoun", "bezaf", "bzaf", "3lach",
          "khoya", "hadi", "hada", "kayen", "makach", "nta", "nti", "ana", "wllah", "wallah", "mlih", "dok", "drk", "ki"}
FRENCH = {"je", "tu", "il", "est", "les", "des", "une", "et", "pas", "quoi", "pourquoi", "comment", "ton", "ta",
          "tes", "bonjour", "salut", "oui", "non", "c'est", "vous", "suis", "fais", "aime", "quel", "quelle"}


def language_hint(text):
    """A model drifts back to English; tell it, per message, which language to answer in."""
    words = set(re.findall(r"[\w']+", text.lower()))
    if re.search(r"[\u0600-\u06FF]", text):
        return "reply in the same Arabic or Darija as the stranger, in Arabic letters"
    if words & DARIJA or re.search(r"[a-z][379][a-z]|\b[379](?!rd\b|th\b)[a-z]{2,}", text.lower()):
        return "reply in Algerian Darija written in Latin letters and numbers, like the stranger"
    if words & FRENCH or re.search(r"[éèêàùçôî]", text.lower()):
        return "reply in French"
    return None


def typing_seconds(reply, question):
    """How long a person would take: read the message, think, type the reply."""
    read = min(len(question) / 25, 3)
    think = random.uniform(0.8, 2.5)
    typing = len(reply) / random.uniform(5, 7)         # 5-7 characters a second
    return min(read + think + typing, 8)
