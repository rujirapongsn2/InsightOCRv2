include /etc/nginx/conf.d/proxy-common.inc;
proxy_connect_timeout 60s;
proxy_send_timeout 300s;
proxy_read_timeout 300s;
proxy_buffering off;
