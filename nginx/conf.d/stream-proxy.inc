include /etc/nginx/conf.d/proxy-common.inc;
proxy_connect_timeout 60s;
proxy_send_timeout 900s;
proxy_read_timeout 900s;
proxy_buffering off;
add_header X-Accel-Buffering "no" always;
