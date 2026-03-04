import pandas as pd
import csv
import os
import glob
import json
import config

def clean_text(text):
    if not isinstance(text, str):
        return ''
    text = text.replace('\x00', '')
    return text.strip()

def load_aliases():
    try:
        import json
        import re
        with open('import/aliases.json', 'r', encoding='utf-8-sig', errors='ignore') as f:
            raw_aliases = json.load(f)
            aliases = {}
            for k, v in raw_aliases.items():
                clean_k = re.sub(r'[^a-zA-Z0-9]', '', k.lower())
                clean_v = re.sub(r'[^a-zA-Z0-9]', '', v.lower())
                aliases[clean_k] = clean_v
            return aliases
    except FileNotFoundError:
        return {}

USER_ALIASES = load_aliases()

def normalize_user(name):
    if not name:
        return ''
    cleaned = clean_text(name).replace('@', '')
    if not cleaned:
        return ''
        
    import re
    # Strip parentheticals entirely, e.g. "(BM)" or "(QIC)"
    cleaned = re.sub(r'\(.*?\)', '', cleaned)
    
    # Strip common suffixes
    cleaned = re.sub(r'(?i)\bqic\b', '', cleaned)
    cleaned = re.sub(r'(?i)\bfngs?\b', '', cleaned)
    
    # Remove all non-alphanumerics to maximize matches
    lowercased = cleaned.lower()
    lowercased = re.sub(r'[^a-zA-Z0-9]', '', lowercased)
    
    if lowercased in USER_ALIASES:
        return USER_ALIASES[lowercased]
    return lowercased

def get_or_create_user_id(name, user_id_map, canonical_id_map, unmatched_qs_data, paxminer_unmatched_data, next_unmatched_id, legacy_emails, email_to_id_map, paxminer_slack_ids):
    normalized_name = normalize_user(name)
    if not normalized_name:
        return '', user_id_map, unmatched_qs_data, paxminer_unmatched_data, next_unmatched_id
        
    if normalized_name in canonical_id_map:
        return canonical_id_map[normalized_name], user_id_map, unmatched_qs_data, paxminer_unmatched_data, next_unmatched_id
        
    if normalized_name in user_id_map:
        return user_id_map[normalized_name], user_id_map, unmatched_qs_data, paxminer_unmatched_data, next_unmatched_id
        
    email_addr = ''
    if normalized_name in legacy_emails:
        email_addr = legacy_emails[normalized_name]
        
    if email_addr and email_addr.lower() in email_to_id_map:
        canonical_id_map[normalized_name] = email_to_id_map[email_addr.lower()]
        return email_to_id_map[email_addr.lower()], user_id_map, unmatched_qs_data, paxminer_unmatched_data, next_unmatched_id
        
    # Create a new TMPQ_ID
    new_id = f"TMPQ_ID_{next_unmatched_id}"
    next_unmatched_id += 1
    user_id_map[normalized_name] = new_id
    
    if normalized_name in paxminer_slack_ids:
        paxminer_unmatched_data[new_id] = {
            'slack_id': paxminer_slack_ids[normalized_name],
            'f3_name': name.strip(),
            'email': email_addr
        }
    else:
        unmatched_qs_data[new_id] = {
            'id': new_id,
            'f3_name': name.strip(),
            'email': email_addr
        }
    
    return new_id, user_id_map, unmatched_qs_data, paxminer_unmatched_data, next_unmatched_id

