import xml.etree.ElementTree as ET
import csv
import os
import re
from html import unescape
from email.utils import parsedate_to_datetime
from datetime import datetime
import glob

def html_to_text(html_content):
    if not html_content:
        return ''
    
    # Replace block-level tags and line breaks with newlines to maintain readability
    text = re.sub(r'<\s*(br\s*/?|/p|/div|/h[1-6]|/li|/tr)[^>]*>', '\n', html_content, flags=re.IGNORECASE)
    
    # Remove all other HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Unescape HTML entities like &nbsp;, &amp;
    text = unescape(text)
    
    # Clean up whitespace: replace multiple spaces with single space
    lines = text.split('\n')
    cleaned_lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in lines]
    
    # Join lines and collapse multiple newlines to max two (paragraphs)
    text = '\n'.join(cleaned_lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

def clean_text(text):
    if not text:
        return ''
        
    # Unescape HTML entities
    text = unescape(text)
    
    # Replace smart quotes and similar problematic typographic characters
    text = text.replace('’', "'").replace('‘', "'")
    text = text.replace('”', '"').replace('“', '"')
    text = text.replace('–', '-').replace('—', '-')
    text = text.replace('…', '...')
    
    # Remove null bytes and other control chars that might break CSV loaders
    text = text.replace('\x00', '')
    return text.strip()

import json

def load_aliases():
    try:
        with open('import/aliases.json', 'r', encoding='utf-8') as f:
            aliases = json.load(f)
    except FileNotFoundError:
        aliases = {}
        
    try:
        with open('import/display_aliases.json', 'r', encoding='utf-8') as f:
            display_aliases = json.load(f)
    except FileNotFoundError:
        display_aliases = {}
        
    return aliases, display_aliases

USER_ALIASES, DISPLAY_ALIASES = load_aliases()

def normalize_user(name):
    if not name:
        return ''
    
    # Clean text and remove common `@` tagging
    cleaned = clean_text(name).lstrip('@')
    if not cleaned:
        return ''
        
    # Strip parentheticals entirely
    cleaned = re.sub(r'\(.*?\)', '', cleaned)
    
    # Lowercase to prevent case fragmentation (e.g. Woz vs woz)
    lowercased = cleaned.lower().strip()
    
    # Strip isolating suffixes/prefixes like QIC and FNG
    lowercased = re.sub(r'\bqic\b', '', lowercased)
    lowercased = re.sub(r'\bfngs?\b', '', lowercased)
    
    lowercased = lowercased.strip()
    
    # Resolve against canonical alias mapping
    if lowercased in USER_ALIASES:
        return USER_ALIASES[lowercased]
        
    return lowercased

def format_time(time_str):
    if not time_str:
        return ''
    time_str = time_str.strip().lower()
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
        print(f"Warning: {locations_csv} not found. Location mappings will fail.")
        return locations, weekday_map
        
    with open(locations_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            workout = row.get('Workout', '').strip()
            if workout:
                locations[workout] = {
                    'org_id': row.get('orgId', ''),
                    'location_id': row.get('locationId', ''),
                    'start_time': format_time(row.get('startTime', ''))
                }
                
                weekday = row.get('weekDay', '').strip()
                if weekday:
                    weekday_map[weekday] = workout
    return locations, weekday_map

def convert_xml_to_csv(xml_file, locations_csv, output_csv):
    # Namespace dictionary
    ns = {
        'content': 'http://purl.org/rss/1.0/modules/content/',
        'dc': 'http://purl.org/dc/elements/1.1/',
        'wp': 'http://wordpress.org/export/1.2/'
    }

    if not os.path.exists(xml_file):
        print(f"Error: {xml_file} not found.")
        return

    locations_map, weekday_map = load_locations(locations_csv)
    
    paxminer_slack_ids = {}
    pm_user_files = glob.glob('import/PAXminer_users_*.csv')
    if pm_user_files:
        with open(pm_user_files[0], 'r', encoding='utf-8-sig', errors='ignore') as f:
            for row in csv.DictReader(f):
                disp = normalize_user(row.get('user_name', ''))
                slack_id = row.get('user_id', '').strip()
                if disp and slack_id:
                    paxminer_slack_ids[disp] = slack_id
                    
    # Pre-build lookup map: normalized_name -> database id
    canonical_id_map = {}
    
    try:
        with open('import/user_master.csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
            for row in csv.DictReader(f):
                fname = normalize_user(row.get('f3_name', ''))
                uid = row.get('id', '')
                if fname and uid:
                    canonical_id_map[fname] = uid
    except Exception as e:
        print(f"Warning: Failed to load import/user_master.csv. ID mappings will be missing! {e}")

    user_id_map = {}
    next_unmatched_id = 1
    unmatched_users_data = {}  # Store unmatched users to write out later
    
    # 1. First Pass: Cache WP Author Metadata so we know who is who if they go unmatched
    wp_authors = {}
    tree = ET.parse(xml_file)
    root = tree.getroot()
    
    # The authors are typically under channel -> wp:author
    channel = root.find('.//channel')
    if channel is not None:
        for author in channel.findall('wp:author', namespaces=ns):
            login = author.findtext('wp:author_login', namespaces=ns)
            if login:
                wp_authors[login.lower()] = {
                    'email': author.findtext('wp:author_email', namespaces=ns) or '',
                    'first_name': author.findtext('wp:author_first_name', namespaces=ns) or '',
                    'last_name': author.findtext('wp:author_last_name', namespaces=ns) or '',
                    'display_name': author.findtext('wp:author_display_name', namespaces=ns) or ''
                }
    
    def extract_explicit_date_and_ao(text, locations_map):
        if not text:
            return None, None
            
        date_patterns = [
            r'(Jan(?:uary|\.)?|Feb(?:ruary|\.)?|Mar(?:ch|\.)?|Apr(?:il|\.)?|May|Jun(?:e|\.)?|Jul(?:y|\.)?|Aug(?:ust|\.)?|Sep(?:tember|\.|t\.)?|Oct(?:ober|\.)?|Nov(?:ember|\.)?|Dec(?:ember|\.)?)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,)?\s+(\d{4})',
            r'(\d{1,2})/(\d{1,2})/(\d{4})',
            r'(\d{4})-(\d{2})-(\d{2})'
        ]
        
        found_date = None
        for pat in date_patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) == 3:
                    try:
                        if groups[0].isdigit() and len(groups[0]) == 4:
                            found_date = f"{groups[0]}-{int(groups[1]):02d}-{int(groups[2]):02d}"
                        elif groups[0].isdigit():
                            found_date = f"{groups[2]}-{int(groups[0]):02d}-{int(groups[1]):02d}"
                        else:
                            month_str = groups[0][:3].title()
                            month_num = datetime.strptime(month_str, '%b').month
                            found_date = f"{groups[2]}-{month_num:02d}-{int(groups[1]):02d}"
                        break
                    except:
                        pass
        
        found_ao = None
        for ao in locations_map.keys():
            if ao.lower() in text.lower():
                if not found_ao or len(ao) > len(found_ao):
                    found_ao = ao
                    
        return found_date, found_ao

    def get_or_create_user_id(name):
        nonlocal next_unmatched_id
        normalized_name = normalize_user(name)
        if not normalized_name:
            return ''
            
        if normalized_name in canonical_id_map:
            return canonical_id_map[normalized_name]
            
        if normalized_name in user_id_map:
            return user_id_map[normalized_name]
            
        # Create a new TMP_ID
        new_id = f"TMP_ID_{next_unmatched_id}"
        next_unmatched_id += 1
        user_id_map[normalized_name] = new_id
        
        # Try to pull email from WP metadata
        email_addr = ''
        if normalized_name in wp_authors:
            email_addr = wp_authors[normalized_name].get('email', '')
            
        unmatched_users_data[new_id] = {
            'id': new_id,
            'f3_name': name.strip(),
            'email': email_addr
        }
        
        return new_id

    # Find all WP items
    items = root.findall('.//item')
    
    out_data = []
    global_seen_attendances = set()
    
    for item in items:
        post_type = item.findtext('wp:post_type', namespaces=ns)
        # Skip attachments, pages, nav_menu_items, etc. We only want posts.
        if post_type != 'post':
            continue
            
        title_raw = item.findtext('title') or ''
        title = clean_text(title_raw).replace('\r', ' ').replace('\n', ' ')
        title = ' '.join(title.split()) # collapse whitespace

        status = item.findtext('wp:status', namespaces=ns)
        
        # Parse Dates
        pub_date_str = item.findtext('pubDate')
        start_date = ''
        weekday_name = ''
        
        if status == 'draft':
            db_date = item.findtext('wp:post_date', namespaces=ns)
            if not db_date or db_date == '0000-00-00 00:00:00':
                db_date = item.findtext('wp:post_modified', namespaces=ns)
                
            if db_date and db_date != '0000-00-00 00:00:00':
                try:
                    dt = datetime.strptime(db_date, '%Y-%m-%d %H:%M:%S')
                    start_date = dt.strftime('%Y-%m-%d')
                    weekday_name = dt.strftime('%A')
                except Exception as e:
                    print(f"Warning: Failed to parse draft date '{db_date}': {e}")
        elif pub_date_str:
            try:
                dt = parsedate_to_datetime(pub_date_str)
                start_date = dt.strftime('%Y-%m-%d')
                weekday_name = dt.strftime('%A')
            except Exception as e:
                print(f"Warning: Failed to parse date '{pub_date_str}': {e}")
                
        # Parse Creator (Q)
        creator = clean_text(item.findtext('dc:creator', namespaces=ns))
        
        # Parse Backblast content
        raw_content = item.findtext('content:encoded', namespaces=ns)
        backblast = clean_text(html_to_text(raw_content))
        
        # Heuristic to detect if the author pasted the whole post into the title box
        if len(title) > 100 and len(backblast) < 50:
            backblast = title
        
        # Categories and Tags
        categories = []
        tags = []
        
        for cat in item.findall('category'):
            domain = cat.attrib.get('domain')
            text = clean_text(cat.text)
            if domain == 'category' and text:
                categories.append(text)
            elif domain == 'post_tag' and text:
                tags.append(text)
                
        # Use first category as the Workout name to map location
        workout_name = categories[0] if categories else ''
        
        # Check text for explicit overrides
        explicit_date, explicit_ao = extract_explicit_date_and_ao(title + " " + backblast[:200], locations_map)
        
        if explicit_date:
            start_date = explicit_date
            try:
                dt = datetime.strptime(start_date, '%Y-%m-%d')
                weekday_name = dt.strftime('%A')
            except:
                pass
        
        if explicit_ao and (not workout_name or workout_name.lower() == 'uncategorized'):
            workout_name = explicit_ao
        elif (not workout_name or workout_name.lower() == 'uncategorized') and weekday_name in weekday_map:
            workout_name = weekday_map[weekday_name]
            
        key = (start_date.strip(), workout_name.strip().lower() if workout_name else '')
        
        loc_data = locations_map.get(workout_name, {})
        
        # Look for a default fallback in the locations_map if this is uncategorized/unrecognized
        default_org_id = next((v['org_id'] for v in locations_map.values() if v.get('org_id')), '37004')
        default_loc_id = next((v['location_id'] for v in locations_map.values() if v.get('location_id')), '123')
        
        org_id = loc_data.get('org_id', '') or default_org_id
        location_id = loc_data.get('location_id', '') or default_loc_id
        start_time = loc_data.get('start_time', '')
        
        # Collect all attending PAX (Creator is assumed to just be an attendee, tags are attendees)
        # We need a unique set of PAX per event to avoid duplicates
        pax_roles = {} # name -> role mapped
        
        if creator:
            creator_name = creator.strip()
            pax_roles[creator_name] = ''
            
        for tag in tags:
            tag_name = tag.strip()
            if tag_name and tag_name not in pax_roles:
                pax_roles[tag_name] = ''
                

        # If no users parsed for some reason, we might skip or record empty user. Let's strictly iterate over found PAX.
        event_attendees = {}
        for pax_name, role in pax_roles.items():
            user_id = get_or_create_user_id(pax_name)
            if not user_id: continue
            
            # If user already exists in this event, upgrade their role if this instance has a higher precedence ('Q' > 'Co-Q' > '')
            existing_role = event_attendees.get(user_id, '')
            if role == 'Q':
                event_attendees[user_id] = role
            elif role == 'Co-Q' and existing_role != 'Q':
                event_attendees[user_id] = role
            elif user_id not in event_attendees:
                event_attendees[user_id] = role
                
        # Enforce exactly ONE Q rule
        q_count = 0
        for uid, role in list(event_attendees.items()):
            if role == 'Q':
                q_count += 1
                if q_count > 1:
                    event_attendees[uid] = 'Co-Q'
                    
        # If there are NO Qs, and there are attendees, force the first attendee to be the Q
        if q_count == 0 and event_attendees:
            # Prefer to make the creator the Q if possible
            creator_id = get_or_create_user_id(creator.strip()) if creator else None
            
            if creator_id and creator_id in event_attendees:
                event_attendees[creator_id] = 'Q'
            else:
                first_uid = list(event_attendees.keys())[0]
                event_attendees[first_uid] = 'Q'
                
        for user_id, role in event_attendees.items():
            dedup_key = (org_id, location_id, start_date, user_id)
            if dedup_key in global_seen_attendances:
                continue
            global_seen_attendances.add(dedup_key)
            
            out_data.append({
                'org_id': org_id,
                'location_id': location_id,
                'series_id': '', # Left empty optionally as per ReadMe
                'start_date': start_date,
                'start_time': start_time,
                'name': workout_name, # Defaults to workout name or AO name
                'description': f"{workout_name} Backblast".strip() if len(title) > 100 else title,
                'backblast': backblast,
                'user_id': user_id,
                'post_type': role
            })


    
    # -------------------------------------------------------------
    # GLOBAL Q ENFORCEMENT & DEDUPLICATION
    # -------------------------------------------------------------
    # The National DB groups events by all metadata columns, not just date/AO.
    # Each unique event MUST have exactly 1 Q.
    grouped_events = {}
    for row in out_data:
        # Match import_backblasts.py key exactly: 
        # (org_id, location_id, series_id, start_date, start_time, name, description, backblast)
        group_key = (
            row.get('org_id', ''),
            row.get('location_id', ''),
            row.get('series_id', ''),
            row.get('start_date', ''),
            row.get('start_time', ''),
            row.get('name', ''),
            row.get('description', ''),
            row.get('backblast', '')
        )
        if group_key not in grouped_events:
            grouped_events[group_key] = []
        grouped_events[group_key].append(row)
        
    final_out_data = []
    for group_key, rows in grouped_events.items():
        if not rows: continue
        
        # Deduplicate users within the group, keeping the highest role ('Q' > 'Co-Q' > '')
        user_roles = {}
        for row in rows:
            uid = row.get('user_id')
            role = row.get('post_type', '')
            if uid not in user_roles:
                user_roles[uid] = role
            else:
                existing = user_roles[uid]
                if role == 'Q':
                    user_roles[uid] = 'Q'
                elif role == 'Co-Q' and existing != 'Q':
                    user_roles[uid] = 'Co-Q'
                    
        # Enforce exactly 1 Q per group
        q_count = 0
        for uid, role in list(user_roles.items()):
            if role == 'Q':
                q_count += 1
                if q_count > 1:
                    user_roles[uid] = 'Co-Q'
                    
        if q_count == 0 and user_roles:
            first_uid = list(user_roles.keys())[0]
            user_roles[first_uid] = 'Q'
            
        # Reconstruct exactly one row per unique user in this group
        # We will use the metadata (name, description, etc.) from the first appearance of this user
        user_metadata = {}
        for row in rows:
            uid = row.get('user_id')
            if uid not in user_metadata:
                user_metadata[uid] = row
                
        for uid, final_role in user_roles.items():
            final_row = user_metadata[uid].copy()
            final_row['post_type'] = final_role
            final_out_data.append(final_row)

    # -------------------------------------------------------------
    headers = ['org_id', 'location_id', 'series_id', 'start_date', 'start_time', 'name', 'description', 'backblast', 'user_id', 'post_type']
    with open('output/output.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(final_out_data)
        
    print(f"Successfully converted data to output/output.csv ({len(final_out_data)} rows).")

    # Save any new unmatched users to insert file
    new_users_added = 0
    if 'unmatched_users_data' in globals() or unmatched_users_data:
        insert_file = 'output/missing_users.csv'
        file_exists = os.path.exists(insert_file)
        
        existing_ids = set()
        if file_exists:
            with open(insert_file, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    existing_ids.add(row.get('id', ''))
                    
        with open(insert_file, 'a', newline='', encoding='utf-8') as f:
            headers = ['id', 'f3_name', 'email']
            writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
            if not file_exists:
                writer.writeheader()
                
            for row_id, data in unmatched_users_data.items():
                if row_id not in existing_ids:
                    writer.writerow({
                        'id': data.get('id', ''),
                        'f3_name': data.get('f3_name', ''),
                        'email': data.get('email', '')
                    })
                    new_users_added += 1
                    
        print(f"Appended {new_users_added} missing users to {insert_file}")

if __name__ == "__main__":
    input_file = 'import/f3stsimons.wordpress.com.2026-02-23.000.xml'
    locations_file = 'import/locations.csv'
    output_file = 'output/output.csv'
    convert_xml_to_csv(input_file, locations_file, output_file)
