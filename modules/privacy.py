"""Protecting residents and the system: personal details in text, spam, flooding, and photo metadata.

- mask_pii: phone numbers, e-mail addresses and ID numbers people type into a complaint are replaced before anything is saved.
- screen: simple spam checks (links, gibberish, repeated characters, promotional phrases). Clear spam is refused,
  doubtful text is held for an officer instead of being sent to a crew.
- RateLimiter: a sliding window, used to stop one visitor (or everyone together) flooding the system.
- clean_photo: checks that an upload is really an image and removes its hidden metadata (camera, date and GPS position).
"""
import io
import re
import unicodedata

MAX_TEXT = 1000
MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_PHOTO_PIXELS = 25_000_000

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_ID12 = re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")                         # 12-digit ID numbers such as Aadhaar
_MOBILE = re.compile(r"(?<!\d)(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")           # Indian mobile numbers
_LANDLINE = re.compile(r"(?<!\d)0\d{2,4}[\s-]?(?:\d{6,8}|\d{3,4}[\s-]\d{3,4})(?!\d)")     # 044 2345 6789, 044-23456789, 04423456789
_URL = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9\-]+\.(?:com|net|org|xyz|top|club|info|biz|ru|cn)\b", re.I)
_PROMO = ("buy now", "click here", "free money", "lottery", "whatsapp me", "casino", "bitcoin", "loan offer", "earn money",
          "limited offer", "100% free", "winner", "viagra")


def clean_text(text):
    """Remove control characters and tidy the spacing."""
    text = unicodedata.normalize("NFKC", text or "")
    text = "".join(c for c in text if c.isprintable() or c in "\n\t ")
    return re.sub(r"\s+", " ", text).strip()


def mask_pii(text):
    """Return (masked text, list of what was removed). Order matters: a 12-digit number such as +91 98765 43210 is a phone."""
    removed = []
    for kind, pattern, label in (("email", _EMAIL, "[email removed]"), ("phone number", _MOBILE, "[phone removed]"),
                                 ("phone number", _LANDLINE, "[phone removed]"), ("id number", _ID12, "[id number removed]")):
        text, n = pattern.subn(label, text)
        if n and kind not in removed:
            removed.append(kind)
    return text, removed


def screen(text):
    """Clean a complaint and decide what to do with it.

    Returns {'text', 'pii_removed', 'score', 'reasons', 'action', 'message'} where action is 'accept', 'review' or 'reject'.
    """
    t = clean_text(text)
    if len(t) > MAX_TEXT:
        return {"text": t[:MAX_TEXT], "pii_removed": [], "score": 9, "reasons": ["too long"], "action": "reject",
                "message": f"Please keep the description under {MAX_TEXT} characters."}
    masked, removed = mask_pii(t)
    reasons, score = [], 0
    low = masked.lower()
    if _URL.search(masked):
        score += 2; reasons.append("contains a web link")
    if any(p in low for p in _PROMO):
        score += 3; reasons.append("promotional wording")
    letters = sum(c.isalpha() for c in masked)
    if len(masked) >= 8 and letters < 0.4 * len(masked):
        score += 2; reasons.append("mostly digits or symbols")
    if re.search(r"(\S)\1{5,}", masked):
        score += 2; reasons.append("repeated characters")
    words = low.split()
    if len(words) >= 6 and len(set(words)) / len(words) < 0.3:
        score += 2; reasons.append("repeated words")
    if len(masked) >= 15 and sum(c.isupper() for c in masked) > 0.8 * max(letters, 1):
        score += 1; reasons.append("all capital letters")
    tokens = [w for w in re.findall(r"[a-z]+", low) if len(w) >= 4]
    mashed = [w for w in tokens if not re.search(r"[aeiou]", w) or re.search(r"[^aeiou\W\d_]{6,}", w)]   # no vowel, or 6+ consonants in a row
    if len(mashed) >= 2 and len(mashed) / len(tokens) >= 0.5:
        score += 2; reasons.append("looks like random typing")
    if score >= 4:
        return {"text": masked, "pii_removed": removed, "score": score, "reasons": reasons, "action": "reject",
                "message": "This looks like spam, so it was not sent. Please describe the civic problem in your own words."}
    if score >= 2:
        return {"text": masked, "pii_removed": removed, "score": score, "reasons": reasons, "action": "review", "message": ""}
    return {"text": masked, "pii_removed": removed, "score": score, "reasons": reasons, "action": "accept", "message": ""}


class RateLimitError(ValueError):
    pass


class RateLimiter:
    """Allow at most `limit` actions per `window_s` seconds for each (key, action)."""

    def __init__(self):
        self._hits = {}

    def hit(self, key, action, limit, window_s, now):
        stamps = [t for t in self._hits.get((key, action), []) if (now - t).total_seconds() < window_s]
        if len(stamps) >= limit:
            wait = int(window_s - (now - stamps[0]).total_seconds()) + 1
            minutes = max(1, round(wait / 60))
            raise RateLimitError(f"Too many requests in a short time. Please wait about {minutes} minute(s) and try again.")
        stamps.append(now)
        self._hits[(key, action)] = stamps


def clean_photo(data):
    """Check an upload and strip its metadata. Returns (clean bytes, 'jpg' or 'png'); raises ValueError otherwise."""
    if len(data) > MAX_PHOTO_BYTES:
        raise ValueError("The photo is larger than 5 MB")
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise ValueError("Photo uploads are unavailable because Pillow is not installed")
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        if fmt not in ("JPEG", "PNG"):
            raise ValueError("The photo must be a JPEG or PNG image")
        if img.size[0] * img.size[1] > MAX_PHOTO_PIXELS:
            raise ValueError("The photo has too many pixels (limit 25 million)")
        img.load()
        try:
            img = ImageOps.exif_transpose(img)                  # keep the picture the right way up before the tags go
        except Exception:
            pass
        mode = "RGB" if fmt == "JPEG" else ("RGBA" if "A" in img.mode or "transparency" in img.info else "RGB")
        img = img.convert(mode)
        clean = Image.new(mode, img.size)
        clean.putdata(list(img.getdata()))                      # pixels only: no EXIF, GPS, camera or date
        out = io.BytesIO()
        clean.save(out, format=fmt, **({"quality": 90} if fmt == "JPEG" else {}))
        return out.getvalue(), ("jpg" if fmt == "JPEG" else "png")
    except ValueError:
        raise
    except Exception:
        raise ValueError("The photo could not be read. Please use a normal JPEG or PNG image")
