# 🎤 Транскрибатор аудио и видео

Приложение на базе Streamlit для транскрибации аудио и видео файлов с использованием OpenAI Whisper API.

## Возможности

- **Транскрибация аудио и видео файлов** из различных источников в текст
- **Автоматическое определение языка** исходного материала
- **Перевод транскрибации** на русский, казахский или английский язык
- **Создание конспектов** из транскрибированного текста
- **Поддержка различных источников контента**:
  - Локальные аудио и видео файлы
  - YouTube видео
  - Видео из ВКонтакте
  - Видео из Instagram
  - Файлы с Яндекс Диска
  - Файлы с Google Drive
- **Сохранение результатов** в форматах TXT и DOCX

## Требования

- Python 3.9 или выше
- OpenAI API ключ
- FFmpeg

## Установка и запуск

### Windows

1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com/zsfreee/Audio_Video_Transcriber.git
   ```

2. Перейдите в директорию проекта:
   ```bash
   cd Audio_Video_Transcriber
   ```

3. Создайте виртуальное окружение и активируйте его:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```

4. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```

5. Запустите приложение:
   ```bash
   streamlit run app.py
   ```

### Linux/macOS

1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com/zsfreee/Audio_Video_Transcriber.git
   ```

2. Перейдите в директорию проекта:
   ```bash
   cd Audio_Video_Transcriber
   ```

3. Установите FFmpeg:
   ```bash
   # Ubuntu
   sudo apt update
   sudo apt install ffmpeg
   
   # macOS
   brew install ffmpeg
   ```

4. Создайте виртуальное окружение и активируйте его:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

5. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```

6. Запустите приложение:
   ```bash
   streamlit run app.py
   ```

## Настройка

1. Получите API ключ OpenAI: https://platform.openai.com/api-keys
2. Введите API ключ в приложении или создайте файл `.env` с содержимым:
   ```
   OPENAI_API_KEY=ваш_api_ключ
   ```

## Структура проекта

- `app.py` - основной файл приложения
- `utils.py` - вспомогательные функции
- `youtube_service.py` - функции для работы с YouTube
- `vk_video_service.py` - функции для работы с VK
- `instagram_service.py` - функции для работы с Instagram
- `yandex_disk_service.py` - функции для работы с Яндекс.Диск
- `gdrive_service.py` - функции для работы с Google Drive
- `folder_picker.py` - выбор папок через диалоговое окно

## Процесс работы

1. Выберите источник контента (локальный файл, YouTube, VK и т.д.)
2. Укажите URL или загрузите файл
3. Выберите язык для конечной транскрибации
4. Запустите процесс транскрибации
5. Дождитесь завершения и получите результаты
