"""Private administrator file drive."""

revision = "0043_admin_drive"


def upgrade(cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_drive_folders (
            id BIGINT NOT NULL AUTO_INCREMENT,
            parent_id BIGINT NULL,
            name VARCHAR(255) NOT NULL,
            created_by BIGINT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_admin_drive_folders_parent (parent_id, name),
            CONSTRAINT fk_admin_drive_folders_parent
                FOREIGN KEY (parent_id) REFERENCES admin_drive_folders(id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_drive_files (
            id BIGINT NOT NULL AUTO_INCREMENT,
            folder_id BIGINT NULL,
            stored_name VARCHAR(80) NOT NULL,
            original_name VARCHAR(255) NOT NULL,
            mime_type VARCHAR(160) NOT NULL DEFAULT 'application/octet-stream',
            size_bytes BIGINT NOT NULL,
            uploaded_by BIGINT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_admin_drive_files_stored_name (stored_name),
            KEY idx_admin_drive_files_folder (folder_id, original_name),
            CONSTRAINT fk_admin_drive_files_folder
                FOREIGN KEY (folder_id) REFERENCES admin_drive_folders(id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
