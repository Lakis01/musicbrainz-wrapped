"""ListenBrainz JSONL importer, data-source discovery, canonicalization, and parallel enrichment."""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from db import DB_PATH, get_connection, init_db, split_artist_names

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_SUBDIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(DATA_SUBDIR, "config.json")
IMPORTS_DIR = os.path.join(BASE_DIR, "imports")
STATIC_CACHE_DIR = os.path.join(BASE_DIR, "static", "cache")
USER_AGENT = "ListenBrainzLocalVisualizer/2.0 (unofficial-community-tool)"


def is_valid_export_dir(path: Optional[str]) -> bool:
    if not path or not os.path.isdir(path):
        return False
    if glob.glob(os.path.join(path, "listens", "*", "*.jsonl")):
        return True
    if glob.glob(os.path.join(path, "listens", "*.jsonl")):
        return True
    if glob.glob(os.path.join(path, "*.jsonl")):
        return True
    return False


def _find_export_root_inside(root_dir: str) -> Optional[str]:
    if is_valid_export_dir(root_dir):
        return root_dir
    try:
        for entry in sorted(os.listdir(root_dir)):
            sub = os.path.join(root_dir, entry)
            if is_valid_export_dir(sub):
                return sub
    except OSError:
        pass
    return None


def extract_archive(archive_path: str, target_parent: str = IMPORTS_DIR) -> Optional[str]:
    """Safely extract a .zip, .tar.gz, or .tgz ListenBrainz export into imports/."""
    if not os.path.isfile(archive_path):
        return None
    os.makedirs(target_parent, exist_ok=True)
    base_name = os.path.basename(archive_path)
    for suffix in (".tar.gz", ".tgz", ".zip"):
        if base_name.lower().endswith(suffix):
            stem = base_name[: -len(suffix)]
            break
    else:
        return None

    dest_dir = os.path.join(target_parent, stem)
    existing = _find_export_root_inside(dest_dir)
    if existing:
        return existing

    os.makedirs(dest_dir, exist_ok=True)
    real_dest = os.path.realpath(dest_dir)

    if archive_path.lower().endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            for member in zf.infolist():
                target = os.path.realpath(os.path.join(dest_dir, member.filename))
                if not (target == real_dest or target.startswith(real_dest + os.sep)):
                    raise ValueError(f"Unsafe zip member path: {member.filename}")
            zf.extractall(dest_dir)
    else:
        with tarfile.open(archive_path, "r:*") as tf:
            for member in tf.getmembers():
                target = os.path.realpath(os.path.join(dest_dir, member.name))
                if not (target == real_dest or target.startswith(real_dest + os.sep)):
                    raise ValueError(f"Unsafe tar member path: {member.name}")
            tf.extractall(dest_dir)

    return _find_export_root_inside(dest_dir)


def read_export_username(data_dir: Optional[str]) -> str:
    if not data_dir:
        return "Listener"
    user_json = os.path.join(data_dir, "user.json")
    if os.path.isfile(user_json):
        try:
            with open(user_json, "r", encoding="utf-8") as f:
                info = json.load(f)
                if info.get("username"):
                    return str(info["username"])
        except Exception:
            pass
    folder = os.path.basename(os.path.normpath(data_dir))
    m = re.match(r"listenbrainz_([^_]+)_", folder, re.IGNORECASE)
    if m:
        return m.group(1)
    return folder or "Listener"


def _count_jsonl_files(data_dir: str) -> int:
    files = set(glob.glob(os.path.join(data_dir, "listens", "*", "*.jsonl")))
    files.update(glob.glob(os.path.join(data_dir, "listens", "*.jsonl")))
    files.update(glob.glob(os.path.join(data_dir, "*.jsonl")))
    return len(files)


def load_app_config() -> Dict[str, Any]:
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def save_app_config(cfg: Dict[str, Any]) -> None:
    os.makedirs(DATA_SUBDIR, exist_ok=True)
    tmp_path = f"{CONFIG_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    try:
        os.chmod(tmp_path, 0o600)
    except OSError:
        pass
    os.replace(tmp_path, CONFIG_PATH)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def discover_data_dirs() -> List[Dict[str, Any]]:
    """Find available ListenBrainz export folders and archives on disk."""
    cfg = load_app_config()
    configured = cfg.get("data_dir")

    candidates: List[Tuple[str, str]] = []
    if configured:
        candidates.append(("configured", os.path.expanduser(str(configured))))

    # 1. Local ./imports/ folder (both extracted folders and archives)
    os.makedirs(IMPORTS_DIR, exist_ok=True)
    for entry in sorted(os.listdir(IMPORTS_DIR), reverse=True):
        full = os.path.join(IMPORTS_DIR, entry)
        if os.path.isdir(full):
            found = _find_export_root_inside(full)
            if found:
                candidates.append(("imports", found))
        elif os.path.isfile(full) and full.lower().endswith((".zip", ".tar.gz", ".tgz")):
            candidates.append(("archive", full))

    # 2. User Music Library & Downloads
    search_globs = [
        os.path.expanduser("~/Documents/Music Library/listenbrainz_*"),
        os.path.expanduser("~/Downloads/listenbrainz_*"),
        os.path.expanduser("~/Music/listenbrainz_*"),
    ]
    for pattern in search_globs:
        for path in sorted(glob.glob(pattern), reverse=True):
            if os.path.isdir(path):
                found = _find_export_root_inside(path)
                if found:
                    candidates.append(("library", found))
            elif os.path.isfile(path) and path.lower().endswith((".zip", ".tar.gz", ".tgz")):
                candidates.append(("archive", path))

    active_dir = get_active_data_dir()
    seen: set[str] = set()
    results: List[Dict[str, Any]] = []

    for source_kind, path in candidates:
        real = os.path.realpath(path)
        if real in seen:
            continue
        if source_kind == "archive":
            seen.add(real)
            results.append({
                "path": path,
                "name": os.path.basename(path),
                "source": "imports_archive",
                "kind": "archive",
                "username": read_export_username(path),
                "file_count": 0,
                "active": False,
            })
        elif is_valid_export_dir(path):
            seen.add(real)
            results.append({
                "path": path,
                "name": os.path.basename(os.path.normpath(path)),
                "source": source_kind,
                "kind": "dir",
                "username": read_export_username(path),
                "file_count": _count_jsonl_files(path),
                "active": bool(active_dir and os.path.realpath(active_dir) == real),
            })

    return results


def get_active_data_dir() -> Optional[str]:
    cfg = load_app_config()
    configured = cfg.get("data_dir")
    if configured:
        expanded = os.path.expanduser(str(configured))
        if is_valid_export_dir(expanded):
            return expanded

    # Default search priority: imports/ -> ~/Documents/Music Library -> ~/Downloads -> ~/Music
    os.makedirs(IMPORTS_DIR, exist_ok=True)
    for entry in sorted(os.listdir(IMPORTS_DIR), reverse=True):
        full = os.path.join(IMPORTS_DIR, entry)
        if os.path.isdir(full):
            found = _find_export_root_inside(full)
            if found:
                return found

    for pattern in (
        os.path.expanduser("~/Documents/Music Library/listenbrainz_*"),
        os.path.expanduser("~/Downloads/listenbrainz_*"),
        os.path.expanduser("~/Music/listenbrainz_*"),
    ):
        for p in sorted(glob.glob(pattern), reverse=True):
            if os.path.isdir(p):
                found = _find_export_root_inside(p)
                if found:
                    return found
    return None


def set_active_data_dir(path: str) -> str:
    expanded = os.path.expanduser(path.strip())
    if os.path.isfile(expanded) and expanded.lower().endswith((".zip", ".tar.gz", ".tgz")):
        extracted = extract_archive(expanded, IMPORTS_DIR)
        if not extracted:
            raise ValueError(f"Archive does not contain ListenBrainz JSONL listens: {expanded}")
        expanded = extracted
    elif os.path.isdir(expanded):
        found = _find_export_root_inside(expanded)
        if not found:
            raise ValueError(f"Directory does not contain ListenBrainz JSONL listens: {expanded}")
        expanded = found
    else:
        raise ValueError(f"Path does not exist: {expanded}")

    cfg = load_app_config()
    cfg["data_dir"] = expanded
    cfg["username"] = read_export_username(expanded)
    save_app_config(cfg)
    return expanded


def get_latest_data_dir() -> Optional[str]:
    return get_active_data_dir()


DATA_DIR = get_active_data_dir()

