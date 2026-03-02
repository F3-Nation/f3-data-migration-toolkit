import csv
import sys
import json
import re

def load_aliases():
    try:
        with open('import/aliases.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

ALIASES = load_aliases()

import html

def normalize_name(name):
    if not name or name == '[NULL]': return ''
    
    # 1. HTML Unescape
    name = html.unescape(name.strip())
    
    # 2. Strip parentheticals entirely, e.g. "(QIC)"
    name = re.sub(r'\(.*?\)', '', name)
    
    # 3. Strip @ and lowercase
    name = name.lstrip('@').lower().strip()
    
    # 4. Strip isolating suffixes/prefixes like QIC and FNG
    name = re.sub(r'\bqic\b', '', name)
    name = re.sub(r'\bfngs?\b', '', name)
    
    name = name.strip()
    
    return ALIASES.get(name, name)

def format_phone(phone_str):
    if not phone_str or phone_str == '[NULL]':
        return phone_str
    # Strip all non-numeric characters
    import re
    digits = re.sub(r'\D', '', phone_str)
    
    # If it's precisely 10 digits
    if len(digits) == 10:
        return f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
    # Alternatively handle 11 digits if starts with 1
    elif len(digits) == 11 and digits.startswith('1'):
        return f"{digits[1:4]}-{digits[4:7]}-{digits[7:11]}"
        
    # Standard formats failed, return original so it gets flagged
    return phone_str.strip()

def is_valid_email(email_str):
    if not email_str or email_str == '[NULL]':
        return True # Empty is "valid" in the sense it doesn't need cleanup flag, just missing
    import re
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(pattern, email_str.strip()) is not None

def get_paxminer_slack_ids():
    import glob
    slack_ids = {}
    pm_files = glob.glob('import/PAXminer_users_*.csv')
    if not pm_files:
        return slack_ids
        
    with open(pm_files[0], 'r', encoding='utf-8-sig', errors='ignore') as f:
        reader = csv.DictReader(f)
        for row in reader:
            disp = normalize_name(row.get('user_name', ''))
            slack_id = row.get('user_id', '').strip()
            if disp and slack_id:
                slack_ids[disp] = slack_id
    return slack_ids

def read_legacy_data():
    legacy_data = {}
    
    # Read pax directory
    with open('import/legacy_pax_directory.csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_f3_name = row.get('F3_Name', '').strip()
            if not raw_f3_name:
                continue
            norm_name = normalize_name(raw_f3_name)
            
            # If we've already seen this normalized name, we update fields rather than overwrite
            if norm_name not in legacy_data:
                legacy_data[norm_name] = {
                    'f3_name': raw_f3_name, # keep original to preserve caps until matched with HQ
                    'first_name': row.get('First\nName', '').strip(),
                    'last_name': row.get('Last\nName', '').strip(),
                    'email': row.get('Email', '').strip(),
                    'phone': row.get('Phone', '').strip(),
                    'emergency_contact': row.get('Emergency Contact', '').strip(),
                    'emergency_phone': row.get('Emergency Number', '').strip(),
                }

    # Read master directory and update (it may have more/different fields, but we align on the core ones)
    with open('import/legacy_master_directory.csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
        reader = csv.DictReader(f)
        for row in reader:
            f3_name = row.get('F3_Name', '').strip()
            if not f3_name:
                continue
            norm_name = normalize_name(f3_name)
            
            first_name = row.get('First\nName', '').strip()
            last_name = row.get('Last\nName', '').strip()
            email = row.get('Email', '').strip()
            phone = row.get('Phone', '').strip()
            emergency_contact = row.get('Emergency Contact', '').strip()
            emergency_phone = row.get('Emergency Number', '').strip()
            
            if norm_name not in legacy_data:
                legacy_data[norm_name] = {'f3_name': f3_name}
            
            # Update only if the master directory has a non-empty value
            if first_name: legacy_data[norm_name]['first_name'] = first_name
            if last_name: legacy_data[norm_name]['last_name'] = last_name
            if email: legacy_data[norm_name]['email'] = email
            if phone: legacy_data[norm_name]['phone'] = phone
            if emergency_contact: legacy_data[norm_name]['emergency_contact'] = emergency_contact
            if emergency_phone: legacy_data[norm_name]['emergency_phone'] = emergency_phone

    return legacy_data


def generate_reports():
    legacy_data = read_legacy_data()
    paxminer_slack_ids = get_paxminer_slack_ids()

    inserts = []
    inserts = []
    updates = []
    conflicts = []
    cleanup_needed = []
    
    hq_users_found = set()
    
    def validate_and_format_user(user_dict, f3_name, first_name, last_name):
        phone = user_dict.get('phone', '')
        e_phone = user_dict.get('emergency_phone', '')
        email = user_dict.get('email', '')
        
        formatted_phone = format_phone(phone)
        formatted_e_phone = format_phone(e_phone)
        user_dict['phone'] = formatted_phone
        user_dict['emergency_phone'] = formatted_e_phone
        
        # Check validity for cleanup logging
        invalid_email = not is_valid_email(email)
        invalid_phone = bool(phone) and phone != '[NULL]' and (formatted_phone == phone and len(re.sub(r'\D', '', phone)) not in [10, 11])
        invalid_e_phone = bool(e_phone) and e_phone != '[NULL]' and (formatted_e_phone == e_phone and len(re.sub(r'\D', '', e_phone)) not in [10, 11])
        
        if invalid_email or invalid_phone or invalid_e_phone:
            cleanup_needed.append({
                'f3_name': f3_name,
                'first_name': first_name,
                'last_name': last_name,
                'invalid_email': email if invalid_email else '',
                'invalid_phone': phone if invalid_phone else '',
                'invalid_emergency_phone': e_phone if invalid_e_phone else ''
            })
    
    # Read HQ Master Data
    with open('import/user_master.csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
        reader = csv.DictReader(f)
        hq_headers = reader.fieldnames
        
        for row in reader:
            f3_name = row.get('f3_name', '').strip()
            if not f3_name:
                continue
                
            validate_and_format_user(
                row, 
                f3_name, 
                row.get('first_name', ''), 
                row.get('last_name', '')
            )
            
            norm_name = normalize_name(f3_name)
            hq_users_found.add(norm_name)
            
            if norm_name in legacy_data:
                legacy_user = legacy_data[norm_name]
                
                # Format legacy comparison fields too
                legacy_user['phone'] = format_phone(legacy_user.get('phone', ''))
                legacy_user['emergency_phone'] = format_phone(legacy_user.get('emergency_phone', ''))
                
                # Check for updates and conflicts
                update_row = row.copy()
                conflict_row = {'f3_name': f3_name}
                has_updates = False
                has_conflicts = False
                
                # field mapping: (hq_field, legacy_field)
                fields_to_check = [
                    ('first_name', 'first_name'),
                    ('last_name', 'last_name'),
                    ('email', 'email'),
                    ('phone', 'phone'),
                    ('emergency_contact', 'emergency_contact'),
                    ('emergency_phone', 'emergency_phone')
                ]
                
                for hq_f, leg_f in fields_to_check:
                    hq_val = row.get(hq_f, '').strip()
                    leg_val = legacy_user.get(leg_f, '').strip()
                    
                    if not leg_val:
                        continue # No info in legacy to provide
                        
                    if hq_val == '[NULL]' or not hq_val:
                        # HQ needs this info - UPDATE
                        update_row[hq_f] = leg_val
                        has_updates = True
                    elif hq_val.lower() != leg_val.lower():
                        # Both have data, but they differ - CONFLICT
                        conflict_row[f'hq_{hq_f}'] = hq_val
                        conflict_row[f'legacy_{hq_f}'] = leg_val
                        has_conflicts = True
                
                if has_updates:
                    updates.append(update_row)
                if has_conflicts:
                    conflicts.append(conflict_row)

    # Check for INSERTS (users in legacy but not in HQ)
    tmp_id_counter = 1
    for norm_name, leg_user in legacy_data.items():
        if norm_name not in hq_users_found:
            insert_row = {
                'id': f'TMP_ID_{tmp_id_counter}',
                'f3_name': leg_user.get('f3_name', ''),
                'first_name': leg_user.get('first_name', ''),
                'last_name': leg_user.get('last_name', ''),
                'email': leg_user.get('email', ''),
                'phone': leg_user.get('phone', ''),
                'emergency_contact': leg_user.get('emergency_contact', ''),
                'emergency_phone': leg_user.get('emergency_phone', ''),
                'status': 'active',
                'paxminer_user_id': paxminer_slack_ids.get(norm_name, '')
            }
            
            validate_and_format_user(
                insert_row, 
                insert_row['f3_name'], 
                insert_row['first_name'], 
                insert_row['last_name']
            )
            
            inserts.append(insert_row)
            tmp_id_counter += 1

    # Write Updates
    if updates:
        with open('output/users_update.csv', 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictReader(open('import/user_master.csv')) # just to get headers easily
            writer = csv.DictWriter(f, fieldnames=hq_headers)
            writer.writeheader()
            writer.writerows(updates)
        print(f"Wrote {len(updates)} records to users_update.csv")
    else:
        print("No updates found.")

    # Write Inserts
    if inserts:
        with open('output/users_insert.csv', 'w', newline='', encoding='utf-8') as f:
            # We use the HQ headers roughly for inserts too
            headers = ['id', 'f3_name', 'first_name', 'last_name', 'email', 'phone', 'emergency_contact', 'emergency_phone', 'status', 'paxminer_user_id']
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(inserts)
        print(f"Wrote {len(inserts)} records to users_insert.csv")
    else:
        print("No inserts found.")

    # Write Conflicts
    if conflicts:
        with open('output/users_conflict.csv', 'w', newline='', encoding='utf-8') as f:
            # Collect all possible conflict keys
            conflict_headers = ['f3_name']
            for c in conflicts:
                for k in c.keys():
                    if k not in conflict_headers:
                        conflict_headers.append(k)
            writer = csv.DictWriter(f, fieldnames=conflict_headers)
            writer.writeheader()
            writer.writerows(conflicts)
        print(f"Wrote {len(conflicts)} records to output/users_conflict.csv")
    else:
        print("No conflicts found.")
        
    # Write Cleanups
    if cleanup_needed:
        with open('output/users_cleanup.csv', 'w', newline='', encoding='utf-8') as f:
            headers = ['f3_name', 'first_name', 'last_name', 'invalid_email', 'invalid_phone', 'invalid_emergency_phone']
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(cleanup_needed)
        print(f"Wrote {len(cleanup_needed)} records to output/users_cleanup.csv awaiting manual formatting review.")
    else:
        print("No cleanup format errors found.")

if __name__ == '__main__':
    generate_reports()
