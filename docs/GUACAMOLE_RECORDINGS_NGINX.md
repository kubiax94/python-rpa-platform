# Guacamole Recordings Behind Nginx

This setup assumes:

- Guacamole or guacd writes session recordings into a Linux filesystem path like `/srv/guacamole/recordings`
- the app uses a recording path like `/recordings/{agent_id}/{username}` when an operator starts an on-demand recorded session
- Nginx exposes that same directory tree over HTTP with JSON autoindex enabled
- FastAPI reads the JSON listing and proxies downloads through `/api/guacamole/recordings/*`

## Recommended Mapping

Guacamole recording settings in the app:

```text
Recording path: /recordings/{agent_id}/{username}
Recording browse URL: https://guac.example.internal/recordings
Recording name: {connection_name}-{timestamp}
```

Linux mount or filesystem:

```text
/recordings                      -> path visible inside Guacamole or guacd
/srv/guacamole/recordings        -> host path served by Nginx
```

If you run containers, mount the same host directory into the Guacamole side and into Nginx.

## Example Nginx Server Block

```nginx
server {
    listen 443 ssl http2;
    server_name guac.example.internal;

    ssl_certificate     /etc/letsencrypt/live/guac.example.internal/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/guac.example.internal/privkey.pem;

    location /recordings/ {
        alias /srv/guacamole/recordings/;

        autoindex on;
        autoindex_exact_size off;
        autoindex_localtime off;
        autoindex_format json;

        types {
            application/octet-stream guac;
        }

        add_header Cache-Control "private, max-age=30";
        add_header X-Content-Type-Options nosniff;
    }
}
```

## Plain HTTP Example

If your Guacamole and recordings are already exposed from a lab host like `http://192.168.1.45:8088`, the recording browse URL in the app should be:

```text
http://192.168.1.45:8088/recordings
```

Example non-TLS block:

```nginx
server {
  listen 80;
  server_name _;

  location = / {
    return 302 $scheme://$http_host/guacamole/;
  }

  location /guacamole/ {
    proxy_pass http://guacamole:8080/guacamole/;
    proxy_http_version 1.1;
    proxy_buffering off;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Port $server_port;

    proxy_hide_header X-Frame-Options;
    add_header Content-Security-Policy "frame-ancestors 'self' http://localhost:3000 http://127.0.0.1:3000 http://localhost:8765 http://127.0.0.1:8765 http://192.168.1.10:3000 http://192.168.1.10:8765" always;
  }

  location /recordings/ {
    alias /srv/guacamole/recordings/;

    autoindex on;
    autoindex_exact_size off;
    autoindex_localtime off;
    autoindex_format json;

    types {
      application/octet-stream guac;
    }

    add_header Cache-Control "private, max-age=30";
    add_header X-Content-Type-Options nosniff;
  }
}
```

Important: the `location /recordings/` block must include the `autoindex*` lines. Without them the backend inventory endpoint will not be able to enumerate files.

## Directory Layout

With the path template `/recordings/{agent_id}/{username}`, files end up like:

```text
/srv/guacamole/recordings/
  agent-01/
    alice/
      alice-session-1711825000.guac
    bob/
      bob-session-1711829000.guac
  agent-02/
    charlie/
      charlie-session-1711832000.guac
```

## Notes

- Do not expose this location publicly without access control. The app now proxies downloads through its own authenticated backend, but the raw Nginx URL should still stay internal when possible.
- `browse_url` should usually be an internal URL reachable by the FastAPI host, for example `https://guac.example.internal/recordings`.
- If your Nginx is HTTP only on an internal network, that also works as long as the FastAPI host can reach it.