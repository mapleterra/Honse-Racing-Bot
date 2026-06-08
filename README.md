# 🏇 Honse Racing Discord Bot

A Discord bot that brings real-world horse racing data straight to your server — upcoming G1 race countdowns, race cards, live odds, official results, trainer and jockey stats, auto result notifications, and an Umamusume: Pretty Derby crossover feature.

---

## Features

- **Upcoming G1 races** — lists races in the next 7 days with live Discord countdowns, filtered by country
- **Race cards** — full list of runners, jockeys, and trainers from Equibase (US) or Racing Post (UK/IRE)
- **Odds** — morning-line odds (Equibase), forecast odds (Racing Post), or multi-bookie comparison (OddsChecker)
- **Official results** — finishing order and payouts from Equibase or Racing Post
- **Horse profiles** — career stats, bloodline, and recent race history from Equibase
- **Trainer & jockey stats** — win rates, career wins, and notable wins from Racing Post
- **Head-to-head compare** — side-by-side career stats for two horses with shared race history
- **News search** — latest horse racing articles from Google News
- **Result subscriptions** — react 🔔 on any race card or use `/subscribe` to get pinged when results post
- **Auto-posts** — daily G1 countdown, race-day alerts (24h/6h/1h), hourly news, and auto result posting
- **Umamusume: Pretty Derby** — character profiles, story lore, and Q&A for horses that appear in the game

### Country filtering

`/upcoming`, `/g1`, `/countdown`, and `/subscribe` all have a `country:` dropdown with:

🌍 All Countries · 🇺🇸 USA · 🇬🇧 UK / Ireland · 🇫🇷 France · 🇯🇵 Japan · 🇦🇺 Australia · 🇦🇪 UAE

---

## Commands

### Race Discovery
| Command | What it does |
|---|---|
| `/upcoming` | G1 races in the next 7 days — optional `country:` filter |
| `/g1` | Details + countdown for a specific race — optional `country:` filter |
| `/countdown` | Self-updating Discord timer for a race — optional `country:` filter |

### Race Day
| Command | What it does |
|---|---|
| `/runners` | Full race card: horses, jockeys, and trainers |
| `/odds` | Morning-line or multi-bookie odds |
| `/result` | Official finishing order + payouts |

### Research
| Command | What it does |
|---|---|
| `/horse` | Full horse profile from Equibase — auto-shows Umamusume card if applicable |
| `/trainer` | Trainer stats from Racing Post |
| `/jockey` | Jockey stats from Racing Post |
| `/compare` | Head-to-head career stats between two horses |
| `/news` | Latest horse racing news from Google News |

### Umamusume: Pretty Derby
| Command | What it does |
|---|---|
| `/umamusume name:<horse>` | Full character profile: personality, story arc, fun facts, lore topics |
| `/umamusume name:<horse> question:<q>` | Ask a lore question about that character |

### Subscriptions
| Command | What it does |
|---|---|
| `/subscribe` | Subscribe to race result pings — optional `country:` filter |
| `/unsubscribe` | Remove a subscription |
| `/mysubscriptions` | See all your active subscriptions |

### Other
| Command | What it does |
|---|---|
| `/help` | Full command reference inside Discord |

---

## Umamusume: Pretty Derby Integration

The bot includes a built-in database of 21 characters from **Umamusume: Pretty Derby** (by Cygames), matched to their real racehorse counterparts.

**How it works:**
- Use `/umamusume name:<horse>` to get a character's full profile
- Add `question:` to ask about specific lore topics (e.g. *"Who is her rival?"*, *"What happened to her?"*)
- When you look up a horse with `/horse`, a 🌸 teaser card automatically appears if that horse has an Umamusume counterpart

**Supported characters include:**

| Real Horse | Character | Known For |
|---|---|---|
| Special Week | 🌸 Special Week | Anime Season 1 protagonist, loves food |
| Silence Suzuka | 💨 Silence Suzuka | "Running through the sky", emotional S1 arc |
| Tokai Teio | 👑 Tokai Teio | Anime Season 2, came back from 3 fractures |
| Mejiro McQueen | 🎩 Mejiro McQueen | Aristocratic, obsessed with cats |
| Rice Shower | 🌧️ Rice Shower | Called "villain" unfairly — heartbreaking story |
| El Condor Pasa | 🦅 El Condor Pasa | Chased the Arc de Triomphe, says "Muy bien!" |
| Gold Ship | 🌊 Gold Ship | Absolute chaos, somehow always wins |
| Oguri Cap | 🍙 Oguri Cap | Food-loving people's champion |
| Symboli Rudolf | 🎖️ Symboli Rudolf | Student council president, greatest of his era |
| Agnes Tachyon | ⚗️ Agnes Tachyon | Mad scientist, undefeated and retired |
| Vodka | 🍸 Vodka | First filly to win the Japan Cup |
| Daiwa Scarlet | 🔴 Daiwa Scarlet | Lost only once — to Vodka |
| Kitasan Black | 🖤 Kitasan Black | Modern champion, sunny personality |
| Taiki Shuttle | 🇺🇸 Taiki Shuttle | First Japanese horse to win a Breeders' Cup |
| Twin Turbo | 💥 Twin Turbo | One strategy: GO FAST NOW |
| Narita Brian | 🌑 Narita Brian | Triple Crown, dark and powerful |
| Mihono Bourbon | ⚙️ Mihono Bourbon | Robotic training style, defeated by Rice Shower |
| Biwa Hayahide | 🎻 Biwa Hayahide | Narita Brian's half-sibling rival |
| Sakura Bakushin O | 🌸💨 Sakura Bakushin O | Japan's greatest sprinter |
| T.M. Opera O | 🎭 T.M. Opera O | Won 8 G1s in one year (2000) |
| Smart Falcon | 🏜️ Smart Falcon | Undefeated in dirt G1s — 7 for 7 |

More characters can be added to `UMAMUSUME_DATA` in `bot.py` at any time — see the template in that file.

---

## Customising Images

Near the top of `bot.py` you'll find dictionaries where you can add your own image URLs:

- `RACE_IMAGES` — banner image shown on each G1 race embed
- `HORSE_IMAGES` — profile photo for `/horse` embeds
- `TRAINER_IMAGES` — photo for `/trainer` embeds
- `JOCKEY_IMAGES` — photo for `/jockey` embeds
- `BOT_BANNER_URL` — default fallback banner for all embeds
- `UMAMUSUME_DATA` entries each have an `"icon_url"` field for character thumbnails

See `GUIDE.md` for full instructions on finding and hosting image URLs for free.

---

## Data Sources

All data is scraped from publicly available websites — no paid API keys required.

| Source | Used for |
|---|---|
| [Equibase](https://www.equibase.com) | US race cards, results, horse profiles |
| [Racing Post](https://www.racingpost.com) | UK/IRE race cards, trainer/jockey stats |
| [OddsChecker](https://www.oddschecker.com) | Multi-bookmaker odds comparison |
| [Google News RSS](https://news.google.com) | Latest horse racing news articles |
| Umamusume: Pretty Derby (Cygames) | In-game character lore — for entertainment only |

---

## Legal

- [Terms of Service](TERMS_OF_SERVICE.md)
- [Privacy Policy](PRIVACY_POLICY.md)

This bot is for **informational and entertainment purposes only**. Nothing it provides constitutes financial or gambling advice. Umamusume: Pretty Derby character information is included as fan reference content only — all game content belongs to Cygames.
