import pandas as pd
import csv
import os

def clean_text(text):
    if not isinstance(text, str):
        return ''
    text = text.replace('\x00', '')
    return text.strip()

import json

def load_aliases():
    try:
        with open('import/aliases.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

USER_ALIASES = load_aliases()

def normalize_user(name):
    if not name:
        return ''
    cleaned = clean_text(name).replace('@', '')
    if not cleaned:
        return ''
    lowercased = cleaned.lower()
    if lowercased in USER_ALIASES:
        return USER_ALIASES[lowercased]
    return lowercased

def get_or_create_user_id(name, user_id_map, canonical_id_map):
    normalized_name = normalize_user(name)
    if not normalized_name:
        return '', user_id_map
        
    if normalized_name in canonical_id_map:
        return canonical_id_map[normalized_name], user_id_map
        
    return f"UNKNOWN_{normalized_name}", user_id_map

def load_locations(locations_csv):
    locations = {}
    with open(locations_csv, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            workout = row.get('Workout', '').strip()
            if workout:
                locations[workout] = row
    return locations

def main():
    import glob
    paxminer_slack_ids = {}
    pm_user_files = glob.glob('import/PAXminer_users_*.csv')
    if pm_user_files:
        with open(pm_user_files[0], 'r', encoding='utf-8-sig', errors='ignore') as f:
            for row in csv.DictReader(f):
                disp = normalize_user(row.get('user_name', ''))
                slack_id = row.get('user_id', '').strip()
                if disp and slack_id:
                    paxminer_slack_ids[disp] = slack_id
                    
    # Load users_map.csv
    user_id_map = {}
    if os.path.exists('output/users_map.csv'):
        with open('output/users_map.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                user_id_map[row['name']] = row['user_id']
                
    # Load Canonical maps to ensure accurate alignment
    canonical_id_map = {}
    try:
        with open('output/my_users_output.csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
            for row in csv.DictReader(f):
                fname = normalize_user(row.get('f3_name', ''))
                uid = row.get('id', '')
                if fname and uid:
                    canonical_id_map[fname] = uid
    except Exception as e:
        print(f"Warning: Failed to load output/my_users_output.csv. ID mappings will be missing! {e}")

    # Load locations
    locations = load_locations('import/locations.csv')

    # Load output.csv
    # We load it into a list of dicts. We also build a lookup index by (date, name)
    events_data = []
    events_by_date_and_name = {}  # (start_date, name) -> list of row dicts
    
    if os.path.exists('output/output.csv'):
        with open('output/output.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                events_data.append(row)
                
                key = (row['start_date'], row['name'].lower() if row['name'] else '')
                if key not in events_by_date_and_name:
                    events_by_date_and_name[key] = []
                events_by_date_and_name[key].append(row)

    # Process schedule
    missing_events_generated = 0
    qs_assigned = 0

    # Ensure format_time logic matches the main script
    def format_time(time_str):
        if not time_str: return ''
        time_str = str(time_str).strip().lower()
        import re
        match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', time_str)
        if not match: return ''
        hour, minute, ampm = int(match.group(1)), int(match.group(2) or 0), match.group(3)
        if ampm == 'pm' and hour < 12: hour += 12
        elif ampm == 'am' and hour == 12: hour = 0
        return f"{hour:02d}{minute:02d}"

    try:
        with open('import/legacy_q_schedule.csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
            reader = csv.DictReader(f)
            for row in reader:
                date_str = row.get('Date', '').strip()
                if not date_str:
                    continue
                    
                try:
                    # Convert something like 2/1/2017 to YYYY-MM-DD
                    dt = pd.to_datetime(date_str)
                    start_date = dt.strftime('%Y-%m-%d')
                except Exception:
                    continue
                    
                # Ignore schedule dates after 2026-03-07 per requirement
                if start_date > '2026-03-07':
                    continue
                    
                workout_name = str(row.get('Workout/Event') or '').strip()
                q_name = str(row.get('Q') or '').strip()
                
                if not workout_name or not q_name:
                    continue
                    
                q_id, user_id_map = get_or_create_user_id(q_name, user_id_map, canonical_id_map)

                key = (start_date, workout_name.lower())
                matching_event_rows = events_by_date_and_name.get(key)
                
                if matching_event_rows:
                    # Group the rows matching this AO/Date by exact event metadata
                    distinct_events = {}
                    for row in matching_event_rows:
                        event_key = (
                            row.get('org_id', ''), row.get('location_id', ''), row.get('series_id', ''),
                            row.get('start_date', ''), row.get('start_time', ''), row.get('name', ''),
                            row.get('description', ''), row.get('backblast', '')
                        )
                        if event_key not in distinct_events:
                            distinct_events[event_key] = []
                        distinct_events[event_key].append(row)
                        
                    # Find which distinct event to assign the Q to
                    # Prefer the one where the user is already an attendee
                    chosen_event_key = list(distinct_events.keys())[0]
                    q_found_in_chosen = False
                    
                    for key, rows in distinct_events.items():
                        for row in rows:
                            if str(row.get('user_id')) == str(q_id):
                                chosen_event_key = key
                                q_found_in_chosen = True
                                break
                        if q_found_in_chosen:
                            break
                            
                    chosen_rows = distinct_events[chosen_event_key]
                    
                    # Demote existing Qs ONLY in the chosen event
                    for row in chosen_rows:
                        if row.get('post_type') == 'Q' and str(row.get('user_id')) != str(q_id):
                            row['post_type'] = 'Co-Q'
                            
                    if q_found_in_chosen:
                        for row in chosen_rows:
                            if str(row.get('user_id')) == str(q_id):
                                row['post_type'] = 'Q'
                                qs_assigned += 1
                                break
                    else:
                        # Copy the first row's metadata of the chosen event to create a new row for the Q
                        sample_row = chosen_rows[0].copy()
                        sample_row['user_id'] = q_id
                        sample_row['post_type'] = 'Q'
                        events_data.append(sample_row)
                        events_by_date_and_name[key].append(sample_row)
                        qs_assigned += 1
                        
                else:
                    # The workout is Scheduled but NO backblast exists at all in the XML!
                    loc_data = locations.get(workout_name, {})
                    
                    default_org_id = next((v['orgId'] for v in locations.values() if v.get('orgId')), '37004')
                    default_loc_id = next((v['locationId'] for v in locations.values() if v.get('locationId')), '123')
                    
                    new_row = {
                        'org_id': loc_data.get('orgId', '') or default_org_id,
                        'location_id': loc_data.get('locationId', '') or default_loc_id,
                        'series_id': '',
                        'start_date': start_date,
                        'start_time': format_time(loc_data.get('startTime', '')),
                        'name': workout_name,
                        'description': 'No Backblast',
                        'backblast': 'No Backblast',
                        'user_id': q_id,
                        'post_type': 'Q'
                    }
                    events_data.append(new_row)
                    events_by_date_and_name[key] = [new_row]
                    missing_events_generated += 1
                    qs_assigned += 1
                    
    except Exception as e:
        print(f"Failed to load Legacy Q Schedule: {e}")
        return

    # Write output.csv
    headers = ['org_id', 'location_id', 'series_id', 'start_date', 'start_time', 'name', 'description', 'backblast', 'user_id', 'post_type']
    with open('output/output.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        
        seen_rows = set()
        deduped_events_data = []
        for row in events_data:
            dedup_key = (row.get('org_id'), row.get('location_id'), row.get('start_date'), row.get('user_id'))
            if dedup_key not in seen_rows:
                seen_rows.add(dedup_key)
                deduped_events_data.append(row)
                
        writer.writerows(deduped_events_data)
        
    print(f"Merge Complete: Overwrote output/output.csv ({len(events_data)} total rows).")
    print(f" - Q Roles successfully mapped: {qs_assigned}")
    print(f" - 'No Backblast' placeholders generated from schedule: {missing_events_generated}")



if __name__ == "__main__":
    main()
