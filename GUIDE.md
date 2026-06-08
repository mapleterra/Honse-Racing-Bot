# Horse Racing Discord Bot — Full Guide

Everything you need to know about running, configuring, and using the bot.

---

## Quick Start

1. Install dependencies:
   ```
   pip install discord.py aiohttp beautifulsoup4 feedparser python-dotenv
   ```
2. Copy `.env.example` to `.env` and fill in your values
3. Run the bot:
   ```
   python bot.py
   ```

---

## Setup: `.env` File

Copy `.env.example` to `.env` and set these three values:

| Variable | What it does |
|---|---|
| `DISCORD_BOT_TOKEN` | Your bot's secret token from the Discord Developer Portal |
| `G1_ALERTS_CHANNEL_ID` | Channel ID where automatic race announcements and results are posted |
| `RACE_UPDATES_CHANNEL_ID` | Channel ID where hourly news updates are posted |

**How to get a channel ID:** Right-click any channel in Discord → Copy Channel ID (Developer Mode must be on in Settings → Advanced).

---

## Discord Developer Portal Requirements

Before running the bot, enable these two settings on your bot's page at https://discord.com/developers:

- **Server Members Intent** — under Bot → Privileged Gateway Intents
- **Message Content Intent** — under Bot → Privileged Gateway Intents

Both are required for the reaction subscription system to work.

---

## Slash Commands

All commands start with `/` and show autocomplete hints in Discord.

---

### Race Discovery

#### `/upcoming [limit]`
Lists the next upcoming G1 races with live countdowns.
- `limit` — how many races to show (default 5, max 10)
- `country` — optional dropdown to filter by country
- Example: `/upcoming limit:3 country:USA`

#### `/g1 [name] [country]`
Shows full details and a live countdown for a Grade 1 race. Leave `name` blank to list the next 5 upcoming.
- `name` — partial race name, e.g. `preakness` or `arc`
- `country` — optional dropdown (16 countries available)
- Example: `/g1 name:belmont country:USA`

#### `/g2 [name] [country]`
Shows Grade 2 race details and countdown. When you search by `name`, it also automatically fetches the latest news for that race.
- `name` — partial race name, e.g. `dante` or `wood memorial`
- `country` — optional dropdown (16 countries available)
- Example: `/g2 name:dante stakes country:UK`

#### `/g3 [name] [country]`
Shows Grade 3 race details and countdown. When you search by `name`, it also automatically fetches the latest news for that race.
- `name` — partial race name, e.g. `holy bull` or `risen star`
- `country` — optional dropdown (16 countries available)
- Example: `/g3 name:holy bull country:USA`

#### `/countdown name:<race>`
Posts a live self-updating countdown message that Discord refreshes automatically using its timestamp format.
- Example: `/countdown name:breeders cup`

---

### Country Dropdown

All race discovery commands include a `country:` dropdown with 16 options:

| Flag | Country | Major Races Included |
|---|---|---|
| 🌍 | All Countries | Everything |
| 🇺🇸 | USA | Kentucky Derby, Preakness, Belmont, Breeders' Cup, + G2/G3 preps |
| 🇬🇧 | UK | Epsom Derby, Royal Ascot, Champions Day, + G2/G3 |
| 🇮🇪 | Ireland | Irish Derby, Irish Champion Stakes, Gallinule, + G3 |
| 🇫🇷 | France | Prix de l'Arc de Triomphe, Prix du Jockey Club, + G2/G3 |
| 🇯🇵 | Japan | Japan Cup, Tokyo Yushun, Tenno Sho, Kyoto Kinen, + G3 |
| 🇦🇺 | Australia | Melbourne Cup, Cox Plate, Caulfield Cup, Hobartville, + G3 |
| 🇦🇪 | UAE | Dubai World Cup, Dubai Turf |
| 🇭🇰 | Hong Kong | Hong Kong Cup, Hong Kong Mile, Chairman's Trophy |
| 🇨🇦 | Canada | Queen's Plate, Canadian International |
| 🇩🇪 | Germany | Deutsches Derby, Grosser Preis von Baden, + G3 |
| 🇸🇬 | Singapore | Singapore Airlines International Cup |
| 🇮🇹 | Italy | Gran Premio di Milano |
| 🇸🇦 | Saudi Arabia | Saudi Cup |
| 🇿🇦 | South Africa | Vodacom Durban July, Daily News 2000 |
| 🇦🇷 | Argentina | Gran Premio Nacional |

---

### Race Day

#### `/runners source:<source> track:<track> date:<date>`
Shows the full race card — every horse, jockey, and trainer entered in a race.
- `source` — `equibase` (US races) or `racingpost` (UK/Ireland/international)
- `track` — track code for Equibase (e.g. `CD`, `BEL`, `PIM`) or track slug for Racing Post (e.g. `ascot`, `newmarket`)
- `date` — `YYYYMMDD` format for Equibase, `YYYY-MM-DD` for Racing Post
- Examples:
  - `/runners source:equibase track:PIM date:20250517`
  - `/runners source:racingpost track:ascot date:2025-06-17`