def load_locations(locations_csv):
    locations = {}
    with open(locations_csv, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            workout = row.get('Workout', '').strip()
            if workout:
                locations[workout] = row
    return locations

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

def main():
    paxminer_slack_ids = {}
    pm_user_files = glob.glob('import/PAXminer_users_*.csv')
    if pm_user_files:
        with open(pm_user_files[0], 'r', encoding='utf-8-sig', errors='ignore') as f:
            for row in csv.DictReader(f):
                disp = normalize_user(row.get('user_name', ''))
                slack_id = row.get('user_id', '').strip()
                if disp and slack_id:
                    paxminer_slack_ids[disp] = slack_id
                    
    # Load canonical ids from bq-users
    canonical_id_map = {}
    try:
        bq_files = glob.glob('import/bq-users-*.csv')
        if bq_files:
            with open(bq_files[0], 'r', encoding='utf-8-sig', errors='ignore') as f:
                for row in csv.DictReader(f):
                    fname = normalize_user(row.get('f3_name', ''))
                    uid = row.get('user_id', '')
                    rid = row.get('home_region_id', '')
                    if fname and uid:
                        if fname in canonical_id_map:
                            if rid == config.REGION_ID:
                                canonical_id_map[fname] = uid
                        else:
                            canonical_id_map[fname] = uid
    except Exception as e:
        print(f"Warning: Failed to load bq-users. {e}")
        
    email_to_id_map = {}
    try:
        with open('import/user_master.csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
            for row in csv.DictReader(f):
                uid = row.get('id', '')
                email = row.get('email', '').strip().lower()
                if uid and email and email != '[null]':
                    email_to_id_map[email] = uid
    except Exception as e:
        print(f"Warning: Failed to load user_master.csv. {e}")
        
    # Load legacy emails
    legacy_emails = {}
    for legacy_file in ['import/legacy_pax_directory.csv', 'import/legacy_master_directory.csv']:
        if os.path.exists(legacy_file):
            try:
                with open(legacy_file, 'r', encoding='utf-8-sig', errors='ignore') as f:
                    for row in csv.DictReader(f):
                        fname = normalize_user(row.get('F3_Name', ''))
                        email = row.get('Email', '').strip()
                        if fname and email and fname not in legacy_emails:
                            legacy_emails[fname] = email
            except Exception as e:
                pass
                
    # Unmatched trackers
    user_id_map = {}
    next_unmatched_id = 1
    unmatched_qs_data = {}
    paxminer_unmatched_data = {}

    locations = load_locations('import/locations.csv')

    # Find ALL events that happened across PAXminer (bq-results) and WP (output local)
    existing_events = set() # (start_date, workout_name)
    
    # 1. BQ Results (Paxminer data)
    bq_result_files = glob.glob('import/bq-results-*.csv')
    if bq_result_files:
        with open(bq_result_files[0], 'r', encoding='utf-8-sig', errors='ignore') as f:
            for row in csv.DictReader(f):
                # The bq-results format varies, but usually has 'date' or 'start_date' and 'ao_name' or similar, we must crossref location_id possibly.
                # Since we want to be safe, if we know WP backblasts + PAXminer is in here:
                date = row.get('date', '').strip()
                if not date:
                    date = row.get('start_date', '').strip()
                # Instead of matching by name, map to location_id
                loc_id = row.get('location_id', '').strip()
                if date and loc_id:
                    existing_events.add((date, loc_id))
                    
    # 2. WordPress data we just generated
    wp_file = f"output/{config.REGION_NAME}_wordpress_backblasts.csv"
    if os.path.exists(wp_file):
        with open(wp_file, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                date = row.get('start_date', '').strip()
                loc_id = row.get('location_id', '').strip()
                if date and loc_id:
                    existing_events.add((date, loc_id))

    missing_backblast_events = []

    try:
        with open('import/legacy_q_schedule.csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
            for row in csv.DictReader(f):
                date_str = row.get('Date', '').strip()
                if not date_str: continue
                
                try:
                    dt = pd.to_datetime(date_str)
                    start_date = dt.strftime('%Y-%m-%d')
                except Exception:
                    continue
                    
                if start_date > '2026-03-07':
                    continue
                    
                workout_name = str(row.get('Workout/Event') or '').strip()
                q_name = str(row.get('Q') or '').strip()
                
                if not workout_name or not q_name:
                    continue
                    
                loc_data = locations.get(workout_name, {})
                loc_id = loc_data.get('locationId', '')
                
                # Check if this date+loc_id combination exists in our known backblasts
                if (start_date, loc_id) not in existing_events:
                    # It's missing! Get the Q's ID
                    q_id, user_id_map, unmatched_qs_data, paxminer_unmatched_data, next_unmatched_id = get_or_create_user_id(
                        q_name, user_id_map, canonical_id_map, unmatched_qs_data, paxminer_unmatched_data, next_unmatched_id, legacy_emails, email_to_id_map, paxminer_slack_ids
                    )
                    
                    default_org_id = next((v['orgId'] for v in locations.values() if v.get('orgId')), '37004')
                    default_loc_id = next((v['locationId'] for v in locations.values() if v.get('locationId')), '123')
                    
                    new_row = {
                        'org_id': loc_data.get('orgId', '') or default_org_id,
                        'location_id': loc_id or default_loc_id,
                        'series_id': '',
                        'start_date': start_date,
                        'start_time': format_time(loc_data.get('startTime', '')),
                        'name': workout_name,
                        'description': 'No Backblast',
                        'backblast': 'No Backblast',
                        'user_id': q_id,
                        'post_type': 'Q'
                    }
                    missing_backblast_events.append(new_row)
                    
    except Exception as e:
        print(f"Failed to load Legacy Q Schedule: {e}")
        return

    # Write output f3stsimons_qschedule_nobackblast.csv
    out_file = f"output/{config.REGION_NAME}_qschedule_nobackblast.csv"
    headers = ['org_id', 'location_id', 'series_id', 'start_date', 'start_time', 'name', 'description', 'backblast', 'user_id', 'post_type']
    with open(out_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        
        # Deduplicate missing events
        seen = set()
        deduped = []
        for row in missing_backblast_events:
            dedup_key = (row['location_id'], row['start_date'], row['user_id'])
            if dedup_key not in seen:
                seen.add(dedup_key)
                deduped.append(row)
                
        writer.writerows(deduped)
        
    print(f"Generated {out_file} with {len(deduped)} missing backblast records.")

    # Write f3stsimons_missing_Qs.csv
    missing_qs_file = f"output/{config.REGION_NAME}_missing_Qs.csv"
    if unmatched_qs_data:
        # always overwrite since we process entire schedule fresh
        with open(missing_qs_file, 'w', newline='', encoding='utf-8') as f:
            headers = ['id', 'f3_name', 'email']
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for row_id, data in unmatched_qs_data.items():
                writer.writerow(data)
                
        print(f"Generated {missing_qs_file} with {len(unmatched_qs_data)} missing Qs.")
    else:
        # clear it if exists and no longer needed
        if os.path.exists(missing_qs_file):
            os.remove(missing_qs_file)
            
    # Write paxminer_unmatched_data (Slack IDs without national IDs)
    pax_unmatched_file = f"output/{config.REGION_NAME}_paxminer_unmatched.csv"
    pax_users_added = 0
    if paxminer_unmatched_data:
        file_exists = os.path.exists(pax_unmatched_file)
        with open(pax_unmatched_file, 'a', newline='', encoding='utf-8') as f:
            headers = ['slack_id', 'f3_name', 'email']
            writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
            if not file_exists:
                writer.writeheader()
                
            for row_id, data in paxminer_unmatched_data.items():
                writer.writerow({
                    'slack_id': data.get('slack_id', ''),
                    'f3_name': data.get('f3_name', ''),
                    'email': data.get('email', '')
                })
                pax_users_added += 1
                
        print(f"Generated {pax_users_added} missing paxminer users to {pax_unmatched_file}")
            
if __name__ == "__main__":
    main()
