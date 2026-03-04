import re
import json
import csv
import os
from html import unescape

def html_to_text(html_content):
    if not html_content:
        return ''
    # Replace block-level tags and line breaks with newlines
    text = re.sub(r'<\s*(br\s*/?|/p|/div|/h[1-6]|/li|/tr)[^>]*>', '\n', html_content, flags=re.IGNORECASE)
    # Remove all other HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Unescape HTML entities
    text = unescape(text)
    # Clean up whitespace
    lines = text.split('\n')
    cleaned_lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in lines]
    text = '\n'.join(cleaned_lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def clean_text(text):
    if not text:
        return ''
    if not isinstance(text, str):
        text = str(text)
    text = unescape(text)
    text = text.replace('’', "'").replace('‘', "'")
    text = text.replace('”', '"').replace('“', '"')
    text = text.replace('–', '-').replace('—', '-')
    text = text.replace('…', '...')
    text = text.replace('\x00', '')
    return text.strip()

def load_aliases():
    aliases = {}
    display_aliases = {}
    
    # Load translation aliases (e.g., "Bearded Millenial" -> "bm")
    try:
        with open('import/aliases.json', 'r', encoding='utf-8-sig', errors='ignore') as f:
            raw_aliases = json.load(f)
            for k, v in raw_aliases.items():
                clean_k = re.sub(r'[^a-zA-Z0-9]', '', k.lower())
                clean_v = re.sub(r'[^a-zA-Z0-9]', '', v.lower())
                aliases[clean_k] = clean_v
    except (FileNotFoundError, json.JSONDecodeError):
        pass
        
    # Load display aliases for logging/reporting
    try:
        with open('import/display_aliases.json', 'r', encoding='utf-8') as f:
            display_aliases = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
        
    return aliases, display_aliases

def normalize_user(name, user_aliases):
    if not name:
        return ''
    cleaned = clean_text(name).lstrip('@')
    if not cleaned:
        return ''
    # Strip parentheticals
    cleaned = re.sub(r'\(.*?\)', '', cleaned)
    # Strip common suffixes
    cleaned = re.sub(r'(?i)\bqic\b', '', cleaned)
    cleaned = re.sub(r'(?i)\bfngs?\b', '', cleaned)
    # Alphanumeric only
    lowercased = cleaned.lower()
    lowercased = re.sub(r'[^a-zA-Z0-9]', '', lowercased)
    
    if lowercased in user_aliases:
        return user_aliases[lowercased]
    return lowercased

def format_time(time_str):
    if not time_str:
        return ''
    time_str = str(time_str).strip().lower()
    match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', time_str)
    if not match:
        return ''
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    ampm = match.group(3)
    if ampm == 'pm' and hour < 12:
        hour += 12
    elif ampm == 'am' and hour == 12:
        hour = 0
    return f"{hour:02d}{minute:02d}"

def load_locations(locations_csv):
    locations = {}
    weekday_map = {}
    if not os.path.exists(locations_csv):
        return locations, weekday_map
        
    with open(locations_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            workout = row.get('Workout', '').strip()
            if workout:
                locations[workout] = {
                    'org_id': row.get('orgId', '').replace(',', ''),
                    'location_id': row.get('locationId', '').replace(',', ''),
                    'start_time': format_time(row.get('startTime', '')),
                    'weekday': row.get('weekDay', '').strip()
                }
                weekday = row.get('weekDay', '').strip()
                if weekday:
                    weekday_map[weekday] = workout
    return locations, weekday_map
