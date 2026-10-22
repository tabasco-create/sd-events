"""Writes sample API responses (shaped like the real SerpApi / Ticketmaster JSON) to
tests/fixtures, for `python fetch_events.py --fixtures tests/fixtures --dry-run`."""
import json
from pathlib import Path

out = Path(__file__).parent / "fixtures"
out.mkdir(exist_ok=True)

def g(title, start, when, addr, desc="", venue=None, link="https://example.com/e"):
    return {"title": title, "date": {"start_date": start, "when": when}, "address": addr,
            "link": link, "description": desc, "venue": {"name": venue or addr[0].split(",")[0]},
            "ticket_info": [{"source": "Example", "link": link, "link_type": "tickets"}]}

general = [
    g("Día de los Muertos Festival", "Oct 25", "Sat, Oct 25, 10 AM – 6 PM", ["Old Town San Diego, 4002 Wallace St", "San Diego, CA"], "Altars, music, face painting for the whole family."),
    g("Pacific Beach Farmers Market", "Oct 21", "Tue, Oct 21, 2 – 7 PM", ["Bayard St & Garnet Ave", "San Diego, CA"], "Weekly farmers market with food trucks."),
    g("Intro to Python Meetup", "Oct 22", "Wed, Oct 22, 6:30 – 8:30 PM", ["Downtown Works, 550 W B St", "San Diego, CA"], "Hands-on coding night for beginners."),
    g("Marketing Growth Webinar", "Oct 22", "Wed, Oct 22, 10 – 11 AM", ["Online"], "A virtual webinar on Zoom."),
    g("Brunch & Mimosas Bottomless", "Oct 26", "Sun, Oct 26, 10 AM – 2 PM", ["The Local, 1065 4th Ave", "San Diego, CA"], "Bottomless brunch."),
    g("Tijuana Night Market", "Oct 24", "Fri, Oct 24, 6 – 11 PM", ["Av. Revolución", "Tijuana, B.C., Mexico"], "Night market."),
    g("Halloween Trunk or Treat", "Oct 31", "Fri, Oct 31, 5 – 8 PM", ["Mission Bay Park", "San Diego, CA"], ""),
    g("Brewery Tour: North Park", "Oct 25", "Sat, Oct 25, 1 – 5 PM", ["North Park Beer Co, 3038 University Ave", "San Diego, CA"], "Craft beer tasting walk."),
    g("Networking Mixer for Realtors", "Oct 23", "Thu, Oct 23, 5 – 7 PM", ["Hotel del Coronado", "Coronado, CA"], ""),
    g("San Diego Fall Home Show", "Oct 24", "Oct 24 – 26", ["Del Mar Fairgrounds, 2260 Jimmy Durante Blvd", "Del Mar, CA"], ""),
]
cat0 = [
    g(f"Kids Story Time at the Library #{i}", "Oct 2" + str(i % 8), f"{'Mon Tue Wed Thu Fri Sat Sun Mon'.split()[i % 8]}, Oct 2{i % 8}, 10:30 – 11:15 AM", ["Pacific Beach Library, 4275 Cass St", "San Diego, CA"], "Stories and songs for toddlers.") for i in range(2, 12)
]
cat1 = [
    g("Pumpkin Patch at Bates Nut Farm", "Oct 20", "Mon, Oct 20 – Fri, Oct 31", ["Bates Nut Farm, 15954 Woods Valley Rd", "Valley Center, CA"], "Hayrides, petting zoo, pumpkins."),
    g("Fleet Science Center: Science Night", "Oct 24", "Fri, Oct 24, 6 – 9 PM", ["Fleet Science Center, 1875 El Prado", "San Diego, CA"], ""),
    g("Día de los Muertos Festival", "Oct 25", "Sat, Oct 25, 10 AM – 6 PM", ["Old Town San Diego, 4002 Wallace St", "San Diego, CA"], "Altars, music, face painting for the whole family."),
]
json.dump({"total_searches_left": 212, "plan_searches_left": 212}, open(out / "serpapi_account.json", "w"))
json.dump({"events_results": general}, open(out / "serpapi_general.json", "w"), indent=1)
json.dump({"events_results": cat0}, open(out / "serpapi_category_0_0.json", "w"), indent=1)
json.dump({"events_results": cat1}, open(out / "serpapi_category_1_0.json", "w"), indent=1)

