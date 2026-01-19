import psycopg2
from dotenv import dotenv_values

config = dotenv_values('.env')

DB_CONFIG = {
    'host': config.get('DB_HOST'),
    'port': int(config.get('DB_PORT')),
    'database': config.get('DB_NAME'),
    'user': config.get('DB_DDL_USER'),
    'password': config.get('DB_DDL_PASSWORD')
}

conn = psycopg2.connect(**DB_CONFIG)
cursor = conn.cursor()
cursor.execute("SET ROLE role_ailog_analyzer_ddl;")

print("Creating tables...")

# 1. peak_raw_data
cursor.execute("""
CREATE TABLE IF NOT EXISTS ailog_peak.peak_raw_data (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    day_of_week INT NOT NULL,
    hour_of_day INT NOT NULL,
    quarter_hour INT NOT NULL,
    namespace VARCHAR(255) NOT NULL,
    error_count FLOAT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (timestamp, day_of_week, hour_of_day, quarter_hour, namespace)
);
""")
conn.commit()
print("OK: peak_raw_data")

# 2. aggregation_data
cursor.execute("""
CREATE TABLE IF NOT EXISTS ailog_peak.aggregation_data (
    id SERIAL PRIMARY KEY,
    day_of_week INT NOT NULL,
    hour_of_day INT NOT NULL,
    quarter_hour INT NOT NULL,
    namespace VARCHAR(255) NOT NULL,
    mean FLOAT,
    stddev FLOAT,
    samples INT DEFAULT 1,
    last_updated TIMESTAMP DEFAULT NOW(),
    UNIQUE (day_of_week, hour_of_day, quarter_hour, namespace)
);
""")
conn.commit()
print("OK: aggregation_data")

# 3. known_issues
cursor.execute("""
CREATE TABLE IF NOT EXISTS ailog_peak.known_issues (
    id SERIAL PRIMARY KEY,
    issue_name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    error_type_pattern VARCHAR(255),
    affected_namespace VARCHAR(255),
    affected_app_name VARCHAR(255),
    typical_ratio_min FLOAT DEFAULT 10,
    typical_ratio_max FLOAT DEFAULT 1000,
    typical_duration_min INT,
    typical_duration_max INT,
    first_detected TIMESTAMP,
    last_occurrence TIMESTAMP,
    occurrence_count INT DEFAULT 0,
    status VARCHAR(50) DEFAULT 'active',
    resolution_steps TEXT,
    is_auto_resolvable BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
""")
conn.commit()
print("OK: known_issues")

# 4. known_peaks
cursor.execute("""
CREATE TABLE IF NOT EXISTS ailog_peak.known_peaks (
    id SERIAL PRIMARY KEY,
    peak_name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    namespace VARCHAR(255),
    app_name VARCHAR(255),
    day_of_week INT,
    hour_of_day INT,
    quarter_hour INT,
    expected_ratio_min FLOAT,
    expected_ratio_max FLOAT,
    expected_duration_min INT,
    expected_duration_max INT,
    peak_type VARCHAR(50),
    is_expected BOOLEAN DEFAULT TRUE,
    first_detected TIMESTAMP,
    last_occurrence TIMESTAMP,
    occurrence_count INT DEFAULT 0,
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW()
);
""")
conn.commit()
print("OK: known_peaks")

# 5. peak_investigation
cursor.execute("""
CREATE TABLE IF NOT EXISTS ailog_peak.peak_investigation (
    peak_id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    day_of_week INT,
    hour_of_day INT,
    quarter_hour INT,
    trace_id VARCHAR(255),
    app_name VARCHAR(255),
    app_version VARCHAR(100),
    namespace VARCHAR(255),
    original_value FLOAT NOT NULL,
    reference_value FLOAT NOT NULL,
    replacement_value FLOAT,
    ratio FLOAT,
    baseline_mean FLOAT,
    same_day_refs_mean FLOAT,
    error_type VARCHAR(255),
    error_message TEXT,
    affected_services TEXT,
    ai_analysis TEXT,
    ai_confidence FLOAT DEFAULT 0.0,
    suspected_root_cause VARCHAR(255),
    known_issue_id INT,
    known_peak_id INT,
    investigation_status VARCHAR(50) DEFAULT 'pending',
    resolution_notes TEXT,
    resolved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (timestamp, namespace, app_name),
    FOREIGN KEY (known_issue_id) REFERENCES ailog_peak.known_issues(id) ON DELETE SET NULL,
    FOREIGN KEY (known_peak_id) REFERENCES ailog_peak.known_peaks(id) ON DELETE SET NULL
);
""")
conn.commit()
print("OK: peak_investigation")

# Create indexes
indexes = [
    "CREATE INDEX IF NOT EXISTS idx_raw_namespace ON ailog_peak.peak_raw_data(namespace)",
    "CREATE INDEX IF NOT EXISTS idx_raw_timestamp ON ailog_peak.peak_raw_data(timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_agg_namespace ON ailog_peak.aggregation_data(namespace)",
    "CREATE INDEX IF NOT EXISTS idx_ki_namespace ON ailog_peak.known_issues(affected_namespace)",
    "CREATE INDEX IF NOT EXISTS idx_kp_namespace ON ailog_peak.known_peaks(namespace)",
    "CREATE INDEX IF NOT EXISTS idx_pi_namespace ON ailog_peak.peak_investigation(namespace)",
    "CREATE INDEX IF NOT EXISTS idx_pi_timestamp ON ailog_peak.peak_investigation(timestamp DESC)",
]

for idx in indexes:
    cursor.execute(idx)
conn.commit()
print("OK: indexes")

conn.close()
print("DONE: DB V2 Setup Complete!")
