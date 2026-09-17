# Nginx template

Template file:

```text
deploy/nginx/cyber-bonus.conf
```

Adjust before installation:

- `server_name`
- TLS certificate paths
- `/opt/cyber-bonus/app/static/`
- `/var/www/clubmodule_uploads/stage/`
- upstream bind address if gunicorn does not listen on `127.0.0.1:8000`
- global `client_max_body_size` if `CLUBMODULE_IMAGE_MAX_MB` changes
- upload limit in `location = /admin/files/upload` if `ADMIN_FILES_REQUEST_MAX_MB` changes

## Install example

```bash
sudo cp deploy/nginx/cyber-bonus.conf /etc/nginx/sites-available/cyber-bonus.conf
sudo ln -s /etc/nginx/sites-available/cyber-bonus.conf /etc/nginx/sites-enabled/cyber-bonus.conf
sudo nginx -t
sudo systemctl reload nginx
```

## Uploads

The `/uploads/` alias must match `CLUBMODULE_UPLOAD_ROOT` and `CLUBMODULE_UPLOAD_URL_PREFIX`.

For the current template:

```env
CLUBMODULE_UPLOAD_ROOT=/var/www/clubmodule_uploads/stage
CLUBMODULE_UPLOAD_URL_PREFIX=/uploads
ADMIN_FILES_ROOT=/var/www/clubmodule_uploads/stage_admin_drive
```

`ADMIN_FILES_ROOT` must stay outside the public `/uploads/` alias. Files from the admin drive are returned only by authenticated `/admin/files/...` routes.

If Nginx is not configured yet, Flask still has a fallback `/uploads/<path>` route, but production should serve uploads through Nginx.
