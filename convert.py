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
                    
    # Pre-build lookup map: normalized_name -> canonical_id
    canonical_id_map = {}
    
    try:
        with open('import/user_master.csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
            for row in csv.DictReader(f):
                fname = normalize_user(row.get('f3_name', ''))
                uid = row.get('id', '')
                if fname and uid:
                    canonical_id_map[fname] = uid
    except Exception as e:
        print(f"Failed to load import/user_master.csv: {e}")
        
    try:
        with open('output/users_insert.csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
            for row in csv.DictReader(f):
                fname = normalize_user(row.get('f3_name', ''))
                uid = row.get('id', '')
                if fname and uid:
                    canonical_id_map[fname] = uid
    except Exception as e:
        print(f"Failed to load output/users_insert.csv: {e}")
        
    try:
        if os.path.exists('output/users_downrange.csv'):
            with open('output/users_downrange.csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
                for row in csv.DictReader(f):
                    fname = normalize_user(row.get('f3_name', ''))
                    uid = row.get('id', '')
                    if fname and uid:
                        canonical_id_map[fname] = uid
    except Exception as e:
        print(f"Failed to load output/users_downrange.csv: {e}")

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
    
    def get_or_create_user_id(name):
        nonlocal next_unmatched_id
        normalized_name = normalize_user(name)
        if not normalized_name:
            return ''
            
        if normalized_name in canonical_id_map:
            # We found a canonical match!
            user_id_map[normalized_name] = canonical_id_map[normalized_name]
            return canonical_id_map[normalized_name]
            
        if normalized_name not in user_id_map:
            # We have a strict unmatched straggler not located in ANY directory.
            fallback_id = f"UNMATCHED_ID_{next_unmatched_id}"
            user_id_map[normalized_name] = fallback_id
            
            # Lookup Author Info if they were a known WP Author explicitly
            author_info = wp_authors.get(normalized_name, {})
            
            # Reconstruct the unrec_norm key that build_alias_map.py used for display_aliases.json
            unrec_norm = re.sub(r'\(.*?\)', '', clean_text(name).lstrip('@')).lower().strip()
            unrec_norm = re.sub(r'\bqic\b', '', unrec_norm)
            unrec_norm = re.sub(r'\bfngs?\b', '', unrec_norm).strip()
            
            display_name = DISPLAY_ALIASES.get(unrec_norm, name)
            
            unmatched_users_data[fallback_id] = {
                'id': fallback_id,
                'f3_name': display_name,  # Exact targeted match or original requested name
                'login': normalized_name,
                'first_name': author_info.get('first_name', ''),
                'last_name': author_info.get('last_name', ''),
                'email': author_info.get('email', ''),
                'display_name': author_info.get('display_name', '')
            }
            next_unmatched_id += 1
            
        return user_id_map[normalized_name]

    # Find all WP items
    items = root.findall('.//item')
    
    out_data = []
    
    # 2. Pre-process PAXminer data before iterating WP
    paxminer_events = {} # Map (Date, Workout) -> Event details
    paxminer_attendance = {} # Map (Date, Workout) -> List of PAX with roles
    
    pm_att_files = glob.glob('import/PAXminer_attendance_view_*.csv')
    if pm_att_files:
        latest_att = max(pm_att_files, key=os.path.getctime)
        with open(latest_att, 'r', encoding='utf-8-sig', errors='ignore') as f:
            for row in csv.DictReader(f):
                date = row.get('Date', '').strip()
                ao = row.get('AO', '').strip() # e.g. "1stf"
                pax = row.get('PAX', '').strip()
                q = row.get('Q', '').strip()
                
                if not date: continue
                # Determine "canonical" AO from PAXminer's generic AO using the weekday_map
                try:
                    dt = datetime.strptime(date, '%Y-%m-%d')
                    weekday_name = dt.strftime('%A')
                    canonical_ao = weekday_map.get(weekday_name, ao)
                except:
                    canonical_ao = ao
                    
                # To ensure strict matching against WP data, lowercase the canonical_ao
                key = (date.strip(), canonical_ao.strip().lower() if canonical_ao else '')
                role = 'Q' if pax.lower() == q.lower() else ''
                
                if key not in paxminer_attendance:
                    paxminer_attendance[key] = {}
                paxminer_attendance[key][pax] = role

    pm_bb_files = glob.glob('import/PAXminer_backblast_*.csv')
    if pm_bb_files:
        latest_bb = max(pm_bb_files, key=os.path.getctime)
        with open(latest_bb, 'r', encoding='utf-8-sig', errors='ignore') as f:
            for row in csv.DictReader(f):
                date = row.get('Date', '').strip()
                ao = row.get('AO', '').strip()
                bb = clean_text(row.get('backblast', ''))
                
                if not date: continue
                
                try:
                    dt = datetime.strptime(date, '%Y-%m-%d')
                    weekday_name = dt.strftime('%A')
                    canonical_ao = weekday_map.get(weekday_name, ao)
                except:
                    canonical_ao = ao
                    
                key = (date.strip(), canonical_ao.strip().lower() if canonical_ao else '')
                paxminer_events[key] = bb

    # Keep track of which PAXminer events we've merged into WP so we can append the remainder
    merged_pm_keys = set()
    
    for item in items:
        post_type = item.findtext('wp:post_type', namespaces=ns)
        # Skip attachments, pages, nav_menu_items, etc. We only want posts.
        if post_type != 'post':
            continue
            
        title = clean_text(item.findtext('title') or '')
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
        
        if (not workout_name or workout_name.lower() == 'uncategorized') and weekday_name in weekday_map:
            workout_name = weekday_map[weekday_name]
            
        key = (start_date.strip(), workout_name.strip().lower() if workout_name else '')
        
        # Merge PAXminer Backblast if it exists
        if key in paxminer_events:
            pm_bb = paxminer_events[key]
            # Verify the texts aren't exact replicas before appending blindly
            if backblast and pm_bb and backblast.strip() != pm_bb.strip():
                backblast = f"--- PAXminer Backblast ---\n{pm_bb.strip()}\n\n--- WordPress Backblast ---\n{backblast.strip()}"
            elif pm_bb and not backblast:
                backblast = pm_bb
            merged_pm_keys.add(key)
        
        loc_data = locations_map.get(workout_name, {})
        
        org_id = loc_data.get('org_id', '')
        location_id = loc_data.get('location_id', '')
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
                
        # Merge PAXminer Attendees if they exist
        if key in paxminer_attendance:
            pm_pax_dict = paxminer_attendance[key]
            for pm_pax, pm_role in pm_pax_dict.items():
                if pm_pax and pm_pax not in pax_roles:
                    pax_roles[pm_pax] = pm_role
                elif pm_pax and pm_role == 'Q': # Override if PM says they were Q
                    pax_roles[pm_pax] = 'Q'
                
        # If no users parsed for some reason, we might skip or record empty user. Let's strictly iterate over found PAX.
        for pax_name, role in pax_roles.items():
            user_id = get_or_create_user_id(pax_name)
            
            out_data.append({
                'org_id': org_id,
                'location_id': location_id,
                'series_id': '', # Left empty optionally as per ReadMe
                'start_date': start_date,
                'start_time': start_time,
                'name': workout_name, # Defaults to workout name or AO name
                'description': title, # Will use Title for description
                'backblast': backblast,
                'user_id': user_id,
                'post_type': role
            })

    # Now add the remaining standalone PAXminer events
    print(f"DEBUG: Total PAXminer events: {len(paxminer_events)}")
    print(f"DEBUG: Total Merged PM keys: {len(merged_pm_keys)}")
    standalone_count = 0
    for key in paxminer_events:
        if key not in merged_pm_keys:
            standalone_count += 1
            date_str, canonical_ao_lower = key
            
            orig_ao = canonical_ao_lower.title()
            for k, v in locations_map.items():
                if k.lower() == canonical_ao_lower:
                    orig_ao = k
                    break
                    
            loc_data = locations_map.get(orig_ao, {})
            org_id = loc_data.get('org_id', '')
            location_id = loc_data.get('location_id', '')
            start_time = loc_data.get('start_time', '')
            
            pm_bb = paxminer_events[key]
            pax_dict = paxminer_attendance.get(key, {})
            
            description = pm_bb.split('\n')[0][:100] if pm_bb else "PAXminer Backblast"
            
            if not pax_dict:
                out_data.append({
                    'org_id': org_id, 'location_id': location_id, 'series_id': '',
                    'start_date': date_str, 'start_time': start_time, 'name': orig_ao,
                    'description': description, 'backblast': pm_bb, 'user_id': '', 'post_type': ''
                })
            else:
                for pax_name, role in pax_dict.items():
                    user_id = get_or_create_user_id(pax_name)
                    out_data.append({
                        'org_id': org_id, 'location_id': location_id, 'series_id': '',
                        'start_date': date_str, 'start_time': start_time, 'name': orig_ao,
                        'description': description, 'backblast': pm_bb, 'user_id': user_id, 'post_type': role
                    })

    print(f"DEBUG: Added {standalone_count} standalone events to array.")

    # Write generated data to output CSV
    headers = ['org_id', 'location_id', 'series_id', 'start_date', 'start_time', 'name', 'description', 'backblast', 'user_id', 'post_type']
    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(out_data)

    print(f"Successfully converted data to {output_csv} ({len(out_data)} rows).")

    # Write Unmatched Info to users_insert.csv
    if unmatched_users_data:
        insert_file = 'output/users_insert.csv'
        file_exists = os.path.exists(insert_file)
        
        # Determine existing IDs to prevent massive duplicates if script reruns without wiping
        existing_ids = set()
        if file_exists:
            with open(insert_file, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    existing_ids.add(row.get('id', ''))
                    
        with open(insert_file, 'a', newline='', encoding='utf-8') as f:
            headers = ['id', 'f3_name', 'first_name', 'last_name', 'email', 'phone', 'emergency_contact', 'emergency_phone', 'status', 'paxminer_user_id']
            writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
            if not file_exists:
                writer.writeheader()
                
            for row_id, data in unmatched_users_data.items():
                if row_id not in existing_ids:
                    writer.writerow({
                        'id': data.get('id', ''),
                        'f3_name': data.get('f3_name', ''),
                        'first_name': data.get('first_name', '[NULL]'),
                        'last_name': data.get('last_name', '[NULL]'),
                        'email': data.get('email', ''),
                        'phone': '[NULL]',
                        'emergency_contact': '[NULL]',
                        'emergency_phone': '[NULL]',
                        'status': 'active',
                        'paxminer_user_id': paxminer_slack_ids.get(data.get('login', ''), '')
                    })
        print(f"Appended {len(unmatched_users_data)} unmatched users to {insert_file}")

if __name__ == "__main__":
    input_file = 'import/f3stsimons.wordpress.com.2026-02-23.000.xml'
    locations_file = 'import/locations.csv'
    output_file = 'output/output.csv'
    convert_xml_to_csv(input_file, locations_file, output_file)