#### `/odds source:<source> track:<track> [date] [race]`
Shows current odds from multiple sources.
- `source` — `equibase` (US morning line), `racingpost` (UK/IRE SP/forecast), or `oddschecker` (multi-bookie comparison)
- `track` — same format as `/runners`
- `date` — optional, defaults to today
- `race` — for OddsChecker, the URL slug of the race
- Examples:
  - `/odds source:equibase track:CD date:20250601`
  - `/odds source:oddschecker race:horse-racing/2025-06-07-epsom/epsom-derby`

#### `/result source:<source> track:<track> [date] [race]`
Fetches the official finishing order and exotic payouts for a completed race.
- `source` — `equibase` or `racingpost`
- `track` — track code or slug
- `date` — optional, defaults to today
- `race` — optional partial race name to filter (e.g. `Preakness`)
- Examples:
  - `/result source:equibase track:PIM date:20250517 race:Preakness`
  - `/result source:racingpost track:ascot date:2025-06-19`

---

### Horse & People Research

#### `/horse name:<name>`
Full horse profile pulled from Equibase:
- Bloodline (Sire, Dam)
- Born, color, sex
- Trainer and owner
- Career record: starts / wins / 2nd / 3rd / earnings
- Recent races table with date, track, finish, distance, odds
- Latest news from Google News
- Horse photo (from Equibase if available, or your custom image)

Example: `/horse name:Justify`

---

#### `/trainer name:<name>`
Trainer profile from Racing Post:
- Location / stable
- Win rate and current-season stats
- Career wins
- Notable/classic wins list
- Recent winners table (date, horse, race, track)
- Latest news articles

Example: `/trainer name:Aidan O'Brien`

---

#### `/jockey name:<name>`
Jockey profile from Racing Post — same structure as `/trainer` but jockey-focused:
- Nationality
- Win rate and current-season stats
- Career wins
- Notable rides list
- Recent winners table
- Latest news articles

Example: `/jockey name:Frankie Dettori`

---

#### `/compare horse_a:<name> horse_b:<name>`
Full head-to-head comparison between any two horses. **Works for active, retired, and deceased horses** — the bot pulls official career stats from Equibase's permanent horse records rather than only recent race entries.

What you get:
1. **Profile card** — bloodline (Sire/Dam), born, colour/sex, trainer, owner, career earnings, links to Equibase profiles
2. **Career stats card** — starts, wins, places (top-2), shows (top-3), win % with a visual bar, direct meeting tally
3. **Recent form table** — up to the last 10 races for each horse (shown only when race data is available)
4. **Direct matchup detail** — every race where both horses ran on the same day at the same track
5. **Latest news** — most recent articles for each horse from Google News

Examples:
- `/compare horse_a:Justify horse_b:American Pharoah` — two retired Triple Crown winners
- `/compare horse_a:Secretariat horse_b:Man o War` — two historical legends

> The `source` parameter is accepted but ignored — the bot always uses Equibase, which has the most complete career records including retired and historical horses.

---

#### `/news [query]`
Searches Google News RSS for the latest horse racing articles.
- `query` — search term (default: `G1 horse racing`)
- Example: `/news query:Breeders Cup entries 2025`

---

### Subscriptions (Getting Pinged for Results)

#### How it works
When the bot posts a G1 race announcement, it automatically adds a 🔔 reaction to the message. Members who click 🔔 are subscribed to that race. When the official result is posted, **only those subscribed members are pinged** — not @here or @everyone. The subscription message is then deleted automatically.

#### `/subscribe name:<race>`
Subscribe to result notifications for a specific race by name.
- `name` — partial race name, e.g. `preakness` or `arc`
- Reply is private (only you can see it)
- Example: `/subscribe name:belmont`

#### `/unsubscribe name:<race>`
Remove yourself from a race's notification list.
- Example: `/unsubscribe name:belmont`

#### `/mysubscriptions`
See all races you're currently subscribed to, with their start times.
- Reply is private (only you can see it)

---

## Automatic Background Tasks

These run on their own — no commands needed.

| Task | Schedule | What it does |
|---|---|---|
| Daily G1 Countdown | Every 24 hours (midnight UTC) | Posts the next 3 G1 races within 30 days to `G1_ALERTS_CHANNEL_ID`, each with a 🔔 reaction for subscribing |
| Race Day Alert | Every 30 minutes | Detects when a G1 is 24h, 6h, or 1h away and posts an alert. At 24h, also posts a fresh subscription card if one isn't already up. Pings existing subscribers |
| Auto-Post Results | Every 5 minutes | After a G1's scheduled post time, fetches the official result from Equibase or Racing Post and posts it. Pings subscribed members. Deletes the subscription card. Stops retrying after 90 minutes |
| Hourly News | Every 1 hour | Posts the latest 3 G1 breaking news articles to `RACE_UPDATES_CHANNEL_ID` |

---

## Adding Custom Images

Open `bot.py` and find the section near the top called `Custom Image URLs`. You'll see four dictionaries and one variable to fill in:

### How to get a free image URL

**Easiest — use Discord itself:**
1. Upload your image to any Discord channel (can be a private one)
2. Click the image to open it full size
3. Right-click → **Copy Link**
4. The URL starts with `https://cdn.discordapp.com/...` — paste that below