KNOWN_ARTIST_COUNTRIES = {
    "Tool": ("US", "United States"),
    "30 Seconds To Mars": ("US", "United States"),
    "Wheel": ("FI", "Finland"),
    "Angine de Poitrine": ("CA", "Canada"),
    "Olivia Rodrigo": ("US", "United States"),
    "Audioslave": ("US", "United States"),
    "Kids See Ghosts": ("US", "United States"),
    "Kanye West": ("US", "United States"),
    "Kid Cudi": ("US", "United States"),
    "Deftones": ("US", "United States"),
    "Will Ramos & Nik Nocturnal": ("US", "United States"),
    "Will Ramos": ("US", "United States"),
    "Nik Nocturnal": ("CA", "Canada"),
    "Dream Theater": ("US", "United States"),
    "Wiener Akademie": ("AT", "Austria"),
    "10 Years": ("US", "United States"),
    "Seether": ("ZA", "South Africa"),
    "Massive Attack": ("GB", "United Kingdom"),
    "Linkin Park": ("US", "United States"),
    "Bob Dylan": ("US", "United States"),
    "System Of A Down": ("US", "United States"),
    "Down": ("US", "United States"),
    "Eddie Vedder": ("US", "United States"),
    "Emmylou Harris": ("US", "United States"),
    "Milton Nascimento • Lô Borges": ("BR", "Brazil"),
    "Milton Nascimento & Lô Borges": ("BR", "Brazil"),
    "Milton Nascimento": ("BR", "Brazil"),
    "Lô Borges": ("BR", "Brazil"),
    "Led Zeppelin": ("GB", "United Kingdom"),
    "Alter Bridge": ("US", "United States"),
    "Alice In Chains": ("US", "United States"),
    "Queens of the Stone Age": ("US", "United States"),
    "Queens Of The Stone Age": ("US", "United States"),
    "Sleep Token": ("GB", "United Kingdom"),
    "Meat Loaf": ("US", "United States"),
    "Charli xcx": ("GB", "United Kingdom"),
    "Avenged Sevenfold": ("US", "United States"),
    "Sleep": ("US", "United States"),
    "Karnivool": ("AU", "Australia"),
    "Julie Fowlis": ("GB", "United Kingdom"),
    "Puddle of Mudd": ("US", "United States"),
    "Shye Ben Tzur, Jonny Greenwood and The Rajasthan Express": ("IN", "India"),
    "Shye Ben Tzur": ("IL", "Israel"),
    "Jonny Greenwood": ("GB", "United Kingdom"),
    "The Rajasthan Express": ("IN", "India"),
    "Breaking Benjamin": ("US", "United States"),
    "Bring Me The Horizon": ("GB", "United Kingdom"),
    "Bring Me the Horizon": ("GB", "United Kingdom"),
    "Knorkator": ("DE", "Germany"),
    "Hoobastank": ("US", "United States"),
    "Hans Söllner": ("DE", "Germany"),
    "The Beatles": ("GB", "United Kingdom"),
    "Metric": ("CA", "Canada"),
    "Berliner Philharmoniker": ("DE", "Germany"),
    "Lucinda Williams": ("US", "United States"),
    "Acid Bath": ("US", "United States"),
    "Acid Arab": ("FR", "France"),
    "Lana Del Rey": ("US", "United States"),
    "Lana Del Rey with Adam Cohen": ("US", "United States"),
    "Adam Cohen": ("CA", "Canada"),
    "Grateful Dead": ("US", "United States"),
    "Gothenburg Symphony Orchestra": ("SE", "Sweden"),
    "The Prodigy": ("GB", "United Kingdom"),
    "PJ Harvey": ("GB", "United Kingdom"),
    "Fleetwood Mac": ("GB", "United Kingdom"),
    "P.O.D.": ("US", "United States"),
    "Black Sabbath": ("GB", "United Kingdom"),
    "Colour Haze": ("DE", "Germany"),
    "Daniel Barenboim": ("AR", "Argentina"),
    "Soundgarden": ("US", "United States"),
    "Jason Derulo": ("US", "United States"),
    "Electric Wizard": ("GB", "United Kingdom"),
    "New Order": ("GB", "United Kingdom"),
    "Green Day": ("US", "United States"),
    "In Extremo": ("DE", "Germany"),
    "Beyoncé": ("US", "United States"),
    "Rise Against": ("US", "United States"),
    "Fair To Midland": ("US", "United States"),
    "Stone Temple Pilots": ("US", "United States"),
    "Iron Maiden": ("GB", "United Kingdom"),
    "Boris": ("JP", "Japan"),
    "Melvins": ("US", "United States"),
    "Ingolf Wunder": ("AT", "Austria"),
    "Max Richter": ("GB", "United Kingdom"),
    "Royal Blood": ("GB", "United Kingdom"),
    "Wind Rose": ("IT", "Italy"),
    "Elidi": ("GB", "United Kingdom"),
    "Fugees": ("US", "United States"),
    "Brand New": ("US", "United States"),
    "Simple Plan": ("CA", "Canada"),
    "Portishead": ("GB", "United Kingdom"),
    "Billy Talent": ("CA", "Canada"),
    "Falco": ("AT", "Austria"),
    "Elliott Smith": ("US", "United States"),
    "Muse": ("GB", "United Kingdom"),
    "Eminem": ("US", "United States"),
    "Kyuss": ("US", "United States"),
    "Haftbefehl": ("DE", "Germany"),
    "The National": ("US", "United States"),
    "The Smashing Pumpkins": ("US", "United States"),
    "The Animals": ("GB", "United Kingdom"),
    "The Pretty Reckless": ("US", "United States"),
    "The Lumineers": ("US", "United States"),
    "Slipknot": ("US", "United States"),
    "Amon Amarth": ("SE", "Sweden"),
    "Scott Walker": ("US", "United States"),
    "Rammstein": ("DE", "Germany"),
    "Porcupine Tree": ("GB", "United Kingdom"),
    "Bon Iver": ("US", "United States"),
    "David Guetta": ("FR", "France"),
    "Chevelle": ("US", "United States"),
    "Bullet For My Valentine": ("GB", "United Kingdom"),
    "The Velvet Underground": ("US", "United States"),
    "Manowar": ("US", "United States"),
    "Johnny Cash": ("US", "United States"),
    "Dead Letter Circus": ("AU", "Australia"),
    "A Perfect Circle": ("US", "United States"),
    "Post Malone": ("US", "United States"),
    "blink-182": ("US", "United States"),
    "3 Doors Down": ("US", "United States"),
    "The Incredible String Band": ("GB", "United Kingdom"),
    "All Time Low": ("US", "United States"),
    "Leonard Cohen": ("CA", "Canada"),
    "Tate McRae": ("CA", "Canada"),
    "Kraftklub": ("DE", "Germany"),
    "AC/DC": ("AU", "Australia"),
    "Robyn": ("SE", "Sweden"),
    "Miles Davis": ("US", "United States"),
    "Steely Dan": ("US", "United States"),
    "The Doors": ("US", "United States"),
    "ABBA": ("SE", "Sweden"),
    "Christina Stürmer": ("AT", "Austria"),
    "Kelly Clarkson": ("US", "United States"),
    "Avril Lavigne": ("CA", "Canada"),
    "Radiohead": ("GB", "United Kingdom"),
    "Metallica": ("US", "United States"),
    "Taylor Swift": ("US", "United States"),
    "Kendrick Lamar": ("US", "United States"),
}

