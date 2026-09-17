#!/bin/bash

DATA_DIR="${BATTERY_GUARD_DATA_DIR:-$HOME/Library/Application Support/Battery Guard}"
LOG_DIR="$DATA_DIR/logs"
LOG_FILE="$LOG_DIR/battery-guard.log"

mkdir -p "$LOG_DIR"


WARNED=0
CRITICAL=0
LOW_COUNT=0
LAST_UPDATE=""

notify_warning() {
    /usr/bin/osascript -e 'display notification "A célula fraca está entrando na zona de risco. Conecte o carregador nos próximos minutos." with title "Bateria: atenção" sound name "Glass"'
    /usr/bin/say "Atenção. Bateria instável. Conecte o carregador."
}

notify_critical() {
    /usr/bin/osascript -e 'display notification "RISCO DE DESLIGAMENTO. Conecte o carregador agora." with title "BATERIA CRÍTICA" sound name "Sosumi"'
    /usr/bin/afplay /System/Library/Sounds/Sosumi.aiff &
    /usr/bin/say "Bateria crítica. Conecte o carregador agora."
}

while true; do

    POWER=$(/usr/bin/pmset -g batt | head -1)

    # Se estiver no carregador, zera o estado dos alertas
    if echo "$POWER" | grep -q "AC Power"; then
        WARNED=0
        CRITICAL=0
        LOW_COUNT=0
        sleep 20
        continue
    fi

    DATA=$(/usr/sbin/ioreg -rn AppleSmartBattery | grep '"BatteryData"')

    CELLS=$(echo "$DATA" | sed -n \
        's/.*CellVoltage"=(\([0-9]*\),\([0-9]*\),\([0-9]*\)).*/\1 \2 \3/p')

    UPDATE=$(echo "$DATA" | sed -n \
        's/.*"UpdateTime"=\([0-9]*\).*/\1/p')

    [ -z "$CELLS" ] && sleep 15 && continue

    read C1 C2 C3 <<< "$CELLS"

    MIN=$C1
    [ "$C2" -lt "$MIN" ] && MIN=$C2
    [ "$C3" -lt "$MIN" ] && MIN=$C3

    MAX=$C1
    [ "$C2" -gt "$MAX" ] && MAX=$C2
    [ "$C3" -gt "$MAX" ] && MAX=$C3

    DELTA=$((MAX - MIN))

    # Só conta quando o controlador realmente atualiza a leitura
    if [ "$UPDATE" != "$LAST_UPDATE" ]; then
        LAST_UPDATE="$UPDATE"

        echo "$(date '+%Y-%m-%d %H:%M:%S') C1=$C1 C2=$C2 C3=$C3 MIN=$MIN DELTA=$DELTA" \
            >> "$LOG_FILE"

        # Pré-alerta: < 3,35 V e diferença >= 0,40 V
        if [ "$MIN" -le 3350 ] && [ "$DELTA" -ge 400 ]; then
            LOW_COUNT=$((LOW_COUNT + 1))
        else
            LOW_COUNT=0
        fi

        # Duas leituras reais consecutivas
        if [ "$LOW_COUNT" -ge 2 ] && [ "$WARNED" -eq 0 ]; then
            WARNED=1
            notify_warning
        fi

        # Zona crítica depois que a tendência já foi confirmada
        if [ "$WARNED" -eq 1 ] && [ "$MIN" -le 3250 ] && [ "$CRITICAL" -eq 0 ]; then
            CRITICAL=1
            notify_critical
        fi

        # Emergência absoluta
        if [ "$MIN" -le 3050 ]; then
            notify_critical
        fi
    fi

    sleep 15
done
