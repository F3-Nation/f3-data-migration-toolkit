import pandas as pd
import csv
import os
import glob
import json
import config
import utils

# Load Aliases at module level
USER_ALIASES, _ = utils.load_aliases()

def normalize_user(name):
    return utils.normalize_user(name, USER_ALIASES)

def get_or_create_user_id(name, user_id_map, canonical_id_map, unmatched_qs_data, next_unmatched_id, legacy_emails, email_to_id_map):
    normalized_name = normalize_user(name)
    if not normalized_name:
        return '', user_id_map, unmatched_qs_data, next_unmatched_id
        
    if normalized_name in canonical_id_map:
        return canonical_id_map[normalized_name], user_id_map, unmatched_qs_data, next_unmatched_id
        
    if normalized_name in user_id_map:
        return user_id_map[normalized_name], user_id_map, unmatched_qs_data, next_unmatched_id
        
    email_addr = ''
    if normalized_name in legacy_emails:
        email_addr = legacy_emails[normalized_name]
        
    if email_addr and email_addr.lower() in email_to_id_map:
        canonical_id_map[normalized_name] = email_to_id_map[email_addr.lower()]
        return email_to_id_map[email_addr.lower()], user_id_map, unmatched_qs_data, next_unmatched_id
        
    # Create a new TMPQ_ID
    new_id = f"TMPQ_ID_{next_unmatched_id}"
    next_unmatched_id += 1
    user_id_map[normalized_name] = new_id
    
    unmatched_qs_data[new_id] = {
        'id': new_id,
        'f3_name': name.strip(),
        'email': email_addr
    }
    
    return new_id, user_id_map, unmatched_qs_data, next_unmatched_id

def load_locations(locations_csv):
    return utils.load_locations(locations_csv)

def main():
    # Load canonical ids from bq-users
    canonical_id_map = {}
    try:
        bq_files = glob.glob('import/bq-users-*.csv')
        if bq_files:
            with open(bq_files[0], 'r', encoding='utf-8-sig', errors='ignore') as f:
                for row in csv.DictReader(f):
                    fname = normalize_user(row.get('f3_name', ''))
                    uid = row.get('user_id', '').replace(',', '')
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
                uid = row.get('id', '').replace(',', '')
                email = row.get('email', '').strip().lower()
                fname = normalize_user(row.get('f3_name', ''))
                
                if uid:
                    if email and email != '[null]':
                        email_to_id_map[email] = uid
                    if fname:
                        # Only overwrite if not already set by bq-users (which filters for region)
                        if fname not in canonical_id_map:
                            canonical_id_map[fname] = uid
    except Exception as e:
        print(f"Warning: Failed to load user_master.csv. {e}")
        
    # Load newly assigned IDs from bulk update output if it exists
    missing_output_file = f"import/{config.REGION_NAME}_missing_users_output.csv"
    if os.path.exists(missing_output_file):
        try:
            with open(missing_output_file, 'r', encoding='utf-8-sig', errors='ignore') as f:
                for row in csv.DictReader(f):
                    uid = row.get('id', '').replace(',', '')
                    fname = normalize_user(row.get('f3_name', ''))
                    email = row.get('email', '').strip().lower()
                    if uid:
                        if fname:
                            canonical_id_map[fname] = uid
                        if email and email != '[null]':
                            email_to_id_map[email] = uid
            print(f"Loaded newly assigned IDs from {missing_output_file}")
        except Exception as e:
            print(f"Warning: Failed to load {missing_output_file}. {e}")
            
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

    locations_map, _ = utils.load_locations('import/locations.csv')

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
                    
                loc_data = locations_map.get(workout_name, {})
                loc_id = loc_data.get('location_id', '')
                
                # Check if this date+loc_id combination exists in our known backblasts
                if (start_date, loc_id) not in existing_events:
                    # It's missing! Get the Q's ID
                    q_id, user_id_map, unmatched_qs_data, next_unmatched_id = get_or_create_user_id(
                        q_name, user_id_map, canonical_id_map, unmatched_qs_data, next_unmatched_id, legacy_emails, email_to_id_map
                    )
                    
                    default_org_id = next((v['org_id'] for v in locations_map.values() if v.get('org_id')), '37004')
                    default_loc_id = next((v['location_id'] for v in locations_map.values() if v.get('location_id')), '123')
                    
                    new_row = {
                        'org_id': loc_data.get('org_id', '') or default_org_id,
                        'location_id': loc_id or default_loc_id,
                        'series_id': '',
                        'start_date': start_date,
                        'start_time': utils.format_time(loc_data.get('start_time', '')),
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
            
            
if __name__ == "__main__":
    main()
