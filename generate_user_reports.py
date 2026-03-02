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
    
    # Read HQ Master Data and merge
    try:
        with open('import/user_master.csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
            reader = csv.DictReader(f)
            for row in reader:
                f3_name = row.get('f3_name', '').strip()
                if not f3_name: continue
                norm_name = normalize_name(f3_name)
                if norm_name not in legacy_data:
                    legacy_data[norm_name] = {'f3_name': f3_name}
                
                # Update with HQ data if present
                for fld in ['first_name', 'last_name', 'email']:
                    val = row.get(fld, '').strip()
                    if val and val != '[NULL]':
                        legacy_data[norm_name][fld] = val
    except FileNotFoundError:
        pass

    # Read PAXminer users
    pm_ids = get_paxminer_slack_ids()
    for norm_name in pm_ids:
        if norm_name not in legacy_data:
            legacy_data[norm_name] = {'f3_name': norm_name.title()}

    my_users = []
    seen_emails = set()
    
    for norm_name, data in legacy_data.items():
        f3_name = data.get('f3_name', norm_name.title())
        first_name = data.get('first_name', '')
        last_name = data.get('last_name', '')
        email = data.get('email', '')
        
        # Format or generate email
        if not email or email == '[NULL]' or not is_valid_email(email):
            safe_name = re.sub(r'[^a-z0-9]', '', norm_name)
            if not safe_name: safe_name = 'unknown'
            email = f"{safe_name}@example.com"
            
        # Deduplicate emails just in case
        original_email = email
        counter = 1
        while email.lower() in seen_emails:
            email = f"{original_email.split('@')[0]}{counter}@{original_email.split('@')[1]}"
            counter += 1
            
        seen_emails.add(email.lower())
        
        my_users.append({
            'f3_name': f3_name,
            'first_name': first_name,
            'last_name': last_name,
            'email': email.lower(),
            'home_region_id': '1'
        })

    with open('output/my_users.csv', 'w', newline='', encoding='utf-8') as f:
        headers = ['f3_name', 'first_name', 'last_name', 'email', 'home_region_id']
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(my_users)
        
    print(f"Wrote {len(my_users)} compliant records to output/my_users.csv")

if __name__ == '__main__':
    generate_reports()
