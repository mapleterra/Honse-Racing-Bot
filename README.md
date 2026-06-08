# 🏇 Horse Racing Bot

A Discord bot for real-world horse racing analysis — live race coverage, G1/G2/G3 race countdowns, horse and jockey research, automatic race-day alerts, and result subscriptions, all in one place.

---

## Features at a Glance

| Category | What it does |
|---|---|
| **Race Discovery** | Browse and search G1, G2, G3 races across 16 countries |
| **Race Day** | Live runners, odds, and official results |
| **Research** | Deep dives on horses, trainers, and jockeys |
| **Auto-Posts** | Daily countdowns, race-day pings, automatic results |
| **Subscriptions** | Get pinged the moment a race result is posted |
| **Umamusume** | Lore cards and Q&A for Uma Musume characters |

---

## Server Setup

Once the bot is in your server, a server admin runs two commands to enable automatic posts:

```
/setup channel_type:alerts  channel:#your-channel
/setup channel_type:news    channel:#your-channel
```

- **Alerts channel** — receives G1 countdown cards, race-day pings (24h / 6h / 1h), and automatic results
- **News channel** — receives the hourly breaking G1 news feed

To check your current configuration:
```
/setup channel_type:view
```

Requires **Manage Server** permission. Each server configures its own channels independently.

---

## Command Reference

### 📅 Race Discovery

| Command | Description |
|---|---|
| `/upcoming` | G1 races in the **next 7 days** — optional `country:` filter |
| `/g1` | Grade 1 details and countdown — browse by country or search by name |
| `/g2` | Grade 2 details and countdown — includes auto-fetched race news |
| `/g3` | Grade 3 details and countdown — includes auto-fetched race news |
| `/countdown name:<race>` | Self-updating Discord timer for any race |

**Supported countries:** 🌍 All · 🇺🇸 USA · 🇬🇧 UK · 🇮🇪 Ireland · 🇫🇷 France · 🇯🇵 Japan · 🇦🇺 Australia · 🇦🇪 UAE · 🇭🇰 Hong Kong · 🇨🇦 Canada · 🇩🇪 Germany · 🇸🇬 Singapore · 🇮🇹 Italy · 🇸🇦 Saudi Arabia · 🇿🇦 South Africa · 🇦🇷 Argentina

---

### 🐎 Race Day

| Command | Description |
|---|---|
| `/runners source:<source> track:<track> date:<date>` | Full race card — horses, jockeys, trainers |
| `/odds source:<source> track:<track>` | Morning-line or multi-bookie odds |
| `/result source:<source> track:<track> date:<date>` | Official finishing order and payouts |

**Sources:**
- `equibase` — US races
- `racingpost` — UK, Ireland, and international races
- `oddschecker` — live odds comparison

---

### 🔍 Research

| Command | Description |
|---|---|
| `/horse name:<name>` | Full Equibase profile — bloodline, career record, recent races, and news |
| `/trainer name:<name>` | Racing Post stats — win rate, notable wins, recent runners |
| `/jockey name:<name>` | Racing Post stats — win rate, career wins, recent rides |
| `/compare horse_a:<name> horse_b:<name>` | Head-to-head comparison — bloodline, career stats, direct meetings |
| `/news query:<term>` | Latest horse racing news from Google News |

`/compare` works for **active, retired, and deceased** horses — pulls full career stats from Equibase.

`/horse` automatically shows a 🌸 Umamusume teaser card if the horse has a character counterpart.

---

### 🔔 Result Subscriptions

React with 🔔 on any race announcement card to subscribe, or use the commands directly:

| Command | Description |
|---|---|
| `/subscribe name:<race>` | Get pinged when that race's official result is posted |
| `/unsubscribe name:<race>` | Remove yourself from a race's alert list |
| `/mysubscriptions` | See all races you're currently subscribed to |

Subscriptions are removed automatically after the result is posted. Each server's subscribers are tracked independently.

---

### 🎌 Umamusume: Pretty Derby

| Command | Description |
|---|---|
| `/umamusume name:<horse>` | Character card — personality, story arc, and fun facts |
| `/umamusume name:<horse> question:<q>` | Ask a lore question about the character |

Supported characters include Special Week, Silence Suzuka, Tokai Teio, Gold Ship, Oguri Cap, El Condor Pasa, and many more.

---

## Automatic Posts

Once channels are configured with `/setup`, the bot handles these automatically — no command needed:

| Post | Schedule | Channel |
|---|---|---|
| **Daily G1 Countdown** | Once per day at midnight UTC | Alerts |
| **Race-Day Alerts** | At 24h, 6h, and 1h before each G1 | Alerts |
| **Auto Results** | 15–90 minutes after each scheduled G1 | Alerts |
| **Breaking News** | Every hour | News |

Race-day alerts include a 🔔 subscription card — members who react are automatically pinged when the result drops.

---

## Supported Race Coverage

### Grade 1 — Full auto-post coverage
Kentucky Derby · Preakness Stakes · Belmont Stakes · Breeders' Cup Classic · Royal Ascot Gold Cup · King George VI & Queen Elizabeth Stakes · Arc de Triomphe · Japan Cup · Melbourne Cup · Dubai World Cup · and more

### Grade 2 & Grade 3
Searchable by name or country with race news auto-fetched at search time.

---

## Data Sources

| Source | Used for |
|---|---|
| **Equibase** | US race results, horse profiles, career stats |
| **Racing Post** | International results, trainer/jockey stats |
| **Oddschecker** | Live odds comparison |
| **Google News** | Breaking racing news |
| **RSS Feeds** | Bloodhorse, TDN, Racing Post headlines |
