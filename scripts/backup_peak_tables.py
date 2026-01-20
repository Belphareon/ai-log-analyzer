#!/usr/bin/env python3
"""
Backup ailog_peak tables: peak_raw_data and aggregation_data
Uses Python psycopg2 (avoids LDAP issues with psql)
"""

import os
import sys
import psycopg2
from datetime import datetime
from io import StringIO

# Read .env manually
env_vars = {}
with open('.env', 'r') as f:
    for line in f:
        if line.strip() and not line.startswith('#') and '=' in line:
            key, val = line.strip().split('=', 1)
            env_vars[key] = val

DB_CONFIG = {
    'host': env_vars.get('DB_HOST'),
    'port': int(env_vars.get('DB_PORT')),
    'database': env_vars.get('DB_NAME'),
    'user': env_vars.get('DB_USER'),
    'password': env_vars.get('DB_PASSWORD')
}

def backup_table(table_name, backup_dir='_backups'):
    """Backup single table to SQL file"""
    
    print(f"\n📊 Backing up {table_name}...")
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Get row count
        cur.execute(f'SELECT COUNT(*) FROM ailog_peak.{table_name}')
        count = cur.fetchone()[0]
        print(f"   📈 Rows: {count:,}")
        
        # Get column names
        cur.execute(f"""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema='ailog_peak' AND table_name='{table_name}'
            ORDER BY ordinal_position
        """)
        columns = cur.fetchall()
        col_names = [c[0] for c in columns]
        
        # Build INSERT statements - use appropriate ORDER BY
        if table_name == 'peak_raw_data':
            cur.execute(f'SELECT * FROM ailog_peak.{table_name} ORDER BY timestamp DESC LIMIT 100000')
        else:
            cur.execute(f'SELECT * FROM ailog_peak.{table_name} LIMIT 100000')
        rows = cur.fetchall()
        
        backup_file = f'{backup_dir}/ailog_peak_{table_name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.sql'
        
        with open(backup_file, 'w') as f:
            # Header
            f.write(f"-- Backup of ailog_peak.{table_name}\n")
            f.write(f"-- Generated: {datetime.now().isoformat()}\n")
            f.write(f"-- Rows: {count:,}\n")
            f.write(f"-- Columns: {', '.join(col_names)}\n\n")
            
            # INSERT statements
            col_list = ', '.join(col_names)
            for row in rows:
                placeholders = ', '.join(['%s'] * len(row))
                values = ', '.join([
                    f"'{str(v).replace(chr(39), chr(39)+chr(39))}'" if v is not None else 'NULL'
                    for v in row
                ])
                f.write(f"INSERT INTO ailog_peak.{table_name} ({col_list}) VALUES ({values});\n")
            
            f.write(f"\n-- End of backup\n")
        
        file_size = os.path.getsize(backup_file) / (1024 * 1024)
        print(f"   ✅ Saved to: {backup_file}")
        print(f"   📁 Size: {file_size:.1f} MB")
        
        conn.close()
        return backup_file
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    print("=" * 80)
    print("💾 AI Log Analyzer - Database Backup")
    print("=" * 80)
    
    os.makedirs('_backups', exist_ok=True)
    
    # Backup both tables
    files = []
    for table in ['peak_raw_data', 'aggregation_data']:
        backup_file = backup_table(table)
        if backup_file:
            files.append(backup_file)
    
    print("\n" + "=" * 80)
    print(f"✅ Backup complete! {len(files)} files created")
    print("=" * 80)
    
    return 0 if len(files) == 2 else 1


if __name__ == '__main__':
    sys.exit(main())
