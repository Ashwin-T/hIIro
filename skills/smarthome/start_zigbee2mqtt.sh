#!/usr/bin/env bash
# Start Zigbee2MQTT if it isn't already running.
# Usage: ./start_zigbee2mqtt.sh
#   stop:    ./start_zigbee2mqtt.sh stop
#   status:  ./start_zigbee2mqtt.sh status

# Load nvm so we get the right Node version
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

Z2M_DIR="/opt/zigbee2mqtt"
PID_FILE="/tmp/zigbee2mqtt.pid"
LOG_FILE="/tmp/zigbee2mqtt.log"

is_running() {
    [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

start() {
    if is_running; then
        echo "zigbee2mqtt already running (pid $(cat "$PID_FILE"))"
        return 0
    fi

    if [ ! -d "$Z2M_DIR" ]; then
        echo "ERROR: $Z2M_DIR not found" >&2
        return 1
    fi

    echo "Starting zigbee2mqtt..."
    cd "$Z2M_DIR" || exit 1
    npm start > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 2

    if is_running; then
        echo "zigbee2mqtt started (pid $(cat "$PID_FILE")), log: $LOG_FILE"
    else
        echo "ERROR: zigbee2mqtt failed to start. Check $LOG_FILE" >&2
        return 1
    fi
}

stop() {
    if ! is_running; then
        echo "zigbee2mqtt is not running"
        rm -f "$PID_FILE"
        return 0
    fi

    echo "Stopping zigbee2mqtt (pid $(cat "$PID_FILE"))..."
    kill "$(cat "$PID_FILE")" 2>/dev/null
    sleep 2
    # Force kill if still alive
    if is_running; then
        kill -9 "$(cat "$PID_FILE")" 2>/dev/null
    fi
    rm -f "$PID_FILE"
    echo "zigbee2mqtt stopped"
}

status() {
    if is_running; then
        echo "zigbee2mqtt is running (pid $(cat "$PID_FILE"))"
    else
        echo "zigbee2mqtt is not running"
    fi
}

case "${1:-start}" in
    start)  start  ;;
    stop)   stop   ;;
    status) status ;;
    restart) stop; start ;;
    *)  echo "Usage: $0 {start|stop|status|restart}" >&2; exit 1 ;;
esac
