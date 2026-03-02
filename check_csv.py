import csv
for f in ['user_master.csv', 'legacy_pax_directory.csv', 'legacy_master_directory.csv']:
    print(f"--- {f} ---")
    with open(f, 'r', encoding='utf-8-sig', errors='ignore') as csvfile:
        reader = csv.reader(csvfile)
        headers = next(reader)
        print("HEADERS:", headers)
        try:
            print("ROW 1:", next(reader))
        except StopIteration:
            pass
