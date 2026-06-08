"""
Horse Racing Discord Bot
========================
Requirements (pip install):
    discord.py>=2.3.0
    aiohttp>=3.9.0
    beautifulsoup4>=4.12.0
    feedparser>=6.0.0
    python-dotenv>=1.0.0

Run:
    python bot.py

.env file (or set env vars directly):
    DISCORD_BOT_TOKEN=your_token_here
    G1_ALERTS_CHANNEL_ID=your_channel_id   # Channel for auto G1 countdown posts
    RACE_UPDATES_CHANNEL_ID=your_channel_id # Channel for race-day updates
"""

import json
import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import feedparser
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ── Per-guild channel config ───────────────────────────────────────────────────
# Replaces the old single G1_ALERTS_CHANNEL_ID / RACE_UPDATES_CHANNEL_ID env
# vars.  Each guild sets its own channels via /setup.  Config persists across
# restarts in guild_config.json next to bot.py.
#
# Schema: { guild_id (int) → {"alerts_channel": int|None, "news_channel": int|None} }

_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
GUILD_CONFIG_FILE = os.path.join(_BOT_DIR, "guild_config.json")
GUILD_CONFIG: dict[int, dict] = {}


def _load_guild_config() -> None:
    global GUILD_CONFIG
    if os.path.exists(GUILD_CONFIG_FILE):
        try:
            with open(GUILD_CONFIG_FILE, "r") as f:
                raw = json.load(f)
            GUILD_CONFIG = {int(k): v for k, v in raw.items()}
            log.info(f"Loaded guild config for {len(GUILD_CONFIG)} guild(s)")
        except Exception as exc:
            log.warning(f"Could not load guild_config.json: {exc}")


def _save_guild_config() -> None:
    try:
        with open(GUILD_CONFIG_FILE, "w") as f:
            json.dump({str(k): v for k, v in GUILD_CONFIG.items()}, f, indent=2)
    except Exception as exc:
        log.warning(f"Could not save guild_config.json: {exc}")


def _get_alerts_channels() -> list:
    """Return every configured G1-alerts TextChannel across all guilds."""
    channels = []
    for cfg in GUILD_CONFIG.values():
        ch_id = cfg.get("alerts_channel")
        if ch_id:
            ch = bot.get_channel(int(ch_id))
            if ch:
                channels.append(ch)
    return channels


def _get_news_channels() -> list:
    """Return every configured news TextChannel across all guilds."""
    channels = []
    for cfg in GUILD_CONFIG.values():
        ch_id = cfg.get("news_channel")
        if ch_id:
            ch = bot.get_channel(int(ch_id))
            if ch:
                channels.append(ch)
    return channels

# ── Custom Image URLs ─────────────────────────────────────────────────────────
#
# Add your own artwork or real horse/person photos here.
# Use any publicly accessible image URL.
#
# HOW TO HOST AN IMAGE FOR FREE:
#   Option A — Discord (easiest):
#     1. Upload your image to any Discord channel (even a private one)
#     2. Right-click the image → "Copy Link"   (looks like https://cdn.discordapp.com/...)
#     3. Paste that URL below
#
#   Option B — Imgur: https://imgur.com/upload
#   Option C — GitHub: push the image to a repo, use the raw URL
#     e.g. https://raw.githubusercontent.com/you/repo/main/images/justify.png
#
# ── RACE BANNER IMAGES ──
# Shown as the large image on every G1 countdown/announcement embed.
# Key = exact race name (from KNOWN_G1_RACES).
RACE_IMAGES: dict[str, str] = {
    # "Preakness Stakes":              "https://cdn.discordapp.com/...",
    # "Belmont Stakes":                "https://cdn.discordapp.com/...",
    # "Breeders' Cup Classic":         "https://cdn.discordapp.com/...",
    # "Arc de Triomphe":               "https://cdn.discordapp.com/...",
}

# ── HORSE PROFILE IMAGES ──
# Shown on /horse embeds. Key = horse's registered name (case-insensitive match).
HORSE_IMAGES: dict[str, str] = {
    # "Justify":    "https://cdn.discordapp.com/...",
    # "Flightline": "https://cdn.discordapp.com/...",
    # "Enable":     "https://cdn.discordapp.com/...",
}

# ── TRAINER IMAGES ──
# Shown on /trainer embeds. Key = trainer's name (case-insensitive match).
TRAINER_IMAGES: dict[str, str] = {
    # "Bob Baffert":   "https://cdn.discordapp.com/...",
    # "Aidan O'Brien": "https://cdn.discordapp.com/...",
}

# ── JOCKEY IMAGES ──
# Shown on /jockey embeds. Key = jockey's name (case-insensitive match).
JOCKEY_IMAGES: dict[str, str] = {
    # "Frankie Dettori": "https://cdn.discordapp.com/...",
    # "Irad Ortiz Jr":   "https://cdn.discordapp.com/...",
}

# ── DEFAULT BOT BANNER ──
# Fallback image shown on race embeds when no specific race image is set above.
# Put your custom artwork/logo URL here to brand every announcement.
BOT_BANNER_URL: str = ""  # e.g. "https://cdn.discordapp.com/your-banner.png"

# ── Umamusume: Pretty Derby Data ──────────────────────────────────────────────
# Maps real horse names (lowercase) → in-game character info + lore Q&A.
# Characters are girls inspired by real racehorses from the mobile/console game
# "Umamusume: Pretty Derby" by Cygames. Each dict entry covers:
#   uma_name    — in-game character name
#   real_name   — official registered horse name
#   emoji       — flavour emoji for the character
#   born        — real horse's birth year
#   real_record — headline real-world racing record
#   personality — in-game personality description
#   story_arc   — notable storyline in the game/anime
#   fun_facts   — list of trivia bullets
#   lore_qa     — keyword → answer pairs for the lore Q&A system
#
# Add a custom thumbnail by setting "icon_url" to any image URL.

