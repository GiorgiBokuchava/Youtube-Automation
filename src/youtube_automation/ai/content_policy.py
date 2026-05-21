"""PG / YouTube-safe rules for all AI-generated text."""

from __future__ import annotations

PG_AI_CONTENT_POLICY = """
CHANNEL SAFETY (mandatory — applies to every response):
- Keep all output PG and family-friendly for a monetized YouTube channel. Never write anything
  that could trigger strikes, demonetization, or removal.
- Avoid: profanity and crude language; slurs and hate; sexual or suggestive content; depicting
  or glorifying violence, injury, death, or self-harm; drugs and substance abuse; extremism;
  graphic, shocking, or tragedy-focused framing; NSFW or adult themes.
- Prefer neutral, light, or comedic tone when clips are chaotic or dramatic — surprise, disbelief,
  or "that escalated" beats sensationalizing harm to people or animals.
- When source material is serious, stay factual and understated; do not dramatize suffering.
""".strip()

# Substring match on lowercased text (same approach as legacy comment filtering).
BANNED_SUBSTRINGS: frozenset[str] = frozenset({
    # profanity
    "fuck", "fucking", "fucked", "fucker", "motherfuck", "motherfucker",
    "shit", "shitty", "bullshit",
    "bitch", "bitches",
    "cunt", "cunts",
    "ass", "asshole", "jackass", "dumbass", "smartass",
    "bastard",
    "dick", "dicks", "dickhead",
    "cock", "cocks",
    "pussy",
    "piss", "pissed",
    "damn", "damnit",
    "crap",
    "twat",
    "wanker", "wank",
    "arse",
    # slurs
    "nigger", "nigga", "nig",
    "faggot", "fag",
    "retard", "retarded",
    "spic", "chink", "gook", "kike", "wetback", "cracker",
    "tranny",
    "coon",
    # sexual content
    "slut", "slutty",
    "whore",
    "rape", "rapist", "raped", "raping",
    "molest", "molested",
    "porn", "porno", "pornhub",
    "nsfw",
    "sex", "sexy", "sexist",
    "horny",
    "dildo",
    "boobs", "tits", "titties",
    "penis", "vagina", "genitals",
    # violence / self-harm
    "kill", "killing", "kills", "killed", "killer",
    "murder", "murders", "murdered",
    "suicide", "suicidal",
    "die", "died", "dying",
    "dead", "death",
    "gore", "gory",
    "blood", "bloody",
    "stab", "stabbed",
    "shoot", "shot",
    "gun", "guns",
    "bomb", "bombing",
    "explode", "explosion",
    "hang", "hanged", "hanging",
    "torture", "torturing",
    "abuse", "abused", "abusive",
    "domestic",
    "assault",
    "attack", "attacked",
    "hurt", "injury", "injured",
    "fatal", "fatality",
    "accident",
    "disaster",
    "tragedy", "tragic",
    # drugs
    "drug", "drugs",
    "cocaine", "heroin", "meth", "crystal",
    "weed", "marijuana",
    "overdose",
    # hate / extremism
    "nazi", "nazis",
    "hitler",
    "terrorist", "terrorism",
    "racist", "racism",
    "hate crime",
})


def apply_content_policy_to_prompt(prompt: str) -> str:
    """Prepend the global PG safety block to an AI user/task prompt."""
    body = (prompt or "").strip()
    if not body:
        return PG_AI_CONTENT_POLICY
    return f"{PG_AI_CONTENT_POLICY}\n\n---\n\n{body}"


def is_pg_safe_text(text: str, *, extra_banned: frozenset[str] | None = None) -> bool:
    """Return True when *text* contains none of the banned substrings."""
    if not text:
        return True
    lower = text.lower()
    banned = BANNED_SUBSTRINGS if extra_banned is None else BANNED_SUBSTRINGS | extra_banned
    return not any(w in lower for w in banned)
