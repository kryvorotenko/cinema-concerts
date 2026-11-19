#!/bin/sh
set -eu
BIN=/opt/kafka/bin
: "${BOOTSTRAP:?set BOOTSTRAP}"
: "${TOPIC_DOMAIN_EVENTS:?load config/project.env}"
: "${TOPIC_NOTIFICATIONS:?load config/project.env}"
: "${TOPIC_TICKET_TELEMETRY:?load config/project.env}"
create_topic() {
  "$BIN/kafka-topics.sh" --bootstrap-server "$BOOTSTRAP" --create --if-not-exists \
    --topic "$1" --partitions "$2" --replication-factor 1
}
create_topic "$TOPIC_DOMAIN_EVENTS" "${DOMAIN_PARTITIONS:-3}"
create_topic "$TOPIC_NOTIFICATIONS" "${NOTIFICATION_PARTITIONS:-3}"
create_topic "$TOPIC_TICKET_TELEMETRY" "${TELEMETRY_PARTITIONS:-3}"
"$BIN/kafka-topics.sh" --bootstrap-server "$BOOTSTRAP" --list
