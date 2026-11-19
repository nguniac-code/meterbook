Meterbook - Meter Reading Field Data Entry (database mini project)
==================================================================

Flask + PostgreSQL web app for registering meters and entering readings
from the field, with a dashboard showing how many readings came out
correct and how many were flagged.

What is in it
-------------
Dashboard       percent correct / flagged, meters still to read, reasons for
                flags, error rate per area, latest flagged readings
Enter reading   pick a meter, type the reading. Customer and previous reading
                are filled in automatically, use is worked out for you
Meters          list of all registered meters
Register meter  add a meter (number, customer, area, type, starting reading)
All readings    every reading, filter All / Correct / Flagged

How a reading gets flagged
--------------------------
The reading is still saved, but marked "flagged" if:
  - it is lower than the previous good reading
  - the use is zero (stuck meter or empty house)
  - the use is more than 3x the meter's usual use (average of its last
    good readings; needs at least 2 earlier readings)
A flagged reading is never used as the "previous" for the next one.

Folder layout
-------------
meter-mini-project/
  app.py
  schema.sql
  requirements.txt
  static/       style.css, logo.svg
  templates/    base, dashboard, entry, register, meters, records

Running it (Windows PowerShell)
-------------------------------
1. Go into this folder:
     cd C:\meter-mini-project

2. Install packages (once):
     pip install -r requirements.txt

3. Make sure the database server is running. If you set up the private
   database on port 5433 earlier, start it with:
     & "C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe" -D C:\pgdata -o "-p 5433" -l C:\pgdata\log.txt start
   (If it says the server is already running, that is fine.)

4. Start the app:
     python app.py

5. Open http://localhost:5000
   The app prints the laptop's Wi-Fi address at startup. Open that address
   with port 5000 on a phone connected to the same Wi-Fi network.
   If the phone cannot connect, run this in an Administrator PowerShell
   window to allow access only from your local subnet:
     New-NetFirewallRule -DisplayName "Meterbook phone access" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5000 -RemoteAddress LocalSubnet -Profile Private,Public

User accounts
-------------
Sign in with the administrator account, then use "Register user" in the
navigation to create accounts. Only the administrator can create users.
User passwords are stored as hashes in the PostgreSQL database.

Database settings
-----------------
The app loads `.env` first, then fills unset settings from the `env` file
in this folder. Set `DB_HOST`, `DB_PORT`, `DB_NAME`,
`DB_USER`, and `DB_PASSWORD` there. PostgreSQL-style names (`PGHOST`,
`PGPORT`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD`) are also supported and
take precedence. The defaults are:
  host 127.0.0.1, port 5432, user postgres, no password, database meter_readings_db

Upgrading from the first version
--------------------------------
Just run the new app.py against the same database. It adds the new columns
and registers the meters found in your old readings automatically. Old
readings count as correct.

To stop the private database:
  & "C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe" -D C:\pgdata stop