KNOWN_ALBUM_YEARS = {
    ("30 Seconds To Mars", "30 Seconds To Mars"): 2002,
    ("Wheel", "Resident Human"): 2021,
    ("Wheel", "Moving Backwards"): 2019,
    ("Wheel", "Charismatic Leaders"): 2024,
    ("Angine de Poitrine", "Vol. 1"): 2023,
    ("Angine de Poitrine", "Vol. II"): 2024,
    ("Angine de Poitrine", "ANGINE DE POITRINE - VOL.1"): 2023,
    ("Angine de Poitrine", "Vol.1"): 2023,
    ("Angine de Poitrine", "Vol.II"): 2024,
    ("Olivia Rodrigo", "GUTS"): 2023,
    ("Olivia Rodrigo", "SOUR"): 2021,
    ("Olivia Rodrigo", "you seem pretty sad for a girl so in love"): 2023,
    ("Tool", "Fear Inoculum"): 2019,
    ("Tool", "10,000 Days"): 2006,
    ("Tool", "Ænima"): 1996,
    ("Tool", "Lateralus"): 2001,
    ("Tool", "Undertow"): 1993,
    ("Tool", "Opiate"): 1992,
    ("Audioslave", "Audioslave"): 2002,
    ("Audioslave", "Out of Exile"): 2005,
    ("Kids See Ghosts", "Kids See Ghosts"): 2018,
    ("Deftones", "Around the Fur"): 1997,
    ("Deftones", "White Pony"): 2000,
    ("Deftones", "Koi No Yokan"): 2012,
    ("Deftones", "Diamond Eyes"): 2010,
    ("Deftones", "Deftones"): 2003,
    ("Deftones", "Saturday Night Wrist"): 2006,
    ("Deftones", "Gore"): 2016,
    ("Deftones", "Ohms"): 2020,
    ("Seether", "Isolate and Medicate"): 2014,
    ("Seether", "Finding Beauty in Negative Spaces"): 2007,
    ("Seether", "Karma and Effect"): 2005,
    ("Seether", "Disclaimer II"): 2004,
    ("Will Ramos & Nik Nocturnal", "Chokehold"): 2023,
    ("Will Ramos", "Chokehold"): 2023,
    ("Dream Theater", "A Change Of Seasons"): 1995,
    ("Dream Theater", "Images and Words"): 1992,
    ("Dream Theater", "Metropolis, Pt. 2: Scenes from a Memory"): 1999,
    ("Down", "NOLA"): 1995,
    ("Wiener Akademie", "Faust-Sinfonie, S. 108"): 2025,
    ("10 Years", "The Autumn Effect"): 2005,
    ("10 Years", "Killing All That Holds You"): 2004,
    ("10 Years", "Division"): 2008,
    ("10 Years", "Feeding the Wolves"): 2010,
    ("10 Years", "Acoustic EP"): 2006,
    ("Massive Attack", "Mezzanine"): 1998,
    ("Massive Attack", "Blue Lines"): 1991,
    ("Linkin Park", "From Zero"): 2024,
    ("Linkin Park", "Hybrid Theory"): 2000,
    ("Linkin Park", "Meteora"): 2003,
    ("Bob Dylan", "Highway 61 Revisited"): 1965,
    ("Bob Dylan", "Bringing It All Back Home"): 1965,
    ("Bob Dylan", "Blood on the Tracks"): 1975,
    ("Bob Dylan", "Desire"): 1976,
    ("Bob Dylan", "The Freewheelin' Bob Dylan"): 1963,
    ("System Of A Down", "Toxicity"): 2001,
    ("System Of A Down", "Mezmerize"): 2005,
    ("System Of A Down", "Hypnotize"): 2005,
    ("System Of A Down", "System Of A Down"): 1998,
    ("Eddie Vedder", "Water On The Road"): 2011,
    ("Eddie Vedder", "Water on the Road"): 2011,
    ("Eddie Vedder", "Into the Wild"): 2007,
    ("Emmylou Harris", "Red Dirt Girl"): 2000,
    ("Emmylou Harris", "Wrecking Ball"): 1995,
    ("Milton Nascimento • Lô Borges", "Clube da Esquina"): 1972,
    ("Milton Nascimento & Lô Borges", "Clube da Esquina"): 1972,
    ("Milton Nascimento", "Clube da Esquina"): 1972,
    ("Led Zeppelin", "Led Zeppelin II"): 1969,
    ("Led Zeppelin", "Led Zeppelin IV"): 1971,
    ("Led Zeppelin", "Led Zeppelin IV (Untitled)"): 1971,
    ("Led Zeppelin", "Physical Graffiti"): 1975,
    ("Led Zeppelin", "Led Zeppelin"): 1969,
    ("Led Zeppelin", "Houses of the Holy"): 1973,
    ("Queens of the Stone Age", "Songs for the Deaf"): 2002,
    ("Queens of the Stone Age", "Queens of the Stone Age"): 1998,
    ("Queens of the Stone Age", "Rated R"): 2000,
    ("Queens of the Stone Age", "…Like Clockwork"): 2013,
    ("Queens of the Stone Age", "Lullabies to Paralyze"): 2005,
    ("Queens of the Stone Age", "Era Vulgaris"): 2007,
    ("Sleep Token", "Take Me Back to Eden"): 2023,
    ("Meat Loaf", "Bat Out of Hell II: Back into Hell"): 1993,
    ("Meat Loaf", "Bat Out of Hell"): 1977,
    ("Charli xcx", "BRAT"): 2024,
    ("Charli xcx", "how i'm feeling now"): 2020,
    ("Charli xcx", "Crash"): 2022,
    ("Avenged Sevenfold", "Life Is But a Dream..."): 2023,
    ("Avenged Sevenfold", "City of Evil"): 2005,
    ("Sleep", "Dopesmoker"): 2003,
    ("Karnivool", "Themata"): 2005,
    ("Karnivool", "Sound Awake"): 2009,
    ("Julie Fowlis", "Brave"): 2012,
    ("Puddle of Mudd", "Come Clean"): 2001,
    ("Shye Ben Tzur, Jonny Greenwood and The Rajasthan Express", "Junun"): 2015,
    ("Breaking Benjamin", "Phobia"): 2006,
    ("Breaking Benjamin", "We Are Not Alone"): 2004,
    ("Bring Me The Horizon", "Sempiternal"): 2013,
    ("Bring Me The Horizon", "POST HUMAN: NeX GEn"): 2024,
    ("Bring Me The Horizon", "POST HUMAN: SURVIVAL MODE"): 2020,
    ("Bring Me The Horizon", "That's the Spirit"): 2015,
    ("Knorkator", "Hasenchartbreaker"): 1999,
    ("Knorkator", "The Schlechtst of"): 1998,
    ("Hoobastank", "The Reason"): 2003,
    ("Hoobastank", "Hoobastank"): 2001,
    ("The Beatles", "Abbey Road"): 1969,
    ("The Beatles", "Revolver"): 1966,
    ("The Beatles", "Sgt. Pepper's Lonely Hearts Club Band"): 1967,
    ("The Beatles", "The Beatles (White Album)"): 1968,
    ("The Beatles", "Rubber Soul"): 1965,
    ("Metric", "Fantasies"): 2009,
    ("Lucinda Williams", "Car Wheels on a Gravel Road"): 1998,
    ("Acid Bath", "When the Kite String Pops"): 1994,
    ("Acid Bath", "Paegan Terrorism Tactics"): 1996,
    ("Acid Arab", "Cercle live set @Aerosol, Paris"): 2026,
    ("Alter Bridge", "One Day Remains"): 2004,
    ("Lana Del Rey", "Norman Fucking Rockwell!"): 2019,
    ("Lana Del Rey", "Born to Die"): 2012,
    ("Grateful Dead", "American Beauty"): 1970,
    ("Grateful Dead", "Workingman's Dead"): 1970,
    ("The Prodigy", "The Fat of the Land"): 1997,
    ("PJ Harvey", "Rid of Me"): 1993,
    ("PJ Harvey", "Stories from the City, Stories from the Sea"): 2000,
    ("PJ Harvey", "To Bring You My Love"): 1995,
    ("Fleetwood Mac", "Rumours"): 1977,
    ("Fleetwood Mac", "Fleetwood Mac"): 1975,
    ("Fleetwood Mac", "Tusk"): 1979,
    ("P.O.D.", "Satellite"): 2001,
    ("Black Sabbath", "Paranoid"): 1970,
    ("Black Sabbath", "Black Sabbath"): 1970,
    ("Black Sabbath", "Master of Reality"): 1971,
    ("Black Sabbath", "Heaven and Hell"): 1980,
    ("Soundgarden", "Superunknown"): 1994,
    ("Soundgarden", "Badmotorfinger"): 1991,
    ("Soundgarden", "Down On The Upside"): 1996,
    ("Electric Wizard", "Dopethrone"): 2000,
    ("Green Day", "Dookie"): 1994,
    ("Green Day", "American Idiot"): 2004,
    ("In Extremo", "Mein rasend' Herz"): 2005,
    ("Rise Against", "The Sufferer & the Witness"): 2006,
    ("Fair To Midland", "Fables From A Mayfly: What I Tell You Three Times Is True"): 2007,
    ("Stone Temple Pilots", "Core"): 1992,
    ("Stone Temple Pilots", "Purple"): 1994,
    ("Iron Maiden", "The Number of the Beast"): 1982,
    ("Iron Maiden", "Powerslave"): 1984,
    ("Boris", "Pink"): 2005,
    ("Boris", "Akuma no Uta"): 2002,
    ("Melvins", "Houdini"): 1993,
    ("Max Richter", "The Blue Notebooks"): 2004,
    ("Max Richter", "Sleep"): 2015,
    ("Max Richter", "Recomposed by Max Richter: Vivaldi - The Four Seasons"): 2012,
    ("Royal Blood", "Royal Blood"): 2014,
    ("Portishead", "Dummy"): 1994,
    ("Billy Talent", "Billy Talent II"): 2006,
    ("Falco", "Einzelhaft"): 1982,
    ("Elliott Smith", "Either/Or"): 1997,
    ("Muse", "Origin of Symmetry"): 2001,
    ("The Smashing Pumpkins", "Siamese Dream"): 1993,
    ("The Smashing Pumpkins", "Mellon Collie and the Infinite Sadness"): 1995,
    ("Slipknot", "Iowa"): 2001,
    ("Slipknot", "Slipknot"): 1999,
    ("Rammstein", "Mutter"): 2001,
    ("Porcupine Tree", "In Absentia"): 2002,
    ("Porcupine Tree", "Fear of a Blank Planet"): 2007,
    ("Porcupine Tree", "Deadwing"): 2005,
    ("Chevelle", "Wonder What's Next"): 2002,
    ("Bullet For My Valentine", "The Poison"): 2005,
    ("The Velvet Underground", "The Velvet Underground & Nico"): 1967,
    ("A Perfect Circle", "Mer de Noms"): 2000,
    ("A Perfect Circle", "Thirteenth Step"): 2003,
    ("The Who", "Who's Next"): 1971,
    ("The Who", "Tommy"): 1969,
    ("The Doors", "The Doors"): 1967,
    ("Steely Dan", "Can’t Buy A Thrill"): 1972,
    ("Steely Dan", "Can't Buy A Thrill"): 1972,
    ("Miles Davis", "Bitches Brew"): 1970,
    ("Bill Evans Trio", "Waltz For Debby"): 1961,
    ("Prince & The Revolution", "Purple Rain"): 1984,
    ("ABBA", "Voulez-Vous"): 1979,
    ("Christina Stürmer", "Lebe Lauter"): 2006,
    ("Post Malone", "F-1 Trillion"): 2024,
    ("Kelly Clarkson", "Breakaway"): 2004,
    ("Simple Plan", "Harder Than It Looks"): 2022,
    ("Matt Skiba and the Sekrets", "KUTS"): 2015,
    ("Shinedown", "The Sound of Madness"): 2008,
}

CUSTOM_ARTIST_URLS = {
    "Angine de Poitrine": "https://coverartarchive.org/release/de0e1482-d8a6-4afe-9cd1-dc9e1a53941e/front-500",
    "Wiener Akademie": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e5/Wiener_Akademie_Martin_Haselboeck.jpg/500px-Wiener_Akademie_Martin_Haselboeck.jpg",
    "Boris": "https://cdn-images.dzcdn.net/images/artist/99dc845bf13ecbfaae6f228bdf69a8b1/500x500-000000-80-0-0.jpg",
    "Ingolf Wunder": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/cb/Ingolf_Wunder_%281%29.jpg/500px-Ingolf_Wunder_%281%29.jpg",
    "Falco": "https://upload.wikimedia.org/wikipedia/en/7/70/Falco_musician_photo.jpg",
    "Muse": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0d/Muse_reading_Louvre_CA2220.jpg/500px-Muse_reading_Louvre_CA2220.jpg",
    "Lucinda Williams": "https://cdn-images.dzcdn.net/images/artist/a9a36d0725e9ae1ed455ad9068a700fe/1000x1000-000000-80-0-0.jpg",
    "Slipknot": "https://cdn-images.dzcdn.net/images/artist/d1a3db36015dd98615f42a5441dcf2f5/1000x1000-000000-80-0-0.jpg",
    "Max Richter": "https://cdn-images.dzcdn.net/images/artist/505cbd328b3ab5d5f4aca88a1684e277/1000x1000-000000-80-0-0.jpg",
    "Fleetwood Mac": "https://cdn-images.dzcdn.net/images/artist/ef23278cf3a67a3ca8404ddaa38699d4/1000x1000-000000-80-0-0.jpg",
    "Will Ramos & Nik Nocturnal": "https://cdn-images.dzcdn.net/images/artist/9e0011ea535afb88f4b008311505fa86/1000x1000-000000-80-0-0.jpg",
    "Will Ramos": "https://cdn-images.dzcdn.net/images/artist/9e0011ea535afb88f4b008311505fa86/1000x1000-000000-80-0-0.jpg",
    "Acid Arab": "https://cdn-images.dzcdn.net/images/artist/5eae6fd225dfcc155b8b872afed1dd31/1000x1000-000000-80-0-0.jpg",
    "Hans Söllner": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/11/Hans_Soellner5.jpg/500px-Hans_Soellner5.jpg",
    "Milton Nascimento • Lô Borges": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c8/Milton_Nascimento_2008.04.30_007.jpg/500px-Milton_Nascimento_2008.04.30_007.jpg",
    "Milton Nascimento & Lô Borges": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c8/Milton_Nascimento_2008.04.30_007.jpg/500px-Milton_Nascimento_2008.04.30_007.jpg",
    "Milton Nascimento": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c8/Milton_Nascimento_2008.04.30_007.jpg/500px-Milton_Nascimento_2008.04.30_007.jpg",
    "Lana Del Rey with Adam Cohen": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d0/LanaDRPrimavera310524_%2832_of_147%29_%2853765476960%29_%28cropped%29.jpg/500px-LanaDRPrimavera310524_%2832_of_147%29_%2853765476960%29_%28cropped%29.jpg",
    "Lana Del Rey": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d0/LanaDRPrimavera310524_%2832_of_147%29_%2853765476960%29_%28cropped%29.jpg/500px-LanaDRPrimavera310524_%2832_of_147%29_%2853765476960%29_%28cropped%29.jpg",
    "Shye Ben Tzur, Jonny Greenwood and The Rajasthan Express": "https://cdn-images.dzcdn.net/images/cover/03efcfef9b37e740a9e63810fa872d3b/500x500-000000-80-0-0.jpg",
}

