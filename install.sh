#!/bin/bash

# Скрипт установки и управления сервисами антенны
# ИЗМЕНЕНО: Запуск от root, пути исправлены на /home/pi/allIN, исправлена ошибка с PrivateTmp

set -e

# --- КОНФИГУРАЦИЯ ---
# Директория с приложением, определена на основе вашего рабочего пространства
APP_DIR="/home/pi/video"
PYTHON_EXEC="${APP_DIR}/vid/bin/python3"
# --- КОНЕЦ КОНФИГУРАЦИИ ---


echo "=== Установка сервисов Antenna Tracker ==="

# Проверяем права sudo
if [ "$EUID" -ne 0 ]; then
    echo "Пожалуйста, запустите скрипт с правами sudo:"
    echo "sudo bash $0"
    exit 1
fi

# Проверяем что основные файлы на месте
if [ ! -f "${APP_DIR}/simple_tracker.py" ] || [ ! -f "${APP_DIR}/fpv_interface.py" ]; then
    echo "ОШИБКА: Файлы simple_tracker.py или fpv_interface.py не найдены в ${APP_DIR}!"
    echo "Убедитесь, что переменная APP_DIR в скрипте указана верно."
    exit 1
fi

# Проверяем python
if [ ! -f "$PYTHON_EXEC" ]; then
    echo "ОШИБКА: Python не найден по пути $PYTHON_EXEC"
    echo "Убедитесь, что виртуальное окружение создано правильно."
    exit 1
fi

echo "1. Создание файлов сервисов (запуск от пользователя: root)..."

# Создаем antenna-tracker.service
cat > /etc/systemd/system/antenna-tracker.service << EOF
[Unit]
Description=Antenna Tracker Service
After=network.target
Wants=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
ExecStart=${PYTHON_EXEC} ${APP_DIR}/simple_tracker.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

# Создаем fpv-interface.service
cat > /etc/systemd/system/fpv-interface.service << EOF
[Unit]
Description=FPV Interface Web Service
After=network.target antenna-tracker.service
Wants=network.target
Requires=antenna-tracker.service

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
Environment=FLASK_ENV=production
ExecStart=${PYTHON_EXEC} ${APP_DIR}/fpv_interface.py
Restart=always
RestartSec=15
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

echo "2. Подготовка временных файлов..."
# Создаем временные файлы, если их нет. 
# Приложения должны сами управлять правами доступа к ним.
touch /tmp/antenna_commands.txt
touch /tmp/antenna_status.json
touch /tmp/antenna_scan_results.json
chmod 666 /tmp/antenna_*.txt /tmp/antenna_*.json

echo "3. Перезагрузка systemd и включение сервисов..."
systemctl daemon-reload
systemctl enable antenna-tracker.service
systemctl enable fpv-interface.service

echo "4. Запуск/перезапуск сервисов..."
systemctl restart antenna-tracker.service
sleep 1
systemctl restart fpv-interface.service

echo ""
echo "=== УСТАНОВКА ЗАВЕРШЕНА ==="
echo ""
echo "Статус сервисов:"
systemctl status antenna-tracker.service --no-pager -l
echo ""
systemctl status fpv-interface.service --no-pager -l
echo ""
echo "Полезные команды:"
echo "  Просмотр логов антенны:     sudo journalctl -u antenna-tracker.service -f"
echo "  Просмотр логов веб-сервера: sudo journalctl -u fpv-interface.service -f"
echo "  Перезапуск антенны:         sudo systemctl restart antenna-tracker.service"
echo "  Перезапуск веб-сервера:     sudo systemctl restart fpv-interface.service"
echo "  Остановка всех сервисов:    sudo systemctl stop antenna-tracker.service fpv-interface.service"
echo "  Запуск всех сервисов:       sudo systemctl start antenna-tracker.service fpv-interface.service"
echo ""
echo "Веб-интерфейс доступен по адресу: http://$(hostname -I | awk '{print $1}'):5000"
echo ""
