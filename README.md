# Telegram Bot для Определения и Разделения Сцен в Видео

Этот бот автоматически разделяет видео на отдельные сцены с сохранением оригинального качества. Поддерживает загрузку видео напрямую через Telegram или по ссылке YouTube.

## Основные возможности
- 🎥 Загрузка видео через Telegram или YouTube
- 🔍 Умное определение сцен с настраиваемыми параметрами
- ✂️ Разделение видео с сохранением оригинального качества
- 🔢 Автоматическая нумерация сцен
- 🇷🇺 Русскоязычный интерфейс

## Системные требования

### Операционная система
- Linux (рекомендуется Ubuntu 20.04 или новее)
- Минимум 4GB RAM
- Минимум 10GB свободного места на диске

### Необходимое ПО
- Python 3.11
- FFmpeg
- Git

### Важное замечание о совместимости
⚠️ Проект протестирован и рекомендуется к использованию с Python 3.11. При использовании Python 3.12 могут возникнуть проблемы совместимости с OpenCV и другими библиотеками.

## Установка

1. Установите системные зависимости:
```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y ffmpeg python3.11 python3.11-dev python3-pip
# Зависимости для OpenCV
sudo apt-get install -y libgl1-mesa-glx libglib2.0-0
```

2. Клонируйте репозиторий:
```bash
git clone https://github.com/ваш-репозиторий/video-scene-bot
cd video-scene-bot
```

3. Создайте виртуальное окружение и активируйте его:
```bash
python3.11 -m venv venv
source venv/bin/activate
```

4. Установите Python зависимости:
```bash
pip install -r requirements.txt
```

## Зависимости Python
Создайте файл requirements.txt со следующим содержимым:
```
ffmpeg-python==0.2.0
opencv-python==4.11.0.86
python-telegram-bot==21.10
pytube==15.0.0
requests==2.32.3
scenedetect==0.6.5.2
yt-dlp==2025.2.19
```

## Известные проблемы с зависимостями
1. OpenCV (opencv-python) может конфликтовать с Python 3.12. Рекомендуется использовать Python 3.11.
2. PySceneDetect требует FFmpeg для работы с видео.
3. YT-DLP периодически требует обновления для работы с YouTube.

## Решение проблем с зависимостями
1. При проблемах с OpenCV:
   ```bash
   # Проверка версии Python
   python --version

   # Если Python 3.12, установите 3.11
   sudo apt-get install python3.11 python3.11-venv python3.11-dev

   # Создайте новое виртуальное окружение
   python3.11 -m venv venv
   source venv/bin/activate

   # Установите зависимости заново
   pip install -r requirements.txt
   ```

2. При проблемах с FFmpeg:
   ```bash
   # Проверка установки FFmpeg
   ffmpeg -version

   # Если не установлен
   sudo apt-get update
   sudo apt-get install -y ffmpeg
   ```

## Настройка окружения

1. Создайте файл `.env` в корневой директории проекта:
```bash
# Обязательные переменные
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Опциональные настройки
TEMP_DIR=temp_videos                  # Директория для временных файлов
MAX_VIDEO_SIZE=2000000000            # Максимальный размер видео (2GB)
MIN_SCENE_LENGTH=2.0                 # Минимальная длина сцены в секундах
THRESHOLD=27.0                       # Порог определения сцен
```

2. Создайте директорию для временных файлов:
```bash
mkdir temp_videos
chmod 755 temp_videos
```

## Запуск

### Локальный запуск для разработки
```bash
python bot.py
```

### Запуск на сервере
Рекомендуется использовать systemd для управления процессом бота.

1. Создайте файл службы `/etc/systemd/system/scene-bot.service`:
```ini
[Unit]
Description=Telegram Scene Detection Bot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/your/bot
Environment=PYTHONPATH=/path/to/your/bot
EnvironmentFile=/path/to/your/bot/.env
ExecStart=/path/to/your/bot/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

2. Активируйте и запустите службу:
```bash
sudo systemctl enable scene-bot
sudo systemctl start scene-bot
```

3. Проверьте статус:
```bash
sudo systemctl status scene-bot
```

## Мониторинг
Логи бота можно просмотреть с помощью:
```bash
sudo journalctl -u scene-bot -f
```

Для просмотра статуса сервиса:
```bash
sudo systemctl status scene-bot
```

### Проверка работоспособности
1. Убедитесь, что сервис запущен:
```bash
sudo systemctl is-active scene-bot
```

2. Проверьте наличие ошибок в логах:
```bash
sudo journalctl -u scene-bot -n 50 --no-pager
```

3. Проверьте права доступа к временной директории:
```bash
ls -la /path/to/your/bot/temp_videos
```

### Рекомендации по обслуживанию
1. Регулярно проверяйте и очищайте временную директорию:
```bash
find /path/to/your/bot/temp_videos -type f -mtime +1 -delete
```

2. Следите за обновлениями зависимостей:
```bash
pip list --outdated
```

3. Мониторьте использование диска:
```bash
du -sh /path/to/your/bot/temp_videos
```


## Troubleshooting

### Ошибка ImportError: libGL.so.1
Если при запуске появляется ошибка:
```
ImportError: libGL.so.1: cannot open shared object file: No such file or directory
```
Это может быть вызвано двумя причинами:

1. Отсутствуют системные библиотеки:
```bash
sudo apt-get update
sudo apt-get install -y libgl1-mesa-glx libglib2.0-0
```

2. Несовместимость версии Python:
Если вы используете Python 3.12, попробуйте переключиться на Python 3.11:
```bash
# Установка Python 3.11
sudo apt-get install python3.11 python3.11-dev python3.11-venv

# Создание нового виртуального окружения
python3.11 -m venv .venv
source .venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt
```

### Ошибки с FFmpeg
Если возникают проблемы при обработке видео:
```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
ffmpeg -version  # Проверка установки
```

## Структура проекта
```
video-scene-bot/
├── bot.py                 # Основной файл бота
├── config.py             # Конфигурация
├── download_manager.py   # Менеджер загрузки видео
├── video_processor.py    # Обработка видео и определение сцен
├── utils.py             # Вспомогательные функции
├── requirements.txt     # Зависимости Python
├── .env                # Переменные окружения (не включать в Git)
└── temp_videos/        # Директория для временных файлов (не включать в Git)
```

## Безопасность
1. Не включайте файл `.env` в Git репозиторий
2. Регулярно обновляйте зависимости
3. Используйте HTTPS для клонирования репозитория
4. Ограничьте доступ к директории бота на сервере

## Поддержка
При возникновении проблем:
1. Проверьте логи: `sudo journalctl -u scene-bot -f`
2. Убедитесь, что все зависимости установлены корректно
3. Проверьте права доступа к временной директории
4. Убедитесь, что переменные окружения настроены правильно