CUSTOM_ALBUM_URLS = {
    ("Will Ramos & Nik Nocturnal", "Chokehold"): "https://cdn-images.dzcdn.net/images/artist/9e0011ea535afb88f4b008311505fa86/1000x1000-000000-80-0-0.jpg",
    ("Milton Nascimento & Lô Borges", "Clube da Esquina"): "https://coverartarchive.org/release/72004245-e234-45ff-b31c-99c08a989ef7/front-500",
    ("10 Years", "The Autumn Effect"): "https://cdn-images.dzcdn.net/images/cover/dc28aae131868e563e715bb9a4f4c75b/1000x1000-000000-80-0-0.jpg",
    ("Fair To Midland", "Fables From A Mayfly: What I Tell You Three Times Is True"): "https://cdn-images.dzcdn.net/images/cover/4f62e9cd7098868354693c93f9059ccf/1000x1000-000000-80-0-0.jpg",
    ("Spinal Tap", "This Is Spinal Tap"): "https://coverartarchive.org/release/d6d0cc81-7b55-4bcf-a990-fa4ec1911962/front-500",
    ("Acid Arab", "Cercle live set @Aerosol, Paris"): "https://cdn-images.dzcdn.net/images/artist/5eae6fd225dfcc155b8b872afed1dd31/1000x1000-000000-80-0-0.jpg",
    ("Angine de Poitrine", "Vol. 1"): "https://coverartarchive.org/release/de0e1482-d8a6-4afe-9cd1-dc9e1a53941e/front-500",
    ("Angine de Poitrine", "Vol. II"): "https://coverartarchive.org/release/aa7845c8-79e3-4149-93ac-3968d7951439/front-500",
    ("Boris", "Akuma no Uta"): "https://cdn-images.dzcdn.net/images/cover/054f55cb418eedd0aab537e3b11c7848/500x500-000000-80-0-0.jpg",
    ("Boris", "Akuma no ato"): "https://cdn-images.dzcdn.net/images/cover/054f55cb418eedd0aab537e3b11c7848/500x500-000000-80-0-0.jpg",
    ("Dream Theater", "A Change Of Seasons"): "https://cdn-images.dzcdn.net/images/cover/bc4907ef690761fcb6a09fb3e2b17309/500x500-000000-80-0-0.jpg",
    ("Eddie Vedder", "Water On The Road"): "https://upload.wikimedia.org/wikipedia/en/c/c0/Water_on_the_Road_dvd.jpg",
    ("Eddie Vedder", "Water on the Road"): "https://upload.wikimedia.org/wikipedia/en/c/c0/Water_on_the_Road_dvd.jpg",
    ("Shye Ben Tzur, Jonny Greenwood and The Rajasthan Express", "Junun"): "https://cdn-images.dzcdn.net/images/cover/03efcfef9b37e740a9e63810fa872d3b/500x500-000000-80-0-0.jpg",
}

DEMONYM_MAP = {
    "american": ("US", "United States"), "united states": ("US", "United States"), "u.s.": ("US", "United States"), "usa": ("US", "United States"),
    "california": ("US", "United States"), "new york": ("US", "United States"), "texas": ("US", "United States"), "los angeles": ("US", "United States"), "chicago": ("US", "United States"), "atlanta": ("US", "United States"), "nashville": ("US", "United States"), "seattle": ("US", "United States"), "boston": ("US", "United States"),
    "british": ("GB", "United Kingdom"), "english": ("GB", "United Kingdom"), "scottish": ("GB", "United Kingdom"), "welsh": ("GB", "United Kingdom"), "uk": ("GB", "United Kingdom"), "united kingdom": ("GB", "United Kingdom"), "london": ("GB", "United Kingdom"), "manchester": ("GB", "United Kingdom"), "birmingham": ("GB", "United Kingdom"), "liverpool": ("GB", "United Kingdom"), "glasgow": ("GB", "United Kingdom"), "edinburgh": ("GB", "United Kingdom"),
    "canadian": ("CA", "Canada"), "canada": ("CA", "Canada"), "toronto": ("CA", "Canada"), "montreal": ("CA", "Canada"), "vancouver": ("CA", "Canada"), "quebec": ("CA", "Canada"), "ottawa": ("CA", "Canada"), "calgary": ("CA", "Canada"),
    "australian": ("AU", "Australia"), "australia": ("AU", "Australia"), "melbourne": ("AU", "Australia"), "sydney": ("AU", "Australia"), "perth": ("AU", "Australia"), "brisbane": ("AU", "Australia"), "adelaide": ("AU", "Australia"),
    "german": ("DE", "Germany"), "germany": ("DE", "Germany"), "berlin": ("DE", "Germany"), "munich": ("DE", "Germany"), "hamburg": ("DE", "Germany"), "cologne": ("DE", "Germany"), "frankfurt": ("DE", "Germany"), "leipzig": ("DE", "Germany"),
    "austrian": ("AT", "Austria"), "austria": ("AT", "Austria"), "vienna": ("AT", "Austria"), "salzburg": ("AT", "Austria"), "graz": ("AT", "Austria"),
    "french": ("FR", "France"), "france": ("FR", "France"), "paris": ("FR", "France"), "marseille": ("FR", "France"), "lyon": ("FR", "France"),
    "italian": ("IT", "Italy"), "italy": ("IT", "Italy"), "rome": ("IT", "Italy"), "milan": ("IT", "Italy"), "naples": ("IT", "Italy"), "turin": ("IT", "Italy"),
    "swedish": ("SE", "Sweden"), "sweden": ("SE", "Sweden"), "stockholm": ("SE", "Sweden"), "gothenburg": ("SE", "Sweden"), "malmö": ("SE", "Sweden"),
    "finnish": ("FI", "Finland"), "finland": ("FI", "Finland"), "helsinki": ("FI", "Finland"), "tampere": ("FI", "Finland"),
    "norwegian": ("NO", "Norway"), "norway": ("NO", "Norway"), "oslo": ("NO", "Norway"), "bergen": ("NO", "Norway"),
    "danish": ("DK", "Denmark"), "denmark": ("DK", "Denmark"), "copenhagen": ("DK", "Denmark"),
    "dutch": ("NL", "Netherlands"), "netherlands": ("NL", "Netherlands"), "amsterdam": ("NL", "Netherlands"), "rotterdam": ("NL", "Netherlands"), "the hague": ("NL", "Netherlands"),
    "brazilian": ("BR", "Brazil"), "brazil": ("BR", "Brazil"), "rio de janeiro": ("BR", "Brazil"), "são paulo": ("BR", "Brazil"), "salvador": ("BR", "Brazil"),
    "japanese": ("JP", "Japan"), "japan": ("JP", "Japan"), "tokyo": ("JP", "Japan"), "osaka": ("JP", "Japan"), "kyoto": ("JP", "Japan"),
    "irish": ("IE", "Ireland"), "ireland": ("IE", "Ireland"), "dublin": ("IE", "Ireland"), "belfast": ("GB", "United Kingdom"),
    "south african": ("ZA", "South Africa"), "south africa": ("ZA", "South Africa"), "johannesburg": ("ZA", "South Africa"), "cape town": ("ZA", "South Africa"), "pretoria": ("ZA", "South Africa"),
    "new zealand": ("NZ", "New Zealand"), "auckland": ("NZ", "New Zealand"), "wellington": ("NZ", "New Zealand"),
    "mexican": ("MX", "Mexico"), "mexico": ("MX", "Mexico"), "mexico city": ("MX", "Mexico"),
    "argentine": ("AR", "Argentina"), "argentinian": ("AR", "Argentina"), "argentina": ("AR", "Argentina"), "buenos aires": ("AR", "Argentina"),
    "russian": ("RU", "Russia"), "russia": ("RU", "Russia"), "moscow": ("RU", "Russia"), "saint petersburg": ("RU", "Russia"),
    "ukrainian": ("UA", "Ukraine"), "ukraine": ("UA", "Ukraine"), "kyiv": ("UA", "Ukraine"),
    "polish": ("PL", "Poland"), "poland": ("PL", "Poland"), "warsaw": ("PL", "Poland"), "kraków": ("PL", "Poland"),
    "spanish": ("ES", "Spain"), "spain": ("ES", "Spain"), "madrid": ("ES", "Spain"), "barcelona": ("ES", "Spain"), "valencia": ("ES", "Spain"), "seville": ("ES", "Spain"),
    "icelandic": ("IS", "Iceland"), "iceland": ("IS", "Iceland"), "reykjavík": ("IS", "Iceland"),
    "belgian": ("BE", "Belgium"), "belgium": ("BE", "Belgium"), "brussels": ("BE", "Belgium"), "antwerp": ("BE", "Belgium"), "ghent": ("BE", "Belgium"),
    "swiss": ("CH", "Switzerland"), "switzerland": ("CH", "Switzerland"), "zurich": ("CH", "Switzerland"), "geneva": ("CH", "Switzerland"), "basel": ("CH", "Switzerland"),
    "israeli": ("IL", "Israel"), "israel": ("IL", "Israel"), "tel aviv": ("IL", "Israel"), "jerusalem": ("IL", "Israel"),
    "indian": ("IN", "India"), "india": ("IN", "India"), "mumbai": ("IN", "India"), "delhi": ("IN", "India"),
    "korean": ("KR", "South Korea"), "south korean": ("KR", "South Korea"), "seoul": ("KR", "South Korea"),
    "greek": ("GR", "Greece"), "greece": ("GR", "Greece"), "athens": ("GR", "Greece"),
    "portuguese": ("PT", "Portugal"), "portugal": ("PT", "Portugal"), "lisbon": ("PT", "Portugal"), "porto": ("PT", "Portugal"),
    "cuban": ("CU", "Cuba"), "cuba": ("CU", "Cuba"), "havana": ("CU", "Cuba"),
    "jamaican": ("JM", "Jamaica"), "jamaica": ("JM", "Jamaica"), "kingston": ("JM", "Jamaica"),
    "colombian": ("CO", "Colombia"), "colombia": ("CO", "Colombia"), "bogotá": ("CO", "Colombia"), "medellín": ("CO", "Colombia"),
    "chilean": ("CL", "Chile"), "chile": ("CL", "Chile"), "santiago": ("CL", "Chile"),
    "nigerian": ("NG", "Nigeria"), "nigeria": ("NG", "Nigeria"), "lagos": ("NG", "Nigeria"),
    "turkish": ("TR", "Turkey"), "turkey": ("TR", "Turkey"), "istanbul": ("TR", "Turkey"), "ankara": ("TR", "Turkey"),
    "czech": ("CZ", "Czech Republic"), "czech republic": ("CZ", "Czech Republic"), "prague": ("CZ", "Czech Republic"),
    "hungarian": ("HU", "Hungary"), "hungary": ("HU", "Hungary"), "budapest": ("HU", "Hungary"),
    "romanian": ("RO", "Romania"), "romania": ("RO", "Romania"), "bucharest": ("RO", "Romania"),
    "estonian": ("EE", "Estonia"), "estonia": ("EE", "Estonia"), "tallinn": ("EE", "Estonia"),
    "latvian": ("LV", "Latvia"), "latvia": ("LV", "Latvia"), "riga": ("LV", "Latvia"),
    "lithuanian": ("LT", "Lithuania"), "lithuania": ("LT", "Lithuania"), "vilnius": ("LT", "Lithuania"),
    "croatian": ("HR", "Croatia"), "croatia": ("HR", "Croatia"), "zagreb": ("HR", "Croatia"),
    "serbian": ("RS", "Serbia"), "serbia": ("RS", "Serbia"), "belgrade": ("RS", "Serbia"),
    "slovenian": ("SI", "Slovenia"), "slovenia": ("SI", "Slovenia"), "ljubljana": ("SI", "Slovenia"),
    "slovak": ("SK", "Slovakia"), "slovakia": ("SK", "Slovakia"), "bratislava": ("SK", "Slovakia"),
    "bulgarian": ("BG", "Bulgaria"), "bulgaria": ("BG", "Bulgaria"), "sofia": ("BG", "Bulgaria"),
}


