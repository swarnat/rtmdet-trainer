# One-shot initialisation container for Garage (uses the admin HTTP API)
FROM alpine:3.20
RUN apk add --no-cache curl jq
COPY init.sh /usr/local/bin/garage-init.sh
RUN chmod +x /usr/local/bin/garage-init.sh
ENTRYPOINT ["/usr/local/bin/garage-init.sh"]