UMAMUSUME_DATA: dict[str, dict] = {
    "special week": {
        "uma_name": "Special Week", "real_name": "Special Week",
        "emoji": "🌸", "born": "1995", "icon_url": "",
        "real_record": "10 JRA wins · Japan Cup ×2 · Tenno Sho Spring · Tenno Sho Autumn (1998–1999)",
        "personality": "Cheerful, food-obsessed, and fiercely determined. Made a promise to her late foster mother to become the best horse in Japan — she never lets it go.",
        "story_arc": "Protagonist of the anime Season 1. Arrives from the countryside as a total unknown, befriends Silence Suzuka, and chases her dream through heartbreak and triumph.",
        "fun_facts": [
            "Her in-game obsession is food — especially mapo tofu. She'll eat almost anything.",
            "Her name literally means she was born on a 'special week' of the year.",
            "Her close bond with Silence Suzuka is the emotional heart of Season 1.",
            "El Condor Pasa is her main rival; they push each other in every race.",
            "Her mother's silhouette appears as a motif throughout her story.",
        ],
        "lore_qa": {
            "food": "Special Week is the biggest foodie in the game — mapo tofu is her absolute favourite, but she'll happily eat everything on the table and then some.",
            "mother": "Special Week promised her late foster mother she would become the best Uma Musume in Japan. That vow is the core motivation behind every race she runs.",
            "suzuka": "Silence Suzuka is Special Week's closest friend and inspiration. Suzuka's devastating injury during Tenno Sho Autumn is the emotional turning point of Season 1.",
            "el condor": "El Condor Pasa is Special Week's rival throughout the anime — their races together bring out the absolute best in both of them.",
            "anime": "Special Week is the main character of the Umamusume: Pretty Derby anime (Season 1, 2018). It follows her journey from rural newcomer to champion.",
            "skill": "Her skills focus on strong turf stamina and a powerful finishing burst in long-distance races.",
            "rival": "Her primary rival is El Condor Pasa in the anime, though she races many iconic opponents throughout her story.",
        },
    },
    "silence suzuka": {
        "uma_name": "Silence Suzuka", "real_name": "Silence Suzuka",
        "emoji": "💨", "born": "1994", "icon_url": "",
        "real_record": "9 JRA wins · Mainichi Okan · Kinko Sho. Injured in 1998 Tenno Sho Autumn and never raced again.",
        "personality": "Calm, elegant, and quietly poetic. She runs not for victory but for the pure feeling of wind rushing past her. Deeply kind to Special Week.",
        "story_arc": "The heart of Season 1. Her bond with Special Week is the show's soul. Her catastrophic injury mid-season reframes the entire story of why horses run.",
        "fun_facts": [
            "Famous in-game for wanting to 'run through the sky' — her racing style is serene and ethereal.",
            "She is one of the most beloved characters in the franchise despite limited race wins.",
            "Her real-life injury during the Tenno Sho Autumn (1998) shocked Japanese racing fans.",
            "In the game, her injury arc is handled with great care and emotional weight.",
            "Her silence and mystery make her one of the most iconic characters in the cast.",
        ],
        "lore_qa": {
            "injury": "Silence Suzuka suffered a fatal leg injury during the 1998 Tenno Sho Autumn and was euthanised. In the anime/game, this event is reimagined as a serious but survivable injury — it's the most emotionally heavy moment in Season 1.",
            "wind": "Suzuka often talks about 'running through the sky' or chasing the wind. It reflects her real racing style — she loved to run free at the front, sometimes by a huge margin.",
            "special week": "Special Week is Suzuka's closest friend and the one who draws out her competitive spirit. Their bond is the emotional core of Season 1.",
            "skill": "Her skills reward front-running (escape position) and open-track sprinting. She's designed to build huge early leads.",
            "personality": "Suzuka is calm, gentle, and a little mysterious. She doesn't race for trophies — she runs for the pure joy of feeling wind against her face.",
            "anime": "She is the co-protagonist of Season 1. Her injury arc midway through the season is considered one of anime's most affecting sports moments.",
        },
    },
    "tokai teio": {
        "uma_name": "Tokai Teio", "real_name": "Tokai Teio",
        "emoji": "👑", "born": "1988", "born": "1988", "icon_url": "",
        "real_record": "12 JRA wins · Japan Cup · Takarazuka Kinen ×2. Overcame three serious injuries.",
        "personality": "Bright, dramatic, and deeply self-confident. Declares herself 'Emperor' and loves grand entrances — but underneath is a horse who refuses to be beaten by anything, even injury.",
        "story_arc": "Central character of anime Season 2. Her arc is about resilience: three career-threatening fractures, and each time she fights her way back. Her bond with Mejiro McQueen is the story's heart.",
        "fun_facts": [
            "She calls herself 'Teio' and refers to herself as emperor/ruler — it's endearing rather than arrogant.",
            "Her catchphrase 'Zeeeetto!' (Absolutely!) is iconic among fans.",
            "Her real horse suffered three separate canon bone fractures and came back each time.",
            "Her relationship with Mejiro McQueen is the central dynamic of Season 2.",
            "She's one of the most popular characters in the entire franchise.",
        ],
        "lore_qa": {
            "injury": "Tokai Teio's injury arc in Season 2 is one of the most emotionally resonant in the franchise. She fractures a bone, recovers, races again — then fractures it again. Her determination to keep coming back defines her character.",
            "emperor": "She styled herself as the emperor/ruler of the track. It's a play on 'Tokai Teio' meaning 'Tokai Emperor'. She's theatrical about it, but it's backed up by genuine talent.",
            "mcqueen": "Mejiro McQueen is Tokai Teio's best friend and greatest rival. Their relationship — both competitive and deeply caring — is the central thread of Season 2.",
            "comeback": "Her real horse came back from three separate fractures across his career. That comeback spirit is fully baked into her in-game character.",
            "catchphrase": "Her catchphrase is 'Zeeeetto!' which roughly means 'Absolutely!' or 'No way am I losing!' She says it with maximum drama.",
            "anime": "Tokai Teio is the protagonist of Umamusume Season 2 (2021). Her resilience arc against constant injury is the season's central theme.",
            "skill": "Her skills reward mid-to-late-race surges on turf, especially at medium and long distances — reflecting her explosive real-racing style.",
        },
    },
    "mejiro mcqueen": {
        "uma_name": "Mejiro McQueen", "real_name": "Mejiro McQueen",
        "emoji": "🎩", "born": "1987", "icon_url": "",
        "real_record": "9 JRA wins · Tenno Sho Spring ×3 · Takarazuka Kinen. Also from the famous Mejiro racing family.",
        "personality": "Composed, aristocratic, and proud. She comes from a distinguished racing lineage and takes that heritage seriously — but Tokai Teio cracks her composure in the best way.",
        "story_arc": "Co-protagonist of Season 2. Her rivalry and deep friendship with Tokai Teio, plus her own health struggles, give Season 2 its emotional weight.",
        "fun_facts": [
            "She is from the Mejiro family — a long line of famous racehorses in Japan, including Mejiro Ryan and Mejiro Palmer.",
            "Her love of cats is a running gag; she'll do anything for a cat.",
            "Her composed exterior hides genuine warmth for those she cares about.",
            "Her voice actress Marika Kouno gives her an iconic formal speech pattern.",
            "Her rivalry with Tokai Teio is considered one of the best character dynamics in the franchise.",
        ],
        "lore_qa": {
            "cats": "Mejiro McQueen absolutely loves cats — she'll break her aristocratic composure immediately if one is nearby. It's one of her most charming character traits.",
            "family": "McQueen comes from the famous Mejiro racing lineage, including Mejiro Ryan (her mother in-game) and Mejiro Palmer. Family legacy is a big part of her character motivation.",
            "teio": "Tokai Teio is McQueen's closest friend and rival. Their bond — Teio's chaotic energy vs McQueen's composure — creates one of the best dynamics in the series.",
            "pride": "McQueen is proud of her bloodline and aristocratic upbringing, but the game shows her pride as something earned rather than empty.",
            "skill": "Her skills excel at long-distance turf races, reflecting the real Mejiro McQueen's dominance in the Tenno Sho Spring (won 3 times).",
            "anime": "McQueen is Tokai Teio's co-star in Season 2 and arguably the emotional anchor of the season.",
            "health": "Like the real horse, McQueen's character faces health challenges that threaten her racing career — mirroring the real Mejiro McQueen's tendon injury.",
        },
    },
    "gold ship": {
        "uma_name": "Gold Ship", "real_name": "Gold Ship",
        "emoji": "🌊", "born": "2009", "icon_url": "",
        "real_record": "13 JRA wins · Kikuka Sho · Tenno Sho Spring ×2 · Takarazuka Kinen ×2 · Arima Kinen. Known for bizarre, unpredictable behaviour.",
        "personality": "Chaotic, loud, weird in the best possible way. She'll do something completely unhinged and then win by four lengths. Absolutely nobody — including herself — knows what she'll do next.",
        "story_arc": "Comic relief turned genuine competitor. Gold Ship appears across multiple stories as the wildcard who somehow always comes through. Her antics with Mejiro McQueen are legendary.",
        "fun_facts": [
            "The real Gold Ship was famous for bizarre antics — refusing to load, running in random directions, doing whatever he felt like. The game leans into this 100%.",
            "Despite her chaos, her race record was exceptional — 13 wins including major G1s.",
            "She is widely considered the funniest character in the game.",
            "Her friendship with Mejiro McQueen is a classic 'chaos meets composure' pairing.",
            "Fan-favourite for meme-ability — many of her voice lines are deliberately absurd.",
        ],
        "lore_qa": {
            "chaos": "Gold Ship's chaotic personality is directly inspired by the real Gold Ship, who was notorious for doing whatever he wanted — refusing to load into the starting gate, bolting sideways, then somehow winning anyway.",
            "mcqueen": "Her relationship with Mejiro McQueen is a running comedy duo — Gold Ship's madness constantly disrupts McQueen's dignity, but McQueen keeps coming back for more.",
            "wins": "Despite all the chaos, Gold Ship is a genuine powerhouse — 13 JRA wins including the Takarazuka Kinen twice, Tenno Sho Spring twice, and the Arima Kinen.",
            "personality": "She's written as completely unpredictable: she might be deeply philosophical one moment and then do something completely bizarre the next. Nobody — including the other characters — knows what she'll do.",
            "skill": "Her skills reflect power and durability — she excels in long-distance races and is built for mid-race surges rather than conventional early positioning.",
            "funny": "Gold Ship is the resident comedic wildcard. Her voice lines, animations and story scenes are written for maximum chaos and maximum laughs.",
        },
    },
    "oguri cap": {
        "uma_name": "Oguri Cap", "real_name": "Oguri Cap",
        "emoji": "🍙", "born": "1985", "icon_url": "",
        "real_record": "12 Japan Racing Association + local wins · Japan Cup · Arima Kinen. A beloved people's champion.",
        "personality": "Gentle, humble, and obsessively fond of food — especially carrots and onigiri (rice balls). She's the ultimate underdog who rose from a local track to become a national legend.",
        "story_arc": "One of the game's most iconic characters — the everyman who became extraordinary. Her kindness, love of food, and quiet determination won Japan's heart.",
        "fun_facts": [
            "The real Oguri Cap was famous for his enormous appetite and affectionate personality — fans would feed him snacks.",
            "His fan following was enormous — over 200,000 people attended his retirement ceremony.",
            "Oguri Cap is the subject of a famous manga and is considered one of Japan's all-time beloved racehorses.",
            "In-game she is always hungry and will do almost anything for food.",
            "Her gentle nature makes her one of the most wholesome characters in the cast.",
        ],
        "lore_qa": {
            "food": "Oguri Cap is almost as food-obsessed as Special Week — she loves onigiri (rice balls) and carrots above all else. Food is her primary motivation for most things.",
            "real horse": "The real Oguri Cap was an extraordinary racehorse who rose from local tracks to win the Japan Cup and Arima Kinen. His retirement in 1990 drew over 200,000 fans to Nakayama Racecourse.",
            "fans": "Both the real horse and the in-game character have enormous fan followings. Oguri Cap is considered a national treasure of Japanese horse racing.",
            "underdog": "Oguri Cap started at small local tracks (not the prestigious JRA circuit) and still rose to beat the best horses in Japan — a true underdog story.",
            "personality": "She's written as soft-spoken, sweet, and easily distracted by food. Despite her humble personality she has a fierce competitive spirit when it counts.",
            "skill": "Her in-game skills reflect her real-life versatility across distances and surfaces, with strong late-race finishing ability.",
        },
    },
    "symboli rudolf": {
        "uma_name": "Symboli Rudolf", "real_name": "Symboli Rudolf",
        "emoji": "🎖️", "born": "1981", "icon_url": "",
        "real_record": "13 JRA wins · Triple Crown · Tenno Sho Spring · Arima Kinen ×2 · Japan Cup. Often called the greatest Japanese racehorse of all time.",
        "personality": "Noble, stoic, and intellectually brilliant. She holds herself as a leader and role model, deeply respected by the entire student body. Her sense of responsibility to others is immense.",
        "story_arc": "The president of Tracen Academy's student council. She mentors younger horses and carries the weight of her legacy with quiet grace.",
        "fun_facts": [
            "The real Symboli Rudolf was the first Japanese horse to win the Triple Crown after 1964 — one of only 7 ever to do so.",
            "He is widely considered the greatest Japanese racehorse of the 20th century.",
            "In-game she is the student council president — fitting for a horse of her stature.",
            "Her calm authority makes her one of the most respected characters in the game.",
            "Tokai Teio is her direct protégé, which makes their generational bond meaningful.",
        ],
        "lore_qa": {
            "triple crown": "The real Symboli Rudolf won the Japanese Triple Crown in 1984 — the Satsuki Sho, Tokyo Yushun (Japanese Derby), and Kikuka Sho. He was the first to do it in 20 years.",
            "greatest": "Symboli Rudolf is often called the greatest Japanese racehorse of the 20th century. 13 career wins against the best competition of his era.",
            "teio": "In-game, Tokai Teio is Symboli Rudolf's direct protégé and the one who carries on her legacy. Their teacher-student bond is a central part of Season 2's backstory.",
            "student council": "She serves as president of Tracen Academy's student council — the in-game school for Uma Musume. Her leadership role reflects her real-life status as the greatest champion of her era.",
            "personality": "Rudolf is calm, eloquent, and deeply principled. She takes her responsibilities to younger horses extremely seriously.",
            "skill": "Her skills are built for classical long-distance turf racing — she's a powerhouse at 2400m+ distances, mirroring her Triple Crown victories.",
        },
    },
    "agnes tachyon": {
        "uma_name": "Agnes Tachyon", "real_name": "Agnes Tachyon",
        "emoji": "⚗️", "born": "1998", "icon_url": "",
        "real_record": "4 JRA wins · Satsuki Sho (undefeated). Retired due to injury before the Japanese Derby — considered potentially the greatest unfinished story in Japanese racing.",
        "personality": "Eccentric genius scientist obsessed with racing research and experiments. She's cryptic, unpredictable, and views everything through the lens of data and hypothesis — but she clearly cares about the horses she studies.",
        "story_arc": "Retired from active racing but can't stop obsessing over it. She runs secret experiments, manipulates events from the shadows, and nobody is entirely sure what she's planning.",
        "fun_facts": [
            "The real Agnes Tachyon retired undefeated after injury — he never lost a race.",
            "In-game she is a researcher and mad scientist who refuses to actually race (despite clearly being brilliant at it).",
            "Her eccentric speech patterns and cryptic behaviour make her deeply beloved by fans.",
            "Her name references the physics term 'tachyon' — a hypothetical particle faster than light.",
            "She is one of the highest-rated characters in the mobile game for competitive play.",
        ],
        "lore_qa": {
            "retired": "The real Agnes Tachyon retired undefeated due to injury before the Japanese Derby — he never got the chance to run in it. The in-game character processes this by becoming a researcher rather than a racer.",
            "scientist": "Her entire in-game persona is 'mad scientist' — she runs experiments on other Uma Musume, speaks in cryptic riddles, and seems to always know more than she lets on.",
            "undefeated": "Agnes Tachyon went 4 for 4 in her real-horse career, including the Satsuki Sho. Many believe he could have been the best of his generation — we never got to find out.",
            "personality": "She's written as aloof and eccentric, but her affection for the horses she studies is genuine. She just expresses it in extremely unusual ways.",
            "name": "The name 'Tachyon' comes from a theoretical physics concept — a particle that travels faster than light. It fits her character perfectly.",
            "skill": "Despite not competing in-game, her playable form is built around explosive speed — fitting for a horse that was never beaten.",
        },
    },
    "rice shower": {
        "uma_name": "Rice Shower", "real_name": "Rice Shower",
        "emoji": "🌧️", "born": "1989", "icon_url": "",
        "real_record": "7 JRA wins · Kikuka Sho · Tenno Sho Spring ×2. Known as 'The Grim Reaper' for repeatedly defeating fan favourite horses.",
        "personality": "Shy, sweet, and deeply insecure. She's haunted by her reputation as the villain of Japanese racing — she never wanted to hurt anyone, she just ran as hard as she could.",
        "story_arc": "One of the most emotionally complex stories in the game. She is adored by players but was booed by real-life fans for defeating beloved horses. Her arc explores what it means to be hated for doing your best.",
        "fun_facts": [
            "The real Rice Shower was nicknamed 'Black Villain' and 'Grim Reaper' because he kept defeating fan favourite Mihono Bourbon and Biwa Hayahide.",
            "Japanese racing fans actually booed the real horse — he was genuinely unpopular in his racing era.",
            "Rice Shower's story in the game reframes this as a deeply tragic misunderstanding.",
            "She is now one of the most beloved Umamusume characters — the fandom gave her the love the real horse never got.",
            "Her shy personality and rain motif make her one of the most visually distinctive characters.",
        ],
        "lore_qa": {
            "villain": "The real Rice Shower was called 'The Grim Reaper' because he kept beating beloved horses like Mihono Bourbon. Real fans actually booed him at the track. The game reframes this as deeply unfair — he was just running his race.",
            "fans": "Rice Shower's in-game story is largely about being hated despite doing nothing wrong. The Umamusume fanbase gave her all the love the real horse never received — she's now one of the most beloved characters.",
            "sad": "Her story arc is genuinely tear-jerking. She just wants to make people happy but her victories kept making crowds upset. It's one of the most affecting stories in the franchise.",
            "personality": "She's written as extremely shy, easily startled, and very sweet. She worries constantly about whether she's causing trouble for others.",
            "bourbon": "Mihono Bourbon and Biwa Hayahide are the horses Rice Shower repeatedly defeated in real life — their rivalry is woven into her character story.",
            "rain": "Rain is Rice Shower's visual motif — grey colour scheme, rain imagery, and a melancholy aesthetic that contrasts with her sweet personality.",
        },
    },
    "el condor pasa": {
        "uma_name": "El Condor Pasa", "real_name": "El Condor Pasa",
        "emoji": "🦅", "born": "1995", "icon_url": "",
        "real_record": "11 wins (Japan + France) · NHK Mile Cup · Japan Cup. Second in the Prix de l'Arc de Triomphe (1999) by a neck — the best result by a Japanese horse at the time.",
        "personality": "Energetic, loud, and warmly American-flavoured. She mixes Spanish and English phrases into her speech and approaches racing with pure infectious enthusiasm. Best rival to Special Week.",
        "story_arc": "Dreams of conquering the world stage — specifically the Arc de Triomphe. Her campaign in France is the climax of Season 1's parallel storyline. She finishes second by a neck.",
        "fun_facts": [
            "Named after the Andean condor and the famous Peruvian folk song 'El Cóndor Pasa'.",
            "The real El Condor Pasa trained and raced in France, learning French racing culture firsthand.",
            "His Arc finish (2nd by a neck behind Montjeu) remains one of Japan's greatest overseas performances.",
            "In-game she frequently says 'Muy bien!' and 'Vamos!' mixing Spanish into her Japanese.",
            "Her rivalry with Special Week is considered one of the most heartfelt in the anime.",
        ],
        "lore_qa": {
            "arc": "El Condor Pasa's dream is to win the Prix de l'Arc de Triomphe for Japan. In real life he came agonisingly close — 2nd by a neck behind Montjeu in 1999. In the anime this is portrayed as a glorious near-miss rather than a defeat.",
            "france": "The real El Condor Pasa moved to France specifically to campaign for the Arc. He won the Grand Prix de Saint-Cloud and ran in multiple major French races. In the game this European adventure is central to her story.",
            "special week": "El Condor Pasa is Special Week's most important rival in Season 1. Their races bring out the best in both of them — it's a rivalry built on genuine mutual respect.",
            "language": "She mixes Spanish words ('Muy bien!', 'Vamos!', 'Sí!') into her speech, reflecting the South American name and the international nature of the real horse.",
            "name": "Named after the condor of the Andes and the famous folk song. It's an unusual and memorable name that suits her bold, international personality.",
            "personality": "She's written as openly enthusiastic, warm, and competitive without being arrogant. She celebrates others' achievements almost as much as her own.",
        },
    },
    "vodka": {
        "uma_name": "Vodka", "real_name": "Vodka",
        "emoji": "🍸", "born": "2004", "icon_url": "",
        "real_record": "8 JRA wins · Japan Cup · Tenno Sho Autumn ×2 · Victoria Mile. First filly to win the Japan Cup outright.",
        "personality": "Confident and competitive, with a short fuse when her dignity is questioned. She and Daiwa Scarlet have a spectacular rivalry that's equal parts competitive and comedic bickering.",
        "story_arc": "Her arc revolves around her intense rivalry with Daiwa Scarlet — two horses who push each other to greatness while refusing to admit they need each other.",
        "fun_facts": [
            "The first filly to win the Japan Cup, defeating males. A landmark moment in Japanese racing.",
            "Her rivalry with Daiwa Scarlet defined Japanese horse racing in the late 2000s.",
            "In-game the two constantly bicker but are clearly best friends underneath.",
            "Her name is literally Vodka — a talking point for every new fan.",
            "She is one of the most competitive characters in the game's roster.",
        ],
        "lore_qa": {
            "name": "Yes, her name is literally Vodka. The real horse was named by her owner after the drink. In-game it's played for comedy — she gets flustered when people make alcohol jokes.",
            "scarlet": "Daiwa Scarlet is Vodka's eternal rival and, under all the arguing, her best friend. Their constant competitive bickering is one of the game's most entertaining dynamics.",
            "filly": "The real Vodka was the first filly to win the Japan Cup outright — a landmark achievement in a race typically dominated by males.",
            "japan cup": "Winning the Japan Cup against males was the real Vodka's crowning achievement. It defined her legacy and is a key moment in her in-game story.",
            "personality": "She's fiercely competitive and easily annoyed, especially by Daiwa Scarlet, but her fighting spirit and commitment to racing are genuinely admirable.",
            "skill": "Her skills are built for mid-distance turf racing with strong late surges — reflecting her real dominance at 2000m.",
        },
    },
    "daiwa scarlet": {
        "uma_name": "Daiwa Scarlet", "real_name": "Daiwa Scarlet",
        "emoji": "🔴", "born": "2004", "icon_url": "",
        "real_record": "12 JRA wins · Oka Sho · Tenno Sho Autumn · Arima Kinen. Lost only once in 13 career starts.",
        "personality": "Dramatic, bold, and secretly soft-hearted. She presents herself as Vodka's superior at every opportunity, but it's obvious she loves the rivalry as much as anyone.",
        "story_arc": "Her story is inseparable from Vodka's — two horses who define each other through competition. Her near-perfect win record and single loss give her arc surprising depth.",
        "fun_facts": [
            "Lost only once in 13 starts — one of the best win percentages in modern Japanese racing.",
            "Her one loss was to Vodka in the Tenno Sho Autumn — the race that makes their rivalry legendary.",
            "In-game she wears a dramatic red colour scheme matching her fiery personality.",
            "Her voice actress Tomoyo Kurosawa gives her a wonderfully theatrical speech pattern.",
            "She and Vodka are frequently listed as the most entertaining character duo in the game.",
        ],
        "lore_qa": {
            "loss": "Daiwa Scarlet lost only once in her career — to Vodka in the Tenno Sho Autumn. This single defeat is what gives their rivalry its dramatic weight in-game.",
            "vodka": "Vodka is Daiwa Scarlet's rival, foil, and best friend — though she'd never admit the last part. Their relationship is built on constant bickering and genuinely pushing each other to run faster.",
            "record": "12 wins from 13 starts is remarkable. The real Daiwa Scarlet was among the most dominant fillies of her generation.",
            "personality": "She's theatrical and loves declaring herself superior, but her actual warmth and loyalty to those she cares about come through clearly in the story.",
            "arima": "Winning the Arima Kinen — Japan's premier year-end race, voted on by fans — was a highlight of the real horse's career, and it features prominently in her in-game story.",
            "skill": "Her skills focus on staying power and mid-race dominance — she's built for races where controlling the pace matters.",
        },
    },
    "kitasan black": {
        "uma_name": "Kitasan Black", "real_name": "Kitasan Black",
        "emoji": "🖤", "born": "2012", "icon_url": "",
        "real_record": "12 JRA wins · Tenno Sho Spring ×2 · Tenno Sho Autumn · Japan Cup · Arima Kinen ×2. One of Japan's greatest modern champions.",
        "personality": "Sunny, loud, and unstoppably enthusiastic. She'll run a full training session and still have energy left to cheer everyone else on. Positivity incarnate.",
        "story_arc": "Her bond with Satono Diamond — who she views as her greatest rival and biggest supporter — is the core of her story. They push each other to heights neither could reach alone.",
        "fun_facts": [
            "The real Kitasan Black was owned by Seiichi Kita, a famous enka singer — his stage name 'Kitasan' gave the horse his name.",
            "12 career wins including 6 G1s — one of the most decorated modern Japanese racehorses.",
            "His retirement ceremony at Nakayama drew enormous crowds.",
            "In-game she is consistently one of the most powerful competitive characters.",
            "Her positive attitude is modelled on the real horse's calm and cooperative temperament.",
        ],
        "lore_qa": {
            "name": "Kitasan Black was named after his owner Seiichi Kita, a famous enka (Japanese folk pop) singer, whose stage name is 'Kitasan'. The 'Black' refers to his dark coat.",
            "satono diamond": "Satono Diamond is Kitasan Black's most important rival. In real life they raced each other multiple times across major G1s — in-game their relationship is one of the franchise's great rivalries.",
            "wins": "12 JRA wins including the Tenno Sho Spring twice, Japan Cup, and Arima Kinen twice. One of the great modern Japanese champions.",
            "personality": "She's written as almost impossibly cheerful and energetic. She brings the mood up wherever she goes and genuinely loves seeing others succeed.",
            "modern": "Unlike many Umamusume characters from the 1980s–90s, Kitasan Black raced in the 2010s — so many fans remember watching the real horse race.",
            "skill": "Strong at pace-setting and long-distance turf endurance races. Her skills reward consistent front-running strategies.",
        },
    },
    "taiki shuttle": {
        "uma_name": "Taiki Shuttle", "real_name": "Taiki Shuttle",
        "emoji": "🇺🇸", "born": "1994", "icon_url": "",
        "real_record": "11 wins (Japan + USA + France) · NHK Mile Cup · Mile Championship · Breeders' Cup Mile (1997). First Japanese-trained horse to win a Breeders' Cup race.",
        "personality": "Casual American-influenced personality. She speaks with English mixed in, loves American culture, and brings a laid-back West Coast vibe to Tracen Academy.",
        "story_arc": "A worldly character who bridges Japanese and international racing cultures. Her overseas success story is unique in the cast.",
        "fun_facts": [
            "First Japanese-trained horse to win a Breeders' Cup race (1997 Breeders' Cup Mile at Hollywood Park).",
            "Also won in France, making him one of the most internationally successful Japanese horses of his era.",
            "In-game she mixes English phrases into her speech and has a distinctly American personality.",
            "Her Breeders' Cup win is a genuinely historic moment in international horse racing.",
            "She trained with US horse Richard Mandella for her Breeders' Cup campaign.",
        ],
        "lore_qa": {
            "breeders cup": "The real Taiki Shuttle won the 1997 Breeders' Cup Mile at Hollywood Park — the first Japanese-trained horse to ever win a Breeders' Cup race. A landmark moment in international racing history.",
            "international": "He raced and won in Japan, the USA, and France — making him one of the most internationally successful Japanese horses of the 1990s.",
            "english": "In-game she drops English words and phrases into her speech to reflect her American racing background. It's a charming character quirk.",
            "america": "Taiki Shuttle has a distinctly American personality — laid-back, casual, enthusiastic about hamburgers and baseball. It's played for fun given how Japanese she actually is.",
            "personality": "She's relaxed and approachable, a contrast to some of the more intense characters. Her international experience gives her a worldly perspective.",
            "skill": "As a specialist miler, her skills are built for speed over shorter distances — reflecting her real-life dominance in mile-distance races.",
        },
    },
    "twin turbo": {
        "uma_name": "Twin Turbo", "real_name": "Twin Turbo",
        "emoji": "💥", "born": "1988", "icon_url": "",
        "real_record": "9 JRA wins including the Arima Kinen (1991) as a massive outsider. Famous for extreme front-running tactics.",
        "personality": "Wildly chaotic energy. She runs to the front from the gun and dares everyone to catch her. Win or blow up spectacularly — there is no middle ground.",
        "story_arc": "Fan favourite for her unhinged commitment to one strategy: GO FAST IMMEDIATELY AND NEVER STOP. Her sheer personality makes her one of the most entertaining characters in the cast.",
        "fun_facts": [
            "The real Twin Turbo was famous for extreme front-running — he'd sprint out and build a lead so massive it was comical. Sometimes it worked brilliantly, sometimes catastrophically.",
            "Won the 1991 Arima Kinen as a huge outsider with his characteristic 'sprint and survive' tactics.",
            "In-game she is written as gloriously unhinged — a one-strategy horse who goes all-in every single time.",
            "She has a legendary following among fans who love high-variance chaos.",
            "Her enthusiasm for going FAST is written as completely pure and non-ironic.",
        ],
        "lore_qa": {
            "running style": "Twin Turbo has exactly one strategy: sprint to the front immediately and don't let anyone pass. It's called an 'escape' in game terms. Sometimes it results in enormous victories, sometimes spectacular implosions. She doesn't care which.",
            "arima": "The real Twin Turbo won the 1991 Arima Kinen (Japan's biggest year-end race) as a heavy outsider using her characteristic front-running. One of the great underdog victories in Japanese racing history.",
            "chaos": "She is one of the most chaotic characters in the game — pure energy, no plan beyond 'go as fast as possible immediately'. Fans adore her for it.",
            "personality": "Loudly enthusiastic about speed. She talks about going fast the way others talk about breathing. There is no off switch.",
            "skill": "Her skills are built exclusively for escape (wire-to-wire front-running) strategies. She builds huge leads early and tries to hold on. High-risk, high-reward.",
        },
    },
    "narita brian": {
        "uma_name": "Narita Brian", "real_name": "Narita Brian",
        "emoji": "🌑", "born": "1991", "icon_url": "",
        "real_record": "13 JRA wins · Triple Crown · Arima Kinen. Dominated Japanese racing in 1994 before career-ending injury.",
        "personality": "Dark, brooding, and almost terrifyingly powerful. She speaks little, projects intensity, and her presence alone unsettles other horses. But underneath is a deep sense of honour.",
        "story_arc": "Often depicted as an overwhelming force — the horse other characters fear to face. Her relationship with Biwa Hayahide (her real-life rival) gives her rare warmth.",
        "fun_facts": [
            "Won the Japanese Triple Crown in 1994 with dominant performances.",
            "Often described as the most physically imposing racehorse of his era.",
            "His career was cut short by injury, leaving fans to wonder what more he could have achieved.",
            "In-game her dark aesthetic and intimidating presence make her instantly iconic.",
            "The real Narita Brian and Biwa Hayahide had one of the great rivalries in 1990s Japanese racing.",
        ],
        "lore_qa": {
            "triple crown": "The real Narita Brian won the 1994 Japanese Triple Crown, dominating his generation. The in-game character's overwhelming power reflects those real performances.",
            "biwa hayahide": "Biwa Hayahide is Narita Brian's most significant rival in-game, reflecting their real-life competition. Their rivalry has a respect-between-warriors quality that gives both characters depth.",
            "personality": "She's written as quiet, intense, and a little frightening — not out of cruelty but because her focus and ability are on another level. Think less 'villain', more 'force of nature'.",
            "dark": "Her visual design leans into darkness — black colour scheme, heavy shadows, an overall aesthetic of controlled power.",
            "injury": "Like the real horse, Narita Brian's story involves the shadow of injury cutting a potentially longer legacy short.",
            "skill": "Her in-game skills reflect dominance — she's built to overwhelm opponents in mid-to-long-distance races with raw power.",
        },
    },
    "mihono bourbon": {
        "uma_name": "Mihono Bourbon", "real_name": "Mihono Bourbon",
        "emoji": "⚙️", "born": "1989", "icon_url": "",
        "real_record": "10 JRA wins · Satsuki Sho · Japanese Derby (undefeated up to that point). Lost the Kikuka Sho to Rice Shower.",
        "personality": "Robotic, data-driven, and utterly disciplined. She approaches racing like an engineering problem — run the optimal pace, execute the optimal finish. Emotions are inefficient.",
        "story_arc": "Her story explores what happens when a perfect machine meets an unpredictable opponent. Rice Shower's defeat of her became one of the defining moments in both real racing and Umamusume lore.",
        "fun_facts": [
            "The real Mihono Bourbon was famous for pacemaking ability — he was basically trained to run specific splits.",
            "He was undefeated until Rice Shower beat him in the Kikuka Sho, devastating his fans.",
            "In-game her robotic personality is written with genuine comedy and occasional touching moments.",
            "Her trainer in real life used a highly scientific training approach — reflected in her character.",
            "She and Rice Shower have one of the most famous rivalries in the entire franchise.",
        ],
        "lore_qa": {
            "robot": "Mihono Bourbon is written as almost machine-like — she thinks in data, runs to precise splits, and finds emotions inefficient. It's played as both funny and occasionally poignant.",
            "rice shower": "Rice Shower defeating Mihono Bourbon in the Kikuka Sho was one of the most shocking upsets of 1992. In-game this defeat is central to both characters' stories.",
            "training": "The real Mihono Bourbon's trainer Hiroshi Ikeda used unusually scientific training methods — precise interval training, strict diet, exact workloads. This is fully reflected in her character.",
            "undefeated": "She was undefeated before the Kikuka Sho — her loss to Rice Shower was genuinely shocking to Japanese racing fans.",
            "personality": "Despite her robotic presentation, occasional moments of genuine feeling break through — especially in scenes with Rice Shower or her trainer.",
            "skill": "Her skills are built around pace control and mid-race efficiency — the in-game version of her real front-running, pace-calculated racing style.",
        },
    },
    "biwa hayahide": {
        "uma_name": "Biwa Hayahide", "real_name": "Biwa Hayahide",
        "emoji": "🎻", "born": "1990", "icon_url": "",
        "real_record": "10 JRA wins · Japanese Derby · Kikuka Sho · Arima Kinen. Lost to Rice Shower in the Tenno Sho Spring.",
        "personality": "Quiet, precise, and thoughtful. She studies opponents carefully before racing and prefers solving problems to forcing them. Her rivalry with Narita Brian (her younger brother) is complicated.",
        "story_arc": "Her story explores sibling rivalry — the real Biwa Hayahide and Narita Brian were half-brothers by the same sire. In-game this becomes a complex older-sister dynamic.",
        "fun_facts": [
            "The real Biwa Hayahide and Narita Brian were both sons of Paramount — making their rivalry literally familial.",
            "Considered one of the best Japanese horses of the early 1990s.",
            "His loss to Rice Shower in the Tenno Sho Spring was another of Rice Shower's villain-label-generating upsets.",
            "In-game she and Narita Brian's sibling dynamic gives both characters more emotional depth.",
            "She is often associated with elegance and classical technique over raw power.",
        ],
        "lore_qa": {
            "narita brian": "The real Biwa Hayahide and Narita Brian were half-siblings by the same sire Paramount. In-game this is developed into a complex older-sister/younger-sister dynamic full of rivalry and quiet pride.",
            "rice shower": "Biwa Hayahide was another horse that Rice Shower defeated — her Tenno Sho Spring loss to Rice Shower added to Rice Shower's 'villain' reputation at the time.",
            "technique": "She is depicted as a precise, technical racer who studies opponents rather than relying on raw speed. It reflects the real horse's versatile racing style.",
            "sibling": "Her relationship with Narita Brian is the most distinctive part of her story — two gifted siblings from the same bloodline taking different paths to greatness.",
            "personality": "Calm and analytical. She communicates efficiently and observes carefully. Less dramatic than many other characters but deeply thoughtful.",
        },
    },
    "sakura bakushin o": {
        "uma_name": "Sakura Bakushin O", "real_name": "Sakura Bakushin O",
        "emoji": "🌸💨", "born": "1989", "icon_url": "",
        "real_record": "11 JRA wins · Sprinters Stakes ×2 · Hanshin Juvenile Fillies. The fastest horse of his era — Japan's greatest sprinter of the 1990s.",
        "personality": "Bubbly, energetic, and obsessed with speed above all else. She'll sprint at maximum effort constantly and has the attention span of someone who runs 1000m at full speed.",
        "story_arc": "The ultimate short-distance specialist in a world that often rewards distance horses. Her joy is purely in going as fast as possible for as long as she can.",
        "fun_facts": [
            "The real Sakura Bakushin O set a 1000m world record in a workout.",
            "Dominated Japanese sprint racing in the early 1990s — considered the greatest Japanese sprinter of his era.",
            "In-game she is the cheerful hyperactive counterpart to longer-distance horses.",
            "Her name means 'Cherry Blossom Explosive Progress'.",
            "A fan favourite for her pure unfiltered enthusiasm for speed.",
        ],
        "lore_qa": {
            "sprint": "Sakura Bakushin O is the game's quintessential sprinter — everything about her is built for short, explosive distances. She's at her best in 1000-1200m races.",
            "speed": "The real horse reportedly set a world-record workout time over 1000m. In-game, her obsession with pure speed is the defining element of her personality.",
            "name": "Her name means something like 'Cherry Blossom Explosive Progress' — the sakura (cherry blossom) plus bakushin (explosive advance). It suits her perfectly.",
            "personality": "She's written as extremely cheerful and high-energy, with a laser focus on going FAST. Distance racing bores her because she's done before anyone gets going.",
            "skill": "Pure sprint skills — her in-game build is almost exclusively focused on short-distance, explosive speed. One of the strongest sprint specialists in the game.",
        },
    },
    "t.m. opera o": {
        "uma_name": "T.M. Opera O", "real_name": "T.M. Opera O",
        "emoji": "🎭", "born": "1996", "icon_url": "",
        "real_record": "14 JRA wins · 2000 Season: won 8 races including all 4 Classic races that year. One of the most dominant single-season performances in Japanese racing history.",
        "personality": "Theatrical, grandiose, and utterly convinced of his own magnificence — but the performance is backed up. He won nearly everything there was to win in his peak year.",
        "story_arc": "A character defined by sheer dominant spectacle. Her year 2000 campaign — winning almost everything — is the centrepiece of her story. Accompanied by her faithful fan Narita Top Road.",
        "fun_facts": [
            "In 2000 the real T.M. Opera O won 8 races — including the four major Classic-distance G1s — in a single calendar year. Almost impossibly dominant.",
            "His fans were nicknamed the 'Teio Army'.",
            "In-game she is dramatically theatrical, treating every race like an opera performance.",
            "Her relationship with Narita Top Road (her 'eternal fan') is a running comedy.",
            "Despite her arrogance, she genuinely earns the adoration — she's legitimately brilliant.",
        ],
        "lore_qa": {
            "2000 season": "The real T.M. Opera O's year 2000 is one of the great dominant seasons in world horse racing: 8 wins from 8 starts, including the Tenno Sho Spring, Takarazuka Kinen, Tenno Sho Autumn, and Japan Cup. It's the centrepiece of her in-game story.",
            "theatrical": "She's written as treating every race like an opera performance — grand gestures, dramatic declarations, absolute confidence. The fact that she actually backs it up makes it entertaining rather than annoying.",
            "narita top road": "Narita Top Road is essentially T.M. Opera O's devoted supporter in-game — following her around, cheering her on, being in awe of her. It's played for comedy.",
            "dominance": "Her peak year is genuinely historic. Winning 8 races in one year including multiple Classic G1s is extraordinary even by the standards of the best horses.",
            "personality": "Theatrical, confident, and genuinely talented. Her arrogance is presented as earned — she really is as good as she thinks she is.",
            "skill": "Built for mid-distance to long-distance turf dominance — reflecting her real 2000m-2400m peak. High stamina and race-controlling skills.",
        },
    },
    "smart falcon": {
        "uma_name": "Smart Falcon", "real_name": "Smart Falcon",
        "emoji": "🏜️", "born": "2005", "icon_url": "",
        "real_record": "22 wins including 7 JRA G1s on dirt. The greatest dirt specialist in Japanese racing history. Undefeated in all his dirt G1 starts.",
        "personality": "Stoic and proud. As the queen of dirt racing in a world that glamorises turf, she's had to fight for recognition — and that struggle has given her an unshakeable toughness.",
        "story_arc": "Her story explores the underappreciated excellence of dirt racing in a sport dominated by turf prestige. She's the best at what she does — she just has to make the world notice.",
        "fun_facts": [
            "The real Smart Falcon went undefeated in dirt G1 races in Japan — 7 wins, 7 starts.",
            "22 career wins total — one of the most prolific winners in Japanese racing history.",
            "Dirt racing in Japan is generally considered less prestigious than turf — Smart Falcon dominated despite this prejudice.",
            "In-game she is one of the most powerful dirt specialists available to players.",
            "Her undefeated G1 record on dirt is one of the great untouchable records in Japanese racing.",
        ],
        "lore_qa": {
            "dirt": "Smart Falcon is Japan's greatest dirt specialist — she dominated dirt G1 racing in a way no other horse has. The in-game story explores what it means to be brilliant at something the establishment doesn't fully value.",
            "undefeated": "The real Smart Falcon was undefeated across 7 dirt G1 starts. 7 for 7 at the highest level of Japanese dirt racing is an extraordinary record.",
            "prestige": "Dirt racing in Japan sits in turf racing's shadow — the big classic races are all on turf. Smart Falcon's story is partly about earning respect despite this bias.",
            "personality": "Tough, proud, and quietly intense. She doesn't need applause — she just needs to run. Her stoicism comes from years of racing in a discipline that doesn't get the spotlight it deserves.",
            "skill": "Dirt-specific skills — she's the in-game dirt queen. Her builds are exclusively optimised for dirt-surface racing, where she outperforms nearly everyone.",
        },
    },
}