def is_excluded_listen(artist_name: Optional[str], track_name: Optional[str] = None, release_name: Optional[str] = None) -> bool:
    art_clean = (artist_name or "").strip().lower()
    trk_clean = (track_name or "").strip().lower()
    rel_clean = (release_name or "").strip().lower()

    art_unbracketed = art_clean.strip("[]()").strip()
    rel_unbracketed = rel_clean.strip("[]()").strip()

    if not art_clean or art_unbracketed in ("unknown", "unknown artist", "none", "null"):
        return True
    if not rel_clean or rel_unbracketed in ("unknown", "unknown album", "none", "null") or rel_clean in ("stereo", "download"):
        return True
    if "podcast" in rel_clean or "podcast" in trk_clean or "podcast" in art_clean:
        return True
    if "eiskeller" in rel_clean or "eiskeller" in trk_clean:
        return True
    if "falsche f" in trk_clean or "falsche_f" in trk_clean or "falsche f" in rel_clean or "falsche_f" in rel_clean:
        return True
    if "m-shadows-shares" in trk_clean:
        return True
    if art_clean == "youtube" and ("study" in rel_clean or "focus" in trk_clean):
        return True
    return False


def canonicalize_artist_name(artist_name: Optional[str], release_name: Optional[str] = None, track_name: Optional[str] = None) -> Optional[str]:
    if not artist_name:
        return artist_name
    art_clean = artist_name.strip()
    art_lower = art_clean.lower()
    rel_lower = (release_name or "").strip().lower()
    trk_lower = (track_name or "").strip().lower()

    if ("chokehold" in trk_lower or rel_lower == "chokehold") and ("will ramos" in art_lower or "nik nocturnal" in art_lower or "nik nokturnal" in art_lower):
        return "Will Ramos & Nik Nocturnal"
    if "clube da esquina" in rel_lower and ("milton nascimento" in art_lower or "lô borges" in art_lower or "lo borges" in art_lower):
        return "Milton Nascimento & Lô Borges"
    if "junun" in rel_lower and ("shye ben tzur" in art_lower or "jonny greenwood" in art_lower or "rajasthan" in art_lower):
        return "Shye Ben Tzur, Jonny Greenwood and The Rajasthan Express"

    canonical_artist_map = {
        "queens of the stone age": "Queens of the Stone Age",
        "30 seconds to mars": "30 Seconds To Mars",
        "bring me the horizon": "Bring Me The Horizon",
        "bullet for my valentine": "Bullet For My Valentine",
        "charli xcx": "Charli xcx",
        "puddle of mudd": "Puddle of Mudd",
        "stick to your guns": "Stick to Your Guns",
        "system of a down": "System Of A Down",
        "rosalía": "Rosalía",
        "rosalia": "Rosalía",
        "mgk": "mgk",
        "boards of canada": "Boards Of Canada",
        "birds of tokyo": "Birds Of Tokyo",
        "[:sitd:]": "[:sitd:]",
        "will ramos & nik nocturnal": "Will Ramos & Nik Nocturnal",
        "will ramos & nik nokturnal": "Will Ramos & Nik Nocturnal",
        "milton nascimento & lô borges": "Milton Nascimento & Lô Borges",
        "milton nascimento • lô borges": "Milton Nascimento & Lô Borges",
        "milton nascimento and lo borges": "Milton Nascimento & Lô Borges",
        "shye ben tzur, jonny greenwood and the rajasthan express": "Shye Ben Tzur, Jonny Greenwood and The Rajasthan Express",
    }
    return canonical_artist_map.get(art_lower, art_clean)


def canonicalize_release_name(artist_name: Optional[str], release_name: Optional[str]) -> Optional[str]:
    if not release_name:
        return release_name
    rel_clean = release_name.strip()
    art_lower = (artist_name or "").strip().lower()

    if art_lower == "angine de poitrine":
        if rel_clean.upper() in ("ANGINE DE POITRINE - VOL.1", "VOL.1", "VOL. 1"):
            return "Vol. 1"
        if rel_clean.upper() in ("VOL.II", "VOL. II", "VOL. 2", "VOL.2"):
            return "Vol. II"

    if art_lower == "30 seconds to mars" and rel_clean.lower() == "30 seconds to mars":
        return "30 Seconds To Mars"
    if art_lower == "queens of the stone age":
        if rel_clean.lower() == "songs for the deaf":
            return "Songs for the Deaf"
        if rel_clean.lower() == "queens of the stone age":
            return "Queens of the Stone Age"
    if art_lower == "deftones":
        if rel_clean.lower() == "around the fur":
            return "Around the Fur"
        if rel_clean.lower() == "koi no yokan":
            return "Koi No Yokan"
    if art_lower == "soundgarden" and rel_clean.lower() == "down on the upside":
        return "Down On The Upside"
    if art_lower == "seether" and rel_clean.lower() == "isolate and medicate":
        return "Isolate and Medicate"
    if art_lower == "down" and rel_clean.lower() == "nola":
        return "NOLA"
    if art_lower == "system of a down":
        if rel_clean.lower() == "toxicity":
            return "Toxicity"
        if rel_clean.lower() == "mezmerize":
            return "Mezmerize"
        if rel_clean.lower() == "hypnotize":
            return "Hypnotize"
    if art_lower == "charli xcx" and rel_clean.lower() == "brat":
        return "BRAT"
    if art_lower == "acid bath" and rel_clean.lower() == "when the kite string pops":
        return "When the Kite String Pops"
    if art_lower == "the who" and rel_clean in ("Who’s Next", "Who's Next"):
        return "Who's Next"
    if art_lower == "in extremo" and rel_clean.lower() in ("mein rasend herz", "mein rasend' herz"):
        return "Mein rasend' Herz"
    if art_lower == "alter bridge" and "one day remains" in rel_clean.lower():
        return "One Day Remains"
    return rel_clean


def canonicalize_track_name(artist_name: Optional[str], track_name: Optional[str], release_name: Optional[str] = None) -> Optional[str]:
    if not track_name:
        return track_name
    t = track_name.strip()
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"\s*\((?:[^)]+?\s+)?(?:Cover|cover)\)", "", t)
    t = re.sub(r"\s*\[(?:[^\]]+?\s+)?(?:Cover|cover)\]", "", t)
    t = re.sub(r"\s*[\(\[]\s*(?:\d{4}\s+)?(?:Remaster|Remastered|Deluxe|Mono|Stereo|Re-master|Anniversary)(?:\s+\d{4})?[^\)\]]*[\)\]]", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*-\s*(?:\d{4}\s+)?(?:Remaster|Remastered|Deluxe|Mono|Stereo)[^\$]*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*\((?:Single\s+)?Edit\)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip(" -")

    art_lower = (artist_name or "").strip().lower()
    t_lower = t.lower()

    track_casing_map = {
        ("10 years", "through the iris"): "Through the Iris",
        ("10 years", "fix me"): "Fix Me",
        ("10 years", "fix me (acoustic)"): "Fix Me",
        ("barry manilow", "mandy"): "Mandy",
        ("billy talent", "rusted from the rain"): "Rusted From the Rain",
        ("black sabbath", "children of the sea"): "Children of the Sea",
        ("bob dylan", "song to woody"): "Song to Woody",
        ("breaking benjamin", "the diary of jane"): "The Diary of Jane",
        ("bring me the horizon", "and the snakes start to sing"): "And the Snakes Start to Sing",
        ("charli xcx", "von dutch"): "Von Dutch",
        ("deftones", "change (in the house of flies)"): "Change (In the House of Flies)",
        ("dolly parton", "coat of many colors"): "Coat of Many Colors",
        ("down", "stone the crow"): "Stone the Crow",
        ("fleetwood mac", "rhiannon"): "Rhiannon",
        ("fleetwood mac", "landslide"): "Landslide",
        ("fleetwood mac", "over my head"): "Over My Head",
        ("grateful dead", "it's all over now, baby blue"): "It's All Over Now, Baby Blue",
        ("grateful dead", "it's all over now baby blue"): "It's All Over Now, Baby Blue",
        ("hoobastank", "crawling in the dark"): "Crawling in the Dark",
        ("judy collins", "both sides now"): "Both Sides Now",
        ("johnny rivers", "positively 4th street"): "Positively 4th Street",
        ("julie fowlis", "touch the sky"): "Touch the Sky",
        ("kraftklub", "alles wegen dir"): "Alles wegen Dir",
        ("landon barker", "friends with your ex"): "Friends With Your Ex",
        ("linkin park", "heavy is the crown"): "Heavy Is The Crown",
        ("linkin park", "heavy is the crown (live)"): "Heavy Is The Crown",
        ("neck deep", "lowlife"): "Lowlife",
        ("neck deep", "lowlife (acoustic)"): "Lowlife",
        ("olivia rodrigo", "making the bed"): "Making the Bed",
        ("p.o.d.", "youth of the nation"): "Youth of the Nation",
        ("pj harvey", "rid of me"): "Rid of Me",
        ("queens of the stone age", "the sky is fallin'"): "The Sky Is Fallin'",
        ("queens of the stone age", "go with the flow"): "Go With the Flow",
        ("queens of the stone age", "a song for the dead"): "A Song for the Dead",
        ("queens of the stone age", "you think i ain't worth a dollar, but i feel like a millionaire"): "You Think I Ain't Worth a Dollar, but I Feel Like a Millionaire",
        ("rosalía", "beso"): "Beso",
        ("red hot chili peppers", "by the way"): "By the Way",
        ("red hot chili peppers", "soul to squeeze"): "Soul to Squeeze",
        ("royal blood", "out of the black"): "Out of the Black",
        ("seether", "nobody praying for me"): "Nobody Praying for Me",
        ("soundgarden", "fell on black days"): "Fell on Black Days",
        ("staind", "it's been awhile"): "It's Been Awhile",
        ("stevie nicks", "edge of seventeen"): "Edge of Seventeen",
        ("taylor swift", "welcome to new york"): "Welcome to New York",
        ("taylor swift", "welcome to new york (taylor's version)"): "Welcome to New York",
        ("10 years", "beautiful (acoustic)"): "Beautiful (Acoustic)",
        ("10 years", "beautiful (acoustic version)"): "Beautiful (Acoustic)",
        ("leprous", "from the flame"): "From the Flame",
        ("soggy bottom boys", "i am a man of constant sorrow (radio station version)"): "I Am a Man of Constant Sorrow (Radio Station Version)",
        ("the mccoys", "hang on sloopy"): "Hang on Sloopy",
        ("the who", "baba o'riley"): "Baba O'Riley",
    }

    if (art_lower, t_lower) in track_casing_map:
        return track_casing_map[(art_lower, t_lower)]
    return t


def get_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]


