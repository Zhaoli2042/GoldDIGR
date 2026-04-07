# ── SNIPPET: id_lookup_tables/Perovskite-ligand-screening_default ─
# Scheduler:   any
# Tool:        any
# Tested:      MD/lib/functions_db.py
# Invariants:
#   - Only accepts a fixed allowlist of table names.
# Notes: Used by stability collection to map metals/halides/ligands.
# ────────────────────────────────────────────────────────────

def get_indices(connection, table=None):
    
    if table is None or table not in ['bodies', 'headgroups', 'linkers', 'metals', 'halides', 'ligands']:
        print('functions.db::get_indices(connection, table): table is not recognized. Accepts only bodies, headgroups, linkers, metals, halides, ligands.\nAborting....\n')
        exit()
    
    try:
        c = connection.cursor()
        c.execute('SELECT id,name FROM {}'.format(table))
        rows = c.fetchall()
    except sqlite3.Error as error:
        print(("\nERROR: Failed to retreive rows from {} table.\n       Error: {}\n".format(table, error)))
        return {}
    
    Indices = {}
    for r in rows:
        Indices[r[1]] = r[0]
        
    return Indices