def find_umamusume(horse_name: str) -> dict | None:
    """
    Return the Umamusume character dict if `horse_name` matches a real horse
    in UMAMUSUME_DATA (case-insensitive, partial match allowed).
    Returns None if no match.
    """
    query = horse_name.lower().strip()
    # Exact match first
    if query in UMAMUSUME_DATA:
        return UMAMUSUME_DATA[query]
    # Partial match — query is substring of key
    for key, data in UMAMUSUME_DATA.items():
        if query in key or key in query:
            return data
    return None


def answer_umamusume_lore(data: dict, question: str) -> str:
    """
    Keyword-match `question` against the character's lore_qa dict.
    Returns the best matching answer, or a helpful fallback listing topics.
    """
    q = question.lower()
    lore_qa: dict = data.get("lore_qa", {})

    # Score each key by how many of its words appear in the question
    best_key = None
    best_score = 0
    for key in lore_qa:
        score = sum(1 for word in key.split() if word in q)
        if score > best_score or (score == best_score and key in q):
            best_score = score
            best_key = key
        if key in q:            # exact phrase match — highest priority
            best_key = key
            break

    if best_key and best_score > 0:
        return lore_qa[best_key]

    # Fallback: list available topics
    topics = ", ".join(f"`{k}`" for k in lore_qa)
    return (
        f"I don't have a specific answer for that, but I know about: {topics}.\n"
        f"Try asking about one of those topics!"
    )


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("horse-racing-bot")

# ── Intents ───────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True        # needed to resolve users who react
intents.reactions = True      # needed for on_raw_reaction_add/remove

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ── Known Upcoming G1 Races (extend this list as needed) ─────────────────────
# Format: { name, date (UTC), track, country, purse }
# Update this list regularly or pull from an API/scrape source.

KNOWN_G1_RACES: list[dict] = [
    {
        "name": "Preakness Stakes",
        "date": datetime(2025, 5, 17, 23, 50, tzinfo=timezone.utc),
        "track": "Pimlico Race Course",
        "country": "USA",
        "purse": "$2,000,000",
        "distance": "1-3/16 miles",
    },
    {
        "name": "Belmont Stakes",
        "date": datetime(2025, 6, 7, 23, 45, tzinfo=timezone.utc),
        "track": "Belmont Park",
        "country": "USA",
        "purse": "$1,500,000",
        "distance": "1-1/2 miles",
    },
    {
        "name": "Royal Ascot - Gold Cup",
        "date": datetime(2025, 6, 19, 15, 45, tzinfo=timezone.utc),
        "track": "Ascot Racecourse",
        "country": "UK",
        "purse": "£625,000",
        "distance": "2-1/2 miles",
    },
    {
        "name": "King George VI & Queen Elizabeth Stakes",
        "date": datetime(2025, 7, 26, 15, 35, tzinfo=timezone.utc),
        "track": "Ascot Racecourse",
        "country": "UK",
        "purse": "£1,350,000",
        "distance": "1-1/2 miles",
    },
    {
        "name": "Breeders' Cup Classic",
        "date": datetime(2025, 11, 1, 23, 40, tzinfo=timezone.utc),
        "track": "Del Mar",
        "country": "USA",
        "purse": "$6,000,000",
        "distance": "1-1/4 miles",
    },
    {
        "name": "Arc de Triomphe",
        "date": datetime(2025, 10, 5, 15, 5, tzinfo=timezone.utc),
        "track": "ParisLongchamp",
        "country": "France",
        "purse": "€5,000,000",
        "distance": "2,400m",
    },
    {
        "name": "Japan Cup",
        "date": datetime(2025, 11, 30, 5, 40, tzinfo=timezone.utc),
        "track": "Tokyo Racecourse",
        "country": "Japan",
        "purse": "¥530,000,000",
        "distance": "2,400m",
    },
    {
        "name": "Melbourne Cup",
        "date": datetime(2025, 11, 4, 3, 0, tzinfo=timezone.utc),
        "track": "Flemington Racecourse",
        "country": "Australia",
        "purse": "AUD $8,000,000",
        "distance": "3,200m",
    },
    {
        "name": "Dubai World Cup",
        "date": datetime(2026, 3, 28, 19, 15, tzinfo=timezone.utc),
        "track": "Meydan Racecourse",
        "country": "UAE",
        "purse": "$12,000,000",
        "distance": "2,000m",
    },
    {
        "name": "Irish Derby",
        "date": datetime(2025, 6, 28, 16, 0, tzinfo=timezone.utc),
        "track": "The Curragh",
        "country": "Ireland",
        "purse": "€1,500,000",
        "distance": "1-1/2 miles",
    },
    {
        "name": "Irish Champion Stakes",
        "date": datetime(2025, 9, 13, 15, 25, tzinfo=timezone.utc),
        "track": "Leopardstown",
        "country": "Ireland",
        "purse": "€1,500,000",
        "distance": "1-1/4 miles",
    },
    {
        "name": "Hong Kong Cup",
        "date": datetime(2025, 12, 14, 9, 30, tzinfo=timezone.utc),
        "track": "Sha Tin Racecourse",
        "country": "Hong Kong",
        "purse": "HK$28,000,000",
        "distance": "2,000m",
    },
    {
        "name": "Hong Kong Mile",
        "date": datetime(2025, 12, 14, 8, 30, tzinfo=timezone.utc),
        "track": "Sha Tin Racecourse",
        "country": "Hong Kong",
        "purse": "HK$28,000,000",
        "distance": "1,600m",
    },
    {
        "name": "Queen's Plate",
        "date": datetime(2025, 8, 10, 18, 30, tzinfo=timezone.utc),
        "track": "Woodbine Racetrack",
        "country": "Canada",
        "purse": "CAD $1,000,000",
        "distance": "1-1/4 miles",
    },
    {
        "name": "Canadian International",
        "date": datetime(2025, 10, 19, 18, 0, tzinfo=timezone.utc),
        "track": "Woodbine Racetrack",
        "country": "Canada",
        "purse": "CAD $1,500,000",
        "distance": "1-1/2 miles",
    },
    {
        "name": "Grosser Preis von Baden",
        "date": datetime(2025, 8, 31, 14, 30, tzinfo=timezone.utc),
        "track": "Baden-Baden",
        "country": "Germany",
        "purse": "€500,000",
        "distance": "2,400m",
    },
    {
        "name": "Deutsches Derby",
        "date": datetime(2025, 7, 6, 14, 0, tzinfo=timezone.utc),
        "track": "Hamburg-Horn",
        "country": "Germany",
        "purse": "€750,000",
        "distance": "2,400m",
    },
    {
        "name": "Singapore Airlines International Cup",
        "date": datetime(2025, 5, 18, 10, 0, tzinfo=timezone.utc),
        "track": "Kranji Racecourse",
        "country": "Singapore",
        "purse": "S$3,000,000",
        "distance": "2,000m",
    },
    {
        "name": "Gran Premio di Milano",
        "date": datetime(2025, 6, 22, 14, 0, tzinfo=timezone.utc),
        "track": "Ippodromo del Galoppo",
        "country": "Italy",
        "purse": "€500,000",
        "distance": "2,400m",
    },
    {
        "name": "Saudi Cup",
        "date": datetime(2026, 2, 21, 18, 0, tzinfo=timezone.utc),
        "track": "King Abdulaziz Racecourse",
        "country": "Saudi Arabia",
        "purse": "$20,000,000",
        "distance": "1,800m",
    },
    {
        "name": "Vodacom Durban July",
        "date": datetime(2025, 7, 5, 13, 0, tzinfo=timezone.utc),
        "track": "Greyville Racecourse",
        "country": "South Africa",
        "purse": "R5,000,000",
        "distance": "2,200m",
    },
    {
        "name": "Gran Premio Nacional",
        "date": datetime(2025, 11, 2, 18, 0, tzinfo=timezone.utc),
        "track": "Hipódromo de Palermo",
        "country": "Argentina",
        "purse": "ARS $50,000,000",
        "distance": "2,500m",
    },
]

# ── Known G2 Races ─────────────────────────────────────────────────────────────
# Grade 2 races across major racing nations. Update dates each season as needed.

KNOWN_G2_RACES: list[dict] = [
    # USA
    {
        "name": "San Felipe Stakes",
        "date": datetime(2026, 3, 7, 22, 30, tzinfo=timezone.utc),
        "track": "Santa Anita Park",
        "country": "USA",
        "purse": "$400,000",
        "distance": "1-1/16 miles",
    },
    {
        "name": "Fountain of Youth Stakes",
        "date": datetime(2026, 3, 7, 21, 0, tzinfo=timezone.utc),
        "track": "Gulfstream Park",
        "country": "USA",
        "purse": "$400,000",
        "distance": "1-1/16 miles",
    },
    {
        "name": "Louisiana Derby",
        "date": datetime(2026, 3, 28, 21, 30, tzinfo=timezone.utc),
        "track": "Fair Grounds",
        "country": "USA",
        "purse": "$1,000,000",
        "distance": "1-3/16 miles",
    },
    {
        "name": "Wood Memorial",
        "date": datetime(2026, 4, 4, 18, 30, tzinfo=timezone.utc),
        "track": "Aqueduct Racetrack",
        "country": "USA",
        "purse": "$750,000",
        "distance": "1-1/8 miles",
    },
    {
        "name": "Rebel Stakes",
        "date": datetime(2026, 3, 14, 21, 30, tzinfo=timezone.utc),
        "track": "Oaklawn Park",
        "country": "USA",
        "purse": "$1,000,000",
        "distance": "1-1/16 miles",
    },
    {
        "name": "Champagne Stakes",
        "date": datetime(2025, 10, 4, 18, 0, tzinfo=timezone.utc),
        "track": "Belmont Park",
        "country": "USA",
        "purse": "$500,000",
        "distance": "1 mile",
    },
    {
        "name": "Beldame Stakes",
        "date": datetime(2025, 10, 4, 18, 45, tzinfo=timezone.utc),
        "track": "Belmont Park",
        "country": "USA",
        "purse": "$500,000",
        "distance": "1-1/8 miles",
    },
    # UK
    {
        "name": "Dante Stakes",
        "date": datetime(2026, 5, 14, 14, 35, tzinfo=timezone.utc),
        "track": "York Racecourse",
        "country": "UK",
        "purse": "£200,000",
        "distance": "1-1/4 miles",
    },
    {
        "name": "Lockinge Stakes",
        "date": datetime(2026, 5, 16, 15, 5, tzinfo=timezone.utc),
        "track": "Newbury Racecourse",
        "country": "UK",
        "purse": "£300,000",
        "distance": "1 mile",
    },
    {
        "name": "Hardwicke Stakes",
        "date": datetime(2026, 6, 20, 16, 0, tzinfo=timezone.utc),
        "track": "Royal Ascot",
        "country": "UK",
        "purse": "£300,000",
        "distance": "1-1/2 miles",
    },
    {
        "name": "Summer Mile",
        "date": datetime(2025, 7, 5, 15, 35, tzinfo=timezone.utc),
        "track": "Ascot Racecourse",
        "country": "UK",
        "purse": "£200,000",
        "distance": "1 mile",
    },
    # Ireland
    {
        "name": "Gallinule Stakes",
        "date": datetime(2026, 5, 17, 15, 30, tzinfo=timezone.utc),
        "track": "The Curragh",
        "country": "Ireland",
        "purse": "€75,000",
        "distance": "1-1/4 miles",
    },
    {
        "name": "Mooresbridge Stakes",
        "date": datetime(2026, 5, 4, 15, 0, tzinfo=timezone.utc),
        "track": "The Curragh",
        "country": "Ireland",
        "purse": "€75,000",
        "distance": "1-1/4 miles",
    },
    # France
    {
        "name": "Prix du Muguet",
        "date": datetime(2026, 5, 3, 14, 30, tzinfo=timezone.utc),
        "track": "Saint-Cloud",
        "country": "France",
        "purse": "€100,000",
        "distance": "1,600m",
    },
    {
        "name": "Prix Gontaut-Biron",
        "date": datetime(2025, 8, 14, 15, 0, tzinfo=timezone.utc),
        "track": "Deauville",
        "country": "France",
        "purse": "€100,000",
        "distance": "2,000m",
    },
    # Japan
    {
        "name": "Kyoto Kinen",
        "date": datetime(2026, 2, 22, 6, 25, tzinfo=timezone.utc),
        "track": "Kyoto Racecourse",
        "country": "Japan",
        "purse": "¥80,000,000",
        "distance": "2,200m",
    },
    {
        "name": "Nikkei Sho",
        "date": datetime(2026, 3, 28, 6, 45, tzinfo=timezone.utc),
        "track": "Nakayama Racecourse",
        "country": "Japan",
        "purse": "¥67,000,000",
        "distance": "2,500m",
    },
    # Australia
    {
        "name": "Hobartville Stakes",
        "date": datetime(2026, 2, 28, 5, 30, tzinfo=timezone.utc),
        "track": "Rosehill Gardens",
        "country": "Australia",
        "purse": "AUD $500,000",
        "distance": "1,400m",
    },
    {
        "name": "Peter Young Stakes",
        "date": datetime(2026, 2, 21, 5, 0, tzinfo=timezone.utc),
        "track": "Caulfield Racecourse",
        "country": "Australia",
        "purse": "AUD $500,000",
        "distance": "1,800m",
    },
    # Hong Kong
    {
        "name": "Chairman's Trophy",
        "date": datetime(2025, 11, 9, 8, 30, tzinfo=timezone.utc),
        "track": "Sha Tin Racecourse",
        "country": "Hong Kong",
        "purse": "HK$10,000,000",
        "distance": "1,600m",
    },
]

# ── Known G3 Races ─────────────────────────────────────────────────────────────
# Grade 3 races across major racing nations. Update dates each season as needed.