def is_valid_image_file(fpath: str) -> bool:
    if not os.path.exists(fpath) or os.path.getsize(fpath) < 500:
        return False
    try:
        with open(fpath, "rb") as fp:
            head = fp.read(32)
            if head.startswith(b"<!DOC") or head.startswith(b"<html") or head.startswith(b"<?xml") or b"Error" in head:
                return False
            if head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG") or head.startswith(b"GIF8") or head.startswith(b"RIFF"):
                return True
    except Exception:
        return False
    return False


def save_image_http(url: str, prefix: str, key: str) -> Optional[str]:
    """Download an image into static/cache using urllib (fallback curl) with validation."""
    os.makedirs(STATIC_CACHE_DIR, exist_ok=True)
    h = get_hash(key)
    fname = f"{prefix}_{h}.jpg"
    fpath = os.path.join(STATIC_CACHE_DIR, fname)
    if is_valid_image_file(fpath):
        return f"/cache/{fname}"
    if os.path.exists(fpath):
        try:
            os.remove(fpath)
        except Exception:
            pass

    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
        if len(data) > 500:
            with open(fpath, "wb") as fp:
                fp.write(data)
            if is_valid_image_file(fpath):
                return f"/cache/{fname}"
            os.remove(fpath)
    except Exception:
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass
    return None


# Backwards compatible alias
save_image_curl = save_image_http


def _fetch_json(url: str, timeout: int = 5) -> Optional[Dict[str, Any]]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def lookup_artist_image(artist_name: str) -> Optional[str]:
    clean_name = artist_name.strip()
    if clean_name in CUSTOM_ARTIST_URLS:
        return CUSTOM_ARTIST_URLS[clean_name]

    query = urllib.parse.quote(clean_name)
    data = _fetch_json(f"https://api.deezer.com/search/artist?q={query}&limit=3", timeout=5)
    if data:
        artists = data.get("data", [])
        for a in artists:
            if a.get("name", "").lower() == clean_name.lower():
                return a.get("picture_xl") or a.get("picture_big") or a.get("picture_medium")
        if artists:
            return artists[0].get("picture_xl") or artists[0].get("picture_big")
    return None


def lookup_album_cover(artist_name: str, release_name: str, caa_release_mbid: Optional[str] = None) -> Optional[str]:
    key = (artist_name.strip(), release_name.strip())
    if key in CUSTOM_ALBUM_URLS:
        return CUSTOM_ALBUM_URLS[key]

    if caa_release_mbid:
        caa_url = f"https://coverartarchive.org/release/{caa_release_mbid}/front-500"
        return caa_url

    query = urllib.parse.quote(f"{artist_name} {release_name}")
    data = _fetch_json(f"https://api.deezer.com/search/album?q={query}&limit=3", timeout=5)
    if data:
        albums = data.get("data", [])
        if albums:
            return albums[0].get("cover_xl") or albums[0].get("cover_big") or albums[0].get("cover_medium")
    return None


def _norm_title(title: str) -> str:
    t = (title or "").lower().replace("’", "'").replace("‘", "'")
    t = re.sub(r"\s*[\(\[].*?[\)\]]", "", t)
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return t


def lookup_album_release_year(artist_name: str, release_name: str) -> Optional[int]:
    """Resolve original release year via KNOWN_ALBUM_YEARS, iTunes Search, and Deezer."""
    key = (artist_name.strip(), release_name.strip())
    if key in KNOWN_ALBUM_YEARS:
        return KNOWN_ALBUM_YEARS[key]

    norm_alb = _norm_title(release_name)
    norm_art = _norm_title(artist_name)
    if not norm_alb:
        return None

    candidate_years: List[int] = []
    q = urllib.parse.quote(f"{artist_name} {release_name}")

    # 1. iTunes Search API (fast, reliable releaseDate, check multiple hits to catch original before remasters)
    itunes = _fetch_json(f"https://itunes.apple.com/search?term={q}&entity=album&limit=8", timeout=5)
    if itunes:
        for item in itunes.get("results", []):
            col_name = _norm_title(item.get("collectionName", ""))
            art_name = _norm_title(item.get("artistName", ""))
            rel_date = item.get("releaseDate", "")
            if not rel_date or len(rel_date) < 4:
                continue
            try:
                yr = int(rel_date[:4])
            except ValueError:
                continue
            if not (1920 <= yr <= datetime.now().year + 1):
                continue
            title_match = col_name == norm_alb or col_name.startswith(norm_alb + " ") or norm_alb.startswith(col_name + " ")
            art_match = not norm_art or norm_art in art_name or art_name in norm_art
            if title_match and art_match:
                candidate_years.append(yr)

    # 2. Deezer Album Search + Album Detail when needed
    if not candidate_years:
        dz = _fetch_json(f"https://api.deezer.com/search/album?q={q}&limit=4", timeout=5)
        if dz:
            for item in dz.get("data", []):
                dz_title = _norm_title(item.get("title", ""))
                dz_art = _norm_title((item.get("artist") or {}).get("name", ""))
                title_match = dz_title == norm_alb or dz_title.startswith(norm_alb + " ")
                art_match = not norm_art or norm_art in dz_art or dz_art in norm_art
                if title_match and art_match and item.get("id"):
                    detail = _fetch_json(f"https://api.deezer.com/album/{item['id']}", timeout=5)
                    if detail and detail.get("release_date"):
                        try:
                            yr = int(str(detail["release_date"])[:4])
                            if 1920 <= yr <= datetime.now().year + 1:
                                candidate_years.append(yr)
                        except ValueError:
                            pass
                    break

    return min(candidate_years) if candidate_years else None


def extract_country_from_wikipedia_text(extract_text: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not extract_text:
        return None, None
    text = extract_text.lower()
    for kw, (code, cname) in DEMONYM_MAP.items():
        pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(pattern, text):
            return code, cname
    return None, None


def resolve_artist_country(artist_name: str) -> Tuple[str, Optional[str], Optional[str]]:
    clean_name = artist_name.strip()
    if clean_name in KNOWN_ARTIST_COUNTRIES:
        return clean_name, KNOWN_ARTIST_COUNTRIES[clean_name][0], KNOWN_ARTIST_COUNTRIES[clean_name][1]

    queries = [
        f"{clean_name} (band)",
        f"{clean_name} (musician)",
        f"{clean_name} (singer)",
        clean_name,
    ]
    headers = {"User-Agent": USER_AGENT}

    for q in queries:
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(q)}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                code, cname = extract_country_from_wikipedia_text(data.get("extract", ""))
                if code and cname:
                    return clean_name, code, cname
        except Exception:
            continue

    return clean_name, None, None


def enrich_all_artist_countries(conn, limit: int = 120, min_plays: int = 2) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT a.artist_name
        FROM artists a
        LEFT JOIN listen_artist_credits c ON a.artist_name = c.artist_name
        WHERE (a.country_fetched IS NULL OR a.country_fetched = 0)
          AND (a.country_code IS NULL OR a.country_code = '')
        GROUP BY a.artist_name
        HAVING COUNT(c.id) >= ?
        ORDER BY COALESCE(SUM(c.duration_ms), 0) DESC
        LIMIT ?
        """,
        (min_plays, limit),
    )
    missing_artists = [r["artist_name"] for r in cur.fetchall()]
    if not missing_artists:
        return 0

    print(f"Resolving country metadata in parallel for {len(missing_artists)} artists...")
    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(resolve_artist_country, missing_artists))

    found_updates = [(code, cname, art) for art, code, cname in results if code and cname]
    all_checked = [(art,) for art, _, _ in results]
    if found_updates:
        cur.executemany(
            "UPDATE artists SET country_code = ?, country_name = ?, country_fetched = 1 WHERE artist_name = ?",
            found_updates,
        )
    if all_checked:
        cur.executemany(
            "UPDATE artists SET country_fetched = 1 WHERE artist_name = ? AND (country_fetched IS NULL OR country_fetched = 0)",
            all_checked,
        )
    conn.commit()
    print(f"Resolved country metadata for {len(found_updates)}/{len(missing_artists)} artists.")
    return len(found_updates)


def load_manual_entries(config_path: Optional[str] = None) -> List[Dict[str, Any]]:
    if config_path is None:
        config_path = os.path.join(DATA_SUBDIR, "manual_entries.json")
    if not os.path.exists(config_path):
        return []
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Failed to load manual entries from {config_path}: {e}")
        return []


def apply_manual_entries(conn) -> None:
    cur = conn.cursor()
    manual_entries = load_manual_entries()
    if not manual_entries:
        return

    cur.execute("DELETE FROM listens WHERE submission_client = 'manual_session'")
    for entry in manual_entries:
        art = canonicalize_artist_name(entry.get("artist_name"))
        rel = canonicalize_release_name(art, entry.get("release_name"))
        trk = canonicalize_track_name(art, entry.get("track_name"), rel)
        dur_mins = entry.get("duration_minutes", 0)
        dur_ms = int(dur_mins * 60000)
        yr = entry.get("year", 2026)
        mo = entry.get("month", 8)
        listened_at = 1788243600

        cur.execute(
            """
            INSERT INTO listens (
                listened_at, artist_name, track_name, release_name, duration_ms,
                submission_client, year, month, day, hour, day_of_week, original_release_year
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (listened_at, art, trk, rel, dur_ms, "manual_session", yr, mo, 15, 12, 1, yr),
        )

        img_url = entry.get("cover_url")
        c_code = entry.get("country_code")
        c_name = entry.get("country_name")
        loc_img = save_image_http(img_url, "artist", art) if img_url else None

        cur.execute(
            """
            INSERT OR REPLACE INTO artists (
                artist_name, image_url, image_local_path, image_fetched, country_code, country_name, country_fetched
            ) VALUES (?, ?, ?, 1, ?, ?, 1)
            """,
            (art, img_url, loc_img, c_code, c_name),
        )

        if loc_img:
            alb_loc = save_image_http(img_url, "album", f"{art}_{rel}")
            cur.execute(
                """
                INSERT OR REPLACE INTO albums (
                    artist_name, release_name, cover_url, cover_local_path, cover_fetched, original_release_year, year_fetched
                ) VALUES (?, ?, ?, ?, 1, ?, 1)
                """,
                (art, rel, img_url, alb_loc, yr),
            )

    conn.commit()


