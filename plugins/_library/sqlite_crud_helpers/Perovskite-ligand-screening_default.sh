# ── SNIPPET: sqlite_crud_helpers/Perovskite-ligand-screening_default ─
# Scheduler:   any
# Tool:        any
# Tested:      MD/lib/functions_db.py
# Invariants:
#   - SQL statements are schema-coupled; keep table/column names unchanged unless schema changes.
#   - Each add_* returns lastrowid; commit is optional via commit flag.
# Notes: This is a library; import and call specific functions.
# ────────────────────────────────────────────────────────────

import sqlite3

def create_connection(db_filename):
    connection = None
    try:
        connection = sqlite3.connect(db_filename)
    except sqlite3.Error as error:
        print(('\nERROR: Failed to connection to database "{}".\n       Error: {}\n'.format(error)))

    return connection

def create_table(connection, sql):
    try:
        c = connection.cursor()
        c.execute(sql)
    except sqlite3.Error as error:
        print(("\nERROR: Failed to create table.\n       Error: {}\n       SQL statement: {}\n".format(error, sql)))
        return False
    return True

def retrieve_rows(connection, sql, values=None):
    try:
        c = connection.cursor()
        
        if values == None:
            c.execute(sql)
        else:
            c.execute(sql, values)
        rows = c.fetchall()
    except sqlite3.Error as error:
        print(("\nERROR: Failed to retreive rows from sqlite table.\n       Error: {}\n       SQL statement: '{}'\n".format(error, sql)))
        return []
    
    return rows

def delete_ligand(connection, task_id):
    try:
        c = connection.cursor()
        c.execute('DELETE FROM ligands WHERE id={}'.format(task_id))
        connection.commit()
    except sqlite3.Error as error:
        print(("\nERROR: Failed to delete ligand from ligands table.\n       Error: {}\n".format(error)))
        return False
    
    return True
