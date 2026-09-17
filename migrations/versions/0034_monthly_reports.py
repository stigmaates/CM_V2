"""Saved monthly club reports and immutable calculation snapshots."""

revision = "0034_monthly_reports"


def upgrade(cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS monthly_reports (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            club_id INT NOT NULL,
            report_year SMALLINT NOT NULL,
            report_month TINYINT NOT NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'ready',
            generated_at DATETIME NOT NULL,
            generated_by BIGINT NULL,
            report_data_json LONGTEXT NOT NULL,
            pdf_path TEXT NOT NULL,
            version VARCHAR(24) NOT NULL DEFAULT 'v1',
            UNIQUE KEY uq_monthly_report_version (club_id, report_year, report_month, version),
            KEY idx_monthly_reports_generated (generated_at),
            KEY idx_monthly_reports_club_period (club_id, report_year, report_month)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