def refresh_artist_credits(conn) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS listen_artist_credits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listen_id INTEGER NOT NULL,
            artist_name TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            listened_at INTEGER,
            year INTEGER,
            month INTEGER
        )
        """
    )
    cur.execute("DELETE FROM listen_artist_credits")

    cur.execute("SELECT id, artist_name, duration_ms, listened_at, year, month FROM listens")
    listens = cur.fetchall()

    credits_to_insert = []
    for l in listens:
        for a in split_artist_names(l["artist_name"]):
            credits_to_insert.append(
                (l["id"], canonicalize_artist_name(a), l["duration_ms"], l["listened_at"], l["year"], l["month"])
            )

    cur.executemany(
        "INSERT INTO listen_artist_credits (listen_id, artist_name, duration_ms, listened_at, year, month) VALUES (?, ?, ?, ?, ?, ?)",
        credits_to_insert,
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_credits_artist ON listen_artist_credits(artist_name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_credits_time ON listen_artist_credits(listened_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_credits_ym ON listen_artist_credits(year, month)")

    cur.execute(
        """
        INSERT OR IGNORE INTO artists (artist_name)
        SELECT DISTINCT artist_name FROM listen_artist_credits WHERE artist_name NOT IN (SELECT artist_name FROM artists)
        """
    )
    conn.commit()


def _collect_jsonl_files(data_dir: Optional[str]) -> List[str]:
    if not data_dir or not os.path.isdir(data_dir):
        return []
    files = set(glob.glob(os.path.join(data_dir, "listens", "*", "*.jsonl")))
    files.update(glob.glob(os.path.join(data_dir, "listens", "*.jsonl")))
    files.update(glob.glob(os.path.join(data_dir, "*.jsonl")))
    return sorted(files)


def import_all_listens(db_path: str = DB_PATH, data_dir: Optional[str] = None) -> Dict[str, Any]:
    init_db(db_path)
    target_dir = data_dir or get_active_data_dir()
    files = _collect_jsonl_files(target_dir)

    records_to_insert = []
    unique_artists: set[str] = set()
    album_mbid_meta: Dict[Tuple[str, str], Tuple[Optional[str], Optional[str]]] = {}
    artist_mbid_meta: Dict[str, str] = {}

    for file_path in files:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue

                listened_at = obj.get("listened_at")
                metadata = obj.get("track_metadata", {})
                raw_artist_name = metadata.get("artist_name")
                raw_track_name = metadata.get("track_name")
                raw_release_name = metadata.get("release_name")

                if not listened_at or not raw_artist_name or not raw_track_name:
                    continue

                listened_at_int = int(listened_at)

                if is_excluded_listen(raw_artist_name, raw_track_name, raw_release_name):
                    continue

                artist_name = canonicalize_artist_name(raw_artist_name, raw_release_name, raw_track_name) or raw_artist_name
                release_name = canonicalize_release_name(artist_name, raw_release_name) if raw_release_name else None
                track_name = canonicalize_track_name(artist_name, raw_track_name, release_name) or raw_track_name

                if is_excluded_listen(artist_name, track_name, release_name):
                    continue

                add_info = metadata.get("additional_info") or {}
                mbid_map = metadata.get("mbid_mapping") or {}

                duration_ms = add_info.get("duration_ms") or 0
                if not duration_ms and add_info.get("duration"):
                    duration_ms = int(float(add_info.get("duration")) * 1000)
                if not duration_ms:
                    duration_ms = 210000

                if artist_name.lower() == "tool" and track_name.lower() == "descending":
                    duration_ms = max(0, duration_ms - 70000)

                recording_mbid = add_info.get("recording_mbid") or mbid_map.get("recording_mbid")
                release_mbid = add_info.get("release_mbid") or mbid_map.get("release_mbid")
                caa_release_mbid = add_info.get("caa_release_mbid") or mbid_map.get("caa_release_mbid")
                raw_caa_id = add_info.get("caa_id") or mbid_map.get("caa_id")
                caa_id = str(raw_caa_id) if raw_caa_id else None
                ambids = add_info.get("artist_mbids") or mbid_map.get("artist_mbids") or []
                artist_mbids_json = json.dumps(ambids)
                submission_client = add_info.get("submission_client")

                dt = datetime.fromtimestamp(listened_at_int)
                records_to_insert.append((
                    listened_at_int, artist_name, track_name, release_name, int(duration_ms),
                    recording_mbid, release_mbid, caa_release_mbid, caa_id,
                    artist_mbids_json, submission_client,
                    dt.year, dt.month, dt.day, dt.hour, dt.weekday(),
                ))

                unique_artists.add(artist_name)
                if len(ambids) == 1 and ambids[0] and artist_name not in artist_mbid_meta:
                    artist_mbid_meta[artist_name] = ambids[0]
                for split_a in split_artist_names(artist_name):
                    unique_artists.add(split_a)

                if release_name:
                    key = (artist_name, release_name)
                    prev = album_mbid_meta.get(key)
                    if prev is None or (not prev[1] and caa_release_mbid):
                        album_mbid_meta[key] = (release_mbid, caa_release_mbid)

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        before_count = cursor.execute("SELECT COUNT(*) FROM listens").fetchone()[0]

        cursor.executemany(
            """
            INSERT OR IGNORE INTO listens (
                listened_at, artist_name, track_name, release_name, duration_ms,
                recording_mbid, release_mbid, caa_release_mbid, caa_id,
                artist_mbids, submission_client,
                year, month, day, hour, day_of_week
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records_to_insert,
        )

        cursor.executemany(
            "INSERT OR IGNORE INTO artists (artist_name) VALUES (?)",
            [(a,) for a in unique_artists],
        )
        if artist_mbid_meta:
            cursor.executemany(
                "UPDATE artists SET artist_mbid = COALESCE(artist_mbid, ?) WHERE artist_name = ?",
                [(mbid, art) for art, mbid in artist_mbid_meta.items()],
            )

        cursor.executemany(
            "INSERT OR IGNORE INTO albums (artist_name, release_name) VALUES (?, ?)",
            list(album_mbid_meta.keys()),
        )
        mbid_album_updates = [
            (rmbid, caa_mbid, art, rel)
            for (art, rel), (rmbid, caa_mbid) in album_mbid_meta.items()
            if rmbid or caa_mbid
        ]
        if mbid_album_updates:
            cursor.executemany(
                """
                UPDATE albums
                SET release_mbid = COALESCE(release_mbid, ?),
                    caa_release_mbid = COALESCE(caa_release_mbid, ?)
                WHERE artist_name = ? AND release_name = ?
                """,
                mbid_album_updates,
            )

        conn.commit()
        apply_manual_entries(conn)
        refresh_artist_credits(conn)
        after_count = cursor.execute("SELECT COUNT(*) FROM listens").fetchone()[0]

    return {
        "new_scrobbles": max(0, after_count - before_count),
        "total_listens": after_count,
        "files_scanned": len(files),
        "data_dir": target_dir,
        "username": read_export_username(target_dir),
    }


def enrich_all_metadata(
    db_path: str = DB_PATH,
    force_refetch: bool = False,
    max_batch: int = 40,
    min_plays: int = 2,
) -> None:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        # 1. Instant local maps
        cursor.executemany(
            "UPDATE artists SET country_code = ?, country_name = ?, country_fetched = 1 WHERE artist_name = ?",
            [(code, cname, artist) for artist, (code, cname) in KNOWN_ARTIST_COUNTRIES.items()],
        )
        cursor.executemany(
            "UPDATE albums SET original_release_year = ?, year_fetched = 1 WHERE artist_name = ? AND release_name = ?",
            [(yr, art, alb) for (art, alb), yr in KNOWN_ALBUM_YEARS.items()],
        )

        # Custom artist/album URLs (only download missing local files)
        missing_art_custom = [
            (art, url)
            for art, url in CUSTOM_ARTIST_URLS.items()
            if not is_valid_image_file(os.path.join(STATIC_CACHE_DIR, f"artist_{get_hash(art)}.jpg"))
        ]
        missing_alb_custom = [
            ((art, alb), url)
            for (art, alb), url in CUSTOM_ALBUM_URLS.items()
            if not is_valid_image_file(os.path.join(STATIC_CACHE_DIR, f"album_{get_hash(f'{art}_{alb}')}.jpg"))
        ]

        if missing_art_custom or missing_alb_custom:
            def _dl_artist_custom(item):
                art, url = item
                return art, url, save_image_http(url, "artist", art)

            def _dl_album_custom(item):
                (art, alb), url = item
                return art, alb, url, save_image_http(url, "album", f"{art}_{alb}")

            with ThreadPoolExecutor(max_workers=8) as ex:
                for art, url, loc in ex.map(_dl_artist_custom, missing_art_custom):
                    if loc:
                        cursor.execute(
                            "UPDATE artists SET image_url = ?, image_local_path = ?, image_fetched = 1 WHERE artist_name = ?",
                            (url, loc, art),
                        )
                for art, alb, url, loc in ex.map(_dl_album_custom, missing_alb_custom):
                    if loc:
                        cursor.execute(
                            "UPDATE albums SET cover_url = ?, cover_local_path = ?, cover_fetched = 1 WHERE artist_name = ? AND release_name = ?",
                            (url, loc, art, alb),
                        )

        conn.commit()

        # 2. Top Artists Image Enrichment (parallel, skips already-fetched unless forced)
        art_filter = "1=1" if force_refetch else "(a.image_fetched IS NULL OR a.image_fetched = 0)"
        cursor.execute(
            f"""
            SELECT c.artist_name
            FROM listen_artist_credits c
            LEFT JOIN artists a ON c.artist_name = a.artist_name
            WHERE (a.image_local_path IS NULL OR a.image_local_path = '') AND {art_filter}
            GROUP BY c.artist_name
            HAVING COUNT(*) >= ?
            ORDER BY SUM(c.duration_ms) DESC
            LIMIT ?
            """,
            (min_plays, max_batch),
        )
        artists_to_fetch = [r["artist_name"] for r in cursor.fetchall()]

        if artists_to_fetch:
            print(f"Fetching portraits in parallel for {len(artists_to_fetch)} artists...")
            def _fetch_artist(art: str):
                url = lookup_artist_image(art)
                loc = save_image_http(url, "artist", art) if url else None
                return art, url, loc

            with ThreadPoolExecutor(max_workers=12) as ex:
                for art, url, loc in ex.map(_fetch_artist, artists_to_fetch):
                    if loc:
                        cursor.execute(
                            "UPDATE artists SET image_url = ?, image_local_path = ?, image_fetched = 1 WHERE artist_name = ?",
                            (url, loc, art),
                        )
                    else:
                        cursor.execute("UPDATE artists SET image_fetched = 1 WHERE artist_name = ?", (art,))
            conn.commit()

        # 3. Top Albums Cover Enrichment (parallel)
        cov_filter = "1=1" if force_refetch else "(al.cover_fetched IS NULL OR al.cover_fetched = 0)"
        cursor.execute(
            f"""
            SELECT l.artist_name, l.release_name, MAX(al.caa_release_mbid) AS caa_release_mbid
            FROM listens l
            JOIN albums al ON l.artist_name = al.artist_name AND l.release_name = al.release_name
            WHERE (al.cover_local_path IS NULL OR al.cover_local_path = '')
              AND l.release_name IS NOT NULL AND l.release_name != ''
              AND {cov_filter}
            GROUP BY l.artist_name, l.release_name
            HAVING COUNT(*) >= ?
            ORDER BY SUM(l.duration_ms) DESC
            LIMIT ?
            """,
            (min_plays, max_batch),
        )
        albums_to_fetch = cursor.fetchall()

        if albums_to_fetch:
            print(f"Fetching covers in parallel for {len(albums_to_fetch)} albums...")
            def _fetch_album_cover(row):
                art, alb, caa = row["artist_name"], row["release_name"], row["caa_release_mbid"]
                url = lookup_album_cover(art, alb, caa_release_mbid=caa)
                loc = save_image_http(url, "album", f"{art}_{alb}") if url else None
                if not loc and caa:
                    url = lookup_album_cover(art, alb, caa_release_mbid=None)
                    loc = save_image_http(url, "album", f"{art}_{alb}") if url else None
                return art, alb, url, loc

            with ThreadPoolExecutor(max_workers=12) as ex:
                for art, alb, url, loc in ex.map(_fetch_album_cover, albums_to_fetch):
                    if loc:
                        cursor.execute(
                            "UPDATE albums SET cover_url = ?, cover_local_path = ?, cover_fetched = 1 WHERE artist_name = ? AND release_name = ?",
                            (url, loc, art, alb),
                        )
                    else:
                        cursor.execute(
                            "UPDATE albums SET cover_fetched = 1 WHERE artist_name = ? AND release_name = ?",
                            (art, alb),
                        )
            conn.commit()

        # 4. Album Original Release Year Enrichment (parallel)
        yr_filter = "1=1" if force_refetch else "(al.year_fetched IS NULL OR al.year_fetched = 0)"
        cursor.execute(
            f"""
            SELECT l.artist_name, l.release_name
            FROM listens l
            JOIN albums al ON l.artist_name = al.artist_name AND l.release_name = al.release_name
            WHERE al.original_release_year IS NULL
              AND l.release_name IS NOT NULL AND l.release_name != ''
              AND {yr_filter}
            GROUP BY l.artist_name, l.release_name
            HAVING COUNT(*) >= ?
            ORDER BY SUM(l.duration_ms) DESC
            LIMIT ?
            """,
            (min_plays, max_batch * 2),
        )
        years_to_fetch = cursor.fetchall()

        if years_to_fetch:
            print(f"Resolving release years in parallel for {len(years_to_fetch)} albums...")
            def _fetch_year(row):
                art, alb = row["artist_name"], row["release_name"]
                yr = lookup_album_release_year(art, alb)
                return art, alb, yr

            with ThreadPoolExecutor(max_workers=12) as ex:
                for art, alb, yr in ex.map(_fetch_year, years_to_fetch):
                    if yr:
                        cursor.execute(
                            "UPDATE albums SET original_release_year = ?, year_fetched = 1 WHERE artist_name = ? AND release_name = ?",
                            (yr, art, alb),
                        )
                    else:
                        cursor.execute(
                            "UPDATE albums SET year_fetched = 1 WHERE artist_name = ? AND release_name = ?",
                            (art, alb),
                        )
            conn.commit()

        # 5. Artist Country Enrichment (parallel)
        enrich_all_artist_countries(conn, limit=max_batch, min_plays=min_plays)


