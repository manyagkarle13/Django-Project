import sqlite3
import os
DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'db.sqlite3')
print('Using DB', DB)
conn = sqlite3.connect(DB)
c = conn.cursor()
res = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='hod_facultysyllabuspdf'").fetchone()
if res:
    print('Table already exists')
else:
    print('Creating table hod_facultysyllabuspdf...')
    c.execute('''CREATE TABLE hod_facultysyllabuspdf (
        id integer PRIMARY KEY AUTOINCREMENT,
        year varchar(10),
        semester varchar(6),
        pdf_file varchar(255),
        title varchar(255),
        created_at datetime,
        updated_at datetime,
        approved integer NOT NULL DEFAULT 0,
        approved_at datetime,
        approved_by_id integer,
        branch_id integer,
        course_id integer,
        created_by_id integer
    );''')
    conn.commit()
    print('Created table')
conn.close()
