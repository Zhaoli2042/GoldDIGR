# ── SNIPPET: sqlite_existence_checks/Perovskite-ligand-screening_default ─
# Scheduler:   any
# Tool:        any
# Tested:      MD/lib/functions_db.py
# Invariants:
#   - If ID is provided, check by id; else require specific keys in record dict.
#   - Abort (exit) if required keys are missing.
# Notes: Includes check_perovskite_A, check_body, check_ligand, check_fingerprint.
# ────────────────────────────────────────────────────────────

def check_body(connection, record={}, ID=None):
    if ID != None:
        sql = 'SELECT count(1) FROM bodies WHERE id={}'.format(ID)
    else:
        columns = ['name', 'series']
        error = False
        for key in columns:
            if key not in list(record.keys()):
                error = True
                print('ERROR: functions_db.py::check_body(): Missing "{}" in record dictionary. Aborting...'.format(key))
        if error: exit()
        
        sql = 'SELECT count(1) FROM bodies WHERE name="{}" AND series="{}"'.format(record['name'], record['series'])

    try:
        c = connection.cursor()
        c.execute(sql)
        count = c.fetchone()[0]
        
    except sqlite3.Error as error:
        print(("\nERROR: functions_db.py::check_body(): Failed to count rows in bodies table.\n       Error: {}\n".format(error)))
        return False
    
    return False if count == 0 else True