def migrate_and_canonicalize_db(db_path: str = DB_PATH, run_enrich: bool = True) -> None:
    print("Running database canonicalization & cleanup...")
    with get_connection(db_path) as conn:
        cur = conn.cursor()

        cur.execute("SELECT id, artist_name, track_name, release_name FROM listens")
        all_listens = cur.fetchall()
        to_delete = [
            row["id"]
            for row in all_listens
            if is_excluded_listen(row["artist_name"], row["track_name"], row["release_name"])
        ]
        if to_delete:
            cur.executemany("DELETE FROM listens WHERE id = ?", [(i,) for i in to_delete])
            cur.executemany("DELETE FROM listen_artist_credits WHERE listen_id = ?", [(i,) for i in to_delete])

        canonical_map = {
            "queens of the stone age": "Queens of the Stone Age",
            "30 seconds to mars": "30 Seconds To Mars",
            "bring me the horizon": "Bring Me The Horizon",
            "bullet for my valentine": "Bullet For My Valentine",
            "charli xcx": "Charli xcx",
            "puddle of mudd": "Puddle of Mudd",
            "stick to your guns": "Stick to Your Guns",
            "system of a down": "System Of A Down",
            "rosalía": "Rosalía",
            "rosalia": "Rosalía",
            "mgk": "mgk",
            "boards of canada": "Boards Of Canada",
            "birds of tokyo": "Birds Of Tokyo",
            "[:sitd:]": "[:sitd:]",
        }
        for art_lower, canonical in canonical_map.items():
            cur.execute("UPDATE listens SET artist_name = ? WHERE LOWER(artist_name) = ? AND artist_name != ?", (canonical, art_lower, canonical))
            cur.execute("UPDATE listen_artist_credits SET artist_name = ? WHERE LOWER(artist_name) = ? AND artist_name != ?", (canonical, art_lower, canonical))

            non_canon_rows = cur.execute(
                "SELECT * FROM artists WHERE artist_name != ? AND LOWER(artist_name) = ?",
                (canonical, art_lower),
            ).fetchall()
            if non_canon_rows:
                cur.execute("INSERT OR IGNORE INTO artists (artist_name) VALUES (?)", (canonical,))
                for ncr in non_canon_rows:
                    if ncr["image_local_path"]:
                        cur.execute(
                            "UPDATE artists SET image_url = COALESCE(image_url, ?), image_local_path = COALESCE(image_local_path, ?), image_fetched = 1 WHERE artist_name = ?",
                            (ncr["image_url"], ncr["image_local_path"], canonical),
                        )
                    if ncr["country_code"]:
                        cur.execute(
                            "UPDATE artists SET country_code = COALESCE(country_code, ?), country_name = COALESCE(country_name, ?), country_fetched = 1 WHERE artist_name = ?",
                            (ncr["country_code"], ncr["country_name"], canonical),
                        )
                cur.execute("DELETE FROM artists WHERE artist_name != ? AND LOWER(artist_name) = ?", (canonical, art_lower))

            cur.execute(
                "UPDATE albums SET artist_name = ? WHERE artist_name != ? AND LOWER(artist_name) = ? AND release_name NOT IN (SELECT release_name FROM albums WHERE artist_name = ?)",
                (canonical, canonical, art_lower, canonical),
            )
            cur.execute("DELETE FROM albums WHERE artist_name != ? AND LOWER(artist_name) = ?", (canonical, art_lower))

        def safe_merge_artist(target_artist: str, condition_sql: str):
            cur.execute(f"SELECT id, listened_at, track_name FROM listens WHERE ({condition_sql}) AND artist_name != ?", (target_artist,))
            for r in cur.fetchall():
                conflict = cur.execute(
                    "SELECT id FROM listens WHERE listened_at = ? AND artist_name = ? AND track_name = ? AND id != ?",
                    (r["listened_at"], target_artist, r["track_name"], r["id"]),
                ).fetchone()
                if conflict:
                    cur.execute("DELETE FROM listens WHERE id = ?", (r["id"],))
                else:
                    cur.execute("UPDATE listens SET artist_name = ? WHERE id = ?", (target_artist, r["id"]))

        safe_merge_artist("Will Ramos & Nik Nocturnal", "track_name LIKE '%Chokehold%' AND (artist_name = 'Will Ramos' OR artist_name LIKE '%Nik Nocturnal%' OR artist_name LIKE '%Nik Nokturnal%')")
        safe_merge_artist("Milton Nascimento & Lô Borges", "release_name = 'Clube da Esquina' OR artist_name IN ('Milton Nascimento', 'Milton Nascimento • Lô Borges', 'Milton Nascimento & Lo Borges')")
        safe_merge_artist("Shye Ben Tzur, Jonny Greenwood and The Rajasthan Express", "release_name = 'Junun' OR artist_name = 'Shye Ben Tzur'")

        cur.execute("SELECT id, artist_name, track_name, release_name FROM listens")
        track_updates = []
        for row in cur.fetchall():
            c_art = canonicalize_artist_name(row["artist_name"])
            c_rel = canonicalize_release_name(c_art, row["release_name"])
            c_trk = canonicalize_track_name(c_art, row["track_name"], c_rel)
            if c_art != row["artist_name"] or c_rel != row["release_name"] or c_trk != row["track_name"]:
                track_updates.append((c_art, c_trk, c_rel, row["id"]))

        if track_updates:
            for c_art, c_trk, c_rel, row_id in track_updates:
                try:
                    cur.execute(
                        "UPDATE listens SET artist_name = ?, track_name = ?, release_name = ? WHERE id = ?",
                        (c_art, c_trk, c_rel, row_id),
                    )
                except Exception:
                    cur.execute("DELETE FROM listens WHERE id = ?", (row_id,))

        cur.execute(
            """
            INSERT OR IGNORE INTO albums (artist_name, release_name)
            SELECT DISTINCT artist_name, release_name FROM listens WHERE release_name IS NOT NULL AND release_name != ''
            """
        )

        cur.execute(
            """
            DELETE FROM albums
            WHERE (artist_name, release_name) NOT IN (
                SELECT DISTINCT artist_name, release_name FROM listens WHERE release_name IS NOT NULL AND release_name != ''
            )
            """
        )

        cur.execute(
            """
            UPDATE listens
            SET duration_ms = duration_ms - 70000
            WHERE LOWER(artist_name) = 'tool' AND LOWER(track_name) = 'descending' AND duration_ms > 750000
            """
        )

        conn.commit()
        apply_manual_entries(conn)
        refresh_artist_credits(conn)
        cur.execute("DELETE FROM artists WHERE artist_name NOT IN (SELECT DISTINCT artist_name FROM listen_artist_credits)")
        conn.commit()

    if run_enrich:
        enrich_all_metadata(db_path)


def sync_data(
    db_path: str = DB_PATH,
    data_dir: Optional[str] = None,
    force_refetch: bool = False,
    full_enrich: bool = False,
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    target_dir = data_dir or get_active_data_dir()
    imp_res = import_all_listens(db_path=db_path, data_dir=target_dir)
    migrate_and_canonicalize_db(db_path=db_path, run_enrich=False)
    enrich_all_metadata(
        db_path=db_path,
        force_refetch=force_refetch,
        max_batch=160 if full_enrich else 40,
        min_plays=1 if full_enrich else 2,
    )
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    imp_res.update({
        "status": "ok",
        "synced_at": datetime.now().isoformat(),
        "elapsed_ms": elapsed_ms,
    })
    return imp_res


if __name__ == "__main__":
    active = get_active_data_dir()
    print(f"Using ListenBrainz export directory: {active}")
    res = sync_data(data_dir=active)
    print(f"Sync complete in {res['elapsed_ms']} ms: {res}")
