#!/usr/bin/env python3
"""Upcoming San Diego events for the tabasco.dev homepage.

Each run (once a day, from GitHub Actions):
  1. Google Events via SerpApi: one general "this week" search, plus two interest
     categories. The categories rotate by day, so each one is searched every few
     days. About 3 searches a day (~93 a month of the free 250).
     Before searching, it asks SerpApi how many searches are left (that check is
     free) and skips SerpApi for the day if the month's allowance is nearly gone.
  2. Ticketmaster Discovery API: everything within 25 miles for the next 3 weeks
     (concerts, theater, family shows, Gulls and San Diego FC games). Free key,
     5,000 calls a day; we use 3.
  2b. MLB's public schedule (no key): Padres home games at Petco Park.
  3. Merges the results into the saved list, so events found on earlier days stay
     until they're over. Tags each event with your interest categories, drops
     anything that matches none of them, online-only events, and ticket add-ons.
     Saved events are re-checked against the current rules on every run, so an edit
     to INTERESTS or EXCLUDE takes effect on the next run.

Writes, for GitHub Pages:
  docs/events.json   events + status, read by the tabasco.dev Worker and index.html

Secrets (repo Settings > Secrets and variables > Actions):
  SERPAPI_KEY        from serpapi.com (free plan)
  TICKETMASTER_KEY   the "Consumer Key" from developer.ticketmaster.com
Either one can be missing; that source is just skipped.

Testing without spending searches:
  python fetch_events.py --fixtures tests/fixtures --dry-run
No third-party packages needed.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Los_Angeles")
SITE = Path("docs")
OUTPUT = SITE / "events.json"
UA = "tabasco.dev events (github.com/tabasco-create/sd-events)"

# ---------------------------------------------------------------------------
# What you're interested in. Edit freely.
#   query    what to search Google Events for on that category's rotation days
#   words    regular expressions matched against title + description (whole words,
#            any case). An event gets every category that matches.
#   places   (optional) also matched against the venue and address, for categories
#            that are about a place rather than a kind of event
#   music    (optional) True: only counts for events that are music (concerts), so
#            "alternative" means alternative rock, not an alternative-medicine fair
#   strict   (optional) True: an event found by this category's search still has to
#            match its words (Google's results for "trivia nights" include other things)
# Order here is the order of the filter buttons on the page.
# ---------------------------------------------------------------------------
INTERESTS = {
    "Family & kids": {
        "query": "family and kids events in San Diego",
        "words": [
            r"kids?", r"family", r"families", r"children'?s?", r"toddlers?", r"story ?time",
            r"pumpkin patch(es)?", r"trick[- ]or[- ]treat(ing)?", r"trunk[- ]or[- ]treat",
            r"petting zoo", r"puppets?", r"zoo", r"safari park", r"legoland",
            r"aquarium", r"fleet science", r"scouts?", r"carnival", r"county fair",
            r"science (fair|festival|night)", r"holiday lights", r"tree lighting",
        ],
    },
    "Local sports": {
        "query": "San Diego Gulls and San Diego FC home games",
        "strict": True,
        # Padres home games also come straight from MLB's schedule (see PADRES below).
        "words": [
            r"padres", r"san diego gulls", r"gulls", r"san diego fc", r"sdfc",
        ],
    },
    "Live music": {
        "query": "ska punk and alternative rock concerts in San Diego",
        "music": True,
        "strict": True,
        "words": [
            r"ska", r"ska[- ]punk", r"two[- ]tone", r"punk", r"punk rock", r"pop[- ]punk",
            r"post[- ]punk", r"skate[- ]punk", r"hardcore( punk)?", r"post[- ]hardcore",
            r"alternative", r"alt[- ]rock", r"alternative rock", r"indie rock", r"emo",
            r"grunge",
        ],
    },
    "Food & beer": {
        "query": "brewery events and beer festivals in San Diego",
        "words": [
            r"beers?", r"brew(ery|eries|fest|ing|pub)", r"craft beer", r"taproom", r"tap takeover",
            r"wine", r"tastings?", r"food (trucks?|festival|fest|fair)", r"tacos?", r"bbq",
            r"barbecue", r"chili cook-?off", r"farmers'? market", r"culinary", r"cocktails?",
            r"oktoberfest", r"restaurant week", r"night market", r"cider", r"distillery",
        ],
    },
    "Trivia": {
        "query": "trivia nights in San Diego",
        "strict": True,
        "words": [
            r"trivia", r"pub quiz", r"quiz night", r"geeks who drink", r"name that tune",
            r"music bingo",
        ],
    },
    "Balboa Park": {
        "query": "Balboa Park events in San Diego",
        "places": True,
        "strict": True,
        "words": [
            r"balboa park", r"spreckels organ( pavilion)?", r"old globe", r"san diego zoo",
            r"fleet science( center)?", r"san diego museum of art", r"natural history museum",
            r"the nat", r"air (&|and) space museum", r"museum of us", r"timken( museum)?",
            r"mingei", r"casa del prado", r"house of pacific relations", r"spanish village",
            r"botanical building", r"japanese friendship garden", r"san diego history center",
            r"museum of photographic arts", r"comic-con museum", r"model railroad museum",
            r"automotive museum", r"marston house", r"starlight bowl", r"el prado",
            r"organ pavilion", r"plaza de panama",
        ],
    },
    "Beach & outdoors": {
        "query": "outdoor beach hiking and nature events in San Diego",
        "words": [
            r"hik(e|es|ing)", r"beach", r"surf(ing)?", r"kayak(ing)?", r"paddle ?board(ing)?",
            r"tide ?pools?", r"nature walks?", r"trail (runs?|walks?|work)", r"botanic(al)? gardens?", r"camp(ing|out)",
            r"whale watch(ing)?", r"(beach |park |coastal )?clean[- ]?up", r"bird(ing| walk)",
            r"ranger", r"bike ride", r"cycling", r"fun run", r"5k", r"10k", r"half marathon",
            r"star party", r"astronomy", r"sailing", r"snorkel(ing)?", r"fishing",
        ],
    },
    "Arts & museums": {
        "query": "museum exhibits art and theater events in San Diego",
        "words": [
            r"museums?", r"exhibits?", r"exhibition", r"galler(y|ies)", r"art walk",
            r"art (show|fair|festival)", r"theat(er|re)", r"musical", r"ballet",
            r"comedy", r"film festival", r"screening", r"planetarium",
            r"sculpture", r"photography", r"dance performance", r"broadway",
        ],
    },
    "Makers & knives": {
        "query": "maker faire craft fair and knife show events in San Diego",
        "words": [
            r"makers?", r"maker ?space", r"maker faire", r"knife", r"knives", r"blade show",
            r"craft (fair|show|market)", r"woodworking", r"leather ?work(ing)?",
            r"blacksmith(ing)?", r"forg(e|ing)", r"metalwork(ing)?", r"swap meet",
            r"flea market", r"3d print(ing|er)?", r"diy", r"tool show", r"artisan market",
        ],
    },
    "Tech meetups": {
        "query": "tech meetups and workshops in San Diego",
        "words": [
            r"tech", r"meetup", r"startups?", r"python", r"javascript", r"developers?",
            r"coding", r"hackathon", r"ai", r"artificial intelligence", r"machine learning",
            r"cyber ?security", r"linux", r"home ?lab", r"raspberry pi", r"robotics",
            r"drones?", r"ham radio", r"open source", r"devops", r"data science",
        ],
    },
}

# Category for anything from the general "this week" search that matches none of the
# interests above. Set to None to drop those instead. Concerts that aren't one of the
# Live music genres are dropped rather than landing here.
OTHER_CATEGORY = "Around town"

# How an event is recognized as music (for the Live music genres): Ticketmaster's
# "Music" classification, or these words in a title or description.
MUSIC_WORDS = [
    r"music", r"concerts?", r"live music", r"band", r"bands", r"tour", r"djs?", r"gig",
    r"symphony", r"orchestra", r"jazz", r"blues", r"tribute", r"in concert", r"rock",
]

# How Ticketmaster's own classification maps onto the categories above. Music isn't
# here: concerts count as Live music only when their genre is one of its words.
# Sports games count only when the title names a team in Local sports.
TM_SEGMENTS = {
    "Arts & Theatre": "Arts & museums",
    "Family": "Family & kids",
}

# Padres home games, from MLB's public schedule (no key needed).
PADRES = {
    "team_id": 135,          # San Diego Padres
    "venue_id": 2680,        # Petco Park (so spring training in Arizona is left out)
    "category": "Local sports",
    "days_ahead": 21,
}

# Dropped if title or description matches any of these (whole words, any case).
EXCLUDE = [
    r"webinar", r"virtual", r"online[- ]only", r"livestream", r"zoom", r"online event",
    # Ticketmaster lists add-ons as their own "events"
    r"parking", r"vip (package|upgrade|experience)", r"premium seating", r"suite", r"upgrade",
    r"gift card", r"season tickets?",
    r"speed dating", r"singles", r"date night",
]

# ---- Budget and range -----------------------------------------------------
SERPAPI_GENERAL_QUERY = "events in San Diego"
SERPAPI_GENERAL_CHIPS = "date:week"   # Google's "this week" filter
SERPAPI_CATEGORIES_PER_DAY = 2        # interest categories searched each day
SERPAPI_CATEGORY_PAGES = 1            # 10 events per page; each page is 1 search
SERPAPI_RESERVE = 25                  # skip SerpApi when fewer searches than this are left
SERPAPI_LOCATION = "San Diego, California, United States"

TM_LATLONG = "32.7157,-117.1611"      # downtown San Diego
TM_RADIUS_MILES = 25
TM_DAYS_AHEAD = 21
TM_PAGES = 3                          # 200 events per page

KEEP_DAYS_AHEAD = 45                  # ignore anything further out than this
FORGET_AFTER_DAYS = 21                # drop an event not seen in any search for this long

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def compile_words(words):
    return re.compile(r"(?<![\w])(" + "|".join(words) + r")(?![\w])", re.IGNORECASE)


INTEREST_RES = {name: compile_words(spec["words"]) for name, spec in INTERESTS.items()}
EXCLUDE_RE = compile_words(EXCLUDE)
MUSIC_RE = compile_words(MUSIC_WORDS)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

class Fetcher:
    """HTTP GET of JSON, or canned responses from a folder when testing."""

    def __init__(self, fixtures=None):
        self.fixtures = Path(fixtures) if fixtures else None
        self.calls = []

    def get(self, kind, url, params):
        self.calls.append(kind)
        if self.fixtures:
            path = self.fixtures / f"{kind}.json"
            if not path.exists():
                raise FileNotFoundError(f"no fixture {path}")
            return json.loads(path.read_text())
        full = url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(full, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read(300).decode("utf-8", "replace")
            # Never let the key leak into logs.
            raise RuntimeError(f"HTTP {e.code} from {urllib.parse.urlsplit(url).hostname}: {body}") from None


def serpapi_left(fetch, key):
    acct = fetch.get("serpapi_account", "https://serpapi.com/account.json", {"api_key": key})
    for field in ("total_searches_left", "plan_searches_left"):
        if isinstance(acct.get(field), int):
            return acct[field]
    return None


def serpapi_search(fetch, key, kind, query, chips=None, start=0):
    params = {
        "engine": "google_events",
        "q": query,
        "location": SERPAPI_LOCATION,
        "hl": "en",
        "gl": "us",
        "api_key": key,
    }
    if chips:
        params["htichips"] = chips
    if start:
        params["start"] = start
    data = fetch.get(kind, "https://serpapi.com/search.json", params)
    if data.get("error") and "hasn't returned any results" not in data["error"]:
        raise RuntimeError(f"SerpApi: {data['error']}")
    return data.get("events_results", []) or []


def ticketmaster_pull(fetch, key, now):
    start = now.astimezone(timezone.utc).replace(microsecond=0)
    end = start + timedelta(days=TM_DAYS_AHEAD)
    found = []
    for page in range(TM_PAGES):
        data = fetch.get(
            f"ticketmaster_{page}",
            "https://app.ticketmaster.com/discovery/v2/events.json",
            {
                "apikey": key,
                "latlong": TM_LATLONG,
                "radius": TM_RADIUS_MILES,
                "unit": "miles",
                "startDateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "endDateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "size": 200,
                "page": page,
                "sort": "date,asc",
                "locale": "*",
            },
        )
        found += (data.get("_embedded") or {}).get("events", [])
        info = data.get("page") or {}
        if info.get("number", page) + 1 >= info.get("totalPages", 0):
            break
    return found


def padres_pull(fetch, now):
    start = now.date()
    end = start + timedelta(days=PADRES["days_ahead"])
    data = fetch.get("mlb", "https://statsapi.mlb.com/api/v1/schedule", {
        "sportId": 1,
        "teamId": PADRES["team_id"],
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
    })
    return [g for d in data.get("dates") or [] for g in d.get("games") or []]


# ---------------------------------------------------------------------------
# Turning each source's records into one shape
# ---------------------------------------------------------------------------

TIME_RE = re.compile(r"(?<![\d:])(\d{1,2})(?::(\d{2}))?\s*([AaPp]\.?[Mm]\b\.?)?")
MONTH_DAY_RE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\b", re.I)


def guess_year(month, day, today):
    """Google gives "Oct 24" with no year. Pick the year that makes it nearest upcoming."""
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if d >= today - timedelta(days=60):
            return d
    return None


def parse_clock(h, m, ampm):
    h = int(h)
    m = int(m or 0)
    if h > 23 or m > 59:
        return None
    if ampm:
        pm = ampm[0].lower() == "p"
        if h == 12:
            h = 0
        if pm:
            h += 12
    return h, m


def parse_google_when(start_date, when, today):
    """Start/end from SerpApi's date block, e.g.
         start_date "Oct 24", when "Fri, Oct 24, 7 – 10 PM"
         when "Sat, Oct 25, 8 PM – Sun, Oct 26, 2 AM"
         when "Oct 24 – 26"
    Returns (start_date, start "HH:MM" or None, end_date or None)."""
    when = (when or "").replace(" ", " ").replace(" ", " ")
    md = MONTH_DAY_RE.search(start_date or "") or MONTH_DAY_RE.search(when)
    if not md:
        return None, None, None
    start = guess_year(MONTHS[md.group(1)[:3].lower()], int(md.group(2)), today)
    if not start:
        return None, None, None

    # end date: a second "Mon DD" in the text, or "Oct 24 – 26"
    end = None
    dates = list(MONTH_DAY_RE.finditer(when))
    if len(dates) >= 2:
        end = guess_year(MONTHS[dates[1].group(1)[:3].lower()], int(dates[1].group(2)), start)
    else:
        span = re.search(r"\b[A-Za-z]{3,9}\.?\s+\d{1,2}\s*[–—-]\s*(\d{1,2})\b(?!\s*:|\s*[AaPp][Mm])", when)
        if span and dates:
            try:
                end = start.replace(day=int(span.group(1)))
            except ValueError:
                end = None
    if end and end <= start:
        end = None if end == start else end

    # start time: the first clock time after the first date. "7 – 10 PM" means 7 PM,
    # so a time without AM/PM borrows the next one in the text.
    clock = None
    first = MONTH_DAY_RE.search(when)
    rest = when[first.end():] if first else when
    rest = MONTH_DAY_RE.sub(" ", rest)                       # later dates aren't times
    rest = re.sub(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\b", " ", rest, flags=re.I)
    t = TIME_RE.search(rest)
    if t:
        ampm = t.group(3)
        if not ampm:
            later = re.search(r"[AaPp]\.?[Mm]\b", rest[t.end():])
            ampm = later.group(0) if later else None
        if ampm:   # a bare number with no AM/PM anywhere is a day, not a time
            hm = parse_clock(t.group(1), t.group(2), ampm)
            if hm and hm != (0, 0):   # "12 AM – 11:59 PM" is Google's all-day
                clock = f"{hm[0]:02d}:{hm[1]:02d}"
    return start, clock, end


def clean(s, limit=None):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s[:limit] if limit else s


def safe_url(u):
    u = clean(u)
    return u if u.startswith("https://") or u.startswith("http://") else None


def from_google(r, today):
    start, clock, end = parse_google_when((r.get("date") or {}).get("start_date"),
                                          (r.get("date") or {}).get("when"), today)
    if not start:
        return None
    address = [clean(a) for a in (r.get("address") or []) if clean(a)]
    venue = clean((r.get("venue") or {}).get("name")) or (address[0].split(",")[0] if address else "")
    link = safe_url(r.get("link"))
    for t in r.get("ticket_info") or []:
        if not link and t.get("link_type") == "tickets":
            link = safe_url(t.get("link"))
    return {
        "title": clean(r.get("title"), 160),
        "date": start.isoformat(),
        "time": clock,
        "end_date": end.isoformat() if end else None,
        "venue": clean(venue, 80),
        "where": clean(", ".join(address), 160),
        "url": link,
        "text": clean(r.get("description"), 400),
        "source": "Google",
        "hint": [],
        "cancelled": False,
    }


def from_mlb(g):
    """A Padres home game at Petco Park, or None."""
    home = ((g.get("teams") or {}).get("home") or {}).get("team") or {}
    away = ((g.get("teams") or {}).get("away") or {}).get("team") or {}
    if home.get("id") != PADRES["team_id"] or (g.get("venue") or {}).get("id") != PADRES["venue_id"]:
        return None
    state = ((g.get("status") or {}).get("detailedState") or "")
    try:
        start = datetime.fromisoformat(str(g["gameDate"]).replace("Z", "+00:00")).astimezone(TZ)
    except (KeyError, ValueError):
        return None
    tbd = (g.get("status") or {}).get("startTimeTBD")
    return {
        "title": clean(f"Padres vs. {away.get('name') or 'TBD'}", 160),
        "date": start.date().isoformat(),
        "time": None if tbd else start.strftime("%H:%M"),
        "end_date": None,
        "venue": "Petco Park",
        "where": "Petco Park, San Diego, CA",
        "url": f"https://www.mlb.com/gameday/{g['gamePk']}" if g.get("gamePk") else "https://www.mlb.com/padres/schedule",
        "text": "Baseball MLB",
        "source": "MLB",
        "hint": [PADRES["category"]],
        "cancelled": bool(re.search(r"postponed|cancel", state, re.I)),
    }


def from_ticketmaster(r):
    d = (r.get("dates") or {}).get("start") or {}
    if not d.get("localDate"):
        return None
    status = ((r.get("dates") or {}).get("status") or {}).get("code", "")
    venues = (r.get("_embedded") or {}).get("venues") or [{}]
    v = venues[0]
    city = clean((v.get("city") or {}).get("name"))
    hint = []
    descr = []
    for c in r.get("classifications") or []:
        seg = (c.get("segment") or {}).get("name")
        if seg in TM_SEGMENTS:
            hint.append(TM_SEGMENTS[seg])
        for part in ("segment", "genre", "subGenre"):
            n = (c.get(part) or {}).get("name")
            if n and n != "Undefined":
                descr.append(n)
    t = d.get("localTime")
    return {
        "title": clean(r.get("name"), 160),
        "date": d["localDate"],
        "time": t[:5] if t and not d.get("timeTBA") and not d.get("noSpecificTime") else None,
        "end_date": None,
        "venue": clean(v.get("name"), 80),
        "where": clean(", ".join(x for x in [v.get("name"), city] if x), 160),
        "url": safe_url(r.get("url")),
        # Genres only. Ticketmaster's "info" is venue boilerplate ("beer and wine
        # available", "family seating") that would tag every concert as something else.
        "text": clean(" ".join(descr), 400),
        "source": "Ticketmaster",
        "hint": hint,
        "cancelled": status in ("cancelled", "canceled"),
    }


# ---------------------------------------------------------------------------
# Tagging, merging, expiring
# ---------------------------------------------------------------------------

def norm_title(t):
    t = t.lower()
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", t)          # "(21+)", "[Rescheduled]"
    t = re.sub(r"\b(the|at|in|presents?|live)\b", " ", t)
    return re.sub(r"[^a-z0-9]+", "", t)


def event_key(e):
    return hashlib.sha1(f"{norm_title(e['title'])}|{e['date']}".encode()).hexdigest()[:12]


PLACE_NAMES_RE = re.compile(
    r"\b(pacific|ocean|imperial|solana|long|huntington|newport|laguna|mission|del mar) beach\b"
    r"|\bmission (valley|hills)\b|\btorrey pines\b|\bsorrento valley\b", re.I)


def is_music(e):
    return bool(MUSIC_RE.search(f"{e['title']} {e.get('text') or ''}"))


def tags_for(e, query_category=None):
    # Title and description only: venue names mislead ("Epstein Family Amphitheater"
    # isn't a family event), and so do neighborhood names ("Pacific Beach Library").
    # Categories marked "places" also look at the venue and address.
    hay = PLACE_NAMES_RE.sub(" ", f"{e['title']} {e.get('text') or ''}")
    where = f"{e.get('venue') or ''} {e.get('where') or ''}"
    music = is_music(e)
    tags = []
    for name, rx in INTEREST_RES.items():
        spec = INTERESTS[name]
        if spec.get("music") and not music:
            continue
        if rx.search(hay) or (spec.get("places") and rx.search(where)):
            tags.append(name)
    for extra in list(e.get("hint") or []) + ([query_category] if query_category else []):
        if extra in INTERESTS and extra not in tags:
            # strict categories only count when their words match (checked above)
            if INTERESTS[extra].get("strict"):
                continue
            tags.append(extra)
    order = list(INTERESTS)
    return sorted(tags, key=order.index)


def final_tags(e, query_category=None):
    """Tags for an event, the catch-all for plain non-music events, or [] to drop it."""
    tags = tags_for(e, query_category)
    if tags:
        return tags
    if OTHER_CATEGORY and e.get("source") == "Google" and not is_music(e):
        return [OTHER_CATEGORY]
    return []


def in_san_diego_area(e):
    where = e["where"]
    if not where:
        return True
    if re.search(r"\b(tijuana|ensenada|rosarito|baja california|los angeles|anaheim|irvine|riverside)\b", where, re.I):
        return False
    # Google addresses end in "San Diego, CA" style; anything outside CA is out.
    return not re.search(r",\s*(?!CA\b)[A-Z]{2}\s*(\d{5})?\s*$", where)


def keep(e, today):
    if not e or not e["title"]:
        return False
    if EXCLUDE_RE.search(f"{e['title']} {e['text']}"):
        return False
    if not in_san_diego_area(e):
        return False
    last = date.fromisoformat(e.get("end_date") or e["date"])
    if last < today or date.fromisoformat(e["date"]) > today + timedelta(days=KEEP_DAYS_AHEAD):
        return False
    return True


def merge(saved, found, today, now_iso, tm_ok=False, padres_ok=False):
    """saved: {key: event}; found: list of (event, tags). Returns the new dict.
    Every event, saved or new, is re-checked against the current rules at the end."""
    out = dict(saved)
    seen_now = set()
    for e, tags in found:
        k = event_key(e)
        old = out.get(k)
        if e["cancelled"]:
            out.pop(k, None)
            continue
        seen_now.add(k)
        rec = {
            "id": k,
            "title": e["title"],
            "date": e["date"],
            "time": e["time"],
            "end_date": e["end_date"],
            "venue": e["venue"],
            "where": e.get("where") or "",
            "url": e["url"],
            "tags": tags,
            "source": e["source"],
            # kept so saved events can be re-checked when the rules change
            "text": (e.get("text") or "")[:300],
            "hint": sorted(set(e.get("hint") or []) | ({e["_query"]} if e.get("_query") in tags else set())),
            "first_seen": now_iso,
            "last_seen": now_iso,
        }
        if old and old.get("source") == "Ticketmaster" and e["source"] == "Ticketmaster":
            # Ticketmaster re-lists everything daily, so its newest tags simply win.
            rec["first_seen"] = old.get("first_seen", now_iso)
        elif old:
            rec["first_seen"] = old.get("first_seen", now_iso)
            # keep what each source knew (descriptions, the categories it was found under)
            if old.get("text") and old.get("text") not in rec["text"]:
                rec["text"] = f"{rec['text']} {old['text']}"[:400]
            rec["hint"] = sorted(set(rec["hint"]) | set(old.get("hint") or []))
            rec["where"] = rec["where"] or old.get("where") or ""
            # Combine what both sources know: Ticketmaster has reliable times/links,
            # Google has better descriptions (already used for tags).
            rec["tags"] = sorted(set(old.get("tags", [])) | set(tags),
                                 key=lambda t: (list(INTERESTS) + [OTHER_CATEGORY]).index(t)
                                 if t in INTERESTS or t == OTHER_CATEGORY else 99)
            if OTHER_CATEGORY in rec["tags"] and len(rec["tags"]) > 1:
                rec["tags"].remove(OTHER_CATEGORY)
            if old.get("source") == "Ticketmaster" and e["source"] != "Ticketmaster":
                for f in ("time", "url", "venue", "title"):
                    rec[f] = old.get(f) or rec[f]
                rec["source"] = "Ticketmaster"
            rec["time"] = rec["time"] or old.get("time")
            rec["url"] = rec["url"] or old.get("url")
        out[k] = rec

    cutoff = today - timedelta(days=FORGET_AFTER_DAYS)
    for k in list(out):
        e = out[k]
        last_day = date.fromisoformat(e.get("end_date") or e["date"])
        seen = datetime.fromisoformat(e["last_seen"]).date()
        if last_day < today or seen < cutoff:
            del out[k]
            continue
        # Ticketmaster and MLB re-list everything in their window on every run, so a
        # saved one they no longer list (sold out, removed, or no longer matching) goes.
        if k not in seen_now and ((tm_ok and e.get("source") == "Ticketmaster") or (padres_ok and e.get("source") == "MLB")):
            days_out = (date.fromisoformat(e["date"]) - today).days
            if days_out <= (TM_DAYS_AHEAD if e.get("source") == "Ticketmaster" else PADRES["days_ahead"]):
                del out[k]
                continue
        # re-check against the current rules (so edits to INTERESTS / EXCLUDE apply)
        if EXCLUDE_RE.search(f"{e['title']} {e.get('text') or ''}"):
            del out[k]
            continue
        tags = final_tags(e)
        if not tags:
            del out[k]
            continue
        e["tags"] = tags

    # Same show listed twice under slightly different names ("Halloween Spooktacular" and
    # "San Diego Symphony: Halloween Spooktacular"): same day and start time, and one
    # name contains the other. Keep the longer, more descriptive name.
    by_slot = {}
    for e in out.values():
        by_slot.setdefault((e["date"], e["time"]), []).append(e)
    for group in by_slot.values():
        group.sort(key=lambda e: -len(norm_title(e["title"])))
        for i, long_e in enumerate(group):
            if long_e["id"] not in out:
                continue
            for short_e in group[i + 1:]:
                s, l = norm_title(short_e["title"]), norm_title(long_e["title"])
                if short_e["id"] in out and len(s) >= 8 and s in l:
                    long_e["tags"] = [t for t in INTERESTS if t in long_e["tags"] or t in short_e["tags"]] or long_e["tags"]
                    long_e["url"] = long_e["url"] or short_e["url"]
                    del out[short_e["id"]]
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_saved():
    try:
        data = json.loads(OUTPUT.read_text())
        return data, {e["id"]: e for e in data.get("events", [])}
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return {}, {}


def todays_categories(today):
    names = list(INTERESTS)
    n = len(names)
    first = (today.toordinal() * SERPAPI_CATEGORIES_PER_DAY) % n
    return [names[(first + i) % n] for i in range(min(SERPAPI_CATEGORIES_PER_DAY, n))]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fixtures", help="read API responses from this folder instead of the internet")
    ap.add_argument("--dry-run", action="store_true", help="print the result, don't write docs/events.json")
    ap.add_argument("--today", help="pretend today is YYYY-MM-DD (testing)")
    ap.add_argument("--category", action="append",
                    help="search this interest category today instead of the rotation (can repeat)")
    args = ap.parse_args(argv)

    now = datetime.now(TZ)
    if args.today:
        now = datetime.combine(date.fromisoformat(args.today), now.timetz())
    today = now.date()
    now_iso = now.isoformat(timespec="seconds")

    fetch = Fetcher(args.fixtures)
    serp_key = os.environ.get("SERPAPI_KEY", "fixture" if args.fixtures else "")
    tm_key = os.environ.get("TICKETMASTER_KEY", "fixture" if args.fixtures else "")

    previous, saved = load_saved()
    found = []
    status = {}
    categories_today = [c.strip() for c in (args.category or []) if c.strip()] or todays_categories(today)
    for c in categories_today:
        if c not in INTERESTS:
            sys.exit(f"Unknown category {c!r}. Choose from: {', '.join(INTERESTS)}")

    # ---- Google Events via SerpApi --------------------------------------
    s = {"ok": False, "category": " + ".join(categories_today), "searches_used": 0, "found": 0}
    if not serp_key:
        s["note"] = "SERPAPI_KEY not set"
    else:
        try:
            left = serpapi_left(fetch, serp_key)
            s["searches_left_before"] = left
            if left is not None and left < SERPAPI_RESERVE:
                s["note"] = f"skipped: only {left} searches left this month"
            else:
                raw = serpapi_search(fetch, serp_key, "serpapi_general", SERPAPI_GENERAL_QUERY,
                                     chips=SERPAPI_GENERAL_CHIPS)
                s["searches_used"] += 1
                batch = [(r, None) for r in raw]
                for ci, category in enumerate(categories_today):
                    spec = INTERESTS[category]
                    for page in range(SERPAPI_CATEGORY_PAGES):
                        raw = serpapi_search(fetch, serp_key, f"serpapi_category_{ci}_{page}", spec["query"],
                                             start=page * 10)
                        s["searches_used"] += 1
                        batch += [(r, category) for r in raw]
                        if len(raw) < 10:
                            break   # no more pages; don't pay for an empty one
                for r, cat in batch:
                    e = from_google(r, today)
                    if not keep(e, today):
                        continue
                    e["_query"] = cat
                    tags = final_tags(e, cat)
                    if not tags:
                        continue
                    found.append((e, tags))
                    s["found"] += 1
                s["ok"] = True
        except Exception as ex:   # one source failing shouldn't stop the other
            s["error"] = str(ex)[:300]
    status["google"] = s

    # ---- Ticketmaster ------------------------------------------------------
    t = {"ok": False, "found": 0, "dropped_no_interest": 0}
    if not tm_key:
        t["note"] = "TICKETMASTER_KEY not set"
    else:
        try:
            for r in ticketmaster_pull(fetch, tm_key, now):
                e = from_ticketmaster(r)
                if not keep(e, today):
                    continue
                tags = final_tags(e)
                if not tags:
                    t["dropped_no_interest"] += 1
                    continue
                found.append((e, tags))
                t["found"] += 1
            t["ok"] = True
        except Exception as ex:
            t["error"] = str(ex)[:300]
    status["ticketmaster"] = t

    # ---- Padres home games (MLB, no key) ------------------------------------
    pd = {"ok": False, "found": 0}
    try:
        for g in padres_pull(fetch, now):
            e = from_mlb(g)
            if not e or not keep(e, today):
                continue
            tags = final_tags(e)
            if tags:
                found.append((e, tags))
                pd["found"] += 1
        pd["ok"] = True
    except Exception as ex:
        pd["error"] = str(ex)[:300]
    status["padres"] = pd

    events = merge(saved, found, today, now_iso, tm_ok=t["ok"], padres_ok=pd["ok"])
    ordered = sorted(events.values(), key=lambda e: (e["date"], e["time"] or "99", e["title"].lower()))
    categories = list(INTERESTS) + ([OTHER_CATEGORY] if OTHER_CATEGORY else [])

    any_ok = status["google"]["ok"] or status["ticketmaster"]["ok"]
    out = {
        "updated": now_iso if any_ok else previous.get("updated"),
        "checked": now_iso,
        "timezone": "America/Los_Angeles",
        "categories": categories,
        "status": status,
        "events": ordered,
    }

    if args.dry_run:
        print(json.dumps(out, indent=2)[:6000])
        print(f"\n{len(ordered)} events; API calls: {', '.join(fetch.calls)}", file=sys.stderr)
    else:
        SITE.mkdir(exist_ok=True)
        OUTPUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
        print(f"Wrote {len(ordered)} events. Google: {status['google']}. Ticketmaster: {status['ticketmaster']}")

    # Fail the workflow run (so the watchdog notices) only when every source failed.
    if not any_ok and (serp_key or tm_key):
        sys.exit("Every source failed: " + json.dumps(status))


if __name__ == "__main__":
    main()
