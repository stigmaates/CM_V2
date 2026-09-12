"""Stage team analytics and a durable first module-registration timestamp."""

revision = "0029_team"


def upgrade(cursor):
    cursor.execute("""CREATE TABLE IF NOT EXISTS team_admins (
        club_id INT NOT NULL, admin_id BIGINT NOT NULL, name VARCHAR(255) NOT NULL,
        admin_status VARCHAR(80) NULL, work_schedule VARCHAR(80) NULL,
        PRIMARY KEY(club_id,admin_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS team_shifts (
        club_id INT NOT NULL, shift_id BIGINT NOT NULL, admin_id BIGINT NOT NULL,
        started_at DATETIME NOT NULL, stopped_at DATETIME NULL,
        PRIMARY KEY(club_id,shift_id), KEY idx_team_shift_time(club_id,started_at,stopped_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS team_sync_state (
        club_id INT PRIMARY KEY, langame_club_id BIGINT NULL, updated_at DATETIME NULL,
        attempted_at DATETIME NULL, error_code VARCHAR(100) NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS module_registrations (
        club_id INT NOT NULL, guest_id BIGINT NOT NULL, registered_at DATETIME NULL,
        source VARCHAR(40) NOT NULL, is_estimated TINYINT NOT NULL DEFAULT 1,
        observed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(club_id,guest_id), KEY idx_module_registered(club_id,registered_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    # Mirroring uses DELETE/INSERT, not UPDATE: imported links must never be stamped as exact new registrations.
    cursor.execute("DROP TRIGGER IF EXISTS team_module_registration")
    cursor.execute("""CREATE TRIGGER team_module_registration AFTER UPDATE ON guests FOR EACH ROW
        BEGIN
          IF (OLD.telegram_id IS NULL OR OLD.telegram_id=0) AND NEW.telegram_id IS NOT NULL AND NEW.telegram_id<>0 THEN
            INSERT INTO module_registrations(club_id,guest_id,registered_at,source,is_estimated,observed_at)
            VALUES(NEW.club_id,NEW.guest_id,UTC_TIMESTAMP(),'telegram_link',0,UTC_TIMESTAMP())
            ON DUPLICATE KEY UPDATE guest_id=module_registrations.guest_id;
          END IF;
        END""")
