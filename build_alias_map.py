import csv
import json
import re
import xml.etree.ElementTree as ET
import os
import difflib
import html
import glob
import html

def clean_text(text):
    if not text: return ''
    return html.unescape(text.strip())

def normalize_name(name):
    if not name or name == '[NULL]': return ''
    name = html.unescape(name.strip())
    name = re.sub(r'\(.*?\)', '', name)
    name = name.lstrip('@').lower().strip()
    name = re.sub(r'\bqic\b', '', name)
    name = re.sub(r'\bfngs?\b', '', name)
    return name.strip()

def normalize_email(email):
    if not email or email == '[NULL]': return ''
    return email.strip().lower()

def build_alias_map():
    # 1. Load HQ Master Profiles
    master_users = []
    
    with open('import/user_master.csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
        reader = csv.DictReader(f)
        for row in reader:
            hq_email = normalize_email(row.get('email', ''))
            f3_name = normalize_name(row.get('f3_name', ''))
            first_name = normalize_name(row.get('first_name', ''))
            last_name = normalize_name(row.get('last_name', ''))
            user_id = row.get('id', '')
            
            if f3_name:
                master_users.append({
                    'f3_name': f3_name,
                    'email': hq_email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'id': user_id,
                    'original_f3_name': clean_text(row.get('f3_name', ''))
                })

    master_names_set = set([u['f3_name'] for u in master_users])

    # 2. Gather Legacy Candidates
    legacy_candidates = {}
    
    def add_to_legacy_candidates(f_name, orig, em, first, last):
        norm = normalize_name(f_name)
        if not norm or norm in master_names_set: return # Resolves identically
        
        if norm not in legacy_candidates:
            legacy_candidates[norm] = {
                'original_name': clean_text(orig),
                'email': normalize_email(em),
                'first_name': normalize_name(first),
                'last_name': normalize_name(last),
                'display_name': ''
            }
        else:
            if not legacy_candidates[norm]['email'] and em: legacy_candidates[norm]['email'] = normalize_email(em)
            if not legacy_candidates[norm]['first_name'] and first: legacy_candidates[norm]['first_name'] = normalize_name(first)
            if not legacy_candidates[norm]['last_name'] and last: legacy_candidates[norm]['last_name'] = normalize_name(last)

    if os.path.exists('import/legacy_pax_directory.csv'):
        with open('import/legacy_pax_directory.csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
            for row in csv.DictReader(f):
                add_to_legacy_candidates(row.get('F3_Name', ''), row.get('F3_Name', ''), row.get('Email', ''), row.get('First\nName', ''), row.get('Last\nName', ''))

    if os.path.exists('import/legacy_master_directory.csv'):
        with open('import/legacy_master_directory.csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
            for row in csv.DictReader(f):
                add_to_legacy_candidates(row.get('F3_Name', ''), row.get('F3_Name', ''), row.get('Email', ''), row.get('First\nName', ''), row.get('Last\nName', ''))

    # 2.5 Gather PAXminer Users Candidates
    paxminer_candidates = {}
    paxminer_files = glob.glob('import/PAXminer_users_*.csv')
    if paxminer_files:
        # Assuming only one or we take the newest
        latest_paxminer = max(paxminer_files, key=os.path.getctime)
        with open(latest_paxminer, 'r', encoding='utf-8-sig', errors='ignore') as f:
            for row in csv.DictReader(f):
                pax_name = row.get('real_name', '')
                if not pax_name:
                    pax_name = row.get('user_name', '')
                paxminer_id = row.get('user_id', '')
                # Slack username vs real name could be mixed up, try to use f3 name if available, often stored in user_name or real_name.
                # In PAXminer export, user_name is often the Slack handle (f3_name)
                f3_name = row.get('user_name', '')
                first_name = ''
                last_name = ''
                if row.get('real_name'):
                    parts = row.get('real_name').split(' ', 1)
                    first_name = parts[0]
                    if len(parts) > 1:
                        last_name = parts[1]

                email = row.get('email', '')
                phone = row.get('phone', '')

                norm = normalize_name(f3_name)
                if not norm: continue
                
                # If it's already in master, we don't strictly *need* it as a candidate, but we keep it for downrange check
                if norm not in paxminer_candidates:
                    paxminer_candidates[norm] = {
                        'original_name': clean_text(f3_name),
                        'email': normalize_email(email),
                        'first_name': normalize_name(first_name),
                        'last_name': normalize_name(last_name),
                        'phone': phone,
                        'paxminer_user_id': paxminer_id,
                        'display_name': clean_text(row.get('real_name', ''))
                    }

    aliases_map = {}
    display_aliases_map = {}
    match_logs = []
    
    # Reusable matching engine
    manual_aliases = {
        "bearded millenial": "beardedmillennial",
        "bearded millennial": "beardedmillennial",
        "bearded millenial (bm)": "beardedmillennial",
        "bm": "beardedmillennial",
        "tin man 2.0": "TinManToo",
        "tin man (2.0?)": "TinManToo",
        "tinman 2.0": "TinManToo",
        "tinman2": "TinManToo",
        "yogibear": "Yogi Bear",
        "yogi": "Yogi Bear",
        "cancan": "can can",
        "sop": "Son of a Preacher",
        "joshuaesc": "Twinkle",
        "big bird": "Big Bird-JAX GUY",
        "hensell harris": "Blackberry",
        "easy go": "EZ GO",
        "howell": "Mrs. Howell",
        "alzheimer": "Alzheimer's",
        "jumanji": "Jumanji - JAX GUY",
        "rob lachance": "Yogi Bear",
        "tebow": "Teebow",
        "used-to": "Used-To"
    }

    def find_match(unrec_norm, unrec_data, target_pool):
        target_f3_names = [u['f3_name'] for u in target_pool]
        
        # 0. Manual Overrides
        if unrec_norm in manual_aliases:
            manual_hq = manual_aliases[unrec_norm]
            matched = next((m for m in target_pool if m['f3_name'] == normalize_name(manual_hq)), None)
            if matched: 
                return matched, "Manual Override"
            else:
                return {
                    'f3_name': normalize_name(manual_hq),
                    'original_f3_name': manual_hq,
                    'id': ''
                }, "Manual Override (New Entity)"

        # 1. Exact Email Matches
        if unrec_data.get('email'):
            matched = next((m for m in target_pool if m['email'] == unrec_data['email']), None)
            if matched: return matched, "Exact Email Match"
            
        # 2. First/Last Name Match
        first = unrec_data.get('first_name')
        last = unrec_data.get('last_name')
        if first and last:
            matched = next((m for m in target_pool if m['first_name'] == first and m['last_name'] == last), None)
            if matched: return matched, "First/Last Name Match"
            
        # 3. Display Name Match
        disp = normalize_name(unrec_data.get('display_name', ''))
        if disp:
            matched = next((m for m in target_pool if m['f3_name'] == disp), None)
            if matched: return matched, "Display Name Match"
            
        # 4. Fuzzy String Match
        matches = difflib.get_close_matches(unrec_norm, target_f3_names, n=1, cutoff=0.8)
        if matches:
            matched = next((m for m in target_pool if m['f3_name'] == matches[0]), None)
            if matched: return matched, f"Fuzzy String Match (>80% accuracy) to '{matches[0]}'"
            
        # 5. Heuristic Substrings (Digits)
        no_digits = re.sub(r'\d+', '', unrec_norm).strip()
        if no_digits and no_digits != unrec_norm:
            matched = next((m for m in target_pool if m['f3_name'] == no_digits), None)
            if matched: return matched, "Heuristic Match (Stripped Digits)"
            
            stripped_fuzzy = difflib.get_close_matches(no_digits, target_f3_names, n=1, cutoff=0.8)
            if stripped_fuzzy:
                matched = next((m for m in target_pool if m['f3_name'] == stripped_fuzzy[0]), None)
                if matched: return matched, f"Heuristic Fuzzy Match (Stripped Digits) to '{stripped_fuzzy[0]}'"

        # 6. Keyword Substrings (ssi/parens)
        scrubbed = re.sub(r'\bssi\b', '', unrec_norm)
        scrubbed = re.sub(r'\(.*?\)', '', scrubbed).strip()
        if scrubbed and scrubbed != unrec_norm:
            matched = next((m for m in target_pool if m['f3_name'] == scrubbed), None)
            if matched: return matched, "Heuristic Match (Stripped Keywords/Parens)"
            
            stripped_fuzzy = difflib.get_close_matches(scrubbed, target_f3_names, n=1, cutoff=0.8)
            if stripped_fuzzy:
                matched = next((m for m in target_pool if m['f3_name'] == stripped_fuzzy[0]), None)
                if matched: return matched, f"Heuristic Fuzzy Match (Stripped Keywords/Parens) to '{stripped_fuzzy[0]}'"
                
        return None, ""

    def append_log(unrec_norm, orig_name, matched_master, reason):
        if unrec_norm not in aliases_map:
            aliases_map[unrec_norm] = matched_master['f3_name']
            display_aliases_map[unrec_norm] = matched_master['original_f3_name']
            
        pool_id = matched_master.get('id', '')
        if not pool_id: pool_id = "Legacy Match (TMP_ID pending)"
        
        match_logs.append({
            'unmatched_name': orig_name,
            'matched_f3_name': matched_master['original_f3_name'],
            'match_reason': reason,
            'user_id': pool_id
        })

    # 3. Evaluate Legacy Candidates against HQ Master
    legacy_master_users = []
    for unrec_norm, unrec_data in legacy_candidates.items():
        matched, reason = find_match(unrec_norm, unrec_data, master_users)
        if matched:
            append_log(unrec_norm, unrec_data['original_name'], matched, reason)
        else:
            # Become Canonical Legacy (TMP_ID target pools)
            legacy_master_users.append({
                'f3_name': unrec_norm,
                'email': unrec_data['email'],
                'first_name': unrec_data['first_name'],
                'last_name': unrec_data['last_name'],
                'id': '',
                'original_f3_name': unrec_data['original_name']
            })

    # 3.5 Evaluate PAXminer Candidates against HQ Master and Legacy Candidates
    downrange_pax = []
    downrange_id_counter = 1
    
    current_known_pool = master_users + legacy_master_users
    
    for unrec_norm, pm_data in paxminer_candidates.items():
        matched, reason = find_match(unrec_norm, pm_data, current_known_pool)
        if matched:
            append_log(unrec_norm, pm_data['original_name'], matched, f"PAXminer Match: {reason}")
        else:
            # It's a Downrange PAX!
            tmp_dr_id = f"TMP_DR_{downrange_id_counter}"
            downrange_id_counter += 1
            
            dr_user = {
                'id': tmp_dr_id,
                'f3_name': unrec_norm,
                'original_f3_name': pm_data['original_name'],
                'first_name': pm_data['first_name'] or '[NULL]',
                'last_name': pm_data['last_name'] or '[NULL]',
                'email': pm_data['email'] or '',
                'phone': pm_data['phone'] or '[NULL]',
                'emergency_contact': '[NULL]',
                'emergency_phone': '[NULL]',
                'status': 'active',
                'paxminer_user_id': pm_data['paxminer_user_id']
            }
            downrange_pax.append(dr_user)
            
            # Add to legacy master so future WP/Schedule lookups can match them
            legacy_master_users.append({
                'f3_name': unrec_norm,
                'email': pm_data['email'],
                'first_name': pm_data['first_name'],
                'last_name': pm_data['last_name'],
                'id': tmp_dr_id,
                'original_f3_name': pm_data['original_name']
            })

    # 4. Gather Unrecognized Users (WP + Q Schedules)
    all_known_users_pool = master_users + legacy_master_users
    legacy_names_set = set([u['f3_name'] for u in legacy_master_users])
    
    unrecognized_users = {}
    
    def add_unrecognized(f3_name_norm, f3_name_orig, email, first, last, display=''):
        if f3_name_orig.startswith('@'): f3_name_orig = f3_name_orig.lstrip('@')
        if not f3_name_norm: return
        if f3_name_norm in master_names_set or f3_name_norm in legacy_names_set: return
        
        if f3_name_norm not in unrecognized_users:
            unrecognized_users[f3_name_norm] = {
                'original_name': f3_name_orig,
                'email': normalize_email(email),
                'first_name': normalize_name(first),
                'last_name': normalize_name(last),
                'display_name': display.strip()
            }
        else:
            if not unrecognized_users[f3_name_norm]['email'] and email: unrecognized_users[f3_name_norm]['email'] = normalize_email(email)
            if not unrecognized_users[f3_name_norm]['first_name'] and first: unrecognized_users[f3_name_norm]['first_name'] = normalize_name(first)
            if not unrecognized_users[f3_name_norm]['last_name'] and last: unrecognized_users[f3_name_norm]['last_name'] = normalize_name(last)

    if os.path.exists('import/legacy_q_schedule.csv'):
        with open('import/legacy_q_schedule.csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
            for row in csv.DictReader(f):
                f_name = row.get('Q', '')
                add_unrecognized(normalize_name(f_name), clean_text(f_name), '', '', '')

    xml_file = 'import/f3stsimons.wordpress.com.2026-02-23.000.xml'
    if os.path.exists(xml_file):
        ns = {'wp': 'http://wordpress.org/export/1.2/'}
        tree = ET.parse(xml_file)
        root = tree.getroot()
        channel = root.find('.//channel')
        if channel is not None:
            for author in channel.findall('wp:author', namespaces=ns):
                login = author.findtext('wp:author_login', namespaces=ns)
                email = author.findtext('wp:author_email', namespaces=ns)
                first = author.findtext('wp:author_first_name', namespaces=ns)
                last = author.findtext('wp:author_last_name', namespaces=ns)
                disp = author.findtext('wp:author_display_name', namespaces=ns)
                orig = disp if disp else login
                add_unrecognized(normalize_name(login), clean_text(orig), email, first, last, disp)

        for item in root.findall('.//item'):
            if item.findtext('wp:post_type', namespaces=ns) != 'post': continue
            for cat in item.findall('category'):
                if cat.attrib.get('domain') == 'post_tag':
                    tag_name = clean_text(cat.text)
                    if tag_name: add_unrecognized(normalize_name(tag_name), tag_name, '', '', '')

    # 5. Evaluate Unrecognized against Dual Master Pools
    for unrec_norm, unrec_data in unrecognized_users.items():
        matched, reason = find_match(unrec_norm, unrec_data, all_known_users_pool)
        if matched:
            append_log(unrec_norm, unrec_data['original_name'], matched, reason)

    # Output validation logs
    with open('output/users_alias.csv', 'w', newline='', encoding='utf-8') as f:
        headers = ['unmatched_name', 'matched_f3_name', 'match_reason', 'user_id']
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(match_logs)

    # Output Downrange PAX
    with open('output/users_downrange.csv', 'w', newline='', encoding='utf-8') as f:
        headers = ['id', 'f3_name', 'original_f3_name', 'first_name', 'last_name', 'email', 'phone', 'emergency_contact', 'emergency_phone', 'status', 'paxminer_user_id']
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(downrange_pax)

    with open('import/aliases.json', 'w', encoding='utf-8') as f:
        json.dump(aliases_map, f, indent=4)
        
    with open('import/display_aliases.json', 'w', encoding='utf-8') as f:
        json.dump(display_aliases_map, f, indent=4)
        
    print(f"Successfully generated aliases.json with {len(aliases_map)} auto-mapped aliases.")
    print(f"Wrote match log to output/users_alias.csv with {len(match_logs)} documented matches.")
    print(f"Wrote {len(downrange_pax)} Downrange PAX to output/users_downrange.csv.")

if __name__ == '__main__':
    build_alias_map()