KNOWN_G3_RACES: list[dict] = [
    # USA
    {
        "name": "Holy Bull Stakes",
        "date": datetime(2026, 2, 7, 18, 30, tzinfo=timezone.utc),
        "track": "Gulfstream Park",
        "country": "USA",
        "purse": "$200,000",
        "distance": "1-1/16 miles",
    },
    {
        "name": "Risen Star Stakes",
        "date": datetime(2026, 2, 21, 19, 0, tzinfo=timezone.utc),
        "track": "Fair Grounds",
        "country": "USA",
        "purse": "$400,000",
        "distance": "1-1/16 miles",
    },
    {
        "name": "Jerome Stakes",
        "date": datetime(2026, 1, 1, 18, 0, tzinfo=timezone.utc),
        "track": "Aqueduct Racetrack",
        "country": "USA",
        "purse": "$150,000",
        "distance": "1 mile",
    },
    {
        "name": "Gotham Stakes",
        "date": datetime(2026, 3, 7, 18, 0, tzinfo=timezone.utc),
        "track": "Aqueduct Racetrack",
        "country": "USA",
        "purse": "$250,000",
        "distance": "1 mile",
    },
    {
        "name": "Hutcheson Stakes",
        "date": datetime(2026, 2, 7, 17, 30, tzinfo=timezone.utc),
        "track": "Gulfstream Park",
        "country": "USA",
        "purse": "$100,000",
        "distance": "7 furlongs",
    },
    {
        "name": "Spiral Stakes",
        "date": datetime(2026, 3, 28, 20, 0, tzinfo=timezone.utc),
        "track": "Turfway Park",
        "country": "USA",
        "purse": "$500,000",
        "distance": "1-1/8 miles",
    },
    # UK
    {
        "name": "Fred Darling Stakes",
        "date": datetime(2026, 4, 18, 14, 0, tzinfo=timezone.utc),
        "track": "Newbury Racecourse",
        "country": "UK",
        "purse": "£70,000",
        "distance": "7 furlongs",
    },
    {
        "name": "Brigadier Gerard Stakes",
        "date": datetime(2026, 5, 23, 15, 5, tzinfo=timezone.utc),
        "track": "Sandown Park",
        "country": "UK",
        "purse": "£100,000",
        "distance": "1-1/4 miles",
    },
    {
        "name": "Gordon Stakes",
        "date": datetime(2025, 7, 31, 15, 0, tzinfo=timezone.utc),
        "track": "Goodwood Racecourse",
        "country": "UK",
        "purse": "£75,000",
        "distance": "1-1/2 miles",
    },
    # Ireland
    {
        "name": "Alleged Stakes",
        "date": datetime(2025, 9, 14, 15, 45, tzinfo=timezone.utc),
        "track": "Leopardstown",
        "country": "Ireland",
        "purse": "€45,000",
        "distance": "1-1/2 miles",
    },
    {
        "name": "Round Tower Stakes",
        "date": datetime(2025, 9, 14, 14, 30, tzinfo=timezone.utc),
        "track": "The Curragh",
        "country": "Ireland",
        "purse": "€45,000",
        "distance": "6 furlongs",
    },
    # France
    {
        "name": "Prix de Barbeville",
        "date": datetime(2026, 4, 12, 14, 0, tzinfo=timezone.utc),
        "track": "Longchamp",
        "country": "France",
        "purse": "€80,000",
        "distance": "2,800m",
    },
    {
        "name": "Prix Corrida",
        "date": datetime(2026, 5, 17, 14, 30, tzinfo=timezone.utc),
        "track": "Saint-Cloud",
        "country": "France",
        "purse": "€75,000",
        "distance": "2,000m",
    },
    # Japan
    {
        "name": "Nakayama Gold Cup",
        "date": datetime(2026, 1, 17, 6, 30, tzinfo=timezone.utc),
        "track": "Nakayama Racecourse",
        "country": "Japan",
        "purse": "¥47,500,000",
        "distance": "2,000m",
    },
    {
        "name": "Kyoto Jubilee Stakes",
        "date": datetime(2026, 4, 12, 6, 25, tzinfo=timezone.utc),
        "track": "Kyoto Racecourse",
        "country": "Japan",
        "purse": "¥47,500,000",
        "distance": "2,200m",
    },
    # Australia
    {
        "name": "Autumn Classic",
        "date": datetime(2026, 3, 21, 5, 30, tzinfo=timezone.utc),
        "track": "Rosehill Gardens",
        "country": "Australia",
        "purse": "AUD $200,000",
        "distance": "2,000m",
    },
    # Germany
    {
        "name": "Grosser Preis der Wirtschaft",
        "date": datetime(2025, 7, 27, 14, 0, tzinfo=timezone.utc),
        "track": "Düsseldorf Racecourse",
        "country": "Germany",
        "purse": "€80,000",
        "distance": "2,400m",
    },
    # South Africa
    {
        "name": "Daily News 2000",
        "date": datetime(2025, 12, 27, 12, 0, tzinfo=timezone.utc),
        "track": "Greyville Racecourse",
        "country": "South Africa",
        "purse": "R1,000,000",
        "distance": "2,000m",
    },
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def format_countdown(dt: datetime) -> str:
    now = datetime.now(timezone.utc)
    delta = dt - now
    if delta.total_seconds() < 0:
        return "Race has already run"
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not days:
        parts.append(f"{seconds}s")
    return " ".join(parts)


COUNTRY_CHOICES = [
    app_commands.Choice(name="🌍 All Countries",   value="all"),
    app_commands.Choice(name="🇺🇸 USA",             value="USA"),
    app_commands.Choice(name="🇬🇧 UK",              value="UK"),
    app_commands.Choice(name="🇮🇪 Ireland",          value="Ireland"),
    app_commands.Choice(name="🇫🇷 France",           value="France"),
    app_commands.Choice(name="🇯🇵 Japan",            value="Japan"),
    app_commands.Choice(name="🇦🇺 Australia",        value="Australia"),
    app_commands.Choice(name="🇦🇪 UAE",              value="UAE"),
    app_commands.Choice(name="🇭🇰 Hong Kong",        value="Hong Kong"),
    app_commands.Choice(name="🇨🇦 Canada",           value="Canada"),
    app_commands.Choice(name="🇩🇪 Germany",          value="Germany"),
    app_commands.Choice(name="🇸🇬 Singapore",        value="Singapore"),
    app_commands.Choice(name="🇮🇹 Italy",            value="Italy"),
    app_commands.Choice(name="🇸🇦 Saudi Arabia",     value="Saudi Arabia"),
    app_commands.Choice(name="🇿🇦 South Africa",     value="South Africa"),
    app_commands.Choice(name="🇦🇷 Argentina",        value="Argentina"),
]


def _filter_races(races: list[dict], country: str = "all") -> list[dict]:
    now = datetime.now(timezone.utc)
    future = [r for r in races if r["date"] > now]
    if country and country.lower() != "all":
        future = [r for r in future if r["country"].lower() == country.lower()]
    return sorted(future, key=lambda r: r["date"])


def upcoming_g1s(limit: int = 10, country: str = "all") -> list[dict]:
    return _filter_races(KNOWN_G1_RACES, country)[:limit]


def upcoming_g2s(limit: int = 10, country: str = "all") -> list[dict]:
    return _filter_races(KNOWN_G2_RACES, country)[:limit]


def upcoming_g3s(limit: int = 10, country: str = "all") -> list[dict]:
    return _filter_races(KNOWN_G3_RACES, country)[:limit]


# ── Web fetching ──────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


async def fetch(url: str, session: aiohttp.ClientSession) -> str:
    async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        resp.raise_for_status()
        return await resp.text()


# ── News: Google News RSS (no API key required) ───────────────────────────────

async def search_racing_news(query: str = "G1 horse racing") -> list[dict]:
    """Return up to 8 news items from Google News RSS."""
    encoded = query.replace(" ", "+")
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(url)
    results = []
    for entry in feed.entries[:8]:
        results.append({
            "title": entry.get("title", "No title"),
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
            "source": entry.get("source", {}).get("title", "Unknown"),
        })
    return results


# ── Race Card: Equibase (US) ──────────────────────────────────────────────────

async def fetch_equibase_entries(track_code: str, date_str: str) -> list[dict]:
    """
    Scrape Equibase entries page for trainer/jockey/horse info.
    date_str format: YYYYMMDD
    track_code examples: CD (Churchill Downs), BEL (Belmont), PIM (Pimlico)

    Returns list of race dicts with horses, jockeys, trainers.
    """
    url = (
        f"https://www.equibase.com/static/entry/"
        f"{track_code}{date_str}USA.html"
    )
    races = []
    async with aiohttp.ClientSession() as session:
        try:
            html = await fetch(url, session)
        except Exception as e:
            log.warning(f"Equibase fetch failed: {e}")
            return []

    soup = BeautifulSoup(html, "html.parser")

    for race_section in soup.select("div.race-info"):
        race_num = race_section.select_one("h2, h3")
        race_name = race_num.get_text(strip=True) if race_num else "Race"

        horses = []
        for row in race_section.select("tr.entry-row, tr[class*='horse']"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            horses.append({
                "horse": cells[1].get_text(strip=True) if len(cells) > 1 else "—",
                "jockey": cells[2].get_text(strip=True) if len(cells) > 2 else "—",
                "trainer": cells[3].get_text(strip=True) if len(cells) > 3 else "—",
                "morning_line": cells[4].get_text(strip=True) if len(cells) > 4 else "—",
            })

        if horses:
            races.append({"race": race_name, "horses": horses})

    return races


# ── Race Card: Racing Post (UK/IRE/international) ─────────────────────────────

async def fetch_racingpost_card(date_str: str, track: str) -> list[dict]:
    """
    Scrape Racing Post race card.
    date_str: YYYY-MM-DD
    track: lowercase hyphenated, e.g. 'ascot', 'newmarket', 'cheltenham'

    Returns list of runner dicts with horse, jockey, trainer.
    """
    url = f"https://www.racingpost.com/racecards/{date_str}/{track}/results"
    runners = []
    async with aiohttp.ClientSession() as session:
        try:
            html = await fetch(url, session)
        except Exception as e:
            log.warning(f"Racing Post fetch failed: {e}")
            return []

    soup = BeautifulSoup(html, "html.parser")

    for card in soup.select("[data-test-id='RC-runnerRow'], .RC-runnerRow"):
        horse = card.select_one("[data-test-id='RC-runnerName'], .RC-runnerName")
        jockey = card.select_one("[data-test-id='RC-jockeyName'], .RC-jockeyName")
        trainer = card.select_one("[data-test-id='RC-trainerName'], .RC-trainerName")
        runners.append({
            "horse": horse.get_text(strip=True) if horse else "—",
            "jockey": jockey.get_text(strip=True) if jockey else "—",
            "trainer": trainer.get_text(strip=True) if trainer else "—",
        })

    return runners


# ── Results: Equibase (US) ───────────────────────────────────────────────────

async def fetch_results_equibase(track_code: str, date_str: str) -> list[dict]:
    """
    Scrape official race results from Equibase results page.
    track_code: CD, BEL, PIM, SA, etc.
    date_str: YYYYMMDD
    Returns list of race dicts: { race, starters, payouts }
    """
    url = (
        f"https://www.equibase.com/static/result/"
        f"{track_code}{date_str}USA.html"
    )
    races: list[dict] = []
    async with aiohttp.ClientSession() as session:
        try:
            html = await fetch(url, session)
        except Exception as e:
            log.warning(f"Equibase results fetch failed: {e}")
            return []

    soup = BeautifulSoup(html, "html.parser")

    for section in soup.select("div[id^='race'], div.race-results"):
        title_el = section.select_one("h2, h3, .race-title, .race-header")
        race_title = title_el.get_text(strip=True) if title_el else "Race"

        starters: list[dict] = []
        for row in section.select("tr.result-row, tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            starters.append({
                "finish":   cells[0].get_text(strip=True),
                "pp":       cells[1].get_text(strip=True) if len(cells) > 1 else "—",
                "horse":    cells[2].get_text(strip=True) if len(cells) > 2 else "—",
                "jockey":   cells[3].get_text(strip=True) if len(cells) > 3 else "—",
                "trainer":  cells[4].get_text(strip=True) if len(cells) > 4 else "—",
                "odds":     cells[5].get_text(strip=True) if len(cells) > 5 else "—",
                "time":     cells[6].get_text(strip=True) if len(cells) > 6 else "—",
            })

        payouts: list[dict] = []
        for row in section.select("tr.payout-row, .payouts tr"):
            cells = row.find_all("td")
            if len(cells) >= 2:
                payouts.append({
                    "bet":    cells[0].get_text(strip=True),
                    "horses": cells[1].get_text(strip=True) if len(cells) > 1 else "—",
                    "payout": cells[2].get_text(strip=True) if len(cells) > 2 else "—",
                })

        if starters:
            races.append({"race": race_title, "starters": starters, "payouts": payouts})

    return races


async def fetch_results_racingpost(date_str: str, track: str) -> list[dict]:
    """
    Scrape race results from Racing Post.
    date_str: YYYY-MM-DD   track: ascot, newmarket, etc.
    Returns list of runner result dicts.
    """
    url = f"https://www.racingpost.com/results/{date_str}/{track}/"
    runners: list[dict] = []
    async with aiohttp.ClientSession() as session:
        try:
            html = await fetch(url, session)
        except Exception as e:
            log.warning(f"Racing Post results fetch failed: {e}")
            return []

    soup = BeautifulSoup(html, "html.parser")

    for row in soup.select("[data-test-id='result-runner-row'], .ui-resultsTable-row"):
        pos     = row.select_one("[data-test-id='result-position'], .ui-resultsTable-position")
        horse   = row.select_one("[data-test-id='result-horse'], .ui-resultsTable-horse")
        jockey  = row.select_one("[data-test-id='result-jockey'], .ui-resultsTable-jockey")
        trainer = row.select_one("[data-test-id='result-trainer'], .ui-resultsTable-trainer")
        sp      = row.select_one("[data-test-id='result-sp'], .ui-resultsTable-sp")
        beaten  = row.select_one("[data-test-id='result-beaten'], .ui-resultsTable-beaten")

        runners.append({
            "finish":       pos.get_text(strip=True)     if pos     else "—",
            "horse":        horse.get_text(strip=True)   if horse   else "—",
            "jockey":       jockey.get_text(strip=True)  if jockey  else "—",
            "trainer":      trainer.get_text(strip=True) if trainer else "—",
            "sp_odds":      sp.get_text(strip=True)      if sp      else "—",
            "beaten_by":    beaten.get_text(strip=True)  if beaten  else "—",
        })

    return runners


# ── Odds: Equibase morning-line (US) ─────────────────────────────────────────

async def fetch_odds_equibase(track_code: str, date_str: str) -> list[dict]:
    """
    Scrape morning-line odds from Equibase entries page.
    track_code: e.g. CD, BEL, PIM, SA
    date_str: YYYYMMDD
    Returns list of race dicts: { race, runners: [{pp, horse, jockey, trainer, ml_odds}] }
    """
    url = (
        f"https://www.equibase.com/static/entry/"
        f"{track_code}{date_str}USA.html"
    )
    races: list[dict] = []
    async with aiohttp.ClientSession() as session:
        try:
            html = await fetch(url, session)
        except Exception as e:
            log.warning(f"Equibase odds fetch failed: {e}")
            return []

    soup = BeautifulSoup(html, "html.parser")

    # Equibase entry pages use a table per race; try multiple selector patterns
    for section in soup.select("div.race-nav ~ div, div[id^='race']"):
        race_title_el = section.select_one("h2, h3, .race-title, .race-header")
        race_title = race_title_el.get_text(strip=True) if race_title_el else "Race"

        runners: list[dict] = []
        for row in section.select("tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            # Column order in Equibase entry HTML: PP, Horse, Jockey, Trainer, Wt, ML
            runners.append({
                "pp":       cells[0].get_text(strip=True),
                "horse":    cells[1].get_text(strip=True) if len(cells) > 1 else "—",
                "jockey":   cells[2].get_text(strip=True) if len(cells) > 2 else "—",
                "trainer":  cells[3].get_text(strip=True) if len(cells) > 3 else "—",
                "weight":   cells[4].get_text(strip=True) if len(cells) > 4 else "—",
                "ml_odds":  cells[5].get_text(strip=True) if len(cells) > 5 else "—",
            })

        if runners:
            races.append({"race": race_title, "runners": runners})

    return races


# ── Odds: Racing Post SP / morning price (UK/IRE) ────────────────────────────

async def fetch_odds_racingpost(date_str: str, track: str) -> list[dict]:
    """
    Scrape Starting Price / morning odds from Racing Post racecard.
    date_str: YYYY-MM-DD   track: e.g. 'ascot', 'newmarket'
    Returns list of runner dicts: { horse, jockey, trainer, sp_odds, forecast_odds }
    """
    url = f"https://www.racingpost.com/racecards/{date_str}/{track}/"
    runners: list[dict] = []
    async with aiohttp.ClientSession() as session:
        try:
            html = await fetch(url, session)
        except Exception as e:
            log.warning(f"Racing Post odds fetch failed: {e}")
            return []

    soup = BeautifulSoup(html, "html.parser")

    for row in soup.select("[data-test-id='RC-runnerRow'], .RC-runnerRow"):
        horse   = row.select_one("[data-test-id='RC-runnerName'], .RC-runnerName")
        jockey  = row.select_one("[data-test-id='RC-jockeyName'], .RC-jockeyName")
        trainer = row.select_one("[data-test-id='RC-trainerName'], .RC-trainerName")
        sp      = row.select_one("[data-test-id='RC-sp'], .RC-sp, .RC-oddsButton")
        forecast= row.select_one("[data-test-id='RC-forecast'], .RC-forecast, .RC-forecastOdds")

        runners.append({
            "horse":          horse.get_text(strip=True)    if horse    else "—",
            "jockey":         jockey.get_text(strip=True)   if jockey   else "—",
            "trainer":        trainer.get_text(strip=True)  if trainer  else "—",
            "sp_odds":        sp.get_text(strip=True)       if sp       else "—",
            "forecast_odds":  forecast.get_text(strip=True) if forecast else "—",
        })

    return runners


# ── Odds: OddsChecker aggregator ─────────────────────────────────────────────

async def fetch_oddschecker(race_slug: str) -> list[dict]:
    """
    Scrape multi-bookmaker odds from OddsChecker for a given race slug.
    race_slug: URL path like 'horse-racing/2025-05-17-pimlico/preakness-stakes'
    Returns list of { horse, best_odds, bookmakers: [{name, odds}] }
    """
    url = f"https://www.oddschecker.com/{race_slug}"
    runners: list[dict] = []
    async with aiohttp.ClientSession() as session:
        try:
            html = await fetch(url, session)
        except Exception as e:
            log.warning(f"OddsChecker fetch failed: {e}")
            return []

    soup = BeautifulSoup(html, "html.parser")

    # OddsChecker renders a table: rows = runners, cols = bookmakers
    header_bms: list[str] = []
    for th in soup.select("thead th[data-bk]"):
        header_bms.append(th.get("data-bk", "?"))

    for row in soup.select("tbody tr[data-bname]"):
        horse_name = row.get("data-bname", "").strip()
        if not horse_name:
            continue

        book_odds: list[dict] = []
        best = "—"
        for td in row.select("td.bc"):
            bk   = td.get("data-bk", "?")
            odds = td.get_text(strip=True)
            if odds:
                book_odds.append({"bookmaker": bk, "odds": odds})
                best = odds  # last non-empty is usually best on right

        best_el = row.select_one(".best-oc-pays, .best-price")
        if best_el:
            best = best_el.get_text(strip=True)

        runners.append({
            "horse":        horse_name,
            "best_odds":    best,
            "bookmakers":   book_odds[:6],  # cap to avoid embed overflow
        })

    return runners


# ── Odds: convert fractional → implied probability ────────────────────────────

def fractional_to_prob(odds_str: str) -> str:
    """Convert '7/2' → '22.2%', '6-1' → '14.3%', '2.50' → '40.0%' (decimal). Returns '' on fail."""
    s = odds_str.strip().replace("-", "/")
    try:
        if "/" in s:
            num, den = s.split("/", 1)
            prob = float(den) / (float(num) + float(den)) * 100
            return f"{prob:.1f}%"
        f = float(s)
        if f > 1:
            return f"{100 / f:.1f}%"
    except (ValueError, ZeroDivisionError):
        pass
    return ""


# ── Horse History: Equibase (US) ──────────────────────────────────────────────

async def search_equibase_horse(name: str) -> str | None:
    """
    Search Equibase for a horse by name and return the profile URL, or None.
    """
    encoded = name.replace(" ", "+")
    url = (
        "https://www.equibase.com/profiles/Results.cfm"
        f"?type=Horse&searchType=H&queryBy=Name&horseName={encoded}"
    )
    async with aiohttp.ClientSession() as session:
        try:
            html = await fetch(url, session)
        except Exception as e:
            log.warning(f"Equibase horse search failed for '{name}': {e}")
            return None

    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one("table.table a[href*='Results.cfm']")
    if link:
        href = link.get("href", "")
        if href.startswith("/"):
            return "https://www.equibase.com" + href
        return href
    return None


async def fetch_horse_history_equibase(name: str) -> dict:
    """
    Fetch recent race results for a US horse from Equibase.
    Returns a dict with 'name', 'url', 'races' (list of result dicts), and 'stats'.
    """
    profile_url = await search_equibase_horse(name)
    races: list[dict] = []

    if profile_url:
        async with aiohttp.ClientSession() as session:
            try:
                html = await fetch(profile_url, session)
            except Exception as e:
                log.warning(f"Equibase profile fetch failed: {e}")
                html = ""

        soup = BeautifulSoup(html, "html.parser")
        for row in soup.select("table.table tbody tr")[:20]:
            cells = row.find_all("td")
            if len(cells) < 6:
                continue
            races.append({
                "date":      cells[0].get_text(strip=True),
                "track":     cells[1].get_text(strip=True),
                "race":      cells[2].get_text(strip=True),
                "distance":  cells[3].get_text(strip=True),
                "finish":    cells[4].get_text(strip=True),
                "surface":   cells[5].get_text(strip=True) if len(cells) > 5 else "—",
                "class":     cells[6].get_text(strip=True) if len(cells) > 6 else "—",
            })

    stats = _compute_stats(races)
    return {"name": name, "url": profile_url or "", "races": races, "stats": stats}


# ── Horse History: Racing Post (UK/IRE/International) ─────────────────────────

async def fetch_horse_history_racingpost(name: str) -> dict:
    """
    Fetch recent results for a horse from Racing Post's form page.
    Returns a dict with 'name', 'url', 'races', and 'stats'.
    """
    slug = name.lower().replace(" ", "-")
    search_url = f"https://www.racingpost.com/profile/horse/0/{slug}/form"
    races: list[dict] = []
    found_url = ""

    async with aiohttp.ClientSession() as session:
        try:
            html = await fetch(search_url, session)
        except Exception as e:
            log.warning(f"Racing Post horse fetch failed for '{name}': {e}")
            html = ""

    if html:
        soup = BeautifulSoup(html, "html.parser")
        found_url = search_url

        for row in soup.select("[data-test-id='form-summary-row'], .ui-resultsTable-row")[:20]:
            date_el    = row.select_one("[data-test-id='form-date'], .ui-resultsTable-date")
            track_el   = row.select_one("[data-test-id='form-course'], .ui-resultsTable-course")
            finish_el  = row.select_one("[data-test-id='form-position'], .ui-resultsTable-position")
            dist_el    = row.select_one("[data-test-id='form-distance'], .ui-resultsTable-distance")
            class_el   = row.select_one("[data-test-id='form-class'], .ui-resultsTable-class")
            race_el    = row.select_one("[data-test-id='form-race-name'], .ui-resultsTable-raceName")

            races.append({
                "date":     date_el.get_text(strip=True)   if date_el   else "—",
                "track":    track_el.get_text(strip=True)  if track_el  else "—",
                "race":     race_el.get_text(strip=True)   if race_el   else "—",
                "distance": dist_el.get_text(strip=True)   if dist_el   else "—",
                "finish":   finish_el.get_text(strip=True) if finish_el else "—",
                "surface":  "Turf",
                "class":    class_el.get_text(strip=True)  if class_el  else "—",
            })

    stats = _compute_stats(races)
    return {"name": name, "url": found_url, "races": races, "stats": stats}


# ── Horse History: Google News supplement ─────────────────────────────────────

async def fetch_horse_news(name: str) -> list[dict]:
    """Pull up to 3 recent news articles about a horse from Google News RSS."""
    return await search_racing_news(f'"{name}" horse racing')


# ── Horse Profile: Equibase ───────────────────────────────────────────────────

async def fetch_horse_equibase(name: str) -> dict:
    """
    Search Equibase for a horse's profile page and scrape career stats.
    Returns a dict with keys: name, sire, dam, trainer, owner, color, sex, dob,
    starts, wins, places, shows, earnings, recent_races (list of dicts).
    """
    search_url = (
        f"https://www.equibase.com/profiles/Search.cfm"
        f"?search={name.replace(' ', '+')}&searchType=Horse"
    )
    profile: dict = {
        "name": name,
        "url": search_url,
        "photo_url": "",   # populated from Equibase profile page if found
        "sire": "—", "dam": "—", "trainer": "—", "owner": "—",
        "color": "—", "sex": "—", "dob": "—",
        "starts": "—", "wins": "—", "places": "—", "shows": "—",
        "earnings": "—",
        "recent_races": [],
    }

    async with aiohttp.ClientSession() as session:
        try:
            html = await fetch(search_url, session)
        except Exception as e:
            log.warning(f"Equibase horse search failed for '{name}': {e}")
            return profile

    soup = BeautifulSoup(html, "html.parser")

    # Equibase search results — first link is usually the exact match
    first_link = soup.select_one("a[href*='/profiles/Results.cfm']")
    if first_link:
        profile_path = first_link.get("href", "")
        profile_url = (
            profile_path if profile_path.startswith("http")
            else f"https://www.equibase.com{profile_path}"
        )
        profile["url"] = profile_url
        profile["name"] = first_link.get_text(strip=True) or name

        async with aiohttp.ClientSession() as session:
            try:
                profile_html = await fetch(profile_url, session)
            except Exception as e:
                log.warning(f"Equibase profile fetch failed: {e}")
                return profile

        psoup = BeautifulSoup(profile_html, "html.parser")

        # Basic info table
        for row in psoup.select("table tr, .profile-info tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            label = cells[0].get_text(strip=True).lower()
            value = cells[1].get_text(strip=True)
            if "sire" in label:
                profile["sire"] = value
            elif "dam" in label and "sire" not in label:
                profile["dam"] = value
            elif "trainer" in label:
                profile["trainer"] = value
            elif "owner" in label:
                profile["owner"] = value
            elif "color" in label or "colour" in label:
                profile["color"] = value
            elif "sex" in label or "gender" in label:
                profile["sex"] = value
            elif "foal" in label or "born" in label or "dob" in label:
                profile["dob"] = value

        # Career stats
        for row in psoup.select(".career-stats tr, table.stats tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            label = cells[0].get_text(strip=True).lower()
            if "total" in label or "career" in label or "life" in label:
                profile["starts"] = cells[1].get_text(strip=True)
                profile["wins"]   = cells[2].get_text(strip=True)
                profile["places"] = cells[3].get_text(strip=True) if len(cells) > 3 else "—"
                profile["shows"]  = cells[4].get_text(strip=True) if len(cells) > 4 else "—"
                profile["earnings"] = cells[5].get_text(strip=True) if len(cells) > 5 else "—"
                break

        # Horse photo (Equibase profile pages often include a headshot)
        photo_el = psoup.select_one(
            ".horse-image img, .profile-image img, "
            "img[alt*='horse'], img[alt*='Horse'], "
            ".profilePhoto img, #horsePhoto"
        )
        if photo_el:
            src = photo_el.get("src") or photo_el.get("data-src") or ""
            if src and not src.startswith("data:"):
                profile["photo_url"] = (
                    src if src.startswith("http")
                    else f"https://www.equibase.com{src}"
                )

        # Recent race lines
        for row in psoup.select("table.results tr, .form-table tr, tr.result-row"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            profile["recent_races"].append({
                "date":     cells[0].get_text(strip=True),
                "track":    cells[1].get_text(strip=True),
                "race":     cells[2].get_text(strip=True) if len(cells) > 2 else "—",
                "finish":   cells[3].get_text(strip=True) if len(cells) > 3 else "—",
                "distance": cells[4].get_text(strip=True) if len(cells) > 4 else "—",
                "odds":     cells[5].get_text(strip=True) if len(cells) > 5 else "—",
            })
        profile["recent_races"] = profile["recent_races"][:8]

    return profile


# ── Trainer Profile: Racing Post ──────────────────────────────────────────────

async def fetch_trainer_racingpost(name: str) -> dict:
    """
    Fetch a trainer's stats page from Racing Post.
    name: e.g. "Aidan O'Brien" or "Bob Baffert"
    Returns dict with keys: name, url, location, win_rate, current_season,
    career_wins, notable_wins (list), recent_winners (list), news (list).
    """
    slug = name.lower().strip().replace("'", "").replace(".", "").replace(" ", "-")
    profile_url = f"https://www.racingpost.com/trainers/{slug}"
    search_url  = f"https://www.racingpost.com/search#q={name.replace(' ', '+')}&section=trainer"

    profile: dict = {
        "name": name, "url": profile_url,
        "location": "—", "win_rate": "—", "current_season": "—",
        "career_wins": "—", "notable_wins": [], "recent_winners": [],
    }

    async with aiohttp.ClientSession() as session:
        try:
            html = await fetch(profile_url, session)
        except Exception as e:
            log.warning(f"Racing Post trainer fetch failed for '{name}': {e}")
            html = ""

    if html:
        soup = BeautifulSoup(html, "html.parser")

        # Location / stable
        loc_el = soup.select_one(".trainer-location, [data-test-id='trainer-location'], .RC-trainerLocation")
        if loc_el:
            profile["location"] = loc_el.get_text(strip=True)

        # Win rate / stats row
        for stat in soup.select(".stat-block, .RC-stat, [data-test-id='stat-block']"):
            label = stat.select_one(".stat-label, .RC-stat-label")
            value = stat.select_one(".stat-value, .RC-stat-value")
            if label and value:
                l = label.get_text(strip=True).lower()
                v = value.get_text(strip=True)
                if "win" in l and "%" in v:
                    profile["win_rate"] = v
                elif "season" in l or "year" in l:
                    profile["current_season"] = v
                elif "career" in l or "total" in l:
                    profile["career_wins"] = v

        # Notable / classic wins
        for el in soup.select(".notable-wins li, .classic-wins li, .big-race-win")[:6]:
            text = el.get_text(strip=True)
            if text:
                profile["notable_wins"].append(text)

        # Recent winners table
        for row in soup.select("table tr, .results-table tr")[:10]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            profile["recent_winners"].append({
                "date":  cells[0].get_text(strip=True),
                "horse": cells[1].get_text(strip=True),
                "race":  cells[2].get_text(strip=True) if len(cells) > 2 else "—",
                "track": cells[3].get_text(strip=True) if len(cells) > 3 else "—",
            })

    profile["news"] = await search_racing_news(f'"{name}" trainer horse racing')
    return profile


# ── Jockey Profile: Racing Post ───────────────────────────────────────────────

async def fetch_jockey_racingpost(name: str) -> dict:
    """
    Fetch a jockey's stats page from Racing Post.
    name: e.g. "Frankie Dettori" or "Irad Ortiz Jr."
    Returns dict with keys: name, url, nationality, win_rate, current_season,
    career_wins, notable_wins (list), recent_winners (list), news (list).
    """
    slug = name.lower().strip().replace("'", "").replace(".", "").replace(" ", "-")
    profile_url = f"https://www.racingpost.com/jockeys/{slug}"

    profile: dict = {
        "name": name, "url": profile_url,
        "nationality": "—", "win_rate": "—", "current_season": "—",
        "career_wins": "—", "notable_wins": [], "recent_winners": [],
    }

    async with aiohttp.ClientSession() as session:
        try:
            html = await fetch(profile_url, session)
        except Exception as e:
            log.warning(f"Racing Post jockey fetch failed for '{name}': {e}")
            html = ""

    if html:
        soup = BeautifulSoup(html, "html.parser")

        # Nationality / flag
        nat_el = soup.select_one(".jockey-nationality, [data-test-id='jockey-nationality'], .RC-nationality")
        if nat_el:
            profile["nationality"] = nat_el.get_text(strip=True)

        # Stats row (same structure as trainer page)
        for stat in soup.select(".stat-block, .RC-stat, [data-test-id='stat-block']"):
            label = stat.select_one(".stat-label, .RC-stat-label")
            value = stat.select_one(".stat-value, .RC-stat-value")
            if label and value:
                l = label.get_text(strip=True).lower()
                v = value.get_text(strip=True)
                if "win" in l and "%" in v:
                    profile["win_rate"] = v
                elif "season" in l or "year" in l:
                    profile["current_season"] = v
                elif "career" in l or "total" in l:
                    profile["career_wins"] = v

        # Notable rides / classic wins
        for el in soup.select(".notable-wins li, .classic-wins li, .big-race-win")[:6]:
            text = el.get_text(strip=True)
            if text:
                profile["notable_wins"].append(text)

        # Recent winners table
        for row in soup.select("table tr, .results-table tr")[:10]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            profile["recent_winners"].append({
                "date":  cells[0].get_text(strip=True),
                "horse": cells[1].get_text(strip=True),
                "race":  cells[2].get_text(strip=True) if len(cells) > 2 else "—",
                "track": cells[3].get_text(strip=True) if len(cells) > 3 else "—",
            })

    profile["news"] = await search_racing_news(f'"{name}" jockey horse racing')
    return profile


# ── Stats helper ──────────────────────────────────────────────────────────────

def _parse_finish(finish_str: str) -> int | None:
    """Convert a finishing position string like '1st', '2', 'PU', 'F' to int or None."""
    clean = finish_str.strip().lower().rstrip("stndrh")  # strip ordinal suffixes
    try:
        return int(clean)
    except ValueError:
        return None  # Non-finishers (PU, F, BD, etc.)


def _compute_stats(races: list[dict]) -> dict:
    """Compute win/place/show rates and average finish from a list of race dicts."""
    if not races:
        return {
            "total": 0, "wins": 0, "places": 0, "shows": 0,
            "win_pct": 0.0, "place_pct": 0.0, "avg_finish": None,
        }

    finishes = [_parse_finish(r["finish"]) for r in races]
    valid = [f for f in finishes if f is not None]
    total = len(races)
    wins   = sum(1 for f in valid if f == 1)
    places = sum(1 for f in valid if f <= 2)
    shows  = sum(1 for f in valid if f <= 3)
    avg    = round(sum(valid) / len(valid), 2) if valid else None

    return {
        "total":      total,
        "wins":       wins,
        "places":     places,
        "shows":      shows,
        "win_pct":    round(wins   / total * 100, 1) if total else 0.0,
        "place_pct":  round(places / total * 100, 1) if total else 0.0,
        "show_pct":   round(shows  / total * 100, 1) if total else 0.0,
        "avg_finish": avg,
    }


def _find_head_to_head(data_a: dict, data_b: dict) -> list[dict]:
    """
    Find races where both horses ran on the same date at the same track.
    Returns list of matchup dicts.
    """
    matchups = []
    index_b = {(r["date"], r["track"]): r for r in data_b["races"]}

    for race_a in data_a["races"]:
        key = (race_a["date"], race_a["track"])
        if key in index_b:
            race_b = index_b[key]
            finish_a = _parse_finish(race_a["finish"])
            finish_b = _parse_finish(race_b["finish"])
            winner = None
            if finish_a is not None and finish_b is not None:
                winner = data_a["name"] if finish_a < finish_b else data_b["name"]
            matchups.append({
                "date":    race_a["date"],
                "track":   race_a["track"],
                "race":    race_a.get("race", "—"),
                "finish_a": race_a["finish"],
                "finish_b": race_b["finish"],
                "winner":   winner,
            })

    return matchups


def _profile_to_compare_data(profile: dict) -> dict:
    """
    Convert a fetch_horse_equibase() full-profile result into the dict format
    that build_compare_embed() and _find_head_to_head() expect.

    This lets /compare work for ANY horse — active, retired, or deceased —
    because Equibase keeps career stats on every horse's profile page even
    after they stop racing.
    """
    def _safe_int(val) -> int:
        try:
            return int(str(val).replace(",", "").strip())
        except (ValueError, TypeError, AttributeError):
            return 0

    total  = _safe_int(profile.get("starts", 0))
    wins   = _safe_int(profile.get("wins", 0))
    places = _safe_int(profile.get("places", 0))
    shows  = _safe_int(profile.get("shows", 0))

    # If official career stats are present, use them directly.
    # Otherwise fall back to computing from scraped recent races.
    if total > 0:
        stats = {
            "total":      total,
            "wins":       wins,
            "places":     places,
            "shows":      shows,
            "win_pct":    round(wins   / total * 100, 1),
            "place_pct":  round(places / total * 100, 1),
            "show_pct":   round(shows  / total * 100, 1),
            "avg_finish": None,
        }
    else:
        recent = profile.get("recent_races", [])
        stats = _compute_stats(recent)

    return {
        "name":     profile.get("name", "Unknown"),
        "url":      profile.get("url", ""),
        "races":    profile.get("recent_races", []),
        "stats":    stats,
        # Extra fields surfaced in the enriched compare embed
        "sire":     profile.get("sire", "—"),
        "dam":      profile.get("dam", "—"),
        "dob":      profile.get("dob", "—"),
        "color":    profile.get("color", "—"),
        "sex":      profile.get("sex", "—"),
        "trainer":  profile.get("trainer", "—"),
        "owner":    profile.get("owner", "—"),
        "earnings": profile.get("earnings", "—"),
    }


# ── Image helpers ─────────────────────────────────────────────────────────────

def _image_for_race(name: str) -> str:
    """Return the best image URL for a race (custom dict → BOT_BANNER_URL)."""
    lower = name.lower()
    for key, url in RACE_IMAGES.items():
        if key.lower() in lower or lower in key.lower():
            return url
    return BOT_BANNER_URL


def _image_for_horse(name: str, scraped_url: str = "") -> str:
    """Return the best image URL for a horse (custom dict → scraped → empty)."""
    lower = name.lower()
    for key, url in HORSE_IMAGES.items():
        if key.lower() in lower or lower in key.lower():
            return url
    return scraped_url  # from Equibase profile page


def _image_for_person(name: str, images_dict: dict) -> str:
    """Return a custom image URL for a trainer or jockey (custom dict → BOT_BANNER_URL)."""
    lower = name.lower()
    for key, url in images_dict.items():
        if key.lower() in lower or lower in key.lower():
            return url
    return BOT_BANNER_URL


# ── Embeds ────────────────────────────────────────────────────────────────────

def build_g1_embed(race: dict, show_countdown: bool = True, grade: str = "G1") -> discord.Embed:
    dt: datetime = race["date"]
    unix_ts = int(dt.timestamp())

    grade_label = race.get("grade", grade)
    grade_colors = {
        "G1": discord.Color.gold(),
        "G2": discord.Color.from_rgb(192, 192, 192),   # silver
        "G3": discord.Color.from_rgb(180, 110, 50),    # bronze
    }
    grade_emoji = {"G1": "🥇", "G2": "🥈", "G3": "🥉"}.get(grade_label, "🏇")
    color = grade_colors.get(grade_label, discord.Color.gold())

    embed = discord.Embed(
        title=f"{grade_emoji} [{grade_label}] {race['name']}",
        color=color,
    )
    embed.add_field(name="📍 Track", value=f"{race['track']}, {race['country']}", inline=True)
    embed.add_field(name="📏 Distance", value=race.get("distance", "—"), inline=True)
    embed.add_field(name="💰 Purse", value=race.get("purse", "—"), inline=True)
    embed.add_field(
        name="📅 Date/Time",
        value=f"<t:{unix_ts}:F> (<t:{unix_ts}:R>)",
        inline=False,
    )
    if show_countdown:
        embed.add_field(name="⏱️ Countdown", value=format_countdown(dt), inline=False)
    img = _image_for_race(race["name"])
    if img:
        embed.set_image(url=img)
    embed.set_footer(text="Times shown in your local timezone via Discord timestamps")
    return embed


def build_runners_embed(race_name: str, runners: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title=f"🐎 Runners — {race_name}",
        color=discord.Color.blue(),
    )
    if not runners:
        embed.description = "No runner data found. The race card may not be published yet."
        return embed

    table_lines = [f"`{'#':>2}` `{'Horse':<22}` `{'Jockey':<20}` `{'Trainer':<20}`"]
    table_lines.append("─" * 70)
    for i, r in enumerate(runners, 1):
        table_lines.append(
            f"`{i:>2}` `{r['horse'][:22]:<22}` `{r['jockey'][:20]:<20}` `{r['trainer'][:20]:<20}`"
        )

    embed.description = "\n".join(table_lines)
    return embed


def _medal(pos: str) -> str:
    clean = pos.strip().lower().rstrip("stndrh")
    return {"1": "🥇", "2": "🥈", "3": "🥉"}.get(clean, "  ")


def build_results_embed_equibase(
    track: str, date: str, races: list[dict], race_name_filter: str = ""
) -> list[discord.Embed]:
    """
    Build result embeds from Equibase data.
    race_name_filter: if set, only include races whose title contains this string (case-insensitive).
    """
    embeds: list[discord.Embed] = []
    filtered = [
        r for r in races
        if not race_name_filter or race_name_filter.lower() in r["race"].lower()
    ] or races  # fall back to all if filter matches nothing

    for race in filtered[:5]:
        embed = discord.Embed(
            title=f"🏁 Official Result — {race['race']}",
            description=f"**{track.upper()}** · {date}  ·  Source: Equibase",
            color=discord.Color.dark_green(),
            timestamp=datetime.now(timezone.utc),
        )

        # Finishing order table
        lines = ["`Fin` `PP` `Horse                 ` `Jockey              ` `Odds   ` `Time`"]
        lines.append("─" * 80)
        for s in race.get("starters", [])[:12]:
            medal = _medal(s["finish"])
            lines.append(
                f"`{s['finish'][:3]:<3}` "
                f"`{s['pp']:<2}` "
                f"{medal} `{s['horse'][:22]:<22}` "
                f"`{s['jockey'][:20]:<20}` "
                f"`{s['odds'][:7]:<7}` "
                f"`{s['time']}`"
            )
        embed.description = (embed.description or "") + "\n\n" + "\n".join(lines)

        # Payouts
        if race.get("payouts"):
            payout_lines = []
            for p in race["payouts"][:6]:
                payout_lines.append(f"**{p['bet']}** — {p['horses']} → **{p['payout']}**")
            embed.add_field(
                name="💵 Payouts",
                value="\n".join(payout_lines),
                inline=False,
            )

        embed.set_footer(text="Official result · Equibase")
        embeds.append(embed)

    if not embeds:
        embeds.append(discord.Embed(
            title="🏁 Results Not Yet Available",
            description=(
                "Results not yet posted for this race/track/date. "
                "They typically appear within 10–15 minutes of the finish."
            ),
            color=discord.Color.orange(),
        ))
    return embeds


def build_results_embed_racingpost(
    track: str, date: str, runners: list[dict], race_name: str = ""
) -> discord.Embed:
    title = f"🏁 Official Result — {race_name or track.title()}"
    embed = discord.Embed(
        title=title,
        description=f"**{track.title()}** · {date}  ·  Source: Racing Post",
        color=discord.Color.dark_green(),
        timestamp=datetime.now(timezone.utc),
    )
    if not runners:
        embed.description = (
            "Results not yet posted. They typically appear within 10–15 minutes of the finish."
        )
        return embed

    lines = ["`Fin` `Horse                 ` `Jockey              ` `SP     ` `Beaten`"]
    lines.append("─" * 76)
    for r in runners[:12]:
        medal = _medal(r["finish"])
        lines.append(
            f"`{r['finish'][:3]:<3}` "
            f"{medal} `{r['horse'][:22]:<22}` "
            f"`{r['jockey'][:20]:<20}` "
            f"`{r['sp_odds'][:7]:<7}` "
            f"`{r['beaten_by'][:6]}`"
        )
    embed.description = (embed.description or "") + "\n\n" + "\n".join(lines)
    embed.set_footer(text="Official result · Racing Post")
    return embed


def build_g1_result_autopost_embed(race: dict, starters: list[dict]) -> discord.Embed:
    """Compact embed used for the automatic post-race result announcement."""
    winner = next((s for s in starters if _medal(s.get("finish", "")) == "🥇"), None)
    second = next((s for s in starters if _medal(s.get("finish", "")) == "🥈"), None)
    third  = next((s for s in starters if _medal(s.get("finish", "")) == "🥉"), None)

    embed = discord.Embed(
        title=f"🏆 RESULT — {race['name']}",
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="📍 Track", value=f"{race['track']}, {race['country']}", inline=True)
    embed.add_field(name="💰 Purse", value=race.get("purse", "—"), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer

    def fmt(s: dict | None, medal: str) -> str:
        if not s:
            return "—"
        return (
            f"{medal} **{s.get('horse', s.get('horse', '—'))}**\n"
            f"Jockey: {s.get('jockey', '—')}  ·  Trainer: {s.get('trainer', '—')}\n"
            f"Odds: {s.get('odds', s.get('sp_odds', '—'))}  ·  Time: {s.get('time', '—')}"
        )

    embed.add_field(name="1st Place", value=fmt(winner, "🥇"), inline=False)
    embed.add_field(name="2nd Place", value=fmt(second, "🥈"), inline=False)
    embed.add_field(name="3rd Place", value=fmt(third,  "🥉"), inline=False)
    embed.set_footer(text="Results auto-posted after race completion")
    return embed


def build_odds_embed_equibase(track: str, date: str, races: list[dict]) -> list[discord.Embed]:
    embeds: list[discord.Embed] = []
    for race in races[:5]:
        embed = discord.Embed(
            title=f"💰 Morning-Line Odds — {race['race']}",
            description=f"**{track.upper()}** · {date}  ·  Source: Equibase",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        lines = ["`PP` `Horse                 ` `ML Odds` `Impl%`"]
        lines.append("─" * 54)
        for r in race.get("runners", []):
            prob = fractional_to_prob(r["ml_odds"])
            lines.append(
                f"`{r['pp']:<2}` "
                f"`{r['horse'][:22]:<22}` "
                f"`{r['ml_odds']:<7}` "
                f"`{prob:<5}`"
            )
        embed.description = (embed.description or "") + "\n\n" + "\n".join(lines)
        embed.set_footer(text="Morning-line = trainer/track estimate before wagering opens")
        embeds.append(embed)
    return embeds if embeds else [discord.Embed(
        title="💰 No Odds Found",
        description="Race card not yet published or track code not recognised.",
        color=discord.Color.red(),
    )]


def build_odds_embed_racingpost(track: str, date: str, runners: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title=f"💰 Race Odds — {track.title()} · {date}",
        description="Source: Racing Post  ·  SP = Starting Price  ·  FC = Forecast",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )
    if not runners:
        embed.description = "No odds data found. Card may not be published yet."
        return embed
    lines = ["`Horse                 ` `SP      ` `Forecast` `Impl%`"]
    lines.append("─" * 58)
    for r in runners:
        odds_str = r["sp_odds"] if r["sp_odds"] != "—" else r["forecast_odds"]
        prob = fractional_to_prob(odds_str)
        lines.append(
            f"`{r['horse'][:22]:<22}` "
            f"`{r['sp_odds'][:8]:<8}` "
            f"`{r['forecast_odds'][:8]:<8}` "
            f"`{prob:<5}`"
        )
    embed.description = (embed.description or "") + "\n\n" + "\n".join(lines)
    embed.set_footer(text="SP shown after race; Forecast = pre-race estimate")
    return embed


def build_odds_embed_oddschecker(race_slug: str, runners: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="💰 Multi-Bookie Odds Comparison",
        description=f"OddsChecker · `{race_slug}`",
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc),
    )
    if not runners:
        embed.description = "No odds data found. Check the race slug and try again."
        return embed

    lines = ["`Horse                 ` `Best  ` `Impl%` `Books`"]
    lines.append("─" * 56)
    for r in runners[:15]:
        prob = fractional_to_prob(r["best_odds"])
        books_preview = "  ".join(
            f"{b['bookmaker']}:{b['odds']}" for b in r["bookmakers"][:3]
        )
        lines.append(
            f"`{r['horse'][:22]:<22}` "
            f"`{r['best_odds'][:6]:<6}` "
            f"`{prob:<5}` "
            f"{books_preview}"
        )
    embed.description = (embed.description or "") + "\n\n" + "\n".join(lines)
    embed.set_footer(text="Best odds across bookmakers · implied probability shown")
    return embed


def build_compare_embed(
    data_a: dict,
    data_b: dict,
    matchups: list[dict],
) -> list[discord.Embed]:
    """
    Return a list of embeds: profile summary + career stats + form table + H2H detail.
    Works for active, retired, and deceased horses — uses official Equibase career data
    when available, so the stats card is never blank even with no recent races.
    """
    sa = data_a["stats"]
    sb = data_b["stats"]
    name_a = data_a["name"]
    name_b = data_b["name"]

    def bar(pct: float, width: int = 10) -> str:
        filled = round(pct / 100 * width)
        return "█" * filled + "░" * (width - filled)

    def winner_marker(val_a, val_b, higher_is_better: bool = True) -> tuple[str, str]:
        if val_a is None or val_b is None:
            return "—", "—"
        a_wins = (val_a > val_b) if higher_is_better else (val_a < val_b)
        b_wins = (val_b > val_a) if higher_is_better else (val_b < val_a)
        return ("✅" if a_wins else ("🔴" if b_wins else "🟡")), \
               ("✅" if b_wins else ("🔴" if a_wins else "🟡"))

    # ── Profile card embed ──────────────────────────────────────────────────────
    profile_embed = discord.Embed(
        title=f"⚔️ Head-to-Head: {name_a} vs {name_b}",
        color=discord.Color.purple(),
        timestamp=datetime.now(timezone.utc),
    )

    def _profile_block(data: dict) -> str:
        lines = []
        if data.get("dob") and data["dob"] != "—":
            lines.append(f"📅 Born: **{data['dob']}**")
        if data.get("color") and data["color"] != "—":
            sex_color = data["color"]
            if data.get("sex") and data["sex"] != "—":
                sex_color += f" {data['sex']}"
            lines.append(f"🎨 {sex_color}")
        if data.get("sire") and data["sire"] != "—":
            lines.append(f"🧬 Sire: **{data['sire']}**")
        if data.get("dam") and data["dam"] != "—":
            lines.append(f"🐴 Dam: **{data['dam']}**")
        if data.get("trainer") and data["trainer"] != "—":
            lines.append(f"🎩 Trainer: {data['trainer']}")
        if data.get("owner") and data["owner"] != "—":
            lines.append(f"👑 Owner: {data['owner']}")
        if data.get("earnings") and data["earnings"] != "—":
            lines.append(f"💰 Career earnings: **{data['earnings']}**")
        return "\n".join(lines) if lines else "*(no profile data available)*"

    profile_embed.add_field(name=f"📄 {name_a}", value=_profile_block(data_a), inline=True)
    profile_embed.add_field(name=f"📄 {name_b}", value=_profile_block(data_b), inline=True)

    profile_links = []
    if data_a.get("url"):
        profile_links.append(f"[{name_a} on Equibase]({data_a['url']})")
    if data_b.get("url"):
        profile_links.append(f"[{name_b} on Equibase]({data_b['url']})")
    if profile_links:
        profile_embed.add_field(name="🔗 Full Profiles", value=" · ".join(profile_links), inline=False)
    profile_embed.set_footer(text="Career stats sourced from Equibase — includes retired and deceased horses")

    # ── Career stats embed ──────────────────────────────────────────────────────
    stats_embed = discord.Embed(
        title=f"📊 Career Statistics",
        color=discord.Color.purple(),
    )

    m_a, m_b = winner_marker(sa["win_pct"], sb["win_pct"])
    stats_embed.add_field(
        name=f"🏇 {name_a}",
        value=(
            f"Starts: **{sa['total']}**\n"
            f"Wins: **{sa['wins']}** ({sa['win_pct']}%) {m_a}\n"
            f"Top-2: **{sa['places']}** ({sa['place_pct']}%)\n"
            f"Top-3: **{sa['shows']}** ({sa.get('show_pct', 0.0)}%)\n"
            f"{bar(sa['win_pct'])} win rate"
        ),
        inline=True,
    )
    stats_embed.add_field(
        name=f"🏇 {name_b}",
        value=(
            f"Starts: **{sb['total']}**\n"
            f"Wins: **{sb['wins']}** ({sb['win_pct']}%) {m_b}\n"
            f"Top-2: **{sb['places']}** ({sb['place_pct']}%)\n"
            f"Top-3: **{sb['shows']}** ({sb.get('show_pct', 0.0)}%)\n"
            f"{bar(sb['win_pct'])} win rate"
        ),
        inline=True,
    )

    # Direct meetings summary in stats embed
    if matchups:
        a_h2h_wins = sum(1 for m in matchups if m["winner"] == name_a)
        b_h2h_wins = sum(1 for m in matchups if m["winner"] == name_b)
        stats_embed.add_field(
            name=f"🥊 Direct Meetings ({len(matchups)} race{'s' if len(matchups) != 1 else ''})",
            value=(
                f"**{name_a}** won {a_h2h_wins}  |  "
                f"**{name_b}** won {b_h2h_wins}"
            ),
            inline=False,
        )
    else:
        stats_embed.add_field(
            name="🥊 Direct Meetings",
            value="No shared races found in available history.",
            inline=False,
        )

    embeds = [profile_embed, stats_embed]

    # ── Recent form tables (only if races are available) ────────────────────────
    def recent_form_embed(data: dict) -> discord.Embed | None:
        races = data.get("races", [])
        if not races:
            return None
        embed = discord.Embed(
            title=f"📋 Recent Form — {data['name']}",
            color=discord.Color.blurple(),
        )
        lines = ["`Date       ` `Track     ` `Fin` `Distance ` `Class    `"]
        lines.append("─" * 62)
        for r in races[:10]:
            fin = r.get("finish", "—")
            marker = "🥇" if fin in ("1", "1st") else ("🥈" if fin in ("2", "2nd") else ("🥉" if fin in ("3", "3rd") else "  "))
            lines.append(
                f"`{str(r.get('date', '—'))[:10]:<10}` "
                f"`{str(r.get('track', '—'))[:10]:<10}` "
                f"`{str(fin)[:3]:<3}` {marker} "
                f"`{str(r.get('distance', '—'))[:8]:<8}` "
                f"`{str(r.get('class', '—'))[:9]:<9}`"
            )
        embed.description = "\n".join(lines)
        return embed

    for fe in (recent_form_embed(data_a), recent_form_embed(data_b)):
        if fe:
            embeds.append(fe)

    # ── Head-to-head matchup detail ─────────────────────────────────────────────
    if matchups:
        h2h_embed = discord.Embed(
            title="🏁 Direct Matchup Results",
            color=discord.Color.orange(),
        )
        lines = []
        for m in matchups[:8]:
            win_tag = f"→ **{m['winner']}** wins" if m["winner"] else "→ Tie / DNF"
            lines.append(
                f"**{m['date']}** @ {m['track']} — {m.get('race', '')}\n"
                f"  {name_a}: **{m['finish_a']}**  |  {name_b}: **{m['finish_b']}**  {win_tag}\n"
            )
        h2h_embed.description = "\n".join(lines) if lines else "No direct meetings found."
        embeds.append(h2h_embed)

    return embeds


def build_horse_embed(data: dict) -> discord.Embed:
    """Profile card for a single horse using Equibase data."""
    embed = discord.Embed(
        title=f"🐴 {data['name']}",
        url=data.get("url", ""),
        color=discord.Color.dark_green(),
        timestamp=datetime.now(timezone.utc),
    )

    # Image: custom dict first, then Equibase scraped photo, then nothing
    img = _image_for_horse(data["name"], data.get("photo_url", ""))
    if img:
        embed.set_image(url=img)

    # Bloodline
    embed.add_field(name="🧬 Sire",   value=data["sire"],  inline=True)
    embed.add_field(name="🧬 Dam",    value=data["dam"],   inline=True)
    embed.add_field(name="🎂 Born",   value=data["dob"],   inline=True)

    # Physical
    embed.add_field(name="🎨 Color/Sex", value=f"{data['color']} / {data['sex']}", inline=True)
    embed.add_field(name="👤 Trainer",   value=data["trainer"],  inline=True)
    embed.add_field(name="🏠 Owner",     value=data["owner"],    inline=True)

    # Career stats
    starts   = data.get("starts", "—")
    wins     = data.get("wins", "—")
    places   = data.get("places", "—")
    shows    = data.get("shows", "—")
    earnings = data.get("earnings", "—")
    embed.add_field(
        name="📊 Career Record",
        value=(
            f"Starts: **{starts}**  |  Wins: **{wins}**  |  "
            f"2nd: **{places}**  |  3rd: **{shows}**\n"
            f"💰 Earnings: **{earnings}**"
        ),
        inline=False,
    )

    # Recent races
    races = data.get("recent_races", [])
    if races:
        lines = ["`Date      ` `Track     ` `Fin` `Distance ` `Odds`"]
        lines.append("─" * 55)
        for r in races[:6]:
            fin = r["finish"]
            medal = (
                "🥇" if fin in ("1", "1st") else
                "🥈" if fin in ("2", "2nd") else
                "🥉" if fin in ("3", "3rd") else "  "
            )
            lines.append(
                f"`{r['date'][:10]:<10}` "
                f"`{r['track'][:10]:<10}` "
                f"`{fin[:3]:<3}` {medal} "
                f"`{r['distance'][:8]:<8}` "
                f"`{r['odds'][:6]:<6}`"
            )
        embed.add_field(name="📋 Recent Races", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="📋 Recent Races", value="No recent races found.", inline=False)

    embed.set_footer(text="Source: Equibase  ·  /horse <name>")
    return embed


def build_trainer_embed(data: dict) -> list[discord.Embed]:
    """Profile + recent winners + news for a trainer from Racing Post."""
    profile = discord.Embed(
        title=f"🎩 Trainer — {data['name']}",
        url=data.get("url", ""),
        color=discord.Color.purple(),
        timestamp=datetime.now(timezone.utc),
    )

    img = _image_for_person(data["name"], TRAINER_IMAGES)
    if img:
        profile.set_thumbnail(url=img)

    profile.add_field(name="📍 Location",      value=data["location"],        inline=True)
    profile.add_field(name="📈 Win Rate",       value=data["win_rate"],        inline=True)
    profile.add_field(name="🏆 Career Wins",    value=data["career_wins"],     inline=True)
    profile.add_field(name="📅 Current Season", value=data["current_season"],  inline=True)

    if data["notable_wins"]:
        profile.add_field(
            name="🌟 Notable Wins",
            value="\n".join(f"• {w}" for w in data["notable_wins"][:5]),
            inline=False,
        )

    winners = data.get("recent_winners", [])
    if winners:
        lines = ["`Date      ` `Horse          ` `Race                ` `Track`"]
        lines.append("─" * 65)
        for w in winners[:8]:
            lines.append(
                f"`{w['date'][:10]:<10}` "
                f"`{w['horse'][:15]:<15}` "
                f"`{w['race'][:20]:<20}` "
                f"`{w['track'][:10]:<10}`"
            )
        profile.add_field(name="🏅 Recent Winners", value="\n".join(lines), inline=False)
    else:
        profile.add_field(name="🏅 Recent Winners", value="No recent winners found.", inline=False)

    profile.set_footer(text="Source: Racing Post  ·  /trainer <name>")
    embeds = [profile]

    # News embed
    articles = data.get("news", [])
    if articles:
        news_embed = discord.Embed(
            title=f"📰 News — {data['name']}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        for a in articles[:4]:
            pub = a.get("published", "")[:16]
            news_embed.add_field(
                name=f"{a['source']} — {pub}",
                value=f"[{a['title'][:200]}]({a['link']})",
                inline=False,
            )
        embeds.append(news_embed)

    return embeds


def build_jockey_embed(data: dict) -> list[discord.Embed]:
    """Profile + recent winners + news for a jockey from Racing Post."""
    profile = discord.Embed(
        title=f"🏇 Jockey — {data['name']}",
        url=data.get("url", ""),
        color=discord.Color.teal(),
        timestamp=datetime.now(timezone.utc),
    )

    img = _image_for_person(data["name"], JOCKEY_IMAGES)
    if img:
        profile.set_thumbnail(url=img)

    profile.add_field(name="🌍 Nationality",   value=data["nationality"],     inline=True)
    profile.add_field(name="📈 Win Rate",       value=data["win_rate"],        inline=True)
    profile.add_field(name="🏆 Career Wins",    value=data["career_wins"],     inline=True)
    profile.add_field(name="📅 Current Season", value=data["current_season"],  inline=True)

    if data["notable_wins"]:
        profile.add_field(
            name="🌟 Notable Rides",
            value="\n".join(f"• {w}" for w in data["notable_wins"][:5]),
            inline=False,
        )

    winners = data.get("recent_winners", [])
    if winners:
        lines = ["`Date      ` `Horse          ` `Race                ` `Track`"]
        lines.append("─" * 65)
        for w in winners[:8]:
            lines.append(
                f"`{w['date'][:10]:<10}` "
                f"`{w['horse'][:15]:<15}` "
                f"`{w['race'][:20]:<20}` "
                f"`{w['track'][:10]:<10}`"
            )
        profile.add_field(name="🏅 Recent Winners", value="\n".join(lines), inline=False)
    else:
        profile.add_field(name="🏅 Recent Winners", value="No recent winners found.", inline=False)

    profile.set_footer(text="Source: Racing Post  ·  /jockey <name>")
    embeds = [profile]

    # News embed
    articles = data.get("news", [])
    if articles:
        news_embed = discord.Embed(
            title=f"📰 News — {data['name']}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        for a in articles[:4]:
            pub = a.get("published", "")[:16]
            news_embed.add_field(
                name=f"{a['source']} — {pub}",
                value=f"[{a['title'][:200]}]({a['link']})",
                inline=False,
            )
        embeds.append(news_embed)

    return embeds


def build_news_embed(query: str, articles: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title=f"📰 Horse Racing News: {query}",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )
    if not articles:
        embed.description = "No news found for that query."
        return embed

    for article in articles[:6]:
        pub = article.get("published", "")[:16]
        embed.add_field(
            name=f"{article['source']} — {pub}",
            value=f"[{article['title'][:200]}]({article['link']})",
            inline=False,
        )
    return embed


# ── Slash Commands ────────────────────────────────────────────────────────────

@tree.command(name="upcoming", description="List G1 races happening in the next 7 days")
@app_commands.describe(
    country="Filter by country (default: all)",
    limit="Number of races to show (default 5, max 10)",
)
@app_commands.choices(country=COUNTRY_CHOICES)
async def cmd_upcoming(
    interaction: discord.Interaction,
    country: app_commands.Choice[str] = None,
    limit: int = 5,
):
    await interaction.response.defer()
    limit = min(max(limit, 1), 10)
    country_val = country.value if country else "all"

    now = datetime.now(timezone.utc)
    week_ahead = now + timedelta(days=7)
    races = [
        r for r in KNOWN_G1_RACES
        if now < r["date"] <= week_ahead
        and (country_val == "all" or r["country"].lower() == country_val.lower())
    ]
    races = sorted(races, key=lambda r: r["date"])[:limit]

    country_label = country.name if country and country_val != "all" else "all countries"

    if not races:
        next_races = upcoming_g1s(1, country=country_val)
        if next_races:
            next_race = next_races[0]
            unix_ts = int(next_race["date"].timestamp())
            await interaction.followup.send(
                f"No G1 races in the next 7 days for **{country_label}**.\n"
                f"The next {next_race['country']} race is **{next_race['name']}** — "
                f"<t:{unix_ts}:F> (<t:{unix_ts}:R>)\n"
                f"Use `/g1 name:{next_race['name'].split()[0].lower()}` for full details."
            )
        else:
            await interaction.followup.send(
                f"No upcoming G1 races found for **{country_label}**.\n"
                "Try a different country or use `/upcoming` with no filter to see all."
            )
        return

    embeds = [build_g1_embed(r) for r in races]
    await interaction.followup.send(
        content=f"**{len(races)} G1 race(s) in the next 7 days** ({country_label}) — times in your local timezone:",
        embeds=embeds[:5],
    )
    if len(embeds) > 5:
        await interaction.followup.send(embeds=embeds[5:])


@tree.command(name="g1", description="Show details and countdown for a specific G1 race")
@app_commands.describe(
    name="Partial name of the G1 race (leave blank to list by country)",
    country="Filter by country",
)
@app_commands.choices(country=COUNTRY_CHOICES)
async def cmd_g1(
    interaction: discord.Interaction,
    name: str = "",
    country: app_commands.Choice[str] = None,
):
    await interaction.response.defer()
    country_val = country.value if country else "all"

    pool = KNOWN_G1_RACES
    if country_val != "all":
        pool = [r for r in pool if r["country"].lower() == country_val.lower()]

    if name:
        query = name.lower()
        matches = [r for r in pool if query in r["name"].lower()]
    else:
        now = datetime.now(timezone.utc)
        matches = sorted([r for r in pool if r["date"] > now], key=lambda r: r["date"])[:5]

    if not matches:
        country_hint = f" in **{country.name}**" if country and country_val != "all" else ""
        await interaction.followup.send(
            f"No G1 race found matching **{name or '(any)'}**{country_hint}.\n"
            "Use `/upcoming` to see all scheduled races."
        )
        return

    embeds = [build_g1_embed(r, grade="G1") for r in matches[:5]]
    await interaction.followup.send(embeds=embeds)


@tree.command(name="g2", description="Show details and countdown for Grade 2 races")
@app_commands.describe(
    name="Partial name of the G2 race (leave blank to list upcoming by country)",
    country="Filter by country",
)
@app_commands.choices(country=COUNTRY_CHOICES)
async def cmd_g2(
    interaction: discord.Interaction,
    name: str = "",
    country: app_commands.Choice[str] = None,
):
    await interaction.response.defer()
    country_val = country.value if country else "all"

    pool = KNOWN_G2_RACES
    if country_val != "all":
        pool = [r for r in pool if r["country"].lower() == country_val.lower()]

    if name:
        query = name.lower()
        matches = [r for r in pool if query in r["name"].lower()]
    else:
        now = datetime.now(timezone.utc)
        matches = sorted([r for r in pool if r["date"] > now], key=lambda r: r["date"])[:5]

    if not matches:
        country_hint = f" in **{country.name}**" if country and country_val != "all" else ""
        await interaction.followup.send(
            f"No G2 race found matching **{name or '(any)'}**{country_hint}.\n"
            "Try `/upcoming` or check the race name spelling."
        )
        return

    embeds = [build_g1_embed(r, grade="G2") for r in matches[:5]]
    await interaction.followup.send(embeds=embeds)

    # If a specific race was searched by name, also pull news for it
    if name and matches:
        race_name = matches[0]["name"]
        news = await fetch_horse_news(f"{race_name} horse racing G2")
        if news:
            await interaction.followup.send(embed=build_news_embed(race_name, news[:4]))


@tree.command(name="g3", description="Show details and countdown for Grade 3 races")
@app_commands.describe(
    name="Partial name of the G3 race (leave blank to list upcoming by country)",
    country="Filter by country",
)
@app_commands.choices(country=COUNTRY_CHOICES)
async def cmd_g3(
    interaction: discord.Interaction,
    name: str = "",
    country: app_commands.Choice[str] = None,
):
    await interaction.response.defer()
    country_val = country.value if country else "all"

    pool = KNOWN_G3_RACES
    if country_val != "all":
        pool = [r for r in pool if r["country"].lower() == country_val.lower()]

    if name:
        query = name.lower()
        matches = [r for r in pool if query in r["name"].lower()]
    else:
        now = datetime.now(timezone.utc)
        matches = sorted([r for r in pool if r["date"] > now], key=lambda r: r["date"])[:5]

    if not matches:
        country_hint = f" in **{country.name}**" if country and country_val != "all" else ""
        await interaction.followup.send(
            f"No G3 race found matching **{name or '(any)'}**{country_hint}.\n"
            "Try `/upcoming` or check the race name spelling."
        )
        return

    embeds = [build_g1_embed(r, grade="G3") for r in matches[:5]]
    await interaction.followup.send(embeds=embeds)

    # If a specific race was searched by name, also pull news for it
    if name and matches:
        race_name = matches[0]["name"]
        news = await fetch_horse_news(f"{race_name} horse racing G3")
        if news:
            await interaction.followup.send(embed=build_news_embed(race_name, news[:4]))


@tree.command(name="runners", description="Show horses, jockeys and trainers for a race")
@app_commands.describe(
    source="Data source: 'equibase' (US) or 'racingpost' (UK/IRE)",
    track="Track code (Equibase: CD, BEL, PIM) or slug (Racing Post: ascot, newmarket)",
    date="Date in YYYYMMDD (Equibase) or YYYY-MM-DD (Racing Post) format. Default: today",
)
async def cmd_runners(
    interaction: discord.Interaction,
    source: str,
    track: str,
    date: str = "",
):
    await interaction.response.defer()

    source = source.lower().strip()
    if not date:
        today = datetime.now(timezone.utc)
        date = today.strftime("%Y%m%d") if source == "equibase" else today.strftime("%Y-%m-%d")

    await interaction.followup.send(
        f"⏳ Fetching race card from **{source}** for **{track}** on **{date}**..."
    )

    if source == "equibase":
        races = await fetch_equibase_entries(track_code=track.upper(), date_str=date)
        if not races:
            await interaction.followup.send(
                "Could not retrieve race card from Equibase. "
                "Check the track code and date, or try again later."
            )
            return
        for race_info in races[:5]:
            embed = build_runners_embed(race_info["race"], race_info["horses"])
            await interaction.followup.send(embed=embed)

    elif source == "racingpost":
        runners = await fetch_racingpost_card(date_str=date, track=track.lower())
        embed = build_runners_embed(f"{track.title()} — {date}", runners)
        await interaction.followup.send(embed=embed)

    else:
        await interaction.followup.send(
            "Unknown source. Use `equibase` for US races or `racingpost` for UK/IRE."
        )


@tree.command(name="news", description="Search for the latest horse racing news")
@app_commands.describe(query="Search term (default: 'G1 horse racing')")
async def cmd_news(interaction: discord.Interaction, query: str = "G1 horse racing"):
    await interaction.response.defer()
    articles = await search_racing_news(query)
    embed = build_news_embed(query, articles)
    await interaction.followup.send(embed=embed)


@tree.command(name="countdown", description="Live countdown timer for a G1 race")
@app_commands.describe(
    name="Partial race name to get countdown for",
    country="Narrow your search by country",
)
@app_commands.choices(country=COUNTRY_CHOICES)
async def cmd_countdown(
    interaction: discord.Interaction,
    name: str,
    country: app_commands.Choice[str] = None,
):
    await interaction.response.defer()
    country_val = country.value if country else "all"
    query = name.lower()
    pool = KNOWN_G1_RACES if country_val == "all" else [
        r for r in KNOWN_G1_RACES if r["country"].lower() == country_val.lower()
    ]
    matches = [r for r in pool if query in r["name"].lower()]

    if not matches:
        country_hint = f" in **{country.name}**" if country and country_val != "all" else ""
        await interaction.followup.send(f"No G1 race found matching **{name}**{country_hint}.")
        return

    race = matches[0]
    dt = race["date"]
    unix_ts = int(dt.timestamp())

    embed = discord.Embed(
        title=f"⏱️ Countdown — {race['name']}",
        color=discord.Color.gold(),
    )
    embed.add_field(name="📍 Track", value=f"{race['track']}, {race['country']}", inline=True)
    embed.add_field(name="💰 Purse", value=race.get("purse", "—"), inline=True)
    embed.add_field(
        name="🏁 Post Time",
        value=f"<t:{unix_ts}:F>",
        inline=False,
    )
    embed.add_field(
        name="⏳ Time Remaining",
        value=f"<t:{unix_ts}:R>",
        inline=False,
    )
    embed.set_footer(text="Discord auto-updates the relative timestamp for you!")
    await interaction.followup.send(embed=embed)


@tree.command(name="compare", description="Head-to-head stats between two horses")
@app_commands.describe(
    horse_a="Full name of the first horse",
    horse_b="Full name of the second horse",
    source="Data source: 'equibase' (US, default) or 'racingpost' (UK/IRE/international)",
)
async def cmd_compare(
    interaction: discord.Interaction,
    horse_a: str,
    horse_b: str,
    source: str = "equibase",
):
    await interaction.response.defer()
    source = source.lower().strip()

    await interaction.followup.send(
        f"⏳ Searching Equibase for **{horse_a}** and **{horse_b}**…\n"
        "This works for active, retired, and deceased horses. May take a few seconds."
    )

    # Always use the full Equibase profile (fetch_horse_equibase) rather than
    # the history-only scraper — the profile page carries official career stats
    # even for retired/deceased horses that have no recent entries.
    raw_a, raw_b = await asyncio.gather(
        fetch_horse_equibase(horse_a),
        fetch_horse_equibase(horse_b),
    )

    data_a = _profile_to_compare_data(raw_a)
    data_b = _profile_to_compare_data(raw_b)
    matchups = _find_head_to_head(data_a, data_b)

    embeds = build_compare_embed(data_a, data_b, matchups)

    # Discord allows max 10 embeds per message — send in batches
    for i in range(0, len(embeds), 5):
        await interaction.followup.send(embeds=embeds[i : i + 5])

    # Pull recent news for both horses
    news_a, news_b = await asyncio.gather(
        fetch_horse_news(horse_a), fetch_horse_news(horse_b)
    )
    if news_a:
        await interaction.followup.send(embed=build_news_embed(horse_a, news_a[:3]))
    if news_b:
        await interaction.followup.send(embed=build_news_embed(horse_b, news_b[:3]))


@tree.command(name="odds", description="Current odds for a race (morning-line or multi-bookie)")
@app_commands.describe(
    source=(
        "Where to pull odds: 'equibase' (US morning-line), "
        "'racingpost' (UK/IRE SP/forecast), 'oddschecker' (multi-bookie comparison)"
    ),
    track=(
        "Track code for equibase (CD, BEL, PIM, SA) or "
        "track slug for racingpost (ascot, newmarket) or "
        "OddsChecker race slug (horse-racing/2025-05-17-pimlico/preakness-stakes)"
    ),
    date="Date — YYYYMMDD for equibase, YYYY-MM-DD for racingpost. Default: today",
)
async def cmd_odds(
    interaction: discord.Interaction,
    source: str,
    track: str,
    date: str = "",
):
    await interaction.response.defer()
    source = source.lower().strip()
    today = datetime.now(timezone.utc)

    if source == "equibase":
        date_str = date or today.strftime("%Y%m%d")
        await interaction.followup.send(
            f"⏳ Fetching morning-line odds from **Equibase** for **{track.upper()}** on **{date_str}**…"
        )
        races = await fetch_odds_equibase(track_code=track.upper(), date_str=date_str)
        embeds = build_odds_embed_equibase(track, date_str, races)
        for i in range(0, len(embeds), 5):
            await interaction.followup.send(embeds=embeds[i : i + 5])

    elif source == "racingpost":
        date_str = date or today.strftime("%Y-%m-%d")
        await interaction.followup.send(
            f"⏳ Fetching odds from **Racing Post** for **{track.title()}** on **{date_str}**…"
        )
        runners = await fetch_odds_racingpost(date_str=date_str, track=track.lower())
        embed = build_odds_embed_racingpost(track, date_str, runners)
        await interaction.followup.send(embed=embed)

    elif source == "oddschecker":
        # track arg doubles as the full OddsChecker race slug
        await interaction.followup.send(
            f"⏳ Fetching multi-bookie odds from **OddsChecker** for `{track}`…"
        )
        runners = await fetch_oddschecker(race_slug=track)
        embed = build_odds_embed_oddschecker(track, runners)
        await interaction.followup.send(embed=embed)

    else:
        await interaction.followup.send(
            "Unknown source. Choose one of: `equibase`, `racingpost`, `oddschecker`\n"
            "Examples:\n"
            "• `/odds source:equibase track:PIM date:20250517`\n"
            "• `/odds source:racingpost track:ascot date:2025-06-19`\n"
            "• `/odds source:oddschecker track:horse-racing/2025-05-17-pimlico/preakness-stakes`"
        )


@tree.command(name="result", description="Official finishing order and payouts for a completed race")
@app_commands.describe(
    source="Data source: 'equibase' (US) or 'racingpost' (UK/IRE)",
    track="Track code (Equibase: CD/BEL/PIM) or slug (Racing Post: ascot/newmarket)",
    date="Date — YYYYMMDD for equibase, YYYY-MM-DD for racingpost. Default: today",
    race="Optional: filter to a specific race name (e.g. 'Preakness')",
)
async def cmd_result(
    interaction: discord.Interaction,
    source: str,
    track: str,
    date: str = "",
    race: str = "",
):
    await interaction.response.defer()
    source = source.lower().strip()
    today = datetime.now(timezone.utc)

    if source == "equibase":
        date_str = date or today.strftime("%Y%m%d")
        await interaction.followup.send(
            f"⏳ Fetching results from **Equibase** for **{track.upper()}** on **{date_str}**…"
        )
        races = await fetch_results_equibase(track_code=track.upper(), date_str=date_str)
        embeds = build_results_embed_equibase(track, date_str, races, race_name_filter=race)
        for i in range(0, len(embeds), 5):
            await interaction.followup.send(embeds=embeds[i : i + 5])

    elif source == "racingpost":
        date_str = date or today.strftime("%Y-%m-%d")
        await interaction.followup.send(
            f"⏳ Fetching results from **Racing Post** for **{track.title()}** on **{date_str}**…"
        )
        runners = await fetch_results_racingpost(date_str=date_str, track=track.lower())
        embed = build_results_embed_racingpost(track, date_str, runners, race_name=race)
        await interaction.followup.send(embed=embed)

    else:
        await interaction.followup.send(
            "Unknown source. Use `equibase` (US) or `racingpost` (UK/IRE).\n"
            "Examples:\n"
            "• `/result source:equibase track:PIM date:20250517 race:Preakness`\n"
            "• `/result source:racingpost track:ascot date:2025-06-19`"
        )


@tree.command(name="horse", description="Full profile, career stats and recent form for a horse (Equibase)")
@app_commands.describe(name="Horse's registered name, e.g. 'Justify' or 'Enable'")
async def cmd_horse(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    await interaction.followup.send(f"⏳ Looking up **{name}** on Equibase…")
    data = await fetch_horse_equibase(name)

    embed = build_horse_embed(data)

    # Pull recent news in parallel
    news = await fetch_horse_news(name)
    embeds_to_send = [embed]

    if news:
        news_embed = discord.Embed(
            title=f"📰 News — {data['name']}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        for a in news[:4]:
            pub = a.get("published", "")[:16]
            news_embed.add_field(
                name=f"{a['source']} — {pub}",
                value=f"[{a['title'][:200]}]({a['link']})",
                inline=False,
            )
        embeds_to_send.append(news_embed)

    await interaction.followup.send(embeds=embeds_to_send)

    # ── Umamusume: Pretty Derby crossover check ────────────────────────────────
    uma = find_umamusume(name)
    if uma:
        teaser = discord.Embed(
            title=f"{uma['emoji']}  {uma['uma_name']} — Umamusume: Pretty Derby",
            description=(
                f"**{data['name']}** has an Umamusume: Pretty Derby counterpart character!\n\n"
                f"{uma['personality']}"
            ),
            color=discord.Color.from_rgb(255, 182, 193),
        )
        teaser.add_field(
            name="🏆 Real Racing Record",
            value=uma["real_record"],
            inline=False,
        )
        teaser.add_field(
            name="📖 Story Arc",
            value=uma["story_arc"],
            inline=False,
        )
        teaser.add_field(
            name="✨ Fun Facts",
            value="\n".join(f"• {f}" for f in uma["fun_facts"][:3]),
            inline=False,
        )
        teaser.set_footer(
            text=f"Use /umamusume name:{name} to get the full character profile and ask lore questions!"
        )
        if uma.get("icon_url"):
            teaser.set_thumbnail(url=uma["icon_url"])
        await interaction.followup.send(embed=teaser)


@tree.command(name="trainer", description="Career stats and recent winners for a trainer (Racing Post)")
@app_commands.describe(name="Trainer's full name, e.g. \"Aidan O'Brien\" or 'Bob Baffert'")
async def cmd_trainer(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    await interaction.followup.send(f"⏳ Looking up trainer **{name}** on Racing Post…")
    data = await fetch_trainer_racingpost(name)
    embeds = build_trainer_embed(data)
    for i in range(0, len(embeds), 5):
        await interaction.followup.send(embeds=embeds[i : i + 5])


@tree.command(name="jockey", description="Career stats and recent winners for a jockey (Racing Post)")
@app_commands.describe(name="Jockey's full name, e.g. 'Frankie Dettori' or 'Irad Ortiz Jr'")
async def cmd_jockey(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    await interaction.followup.send(f"⏳ Looking up jockey **{name}** on Racing Post…")
    data = await fetch_jockey_racingpost(name)
    embeds = build_jockey_embed(data)
    for i in range(0, len(embeds), 5):
        await interaction.followup.send(embeds=embeds[i : i + 5])


@tree.command(name="umamusume", description="Look up an Umamusume: Pretty Derby character and ask lore questions")
@app_commands.describe(
    name="Real horse name or Uma Musume character name (e.g. 'Special Week', 'Gold Ship')",
    question="Optional: ask a lore question about this character (e.g. 'Who is her rival?')",
)
async def cmd_umamusume(interaction: discord.Interaction, name: str, question: str = ""):
    await interaction.response.defer()

    uma = find_umamusume(name)
    if not uma:
        known = ", ".join(f"**{v['uma_name']}**" for v in list(UMAMUSUME_DATA.values())[:10])
        await interaction.followup.send(
            f"No Umamusume character found matching **{name}**.\n\n"
            f"Some available characters: {known}, and more.\n"
            "Try the horse's registered name — e.g. `/umamusume name:gold ship`"
        )
        return

    # ── Main profile embed ────────────────────────────────────────────────────
    embed = discord.Embed(
        title=f"{uma['emoji']}  {uma['uma_name']}  —  Umamusume: Pretty Derby",
        description=uma["personality"],
        color=discord.Color.from_rgb(255, 182, 193),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="🐴 Real Horse", value=uma["real_name"], inline=True)
    embed.add_field(name="📅 Born", value=uma.get("born", "—"), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(
        name="🏆 Real Racing Record",
        value=uma["real_record"],
        inline=False,
    )
    embed.add_field(
        name="📖 Story Arc",
        value=uma["story_arc"],
        inline=False,
    )
    embed.add_field(
        name="✨ Fun Facts",
        value="\n".join(f"• {f}" for f in uma["fun_facts"]),
        inline=False,
    )

    topics = " · ".join(f"`{k}`" for k in uma.get("lore_qa", {}))
    embed.add_field(
        name="💬 Ask a Lore Question",
        value=f"Use `/umamusume name:{uma['real_name'].lower()} question:<your question>`\n"
              f"Topics I know about: {topics}",
        inline=False,
    )
    embed.set_footer(text="Data sourced from Umamusume: Pretty Derby by Cygames · For entertainment only")

    if uma.get("icon_url"):
        embed.set_thumbnail(url=uma["icon_url"])

    await interaction.followup.send(embed=embed)

    # ── Lore Q&A embed (if question provided) ─────────────────────────────────
    if question.strip():
        answer = answer_umamusume_lore(uma, question)
        qa_embed = discord.Embed(
            title=f"💬  Lore Q&A — {uma['uma_name']}",
            color=discord.Color.from_rgb(200, 150, 220),
        )
        qa_embed.add_field(name=f"❓ {question}", value=answer, inline=False)
        qa_embed.set_footer(text="Ask another question with /umamusume name:... question:...")
        await interaction.followup.send(embed=qa_embed)


# ── /setup ────────────────────────────────────────────────────────────────────

@tree.command(
    name="setup",
    description="Configure this server's alert/news channels (admin only)",
)
@app_commands.describe(
    channel_type='Choose what this channel is used for: "alerts" for G1 countdowns/results, "news" for hourly news, "view" to see current settings',
    channel="The channel to assign (leave blank with type=view)",
)
@app_commands.choices(
    channel_type=[
        app_commands.Choice(name="alerts — G1 countdowns, race-day pings & auto-results", value="alerts"),
        app_commands.Choice(name="news   — hourly G1 breaking news feed",                value="news"),
        app_commands.Choice(name="view   — show current settings for this server",        value="view"),
    ]
)
async def cmd_setup(
    interaction: discord.Interaction,
    channel_type: app_commands.Choice[str],
    channel: discord.TextChannel = None,
):
    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("❌ This command must be used inside a server.", ephemeral=True)
        return

    # View-only mode — no permission check needed
    if channel_type.value == "view":
        cfg = GUILD_CONFIG.get(guild.id, {})
        alerts_id = cfg.get("alerts_channel")
        news_id   = cfg.get("news_channel")
        alerts_str = f"<#{alerts_id}>" if alerts_id else "*(not set)*"
        news_str   = f"<#{news_id}>"   if news_id   else "*(not set)*"
        embed = discord.Embed(
            title="⚙️  Bot Channel Configuration",
            description=f"Current settings for **{guild.name}**",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="🏆 G1 Alerts channel",  value=alerts_str, inline=False)
        embed.add_field(name="📰 News feed channel",  value=news_str,   inline=False)
        embed.set_footer(text="Use /setup alerts/news to change these")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    # Setting a channel — requires Manage Guild permission
    member = interaction.user
    if not isinstance(member, discord.Member) or not member.guild_permissions.manage_guild:
        await interaction.followup.send(
            "❌ You need the **Manage Server** permission to change bot settings.",
            ephemeral=True,
        )
        return

    if channel is None:
        await interaction.followup.send(
            "❌ Please provide a channel. Example: `/setup channel_type:alerts channel:#general`",
            ephemeral=True,
        )
        return

    if guild.id not in GUILD_CONFIG:
        GUILD_CONFIG[guild.id] = {}

    field = "alerts_channel" if channel_type.value == "alerts" else "news_channel"
    GUILD_CONFIG[guild.id][field] = channel.id
    _save_guild_config()

    label = "G1 Alerts" if channel_type.value == "alerts" else "News Feed"
    embed = discord.Embed(
        title="✅  Channel Saved",
        description=f"**{label}** will now post to {channel.mention}.\n\nBackground tasks will pick it up on the next cycle.",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Use /setup view to confirm settings · /setup to change them again")
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="help", description="Show all available bot commands and what they do")
async def cmd_help(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    embed = discord.Embed(
        title="🏇 Horse Racing Bot — Command Reference",
        description="All commands use `/` in Discord. Click any command name to use it.",
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc),
    )

    embed.add_field(
        name="📅  Race Discovery",
        value=(
            "`/upcoming` — G1 races in the **next 7 days** · optional `country:` dropdown to filter\n"
            "`/g1` — Grade 1 details + countdown · browse by `country:` or search by `name:`\n"
            "`/g2` — Grade 2 details + countdown + race news · same `country:` / `name:` filters\n"
            "`/g3` — Grade 3 details + countdown + race news · same `country:` / `name:` filters\n"
            "`/countdown name:<race>` — Self-updating Discord timer · optional `country:` filter\n\n"
            "**Countries:** 🌍 All · 🇺🇸 USA · 🇬🇧 UK · 🇮🇪 Ireland · 🇫🇷 France · 🇯🇵 Japan · "
            "🇦🇺 Australia · 🇦🇪 UAE · 🇭🇰 Hong Kong · 🇨🇦 Canada · 🇩🇪 Germany · "
            "🇸🇬 Singapore · 🇮🇹 Italy · 🇸🇦 Saudi Arabia · 🇿🇦 South Africa · 🇦🇷 Argentina"
        ),
        inline=False,
    )

    embed.add_field(
        name="🐎  Race Day",
        value=(
            "`/runners source:<source> track:<track> date:<date>` — Full race card (horses, jockeys, trainers)\n"
            "`/odds source:<source> track:<track>` — Morning-line or multi-bookie odds for a race\n"
            "`/result source:<source> track:<track> date:<date>` — Official finishing order + payouts\n\n"
            "Sources: `equibase` for US races · `racingpost` for UK/IRE/international · `oddschecker` for odds"
        ),
        inline=False,
    )

    embed.add_field(
        name="🔍  Research",
        value=(
            "`/horse name:<name>` — Full profile from Equibase: bloodline, career record, recent races + news\n"
            "`/trainer name:<name>` — Trainer stats from Racing Post: win rate, notable wins, recent winners\n"
            "`/jockey name:<name>` — Jockey stats from Racing Post: win rate, career wins, recent winners\n"
            "`/compare horse_a:<name> horse_b:<name>` — Full head-to-head: bloodline, career record, direct meetings\n"
            "  ↳ Works for **active, retired, and deceased** horses — pulls career stats directly from Equibase\n"
            "`/news query:<term>` — Latest horse racing news from Google News (default: G1 racing)"
        ),
        inline=False,
    )

    embed.add_field(
        name="🎌  Umamusume: Pretty Derby",
        value=(
            "`/umamusume name:<horse>` — Look up a horse's Umamusume character: personality, story arc, fun facts\n"
            "`/umamusume name:<horse> question:<q>` — Ask a lore question about the character\n\n"
            "**Auto-indicator:** `/horse` automatically shows a 🌸 teaser card if an Uma Musume counterpart exists\n"
            f"Supported: Special Week, Silence Suzuka, Tokai Teio, Gold Ship, Oguri Cap, El Condor Pasa, and {len(UMAMUSUME_DATA) - 6} more"
        ),
        inline=False,
    )

    embed.add_field(
        name="🔔  Result Subscriptions",
        value=(
            "`/subscribe name:<race>` — Get pinged when that race's official result is posted\n"
            "`/unsubscribe name:<race>` — Remove yourself from a race's notification list\n"
            "`/mysubscriptions` — See all races you're currently subscribed to\n\n"
            "You can also react 🔔 on any race announcement to subscribe — and un-react to unsubscribe"
        ),
        inline=False,
    )

    embed.add_field(
        name="⚙️  Automatic Posts (no command needed)",
        value=(
            "**Daily countdown** — Top 3 upcoming G1s posted each day with a 🔔 subscribe card\n"
            "**Race-day alerts** — Pings at 24h, 6h and 1h before each G1\n"
            "**Auto results** — Fetches and posts the official result 15–90 min after each race\n"
            "**Hourly news** — Latest breaking G1 news posted every hour\n\n"
            "→ Use `/setup` to choose which channels in *this server* receive these posts"
        ),
        inline=False,
    )

    embed.add_field(
        name="🔧  Server Setup",
        value=(
            "`/setup channel_type:alerts channel:#your-channel` — Set the G1 alerts & results channel\n"
            "`/setup channel_type:news   channel:#your-channel` — Set the hourly news feed channel\n"
            "`/setup channel_type:view`                         — See current channel configuration\n\n"
            "Requires **Manage Server** permission · Each server configures its own channels"
        ),
        inline=False,
    )

    embed.set_footer(text="For full setup and image customisation instructions, see GUIDE.md")
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="subscribe", description="Subscribe to get pinged when a G1 race result is posted")
@app_commands.describe(
    name="Partial name of the G1 race to subscribe to",
    country="Narrow your search by country",
)
@app_commands.choices(country=COUNTRY_CHOICES)
async def cmd_subscribe(
    interaction: discord.Interaction,
    name: str,
    country: app_commands.Choice[str] = None,
):
    await interaction.response.defer(ephemeral=True)
    country_val = country.value if country else "all"
    query = name.lower()
    pool = KNOWN_G1_RACES if country_val == "all" else [
        r for r in KNOWN_G1_RACES if r["country"].lower() == country_val.lower()
    ]
    matches = [r for r in pool if query in r["name"].lower()]

    if not matches:
        country_hint = f" in **{country.name}**" if country and country_val != "all" else ""
        await interaction.followup.send(
            f"No G1 race found matching **{name}**{country_hint}. Use `/upcoming` to see available races.",
            ephemeral=True,
        )
        return

    race = matches[0]
    race_key = race["name"]
    now = datetime.now(timezone.utc)

    if race["date"] < now:
        await interaction.followup.send(
            f"**{race_key}** has already been run. Subscribe to an upcoming race.",
            ephemeral=True,
        )
        return

    uid = interaction.user.id
    if race_key not in _race_subscriptions:
        _race_subscriptions[race_key] = set()
    _race_subscriptions[race_key].add(uid)

    dt = race["date"]
    unix_ts = int(dt.timestamp())
    await interaction.followup.send(
        f"✅ **Subscribed to {race_key}!**\n"
        f"You'll be pinged here when the official result is posted.\n"
        f"Race starts <t:{unix_ts}:R> · <t:{unix_ts}:F>\n\n"
        f"Use `/unsubscribe` to cancel at any time.",
        ephemeral=True,
    )
    log.info(f"User {uid} subscribed to {race_key} via /subscribe")


@tree.command(name="unsubscribe", description="Unsubscribe from a G1 race result notification")
@app_commands.describe(name="Partial name of the G1 race to unsubscribe from")
async def cmd_unsubscribe(interaction: discord.Interaction, name: str):
    await interaction.response.defer(ephemeral=True)
    query = name.lower()
    uid = interaction.user.id
    removed = []

    for race_key, subs in _race_subscriptions.items():
        if query in race_key.lower() and uid in subs:
            subs.discard(uid)
            removed.append(race_key)

    if removed:
        await interaction.followup.send(
            f"🔕 Unsubscribed from: **{', '.join(removed)}**",
            ephemeral=True,
        )
    else:
        await interaction.followup.send(
            f"You are not subscribed to any race matching **{name}**.",
            ephemeral=True,
        )


@tree.command(name="mysubscriptions", description="See which G1 races you're subscribed to")
async def cmd_mysubscriptions(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    uid = interaction.user.id
    subscribed = [
        race_key for race_key, subs in _race_subscriptions.items() if uid in subs
    ]

    if not subscribed:
        await interaction.followup.send(
            "You have no active subscriptions.\n"
            "React 🔔 on any race announcement, or use `/subscribe <race name>`.",
            ephemeral=True,
        )
        return

    lines = []
    for race_key in subscribed:
        race = next((r for r in KNOWN_G1_RACES if r["name"] == race_key), None)
        if race:
            unix_ts = int(race["date"].timestamp())
            lines.append(f"• **{race_key}** — <t:{unix_ts}:R>")
        else:
            lines.append(f"• {race_key}")

    await interaction.followup.send(
        f"**Your G1 subscriptions ({len(subscribed)}):**\n" + "\n".join(lines) +
        "\n\nUse `/unsubscribe <race name>` to cancel any of these.",
        ephemeral=True,
    )


# ── Prefix Commands (! style) ─────────────────────────────────────────────────

@bot.command(name="upcoming")
async def prefix_upcoming(ctx: commands.Context, limit: int = 5):
    """!upcoming [limit] — Show next N upcoming G1 races"""
    limit = min(max(limit, 1), 10)
    races = upcoming_g1s(limit)
    if not races:
        await ctx.send("No upcoming G1 races in the schedule.")
        return
    for race in races[:5]:
        await ctx.send(embed=build_g1_embed(race))


@bot.command(name="news")
async def prefix_news(ctx: commands.Context, *, query: str = "G1 horse racing"):
    """!news [query] — Search for horse racing news"""
    async with ctx.typing():
        articles = await search_racing_news(query)
        embed = build_news_embed(query, articles)
        await ctx.send(embed=embed)


@bot.command(name="result")
async def prefix_result(ctx: commands.Context, source: str, track: str, date: str = "", *, race: str = ""):
    """
    !result <equibase|racingpost> <track> [date] [race name filter]
    Examples:
      !result equibase PIM 20250517 Preakness
      !result racingpost ascot 2025-06-19
    """
    source = source.lower().strip()
    today = datetime.now(timezone.utc)
    async with ctx.typing():
        if source == "equibase":
            date_str = date or today.strftime("%Y%m%d")
            races = await fetch_results_equibase(track_code=track.upper(), date_str=date_str)
            embeds = build_results_embed_equibase(track, date_str, races, race_name_filter=race)
            for i in range(0, len(embeds), 5):
                await ctx.send(embeds=embeds[i : i + 5])
        elif source == "racingpost":
            date_str = date or today.strftime("%Y-%m-%d")
            runners = await fetch_results_racingpost(date_str=date_str, track=track.lower())
            embed = build_results_embed_racingpost(track, date_str, runners, race_name=race)
            await ctx.send(embed=embed)
        else:
            await ctx.send(
                "Usage: `!result <equibase|racingpost> <track> [date] [race name]`\n"
                "Examples:\n"
                "• `!result equibase PIM 20250517 Preakness`\n"
                "• `!result racingpost ascot 2025-06-19`"
            )


@bot.command(name="odds")
async def prefix_odds(ctx: commands.Context, source: str, track: str, date: str = ""):
    """
    !odds <equibase|racingpost|oddschecker> <track/slug> [date]
    Examples:
      !odds equibase PIM 20250517
      !odds racingpost ascot 2025-06-19
      !odds oddschecker horse-racing/2025-05-17-pimlico/preakness-stakes
    """
    source = source.lower().strip()
    today = datetime.now(timezone.utc)

    async with ctx.typing():
        if source == "equibase":
            date_str = date or today.strftime("%Y%m%d")
            races = await fetch_odds_equibase(track_code=track.upper(), date_str=date_str)
            embeds = build_odds_embed_equibase(track, date_str, races)
            for i in range(0, len(embeds), 5):
                await ctx.send(embeds=embeds[i : i + 5])

        elif source == "racingpost":
            date_str = date or today.strftime("%Y-%m-%d")
            runners = await fetch_odds_racingpost(date_str=date_str, track=track.lower())
            embed = build_odds_embed_racingpost(track, date_str, runners)
            await ctx.send(embed=embed)

        elif source == "oddschecker":
            runners = await fetch_oddschecker(race_slug=track)
            embed = build_odds_embed_oddschecker(track, runners)
            await ctx.send(embed=embed)

        else:
            await ctx.send(
                "Usage: `!odds <equibase|racingpost|oddschecker> <track> [date]`\n"
                "Examples:\n"
                "• `!odds equibase PIM 20250517`\n"
                "• `!odds racingpost ascot 2025-06-19`\n"
                "• `!odds oddschecker horse-racing/2025-05-17-pimlico/preakness-stakes`"
            )


@bot.command(name="compare")
async def prefix_compare(ctx: commands.Context, source: str, *, horses: str):
    """
    !compare <equibase|racingpost> <Horse A> vs <Horse B>
    Example: !compare equibase Justify vs American Pharoah
    """
    if " vs " not in horses.lower():
        await ctx.send(
            "Usage: `!compare <equibase|racingpost> <Horse A> vs <Horse B>`\n"
            "Example: `!compare equibase Justify vs American Pharoah`"
        )
        return

    split_idx = horses.lower().index(" vs ")
    horse_a = horses[:split_idx].strip()
    horse_b = horses[split_idx + 4:].strip()
    source = source.lower().strip()

    fetch_fn = (
        fetch_horse_history_equibase
        if source == "equibase"
        else fetch_horse_history_racingpost
    )

    async with ctx.typing():
        data_a, data_b = await asyncio.gather(fetch_fn(horse_a), fetch_fn(horse_b))
        matchups = _find_head_to_head(data_a, data_b)
        embeds = build_compare_embed(data_a, data_b, matchups)

        for i in range(0, len(embeds), 5):
            await ctx.send(embeds=embeds[i : i + 5])

        news_a, news_b = await asyncio.gather(
            fetch_horse_news(horse_a), fetch_horse_news(horse_b)
        )
        if news_a:
            await ctx.send(embed=build_news_embed(horse_a, news_a[:3]))
        if news_b:
            await ctx.send(embed=build_news_embed(horse_b, news_b[:3]))


@bot.command(name="runners")
async def prefix_runners(ctx: commands.Context, source: str, track: str, date: str = ""):
    """!runners <equibase|racingpost> <track> [date] — Show race card"""
    source = source.lower()
    if not date:
        today = datetime.now(timezone.utc)
        date = today.strftime("%Y%m%d") if source == "equibase" else today.strftime("%Y-%m-%d")

    async with ctx.typing():
        if source == "equibase":
            races = await fetch_equibase_entries(track_code=track.upper(), date_str=date)
            for race_info in races[:3]:
                embed = build_runners_embed(race_info["race"], race_info["horses"])
                await ctx.send(embed=embed)
        elif source == "racingpost":
            runners = await fetch_racingpost_card(date_str=date, track=track.lower())
            embed = build_runners_embed(f"{track.title()} — {date}", runners)
            await ctx.send(embed=embed)
        else:
            await ctx.send("Use `equibase` (US) or `racingpost` (UK/IRE) as the source.")


# ── Scheduled Tasks ───────────────────────────────────────────────────────────

@tasks.loop(hours=24)
async def daily_g1_alert():
    """Post daily G1 countdown to every configured alerts channel at midnight UTC."""
    channels = _get_alerts_channels()
    if not channels:
        return

    races = upcoming_g1s(3)
    if not races:
        return

    for channel in channels:
        await channel.send(
            f"**🏆 Daily G1 Race Countdown** — React {SUBSCRIBE_EMOJI} on a race below to get "
            "pinged the moment its official result is posted!"
        )
        for race in races:
            days_away = (race["date"] - datetime.now(timezone.utc)).days
            if days_away <= 30:
                # Check if this guild already has a sub card for this race
                existing = _race_sub_messages.get(race["name"], [])
                already_posted = any(ch_id == channel.id for ch_id, _ in existing)
                if not already_posted:
                    await post_race_subscription_card(channel, race)
                else:
                    await channel.send(embed=build_g1_embed(race))


@tasks.loop(hours=1)
async def hourly_news_check():
    """Post breaking G1 news to every configured news channel once per hour."""
    channels = _get_news_channels()
    if not channels:
        return

    articles = await search_racing_news("G1 horse racing breaking news")
    if articles:
        embed = build_news_embed("G1 Horse Racing — Latest News", articles[:3])
        embed.set_footer(text="Auto-updated every hour")
        for channel in channels:
            await channel.send(embed=embed)


@tasks.loop(minutes=30)
async def race_day_alert():
    """Alert every configured alerts channel when a G1 is within 24 hours."""
    channels = _get_alerts_channels()
    if not channels:
        return

    now = datetime.now(timezone.utc)
    for race in KNOWN_G1_RACES:
        delta = race["date"] - now
        hours_away = delta.total_seconds() / 3600

        # Alert at 24h, 6h, and 1h marks (with small ±5 min window)
        for threshold in [24, 6, 1]:
            if abs(hours_away - threshold) <= 0.08:  # ~5 minute window
                embed = build_g1_embed(race)
                embed.color = discord.Color.red()
                ping = _subscriber_ping(race["name"])
                content = f"🚨 **{race['name']} is in ~{threshold} hour(s)!**"
                if ping:
                    content += f"\n{ping}"
                for channel in channels:
                    # At 24h, post a fresh sub card if not already up for this guild
                    if threshold == 24:
                        existing = _race_sub_messages.get(race["name"], [])
                        already_posted = any(ch_id == channel.id for ch_id, _ in existing)
                        if not already_posted:
                            await post_race_subscription_card(channel, race)
                    await channel.send(content=content, embed=embed)


# ── Auto-Post G1 Results ─────────────────────────────────────────────────────
#
# Tracks which G1 races have been posted so we don't double-post.
# Resets on bot restart (in-memory only — good enough for a long-running process).
_posted_results: set[str] = set()

# ── Race Subscription State ───────────────────────────────────────────────────
# race_name → list of (channel_id, message_id) — one entry per guild that has
#   a subscription card posted.  Multiple guilds can track the same race.
_race_sub_messages: dict[str, list[tuple[int, int]]] = {}
# race_name → set of user_ids who reacted with SUBSCRIBE_EMOJI (global across guilds)
_race_subscriptions: dict[str, set[int]] = {}
# message_id → race_name (reverse lookup for reaction events)
_msg_to_race: dict[int, str] = {}

SUBSCRIBE_EMOJI = "🔔"


async def post_race_subscription_card(
    channel: discord.TextChannel, race: dict
) -> discord.Message:
    """
    Post an upcoming-G1 embed with a 🔔 reaction attached.
    Members who react are stored in _race_subscriptions and pinged when
    the official result drops.  The message is deleted automatically after.
    Supports multiple guilds — each gets its own subscription card tracked.
    """
    embed = build_g1_embed(race)
    embed.add_field(
        name=f"{SUBSCRIBE_EMOJI}  Get pinged when the result drops",
        value=(
            f"React with **{SUBSCRIBE_EMOJI}** to subscribe. "
            "You'll be mentioned the moment the official result is posted. "
            "Your subscription is removed automatically after the race."
        ),
        inline=False,
    )
    embed.set_footer(text="React 🔔 to subscribe  ·  React again to unsubscribe")
    msg = await channel.send(embed=embed)
    await msg.add_reaction(SUBSCRIBE_EMOJI)
    # Append this guild's card to the list (don't overwrite — multiple guilds)
    if race["name"] not in _race_sub_messages:
        _race_sub_messages[race["name"]] = []
    _race_sub_messages[race["name"]].append((channel.id, msg.id))
    _msg_to_race[msg.id] = race["name"]
    return msg


def _subscriber_ping(race_key: str) -> str:
    """Return a space-separated string of <@user_id> mentions for a race's subscribers."""
    subs = _race_subscriptions.get(race_key, set())
    return " ".join(f"<@{uid}>" for uid in subs) if subs else ""


async def _cleanup_subscription(race_key: str) -> None:
    """Delete all subscription messages (one per guild) and wipe subscription data."""
    entries = _race_sub_messages.pop(race_key, [])
    for ch_id, msg_id in entries:
        _msg_to_race.pop(msg_id, None)
        channel = bot.get_channel(ch_id)
        if channel:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
    _race_subscriptions.pop(race_key, None)


# Map known G1 races to their Equibase track code + Racing Post track slug
# so the auto-poster knows where to pull results from.
# Add entries here to match the KNOWN_G1_RACES list above.
G1_RESULT_SOURCES: dict[str, dict] = {
    "Preakness Stakes":                         {"source": "equibase", "track": "PIM"},
    "Belmont Stakes":                            {"source": "equibase", "track": "BEL"},
    "Breeders' Cup Classic":                     {"source": "equibase", "track": "DMR"},
    "Royal Ascot - Gold Cup":                   {"source": "racingpost", "track": "ascot"},
    "King George VI & Queen Elizabeth Stakes":  {"source": "racingpost", "track": "ascot"},
    "Arc de Triomphe":                          {"source": "racingpost", "track": "longchamp"},
    "Japan Cup":                                {"source": "racingpost", "track": "tokyo"},
    "Melbourne Cup":                            {"source": "racingpost", "track": "flemington"},
    "Dubai World Cup":                          {"source": "racingpost", "track": "meydan"},
}


@tasks.loop(minutes=5)
async def auto_post_g1_results():
    """
    Checks every 5 minutes whether any known G1 race has just finished
    (post time + 15 min grace period).  When detected, fetches the official
    result and posts a highlight card to every configured alerts channel.
    Result data is fetched once per race, then broadcast to all guilds.
    """
    channels = _get_alerts_channels()
    if not channels:
        return

    now = datetime.now(timezone.utc)

    for race in KNOWN_G1_RACES:
        race_key = race["name"]

        # Skip if already posted this session
        if race_key in _posted_results:
            continue

        minutes_since = (now - race["date"]).total_seconds() / 60

        # Only attempt between 15 and 90 minutes after scheduled post time
        if not (15 <= minutes_since <= 90):
            continue

        log.info(f"Attempting to auto-fetch result for {race_key} ({minutes_since:.0f} min after post)")

        source_info = G1_RESULT_SOURCES.get(race_key)

        if source_info:
            src = source_info["source"]
            trk = source_info["track"]

            if src == "equibase":
                date_str = race["date"].strftime("%Y%m%d")
                races_data = await fetch_results_equibase(track_code=trk.upper(), date_str=date_str)
                matched = next(
                    (r for r in races_data if race_key.lower() in r["race"].lower()),
                    races_data[0] if races_data else None,
                )
                if matched:
                    starters = matched.get("starters", [])
                    if starters:
                        # Build embeds once, broadcast to all guilds
                        highlight = build_g1_result_autopost_embed(race, starters)
                        ping = _subscriber_ping(race_key)
                        sub_count = len(_race_subscriptions.get(race_key, set()))
                        content = f"🏆 **{race_key} — OFFICIAL RESULT**"
                        if ping:
                            content += f"\n{ping}"
                        elif sub_count == 0:
                            content += "\n*(No subscribers — react 🔔 to future announcements to be pinged)*"
                        full_embeds = build_results_embed_equibase(
                            trk, date_str, [matched], race_name_filter=race_key
                        )
                        for channel in channels:
                            await channel.send(content=content, embed=highlight)
                            for i in range(0, len(full_embeds), 5):
                                await channel.send(embeds=full_embeds[i : i + 5])
                        await _cleanup_subscription(race_key)
                        _posted_results.add(race_key)
                        log.info(f"Auto-posted result for {race_key} to {len(channels)} channel(s) ({sub_count} subscriber(s) pinged)")

            elif src == "racingpost":
                date_str = race["date"].strftime("%Y-%m-%d")
                runners = await fetch_results_racingpost(date_str=date_str, track=trk)
                if runners:
                    adapted = [
                        {
                            "finish":  r["finish"],
                            "horse":   r["horse"],
                            "jockey":  r["jockey"],
                            "trainer": r["trainer"],
                            "odds":    r["sp_odds"],
                            "time":    r.get("beaten_by", "—"),
                        }
                        for r in runners
                    ]
                    highlight = build_g1_result_autopost_embed(race, adapted)
                    ping = _subscriber_ping(race_key)
                    sub_count = len(_race_subscriptions.get(race_key, set()))
                    content = f"🏆 **{race_key} — OFFICIAL RESULT**"
                    if ping:
                        content += f"\n{ping}"
                    elif sub_count == 0:
                        content += "\n*(No subscribers — react 🔔 to future announcements to be pinged)*"
                    full_embed = build_results_embed_racingpost(trk, date_str, runners, race_name=race_key)
                    for channel in channels:
                        await channel.send(content=content, embed=highlight)
                        await channel.send(embed=full_embed)
                    await _cleanup_subscription(race_key)
                    _posted_results.add(race_key)
                    log.info(f"Auto-posted result for {race_key} to {len(channels)} channel(s) ({sub_count} subscriber(s) pinged)")

        else:
            # No source mapping — post a "result pending" notice and mark as handled
            if minutes_since >= 30:
                embed = discord.Embed(
                    title=f"🏁 {race_key} — Result Pending",
                    description=(
                        f"The race ran at {race['track']}, {race['country']}. "
                        f"No automated result source is configured for this race.\n\n"
                        f"Use `/result` to look it up manually."
                    ),
                    color=discord.Color.orange(),
                    timestamp=now,
                )
                for channel in channels:
                    await channel.send(embed=embed)
                _posted_results.add(race_key)


# ── Bot Events ────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")

    # Load per-guild channel config from disk
    _load_guild_config()

    # Sync slash commands globally (may take up to 1h to propagate)
    # For instant testing in one server, use: await tree.sync(guild=discord.Object(id=YOUR_GUILD_ID))
    synced = await tree.sync()
    log.info(f"Synced {len(synced)} slash commands")

    # Start background tasks
    if not daily_g1_alert.is_running():
        daily_g1_alert.start()
    if not hourly_news_check.is_running():
        hourly_news_check.start()
    if not race_day_alert.is_running():
        race_day_alert.start()
    if not auto_post_g1_results.is_running():
        auto_post_g1_results.start()

    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="🏇 G1 Horse Racing",
        )
    )


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandNotFound):
        return
    log.error(f"Command error: {error}")
    await ctx.send(f"❌ Error: {error}")


# ── Reaction Subscription Handlers ────────────────────────────────────────────

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """Track 🔔 reactions on subscription cards to add users to race alerts."""
    if payload.user_id == bot.user.id:
        return  # ignore own reactions
    if str(payload.emoji) != SUBSCRIBE_EMOJI:
        return

    race_key = _msg_to_race.get(payload.message_id)
    if not race_key:
        return  # not a subscription card

    # Guard: don't subscribe to races that have already run
    race = next((r for r in KNOWN_G1_RACES if r["name"] == race_key), None)
    if race and race["date"] < datetime.now(timezone.utc):
        return

    uid = payload.user_id
    if race_key not in _race_subscriptions:
        _race_subscriptions[race_key] = set()

    if uid not in _race_subscriptions[race_key]:
        _race_subscriptions[race_key].add(uid)
        log.info(f"User {uid} subscribed to {race_key} via reaction")

        # DM the user a confirmation
        try:
            user = await bot.fetch_user(uid)
            unix_ts = int(race["date"].timestamp()) if race else 0
            dm_msg = (
                f"✅ **Subscribed to {race_key}!**\n"
                f"You'll be mentioned in the race channel the moment the official result is posted.\n"
            )
            if unix_ts:
                dm_msg += f"Race starts <t:{unix_ts}:F> (<t:{unix_ts}:R>)\n"
            dm_msg += "\nRemove your 🔔 reaction or use `/unsubscribe` to cancel."
            await user.send(dm_msg)
        except (discord.Forbidden, discord.HTTPException):
            pass  # user has DMs closed — that's fine


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    """Remove a user from a race's subscription when they un-react with 🔔."""
    if payload.user_id == bot.user.id:
        return
    if str(payload.emoji) != SUBSCRIBE_EMOJI:
        return

    race_key = _msg_to_race.get(payload.message_id)
    if not race_key:
        return

    uid = payload.user_id
    subs = _race_subscriptions.get(race_key, set())
    if uid in subs:
        subs.discard(uid)
        log.info(f"User {uid} unsubscribed from {race_key} via reaction remove")

        try:
            user = await bot.fetch_user(uid)
            await user.send(
                f"🔕 You've unsubscribed from **{race_key}**. "
                "You won't be pinged when the result drops."
            )
        except (discord.Forbidden, discord.HTTPException):
            pass


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("ERROR: Set DISCORD_BOT_TOKEN in your .env file or environment variables.")
        raise SystemExit(1)
    bot.run(TOKEN, log_handler=None)