Other options: Imgur (imgur.com/upload) or GitHub (upload to a repo, use the raw URL).

---

### `RACE_IMAGES`
Banner image shown on race embeds for G1, G2, and G3 races. The key must match the race name exactly as it appears in `KNOWN_G1_RACES`, `KNOWN_G2_RACES`, or `KNOWN_G3_RACES`.
```python
RACE_IMAGES: dict[str, str] = {
    "Preakness Stakes":      "https://cdn.discordapp.com/your-image.jpg",
    "Breeders' Cup Classic": "https://cdn.discordapp.com/your-image.jpg",
    "Wood Memorial":         "https://cdn.discordapp.com/your-image.jpg",
    "Holy Bull Stakes":      "https://cdn.discordapp.com/your-image.jpg",
}
```

---

### `BOT_BANNER_URL`
A single fallback image shown on any race embed that doesn't have its own entry in `RACE_IMAGES`. Good for a custom logo or branded banner artwork.
```python
BOT_BANNER_URL: str = "https://cdn.discordapp.com/your-banner.png"
```

---

### `HORSE_IMAGES`
Photo shown on `/horse` and `/compare` embeds. The bot also tries to auto-scrape a photo from Equibase — your custom URL always wins if both exist.
```python
HORSE_IMAGES: dict[str, str] = {
    "Justify":    "https://cdn.discordapp.com/justify.jpg",
    "Flightline": "https://cdn.discordapp.com/flightline.jpg",
}
```
Keys are case-insensitive partial matches — `"justify"` will match `"Justify"`.

---

### `TRAINER_IMAGES`
Thumbnail shown on `/trainer` embeds.
```python
TRAINER_IMAGES: dict[str, str] = {
    "Bob Baffert":   "https://cdn.discordapp.com/baffert.jpg",
    "Aidan O'Brien": "https://cdn.discordapp.com/obrien.jpg",
}
```

---

### `JOCKEY_IMAGES`
Thumbnail shown on `/jockey` embeds.
```python
JOCKEY_IMAGES: dict[str, str] = {
    "Frankie Dettori": "https://cdn.discordapp.com/dettori.jpg",
    "Irad Ortiz Jr":   "https://cdn.discordapp.com/ortiz.jpg",
}
```

---

## Adding or Updating Race Schedules

The bot has three race lists in `bot.py`:
- `KNOWN_G1_RACES` — Grade 1 races
- `KNOWN_G2_RACES` — Grade 2 races
- `KNOWN_G3_RACES` — Grade 3 races

All three use the same format. To add a race to any list:

```python
{
    "name":     "Wood Memorial",
    "date":     datetime(2026, 4, 4, 18, 30, tzinfo=timezone.utc),
    "track":    "Aqueduct Racetrack",
    "country":  "USA",
    "distance": "1-1/8 miles",
    "purse":    "$750,000",
},
```

- `date` is always in UTC. Convert from local time if needed.
- `country` must match one of the 16 values in `COUNTRY_CHOICES` exactly (e.g. `"USA"`, `"UK"`, `"Ireland"`, `"Hong Kong"`).

For G1 races only — also add a matching entry to `G1_RESULT_SOURCES` so the auto-poster knows where to fetch the result:

```python
G1_RESULT_SOURCES: dict[str, dict] = {
    ...
    "Epsom Derby": {"source": "racingpost", "track": "epsom"},
}
```

Use `"source": "equibase"` for US races, `"source": "racingpost"` for everything else.

> G2 and G3 races are display-only — they don't trigger automatic result posting.

---

## Data Sources

| Source | Used for | Coverage |
|---|---|---|
| Equibase | Race cards, results, horse profiles, career stats (all horses inc. retired/deceased) | US races |
| Racing Post | Race cards, results, trainer/jockey profiles, SP odds | UK, Ireland, international |
| OddsChecker | Multi-bookie odds comparison | UK/IRE |
| Google News RSS | News search for horses, trainers, jockeys, races | Global, real-time |

All data is scraped from public web pages — no API keys required.

---

## Prefix Commands (Alternative to Slash Commands)

Every major command also works with the `!` prefix for quick typing in chat:

| Prefix command | Slash equivalent |
|---|---|
| `!upcoming [limit]` | `/upcoming` |
| `!news <query>` | `/news` |
| `!result <source> <track> <date> [race]` | `/result` |
| `!odds <source> <track> [date]` | `/odds` |
| `!compare <horse_a> vs <horse_b>` | `/compare` |
| `!runners <source> <track> <date>` | `/runners` |

---

## File Structure

```
horse-racing-bot/
├── bot.py              ← Everything — all commands, scrapers, embeds, tasks
├── .env                ← Your private config (token + channel IDs) — never share this
├── .env.example        ← Template showing what variables are needed
├── requirements.txt    ← Python packages to install
├── README.md           ← Feature overview and setup summary
├── GUIDE.md            ← This file — full usage and configuration guide
├── TERMS_OF_SERVICE.md ← Required for Discord bot verification
└── PRIVACY_POLICY.md   ← Required for Discord bot verification
```
