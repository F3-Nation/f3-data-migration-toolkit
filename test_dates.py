import re
import datetime

titles = [
    "Thursday Renegade Jan. 7, 2021MrBrady, YogiBear...",
    "Sailors warning January 11, 2021",
    "Ironman 12/25/2020",
    "Random Title 2021-01-12",
    "Jailbreak (01/11/2021)"
]
aos = ["Renegade", "Iron Man", "Ironman", "Jailbreak", "Sailors Warning", "Sailor's Warning", "Rubicon"]

date_patterns = [
    r'(Jan(?:uary|\.)?|Feb(?:ruary|\.)?|Mar(?:ch|\.)?|Apr(?:il|\.)?|May|Jun(?:e|\.)?|Jul(?:y|\.)?|Aug(?:ust|\.)?|Sep(?:tember|\.|t\.)?|Oct(?:ober|\.)?|Nov(?:ember|\.)?|Dec(?:ember|\.)?)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,)?\s+(\d{4})',
    r'(\d{1,2})/(\d{1,2})/(\d{4})',
    r'(\d{4})-(\d{2})-(\d{2})'
]

for text in titles:
    found_date = None
    for pat in date_patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            groups = match.groups()
            if len(groups) == 3:
                try:
                    if groups[0].isdigit() and len(groups[0]) == 4:
                        # YYYY-MM-DD
                        found_date = f"{groups[0]}-{int(groups[1]):02d}-{int(groups[2]):02d}"
                    elif groups[0].isdigit():
                        # MM/DD/YYYY
                        found_date = f"{groups[2]}-{int(groups[0]):02d}-{int(groups[1]):02d}"
                    else:
                        # Month DD, YYYY
                        month_str = groups[0][:3].title()
                        month_num = datetime.datetime.strptime(month_str, '%b').month
                        found_date = f"{groups[2]}-{month_num:02d}-{int(groups[1]):02d}"
                    break
                except:
                    pass
    
    found_ao = None
    for ao in aos:
        if ao.lower() in text.lower():
            found_ao = ao
            break
            
    print(f"[{found_date}] [{found_ao}]  -- FROM: {text}")
