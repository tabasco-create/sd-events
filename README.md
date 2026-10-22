# sd-events

Upcoming San Diego events, filtered to our interests, for the "This week in San Diego"
section of the tabasco.dev homepage.

Status page: https://tabasco-create.github.io/sd-events/
Data: `https://tabasco-create.github.io/sd-events/events.json`

A GitHub Actions workflow (`.github/workflows/update.yml`) runs `fetch_events.py` once a
day. Sources:

- **Google Events via SerpApi** (free plan, 250 searches/month). Each day: one general
  "events in San Diego this week" search, plus two interest categories. The categories
  rotate daily, so each one is searched every five days. About 3 searches a day, ~93 a
  month. The run checks the remaining allowance first (free) and skips SerpApi
  if fewer than 25 are left.
- **Ticketmaster Discovery API** (free key). Everything within 25 miles for the next three
  weeks (including Gulls and San Diego FC games), about 1–3 calls a day.
- **MLB's public schedule** (no key). Padres home games at Petco Park.

Events are kept in `docs/events.json` until they're over, so the list builds up across
the week's rotation.

## Setup

1. Repo **Settings > Secrets and variables > Actions > New repository secret**:
   - `SERPAPI_KEY` from serpapi.com > Dashboard > Your Private API Key
   - `TICKETMASTER_KEY` from developer.ticketmaster.com > My Apps > Consumer Key
2. **Settings > Pages**: Deploy from a branch, `main`, folder `/docs`.
3. **Actions > Update San Diego events > Run workflow** for the first fill.

## Changing what shows up

Edit `INTERESTS` in `fetch_events.py`: each category has the Google search used on its
rotation days and the words that tag an event with it (whole words, any case). Add words to
`EXCLUDE` to drop things. Live music only keeps the genres in its word list (ska, punk,
alternative rock and close cousins). Pushing a change to `fetch_events.py` runs the
workflow right away, and saved events are re-checked against the new rules.

Test changes without spending searches:

```
python tests/make_fixtures.py
python fetch_events.py --fixtures tests/fixtures --dry-run
```

To try a category's search right away: Actions > Run workflow, and type the category name.
