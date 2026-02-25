#!/usr/bin/env python3
"""
Baseline Loader - Načítá historické baseline data z peak_investigation tabulky

Účel:
    Regular phase (15-min) potřebuje HISTORICKÉ baseline pro detekci peak.
    Bez historické informace nemůže detekovat, že se něco změnilo.
    
Algoritmus:
    1. SELECT z peak_investigation za posledních 7 dní (indexované podle timestamp)
    2. Seskupi po error_type a timestamp
    3. Spočítej histórii baseline rate (reference_value) v 15-min oknech
    4. Vrať seznam rates pro každý error_type
    
Integrace:
    baseline_loader = BaselineLoader(db_conn)
    historical = baseline_loader.load_historical_rates(
        error_types=['NullPointerException', 'TimeoutException'],
        lookback_days=7
    )
    # historical = {
    #   'NullPointerException': [0, 1, 0, 2, 1, 0, ..., 3, 2],  ← 96+ oken
    # }
"""

import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from collections import defaultdict


class BaselineLoader:
    """Načítá historické baseline data z DB"""
    
    def __init__(self, db_conn):
        """
        Args:
            db_conn: psycopg2 connection (musí mít SELECT na peak_investigation)
        """
        self.db_conn = db_conn
    
    def load_historical_rates(
        self,
        error_types: List[str],
        lookback_days: int = 7,
        window_minutes: int = 15,
        min_samples: int = 3
    ) -> Dict[str, List[float]]:
        """
        Načte historické baseline rates (reference_value) z peak_investigation.
        
        Vrací slovník:
            {
              'error_type': [rate1, rate2, ..., rateN],  # Seřazeno chronologicky
              ...
            }
        
        Args:
            error_types: Seznam error_type k načtení (např. ['NullPointerException'])
            lookback_days: Kolik dní historie vzít (default: 7)
            window_minutes: Velikost okna (default: 15)
            min_samples: Minimální počet vzorků k Return (default: 3)
        
        Returns:
            {error_type -> [baseline_rates]}
        """
        if not error_types:
            return {}
        
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        
        try:
            cursor = self.db_conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # SQL: SELECT reference_value (baseline) z tabulky
            # Načte VŠECHNA data (ne jen anomální) pro přesný baseline
            query = """
            SELECT
                error_type,
                reference_value,
                timestamp,
                EXTRACT(EPOCH FROM timestamp)::BIGINT as ts_epoch
            FROM ailog_peak.peak_investigation
            WHERE
                error_type = ANY(%s)
                AND timestamp > %s
                AND reference_value IS NOT NULL
                AND reference_value > 0
            ORDER BY error_type, timestamp ASC
            """
            
            cursor.execute(query, (error_types, cutoff_time))
            rows = cursor.fetchall()
            cursor.close()
            
            if not rows:
                print(f"⚠️ BaselineLoader: Žádná data pro error_types={error_types}")
                return {}
            
            # Seskupi po error_type
            rates_by_error: Dict[str, List[Dict]] = defaultdict(list)
            for row in rows:
                rates_by_error[row['error_type']].append({
                    'reference_value': row['reference_value'],
                    'timestamp': row['timestamp'],
                    'ts_epoch': row['ts_epoch'],
                })
            
            # Proces každý error_type
            result = {}
            for error_type, records in rates_by_error.items():
                if len(records) < min_samples:
                    # Málo vzorků - skip
                    continue
                
                # Seřaď chronologicky (mělo by být, ale jistota)
                records.sort(key=lambda x: x['ts_epoch'])
                
                # Extrahuj baseline rates
                baseline_rates = [r['reference_value'] for r in records]
                result[error_type] = baseline_rates
                
                print(f"✓ {error_type}: {len(baseline_rates)} historical rates")
            
            return result
            
        except Exception as e:
            print(f"❌ BaselineLoader error: {e}")
            return {}
    
    def load_baseline_for_fingerprint(
        self,
        fingerprint: str,
        lookback_days: int = 7,
        min_samples: int = 3
    ) -> List[float]:
        """
        Načte historický baseline pro konkrétní fingerprint.
        
        (Alternativa k load_historical_rates pro single fingerprint)
        """
        try:
            cursor = self.db_conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=lookback_days)
            
            query = """
            SELECT reference_value
            FROM ailog_peak.peak_investigation
            WHERE
                reference_value IS NOT NULL
                AND timestamp > %s
            ORDER BY timestamp ASC
            LIMIT 1000
            """
            
            cursor.execute(query, (cutoff_time,))
            rows = cursor.fetchall()
            cursor.close()
            
            if not rows or len(rows) < min_samples:
                return []
            
            return [float(r['reference_value']) for r in rows]
            
        except Exception as e:
            print(f"❌ load_baseline_for_fingerprint error: {e}")
            return []
    
    def get_baseline_stats(
        self,
        error_types: List[str],
        lookback_days: int = 7
    ) -> Dict[str, Dict]:
        """
        Vrátí statistiku baseline - min, max, avg pro každý error_type.
        
        Returns:
            {
              'NullPointerException': {
                'min': 0.5,
                'max': 45.2,
                'avg': 12.3,
                'median': 10.0,
                'count': 126
              },
              ...
            }
        """
        rates = self.load_historical_rates(error_types, lookback_days)
        
        if not rates:
            return {}
        
        result = {}
        for error_type, rate_list in rates.items():
            if not rate_list:
                continue
            
            sorted_rates = sorted(rate_list)
            count = len(sorted_rates)
            median_idx = count // 2
            
            result[error_type] = {
                'min': min(rate_list),
                'max': max(rate_list),
                'avg': sum(rate_list) / count,
                'median': sorted_rates[median_idx],
                'count': count,
            }
        
        return result


# CLI pro testování
if __name__ == '__main__':
    import argparse
    import os
    from dotenv import load_dotenv
    from pathlib import Path
    
    load_dotenv()
    load_dotenv(Path(__file__).parent.parent.parent / '.env')
    
    parser = argparse.ArgumentParser(description='Baseline Loader - Debug tool')
    parser.add_argument('--error-types', nargs='+', help='Error types k testování')
    parser.add_argument('--days', type=int, default=7, help='Lookback days')
    parser.add_argument('--stats', action='store_true', help='Show statistics')
    
    args = parser.parse_args()
    
    # Connect to DB
    try:
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST'),
            port=int(os.getenv('DB_PORT', 5432)),
            database=os.getenv('DB_NAME'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
        )
    except Exception as e:
        print(f"❌ DB connection failed: {e}")
        exit(1)
    
    loader = BaselineLoader(conn)
    
    if args.error_types:
        if args.stats:
            stats = loader.get_baseline_stats(args.error_types, args.days)
            print(f"\n📊 Baseline Statistics ({args.days} days):\n")
            for et, stat in stats.items():
                print(f"{et}:")
                print(f"  Count: {stat['count']}")
                print(f"  Avg:   {stat['avg']:.2f}")
                print(f"  Min:   {stat['min']:.2f}")
                print(f"  Max:   {stat['max']:.2f}")
        else:
            rates = loader.load_historical_rates(args.error_types, args.days)
            print(f"\n📈 Historical Rates ({args.days} days):\n")
            for et, rate_list in rates.items():
                print(f"{et}: {len(rate_list)} samples")
                print(f"  First 10: {rate_list[:10]}")
                if len(rate_list) > 10:
                    print(f"  Last 10:  {rate_list[-10:]}")
    else:
        print("Usage: python baseline_loader.py --error-types NullPointerException TimeoutException [--stats]")
    
    conn.close()