def tm(name, d, t, venue, seg, genre, status="onsale", city="San Diego"):
    return {"name": name, "url": "https://www.ticketmaster.com/event/X" + str(abs(hash(name)) % 10**6),
            "dates": {"start": {"localDate": d, "localTime": t}, "status": {"code": status}},
            "classifications": [{"segment": {"name": seg}, "genre": {"name": genre}}],
            "_embedded": {"venues": [{"name": venue, "city": {"name": city}}]}}

tm_events = [
    tm("The Aquabats!", "2026-10-24", "20:00:00", "House of Blues San Diego", "Music", "Ska"),
    tm("Rocket From The Crypt", "2026-10-24", "18:30:00", "House of Blues San Diego", "Music", "Punk"),
    tm("Generic Pop Star", "2026-10-23", "20:00:00", "Pechanga Arena", "Music", "Pop"),
    tm("San Diego Gulls vs. Ontario Reign", "2026-10-25", "17:00:00", "Pechanga Arena", "Sports", "Hockey"),
    tm("San Diego FC vs. LA Galaxy", "2026-10-26", "19:30:00", "Snapdragon Stadium", "Sports", "Soccer"),
    tm("San Diego Symphony: Halloween Spooktacular", "2026-10-25", "19:30:00", "The Rady Shell at Jacobs Park", "Music", "Classical"),
    tm("Padres vs Dodgers", "2026-10-21", "18:40:00", "Petco Park", "Sports", "Baseball"),
    tm("Parking: Padres vs Dodgers", "2026-10-21", "16:40:00", "Petco Park", "Miscellaneous", "Undefined"),
    tm("Disney On Ice", "2026-10-30", "19:00:00", "Pechanga Arena", "Family", "Ice Shows"),
    tm("Hamilton", "2026-10-28", "19:30:00", "San Diego Civic Theatre", "Arts & Theatre", "Theatre"),
    tm("Cancelled Rock Show", "2026-10-26", "20:00:00", "House of Blues", "Music", "Rock", status="cancelled"),
    tm("Halloween Spooktacular", "2026-10-25", "19:30:00", "The Rady Shell", "Music", "Classical"),
    tm("Jazz at the Athenaeum", "2026-10-23", "19:30:00", "Athenaeum Music & Arts Library", "Music", "Jazz", city="La Jolla"),
]
json.dump({"_embedded": {"events": tm_events}, "page": {"number": 0, "totalPages": 1}}, open(out / "ticketmaster_0.json", "w"), indent=1)
mlb = {"dates": [{"games": [
    {"gamePk": 900001, "gameDate": "2026-10-27T01:40:00Z", "status": {"detailedState": "Scheduled"},
     "teams": {"home": {"team": {"id": 135, "name": "San Diego Padres"}}, "away": {"team": {"id": 119, "name": "Los Angeles Dodgers"}}},
     "venue": {"id": 2680, "name": "Petco Park"}},
    {"gamePk": 900002, "gameDate": "2026-10-28T02:10:00Z", "status": {"detailedState": "Scheduled"},
     "teams": {"home": {"team": {"id": 119, "name": "Los Angeles Dodgers"}}, "away": {"team": {"id": 135, "name": "San Diego Padres"}}},
     "venue": {"id": 22, "name": "Dodger Stadium"}},
]}]}
json.dump(mlb, open(out / "mlb.json", "w"), indent=1)
json.dump({"events_results": [
    g("Tuesday Trivia Night", "Oct 21", "Tue, Oct 21, 7 – 9 PM", ["Mike Hess Brewing, 3812 Grim Ave", "San Diego, CA"], "Free pub trivia."),
    g("December Nights Preview", "Oct 25", "Sat, Oct 25, 5 – 9 PM", ["Balboa Park, 1549 El Prado", "San Diego, CA"], "Lights and music."),
    g("Smooth Jazz Brunch", "Oct 26", "Sun, Oct 26, 11 AM – 2 PM", ["Some Lounge", "San Diego, CA"], "Live jazz band."),
]}, open(out / "serpapi_general.json", "w"), indent=1)
print("fixtures written to", out)
