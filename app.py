import os
import sys
import glob
import time
import re
import shutil
import markdown
import threading
import tempfile
import datetime
import subprocess
from pathlib import Path

import openai
import streamlit as st
from dotenv import load_dotenv

import utils
from utils import (
    transcribe_audio_whisper, audio_info,
    format_text, split_markdown_text, process_documents, 
    num_tokens_from_string, split_text, process_text_chunks,
    save_text_to_docx, markdown_to_docx
)
from youtube_service import YouTubeDownloader
from gdrive_service import GoogleDriveDownloader
from instagram_service import InstagramDownloader
from yandex_disk_service import YandexDiskDownloader
from vk_video_service import VKVideoDownloader
import platform

# Конфигурация страницы Streamlit (должна быть первой командой Streamlit)
st.set_page_config(
    page_title="Транскрибатор",
    page_icon="🎤",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Функция для выбора папки через диалоговое окно
def choose_folder():
    try:
        # Получаем путь к скрипту folder_picker.py
        folder_picker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "folder_picker.py")
        
        # Запускаем скрипт и получаем результат
        result = subprocess.run([sys.executable, folder_picker_path], 
                              capture_output=True, text=True, check=True)
        
        # Получаем путь из вывода
        folder_path = result.stdout.strip()
        
        # Если путь не пустой, возвращаем его
        if folder_path:
            return folder_path
        return None
    except Exception as e:
        st.error(f"Ошибка при выборе папки: {str(e)}")
        return None

# Функция для очистки временных файлов
def clean_temp_files(directory, days_old=7):
    """
    Очищает файлы из указанной директории, которые старше указанного количества дней.
    
    Args:
        directory (str): Путь к директории для очистки
        days_old (int): Удалять файлы старше указанного количества дней
    
    Returns:
        tuple: (количество удаленных файлов, общий размер освобожденного места в байтах)
    """
    if not os.path.exists(directory):
        return 0, 0
    
    now = datetime.datetime.now()
    cutoff_date = now - datetime.timedelta(days=days_old)
    count = 0
    total_size = 0
    
    for file_path in glob.glob(f"{directory}/**/*", recursive=True):
        if os.path.isfile(file_path):
            file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
            if file_mtime < cutoff_date:
                try:
                    file_size = os.path.getsize(file_path)
                    os.remove(file_path)
                    count += 1
                    total_size += file_size
                except Exception as e:
                    st.error(f"Ошибка при удалении файла {file_path}: {str(e)}")
    
    # Удаляем пустые папки
    for root, dirs, files in os.walk(directory, topdown=False):
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            if not os.listdir(dir_path):  # Проверяем, пуста ли директория
                try:
                    os.rmdir(dir_path)
                except Exception as e:
                    st.error(f"Ошибка при удалении пустой директории {dir_path}: {str(e)}")
    
    return count, total_size

# Функция для периодической очистки временных файлов
def scheduled_cleanup(temp_dirs, interval_hours=12, days_old=7):
    """
    Запускает периодическую очистку временных файлов в фоновом режиме.
    
    Args:
        temp_dirs (list): Список директорий для очистки
        interval_hours (int): Интервал между очистками в часах
        days_old (int): Удалять файлы старше указанного количества дней
    """
    while True:
        # Спим указанное количество часов
        time.sleep(interval_hours * 3600)
        
        # Для каждой директории в списке
        for directory in temp_dirs:
            if os.path.exists(directory):
                try:
                    count, size = clean_temp_files(directory, days_old)
                    print(f"[Автоочистка] Из {directory} удалено {count} файлов, освобождено {size/(1024*1024):.2f} MB")
                except Exception as e:
                    print(f"[Автоочистка] Ошибка при очистке {directory}: {str(e)}")

# Загрузка переменных окружения из файла .env
load_dotenv()

# Определяем пути для хранения файлов
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRANSCRIPTIONS_DIR = os.path.join(BASE_DIR, "transcriptions")  # Для конечных файлов
TEMP_FILES_DIR = os.path.join(BASE_DIR, "temp_files")  # Для временных файлов
AUDIO_FILES_DIR = os.path.join(BASE_DIR, "audio_files")  # Для аудио файлов
MARKDOWN_DIR = os.path.join(BASE_DIR, "markdown")  # Для хранения markdown файлов

# Создаем все необходимые директории
for dir_path in [TRANSCRIPTIONS_DIR, TEMP_FILES_DIR, AUDIO_FILES_DIR, MARKDOWN_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# Определяем путь к ffmpeg и добавляем его в переменные окружения
current_dir = os.path.dirname(os.path.abspath(__file__))
if platform.system() == "Windows":
    ffmpeg_bin = os.path.join(current_dir, "ffmpeg.exe")
    ffprobe_bin = os.path.join(current_dir, "ffprobe.exe")
    os.environ["FFMPEG_BINARY"] = ffmpeg_bin
    os.environ["FFPROBE_BINARY"] = ffprobe_bin
    # Добавление текущей директории с DLL файлами в PATH
    os.environ["PATH"] = current_dir + os.pathsep + os.environ.get("PATH", "")
else:
    # Для Linux и macOS предполагается, что ffmpeg установлен системно
    ffmpeg_bin = "ffmpeg"
    ffprobe_bin = "ffprobe"

# Проверяем наличие ffmpeg
try:
    subprocess.run([ffmpeg_bin, "-version"], capture_output=True, text=True, check=True)
    st.sidebar.success("FFmpeg найден и готов к использованию")
except Exception as e:
    st.sidebar.error(f"Ошибка при проверке FFmpeg: {str(e)}")

# Запускаем автоматическую очистку временных файлов при запуске
clean_temp_files(TEMP_FILES_DIR, days_old=7)

# Запускаем периодическую очистку временных файлов в фоновом режиме
cleanup_thread = threading.Thread(target=scheduled_cleanup, args=([TEMP_FILES_DIR], 12, 7), daemon=True)
cleanup_thread.start()

# Вспомогательная функция для получения более строгих языковых инструкций
def get_language_instruction(target_language):
    """
    Возвращает строгие языковые инструкции для указанного языка
    """
    if target_language.lower() == "казахский":
        return """БАРЛЫҚ МӘТІНДІ ТЕК ҚАЗАҚ ТІЛІНДЕ ЖАЗУ КЕРЕК. 
        Басқа тілдерді қолданбаңыз. 
        Тақырыптар, мәтін мазмұны, бөлімдер - бәрі қазақ тілінде болуы керек. 
        Орыс немесе ағылшын сөздерін араластырмаңыз."""
    elif target_language.lower() == "английский":
        return """ALL TEXT MUST BE WRITTEN ONLY IN ENGLISH.
        Do not use other languages.
        Headings, content, sections - everything should be in English.
        Do not mix in Russian or Kazakh words."""
    else:  # русский по умолчанию
        return """ВЕСЬ ТЕКСТ ДОЛЖЕН БЫТЬ НАПИСАН ТОЛЬКО НА РУССКОМ ЯЗЫКЕ.
        Не используйте другие языки.
        Заголовки, содержание, разделы - всё должно быть на русском языке.
        Не смешивайте с казахскими или английскими словами."""

# Функция для создания конспекта из текста транскрибации с уникальными именами файлов
def create_handbook(text, save_path, original_filename, target_language="русский"):
    st.write("### Создаем конспект из транскрибации...")
    
    # Получаем базовое имя файла без префикса, если он есть
    if original_filename.startswith("Conspect_"):
        original_filename = original_filename[len("Conspect_"):]
    
    # Определяем пути к файлам
    md_text_path = os.path.join(TEMP_FILES_DIR, f"{original_filename}_processed_md_text.txt")
    handbook_path = os.path.join(TEMP_FILES_DIR, f"{original_filename}_summary_draft.txt")
    
    # Пути к конечным файлам конспекта в папке экспорта
    handbook_export_txt_path = os.path.join(save_path, f"Summary_{original_filename}.txt")
    handbook_export_docx_path = os.path.join(save_path, f"Summary_{original_filename}.docx")

    # Определяем размер текста в токенах
    tokens = num_tokens_from_string(text)
    st.write(f"Количество токенов в тексте: {tokens}")
    
    # Получаем языковые инструкции для более строгого указания языка
    lang_instruction = get_language_instruction(target_language)
    
    # Системный промпт для разделения текста на разделы
    system_prompt = f"""Вы гений текста, копирайтинга, писательства. Ваша задача распознать разделы в тексте
и разбить его на эти разделы сохраняя весь текст на 100%. {lang_instruction}"""

    # Пользовательский промпт для разделения текста
    user_prompt = f"""Пожалуйста, давайте подумаем шаг за шагом: Подумайте, какие разделы в тексте вы можете
распознать и какое название по смыслу можно дать каждому разделу. Далее напишите ответ по всему
предыдущему ответу и оформи в порядке:
## Название раздела, после чего весь текст, относящийся к этому разделу. {lang_instruction} Текст:"""
    
    # В зависимости от размера текста либо обрабатываем текст целиком, либо делим на чанки
    md_processed_text = ""
    
    with st.spinner("Обрабатываем текст, разбивая на разделы..."):
        # Если текст небольшой (менее 16к токенов для безопасности), обрабатываем целиком
        if tokens < 16000:
            md_processed_text = utils.generate_answer(system_prompt, user_prompt, text)
        # Иначе разбиваем на чанки и обрабатываем по частям
        else:
            st.write("Текст слишком большой, разбиваем на части...")
            # Разбиваем текст на чанки
            text_chunks = split_text(text, chunk_size=30000, chunk_overlap=1000)
            st.write(f"Текст разбит на {len(text_chunks)} частей")
            # Обрабатываем каждый чанк отдельно
            md_processed_text = process_text_chunks(text_chunks, system_prompt, user_prompt)
    
    # Сохраняем промежуточный текст с разделами в txt файл в папке для временных файлов
    with open(md_text_path, "w", encoding="utf-8") as f:
        f.write(md_processed_text)
    
    # Копируем файл с разделами в папку markdown для длительного хранения
    markdown_file_path = os.path.join(MARKDOWN_DIR, f"{original_filename}_processed_md_text.txt")
    shutil.copy2(md_text_path, markdown_file_path)
    st.success(f"Текст с разделами сохранен и скопирован в папку markdown для длительного хранения")
    
    # Получаем список документов, разбитых по заголовкам
    chunks_md_splits = split_markdown_text(md_processed_text)
    st.write("### Заголовки разделов:")
    for chunk in chunks_md_splits:
        try:
            if "Header 2" in chunk.metadata:
                st.write(f"- {chunk.metadata['Header 2']}")
        except:
            pass
    
    # Системный промпт для формирования конспекта
    system_prompt_handbook = f"""Ты гений копирайтинга. Ты получаешь раздел необработанного текста по определенной теме.
Нужно из этого текста выделить самую суть, только самое важное, сохранив все нужные подробности и детали,
но убрав всю "воду" и слова (предложения), не несущие смысловой нагрузки.
ОЧЕНЬ ВАЖНО: {lang_instruction}
Ты ДОЛЖЕН писать ВЕСЬ текст ТОЛЬКО на {target_language} языке. НЕ ИСПОЛЬЗУЙ другие языки вообще."""

    # Пользовательский промпт для формирования конспекта
    user_prompt_handbook = f"""Из данного текста выдели только ключевую и ценную с точки зрения темы раздела информацию.
Удали всю "воду". В итоге у тебя должен получится раздел для конспекта по указанной теме. Опирайся
только на данный тебе текст, не придумывай ничего от себя. Ответ нужен в формате:
## Название раздела, и далее выделенная тобой ценная информация из текста. Используй маркдаун-разметку для выделения важных моментов: 
**жирный текст** для важных фактов, *курсив* для определений, списки для перечислений и т.д. 

ОЧЕНЬ ВАЖНО: {lang_instruction}
Ты ДОЛЖЕН писать ВЕСЬ текст ТОЛЬКО на {target_language} языке.
НЕ ИСПОЛЬЗУЙ русский или любой другой язык, кроме {target_language}.

Весь твой ответ должен быть на {target_language} языке, включая все заголовки, выделения и пояснения."""
    
    with st.spinner("Формируем конспект из разделов..."):
        # Обработка каждого документа (раздела) для формирования конспекта
        handbook_md_text = process_documents(
            TEMP_FILES_DIR, 
            chunks_md_splits, 
            system_prompt_handbook, 
            user_prompt_handbook, 
            original_filename, 
            target_language
        )
    
    # Сохраняем черновик конспекта в файл для временных данных
    with open(handbook_path, "w", encoding="utf-8") as f:
        f.write(handbook_md_text)
    
    # Сохраняем конспект в указанную директорию экспорта
    with open(handbook_export_txt_path, "w", encoding="utf-8") as f:
        f.write(handbook_md_text)
    
    # Сохраняем конспект в docx с правильным форматированием
    markdown_to_docx(handbook_md_text, handbook_export_docx_path)
    
    st.success(f"Конспект успешно создан и сохранен в {handbook_export_txt_path} и {handbook_export_docx_path}")
    
    # Создаем текстовую область с конспектом для просмотра и копирования
    with st.expander("Просмотр конспекта", expanded=False):
        handbook_html = markdown.markdown(handbook_md_text)
        st.markdown(handbook_html, unsafe_allow_html=True)
        st.info("Для копирования выделите текст выше и нажмите Ctrl+C")
    
    return handbook_md_text, md_processed_text

# Функция для обработки загруженного файла
def process_uploaded_file(file_obj, save_path, file_name, target_language, save_txt=True, save_docx=True, create_handbook_option=False):
    # Создаем отдельную папку для файла в директории экспорта
    file_dir = os.path.join(save_path, file_name)
    os.makedirs(file_dir, exist_ok=True)
    
    # Выводим информацию о созданном каталоге для отладки
    st.info(f"Создан каталог для результатов: {file_dir}")
    
    # Сохраняем загруженный файл во времний файл
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file_obj.name).suffix) as tmp_file:
        tmp_file.write(file_obj.getbuffer())
        temp_file_path = tmp_file.name

    st.info(f"Файл временно сохранен: {temp_file_path}")

    # Получаем информацию об аудио файле
    audio = audio_info(temp_file_path)
    st.write(f"Продолжительность: {audio.duration_seconds / 60:.2f} мин.")
    st.write(f"Частота дискретизации: {audio.frame_rate} Гц")
    st.write(f"Количество каналов: {audio.channels}")

    # Транскрибация аудио
    with st.spinner("Выполняем транскрибацию..."):
        start_time = time.time()
        transcription, original_language = transcribe_audio_whisper(
            audio_path=temp_file_path,
            file_title=file_name,
            save_folder_path=TEMP_FILES_DIR  # Сохраняем рабочий файл во временную директорию
        )
        transcription = utils.format_transcription_paragraphs(transcription)
        elapsed_time = time.time() - start_time

    st.success(f"Транскрибация завершена за {elapsed_time / 60:.2f} минут!")

    # Сохраняем оригинал в папку файла
    original_txt_path = os.path.join(file_dir, f"Original_{file_name}.txt")
    
    # Еще раз проверяем существование директории перед записью
    if not os.path.exists(file_dir):
        os.makedirs(file_dir, exist_ok=True)
        st.info(f"Повторно создан каталог для результатов: {file_dir}")
        
    try:
        with open(original_txt_path, "w", encoding="utf-8") as f:
            f.write(transcription)
        st.success(f"Оригинал TXT сохранен: {original_txt_path}")
    except Exception as e:
        st.error(f"Ошибка при сохранении TXT: {str(e)}")
    
    if save_docx:
        try:
            original_docx_path = os.path.join(file_dir, f"Original_{file_name}.docx")
            save_text_to_docx(transcription, original_docx_path)
            st.success(f"Оригинал Word сохранен: {original_docx_path}")
        except Exception as e:
            st.error(f"Ошибка при сохранении DOCX: {str(e)}")

    # Определяем, нужен ли перевод
    # Словари для маппинга названий языков в коды и наоборот
    lang_map = {"русский": "ru", "казахский": "kk", "английский": "en"}
    lang_code_to_name = {"ru": "русский", "kk": "казахский", "en": "английский", "ko": "корейский", 
                        "ja": "японский", "zh": "китайский", "es": "испанский", "fr": "французский", 
                        "de": "немецкий", "it": "итальянский", "pt": "португальский"}
    
    # Получаем код оригинального языка
    orig_lang_code = original_language.lower() if original_language else "unknown"
    
    # Дополнительная проверка для корейского и других языков
    if orig_lang_code == "unknown" or orig_lang_code not in ["ru", "kk", "en", "ko", "ja", "zh"]:
        # Определяем язык из текста с помощью нашей улучшенной функции
        orig_lang_code = utils.detect_language(transcription)
    
    # Получаем код целевого языка
    target_lang_code = lang_map.get(target_language.lower(), "ru")
    
    # Всегда переводим с языка, отличного от целевого
    need_translate = orig_lang_code != target_lang_code
    translated_text = transcription  # По умолчанию используем оригинальный текст
    
    # Показываем информацию о языке оригинала для диагностики
    orig_lang_name = lang_code_to_name.get(orig_lang_code, f"неизвестный ({orig_lang_code})")
    st.info(f"Определен язык оригинала: {orig_lang_name}")
    
    if need_translate:
        with st.spinner(f"Переводим транскрибацию с {orig_lang_name} на {target_language}..."):
            translated_text = utils.translate_text_gpt(transcription, target_language)
        st.success(f"Перевод завершён!")
    else:
        st.info(f"Язык оригинала ({orig_lang_name}) совпадает с целевым языком ({target_language}). Перевод не требуется.")

    # Сохраняем переведённую транскрипцию или оригинал, если перевод не нужен
    trans_txt_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.txt")
    with open(trans_txt_path, "w", encoding="utf-8") as f:
        f.write(translated_text)
    if save_docx:
        trans_docx_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.docx")
        save_text_to_docx(translated_text, trans_docx_path)
        st.success(f"Переведённый Word сохранен: {trans_docx_path}")
    st.success(f"Переведённый TXT сохранен: {trans_txt_path}")

    # Выводим оба текста
    st.subheader("Оригинальная транскрибация")
    st.text_area("Оригинал", transcription, height=200)
    st.subheader(f"Транскрибация на {target_language.capitalize()}")
    st.text_area("Перевод", translated_text, height=200)

    # Создаём конспект по переводу
    handbook_text = None
    if create_handbook_option:
        # Используем оригинальное имя файла без префикса "Conspect_"
        handbook_text, md_processed_text = create_handbook(translated_text, file_dir, file_name, target_language)
        return transcription, handbook_text, md_processed_text

    return transcription, None, None

# Функция для обработки YouTube видео
def process_youtube_video(url, save_path, target_language, save_txt=True, save_docx=True, create_handbook_option=False):
    downloader = YouTubeDownloader(output_dir=AUDIO_FILES_DIR)
    if not downloader.is_youtube_url(url):
        st.error("Указанный URL не похож на ссылку YouTube видео.")
        return None, None, None
    video_id = downloader.get_video_id(url) or "video"
    file_name = f"youtube_{video_id}"
    
    # Создаем отдельную папку для файла в директории экспорта
    file_dir = os.path.join(save_path, file_name)
    os.makedirs(file_dir, exist_ok=True)
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    def update_progress(percent, message):
        progress_bar.progress(int(percent) / 100)
        status_text.text(message)
    with st.spinner("Загружаем аудио из YouTube видео..."):
        audio_file = downloader.download_audio(
            url=url, 
            output_filename=file_name,
            progress_callback=update_progress
        )
    if not audio_file:
        st.error("Ошибка при загрузке аудио из YouTube видео.")
        return None, None, None
    st.success(f"Аудио успешно загружено: {audio_file}")
    audio = audio_info(audio_file)
    st.write(f"Продолжительность: {audio.duration_seconds / 60:.2f} мин.")
    st.write(f"Частота дискретизации: {audio.frame_rate} Гц")
    st.write(f"Количество каналов: {audio.channels}")
    # Транскрибация аудио
    with st.spinner("Выполняем транскрибацию..."):
        start_time = time.time()
        transcription, original_language = transcribe_audio_whisper(
            audio_path=audio_file,
            file_title=file_name,
            save_folder_path=TEMP_FILES_DIR  # Сохраняем рабочий файл во временную директорию
        )
        transcription = utils.format_transcription_paragraphs(transcription)
        elapsed_time = time.time() - start_time
    st.success(f"Транскрибация завершена за {elapsed_time / 60:.2f} минут!")
    
    # Сохраняем оригинал в папку файла
    original_txt_path = os.path.join(file_dir, f"Original_{file_name}.txt")
    with open(original_txt_path, "w", encoding="utf-8") as f:
        f.write(transcription)
    if save_docx:
        original_docx_path = os.path.join(file_dir, f"Original_{file_name}.docx")
        save_text_to_docx(transcription, original_docx_path)
        st.success(f"Оригинал Word сохранен: {original_docx_path}")
    st.success(f"Оригинал TXT сохранен: {original_txt_path}")

    # Унифицированная логика определения необходимости перевода
    lang_map = {"русский": "ru", "казахский": "kk", "английский": "en"}
    lang_code_to_name = {"ru": "русский", "kk": "казахский", "en": "английский", "ko": "корейский", 
                        "ja": "японский", "zh": "китайский", "es": "испанский", "fr": "французский", 
                        "de": "немецкий", "it": "итальянский", "pt": "португальский"}
    
    # Получаем код оригинального языка
    orig_lang_code = original_language.lower() if original_language else "unknown"
    
    # Дополнительная проверка для корейского и других языков
    if orig_lang_code == "unknown" or orig_lang_code not in ["ru", "kk", "en", "ko", "ja", "zh"]:
        # Повторно определяем язык из текста
        orig_lang_code = utils.detect_language(transcription)
    
    # Получаем код целевого языка
    target_lang_code = lang_map.get(target_language.lower(), "ru")
    
    # Всегда переводим с языка, отличного от целевого
    need_translate = orig_lang_code != target_lang_code
    translated_text = transcription  # По умолчанию используем оригинальный текст
    
    # Показываем информацию о языке оригинала для диагностики
    orig_lang_name = lang_code_to_name.get(orig_lang_code, f"неизвестный ({orig_lang_code})")
    st.info(f"Определен язык оригинала: {orig_lang_name}")
    
    if need_translate:
        with st.spinner(f"Переводим транскрибацию с {orig_lang_name} на {target_language}..."):
            translated_text = utils.translate_text_gpt(transcription, target_language)
        st.success(f"Перевод завершён!")
    else:
        st.info(f"Язык оригинала ({orig_lang_name}) совпадает с целевым языком ({target_language}). Перевод не требуется.")

    # Сохраняем переведённую транскрипцию или оригинал, если перевод не нужен
    trans_txt_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.txt")
    with open(trans_txt_path, "w", encoding="utf-8") as f:
        f.write(translated_text)
    if save_docx:
        trans_docx_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.docx")
        save_text_to_docx(translated_text, trans_docx_path)
        st.success(f"Переведённый Word сохранен: {trans_docx_path}")
    st.success(f"Переведённый TXT сохранен: {trans_txt_path}")

    # Выводим оба текста
    st.subheader("Оригинальная транскрибация")
    st.text_area("Оригинал", transcription, height=200)
    st.subheader(f"Транскрибация на {target_language.capitalize()}")
    st.text_area("Перевод", translated_text, height=200)

    # Создаём конспект по переводу
    handbook_text = None
    if create_handbook_option:
        # Используем оригинальное имя файла без префикса "Conspect_"
        handbook_text, md_processed_text = create_handbook(translated_text, file_dir, file_name, target_language)
        return transcription, handbook_text, md_processed_text

    return transcription, None, None

# Функция для обработки видео из ВКонтакте
def process_vk_video(url, save_path, target_language, save_txt=True, save_docx=True, create_handbook_option=False):
    """
    Скачивает и обрабатывает видео из ВКонтакте
    
    Args:
        url: URL на видео ВКонтакте
        save_path: Путь для сохранения результатов
        target_language: Целевой язык для перевода
        save_txt: Сохранять ли результат в TXT
        save_docx: Сохранять ли результат в DOCX
        create_handbook_option: Создавать ли конспект
        
    Returns:
        Кортеж с результатами (транскрипция, конспект, обработанный текст)
    """
    downloader = VKVideoDownloader(output_dir=AUDIO_FILES_DIR)
    if not downloader.is_vk_url(url):
        st.error("Указанный URL не похож на ссылку на видео ВКонтакте.")
        return None, None, None
    
    # Нормализуем URL, чтобы обработать ссылки из разных источников
    url = downloader.normalize_vk_url(url)
    video_id = downloader.get_video_id(url) or "video"
    file_name = f"vk_video_{video_id}"
    
    # Создаем отдельную папку для файла в директории экспорта
    file_dir = os.path.join(save_path, file_name)
    os.makedirs(file_dir, exist_ok=True)
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    def update_progress(percent, message):
        progress_bar.progress(int(percent) / 100)
        status_text.text(message)
    
    with st.spinner("Загружаем аудио из видео ВКонтакте..."):
        audio_file = downloader.download_audio(
            url=url, 
            output_filename=file_name,
            progress_callback=update_progress
        )
    
    if not audio_file:
        st.error("Ошибка при загрузке аудио из видео ВКонтакте.")
        return None, None, None
    
    st.success(f"Аудио успешно загружено: {audio_file}")
    audio = audio_info(audio_file)
    st.write(f"Продолжительность: {audio.duration_seconds / 60:.2f} мин.")
    st.write(f"Частота дискретизации: {audio.frame_rate} Гц")
    st.write(f"Количество каналов: {audio.channels}")
    
    # Транскрибация аудио
    with st.spinner("Выполняем транскрибацию..."):
        start_time = time.time()
        transcription, original_language = transcribe_audio_whisper(
            audio_path=audio_file,
            file_title=file_name,
            save_folder_path=TEMP_FILES_DIR  # Сохраняем рабочий файл во временную директорию
        )
        transcription = utils.format_transcription_paragraphs(transcription)
        elapsed_time = time.time() - start_time
    
    st.success(f"Транскрибация завершена за {elapsed_time / 60:.2f} минут!")
    
    # Сохраняем оригинал в папку файла
    original_txt_path = os.path.join(file_dir, f"Original_{file_name}.txt")
    with open(original_txt_path, "w", encoding="utf-8") as f:
        f.write(transcription)
    if save_docx:
        original_docx_path = os.path.join(file_dir, f"Original_{file_name}.docx")
        save_text_to_docx(transcription, original_docx_path)
        st.success(f"Оригинал Word сохранен: {original_docx_path}")
    st.success(f"Оригинал TXT сохранен: {original_txt_path}")

    # Определяем, нужен ли перевод
    # Словари для маппинга названий языков в коды и наоборот
    lang_map = {"русский": "ru", "казахский": "kk", "английский": "en"}
    lang_code_to_name = {"ru": "русский", "kk": "казахский", "en": "английский", "ko": "корейский", 
                        "ja": "японский", "zh": "китайский", "es": "испанский", "fr": "французский", 
                        "de": "немецкий", "it": "итальянский", "pt": "португальский"}
    
    # Получаем код оригинального языка
    orig_lang_code = original_language.lower() if original_language else "unknown"
    
    # Дополнительная проверка для корейского и других языков
    if orig_lang_code == "unknown" or orig_lang_code not in ["ru", "kk", "en", "ko", "ja", "zh"]:
        # Повторно определяем язык из текста
        orig_lang_code = utils.detect_language(transcription)
    
    # Получаем код целевого языка
    target_lang_code = lang_map.get(target_language.lower(), "ru")
    
    # Всегда переводим с языка, отличного от целевого
    need_translate = orig_lang_code != target_lang_code
    translated_text = transcription  # По умолчанию используем оригинальный текст
    
    # Показываем информацию о языке оригинала для диагностики
    orig_lang_name = lang_code_to_name.get(orig_lang_code, f"неизвестный ({orig_lang_code})")
    st.info(f"Определен язык оригинала: {orig_lang_name}")
    
    if need_translate:
        with st.spinner(f"Переводим транскрибацию с {orig_lang_name} на {target_language}..."):
            translated_text = utils.translate_text_gpt(transcription, target_language)
        st.success(f"Перевод завершён!")
    else:
        st.info(f"Язык оригинала ({orig_lang_name}) совпадает с целевым языком ({target_language}). Перевод не требуется.")

    # Сохраняем переведённую транскрипцию или оригинал, если перевод не нужен
    trans_txt_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.txt")
    with open(trans_txt_path, "w", encoding="utf-8") as f:
        f.write(translated_text)
    if save_docx:
        trans_docx_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.docx")
        save_text_to_docx(translated_text, trans_docx_path)
        st.success(f"Переведённый Word сохранен: {trans_docx_path}")
    st.success(f"Переведённый TXT сохранен: {trans_txt_path}")

    # Выводим оба текста
    st.subheader("Оригинальная транскрибация")
    st.text_area("Оригинал", transcription, height=200)
    st.subheader(f"Транскрибация на {target_language.capitalize()}")
    st.text_area("Перевод", translated_text, height=200)

    # Создаём конспект по переводу
    handbook_text = None
    if create_handbook_option:
        # Используем оригинальное имя файла без префикса "Conspect_"
        handbook_text, md_processed_text = create_handbook(translated_text, file_dir, file_name, target_language)
        return transcription, handbook_text, md_processed_text

    return transcription, None, None

# Функция для обработки Instagram видео
def process_instagram_video(url, save_path, target_language, save_txt=True, save_docx=True, create_handbook_option=False):
    downloader = InstagramDownloader(output_dir=AUDIO_FILES_DIR)
    if not downloader.is_instagram_url(url):
        st.error("Указанный URL не похож на ссылку Instagram видео.")
        return None, None, None
    shortcode = downloader.extract_shortcode(url) or "video"
    file_name = f"instagram_{shortcode}"
    
    # Создаем отдельную папку для файла в директории экспорта
    file_dir = os.path.join(save_path, file_name)
    os.makedirs(file_dir, exist_ok=True)
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    def update_progress(percent, message):
        progress_bar.progress(int(percent) / 100)
        status_text.text(message)
    with st.spinner("Загружаем аудио из Instagram видео..."):
        audio_file = downloader.download_audio(
            url=url, 
            output_filename=file_name,
            progress_callback=update_progress
        )
    if not audio_file:
        st.error("Ошибка при загрузке аудио из Instagram видео.")
        return None, None, None
    st.success(f"Аудио успешно загружено: {audio_file}")
    audio = audio_info(audio_file)
    st.write(f"Продолжительность: {audio.duration_seconds / 60:.2f} мин.")
    st.write(f"Частота дискретизации: {audio.frame_rate} Гц")
    st.write(f"Количество каналов: {audio.channels}")
    # Транскрибация аудио
    with st.spinner("Выполняем транскрибацию..."):
        start_time = time.time()
        transcription, original_language = transcribe_audio_whisper(
            audio_path=audio_file,
            file_title=file_name,
            save_folder_path=TEMP_FILES_DIR  # Сохраняем рабочий файл во временную директорию
        )
        transcription = utils.format_transcription_paragraphs(transcription)
        elapsed_time = time.time() - start_time
    st.success(f"Транскрибация завершена за {elapsed_time / 60:.2f} минут!")
    
    # Сохраняем оригинал в папку файла
    original_txt_path = os.path.join(file_dir, f"Original_{file_name}.txt")
    with open(original_txt_path, "w", encoding="utf-8") as f:
        f.write(transcription)
    if save_docx:
        original_docx_path = os.path.join(file_dir, f"Original_{file_name}.docx")
        save_text_to_docx(transcription, original_docx_path)
        st.success(f"Оригинал Word сохранен: {original_docx_path}")
    st.success(f"Оригинал TXT сохранен: {original_txt_path}")

    # Унифицированная логика определения необходимости перевода
    lang_map = {"русский": "ru", "казахский": "kk", "английский": "en"}
    lang_code_to_name = {"ru": "русский", "kk": "казахский", "en": "английский", "ko": "корейский", 
                        "ja": "японский", "zh": "китайский", "es": "испанский", "fr": "французский", 
                        "de": "немецкий", "it": "итальянский", "pt": "португальский"}
    
    # Получаем код оригинального языка
    orig_lang_code = original_language.lower() if original_language else "unknown"
    
    # Дополнительная проверка для корейского и других языков
    if orig_lang_code == "unknown" or orig_lang_code not in ["ru", "kk", "en", "ko", "ja", "zh"]:
        # Повторно определяем язык из текста
        orig_lang_code = utils.detect_language(transcription)
    
    # Получаем код целевого языка
    target_lang_code = lang_map.get(target_language.lower(), "ru")
    
    # Всегда переводим с языка, отличного от целевого
    need_translate = orig_lang_code != target_lang_code
    translated_text = transcription  # По умолчанию используем оригинальный текст
    
    # Показываем информацию о языке оригинала для диагностики
    orig_lang_name = lang_code_to_name.get(orig_lang_code, f"неизвестный ({orig_lang_code})")
    st.info(f"Определен язык оригинала: {orig_lang_name}")
    
    if need_translate:
        with st.spinner(f"Переводим транскрибацию с {orig_lang_name} на {target_language}..."):
            translated_text = utils.translate_text_gpt(transcription, target_language)
        st.success(f"Перевод завершён!")
    else:
        st.info(f"Язык оригинала ({orig_lang_name}) совпадает с целевым языком ({target_language}). Перевод не требуется.")

    # Сохраняем переведённую транскрипцию или оригинал, если перевод не нужен
    trans_txt_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.txt")
    with open(trans_txt_path, "w", encoding="utf-8") as f:
        f.write(translated_text)
    if save_docx:
        trans_docx_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.docx")
        save_text_to_docx(translated_text, trans_docx_path)
        st.success(f"Переведённый Word сохранен: {trans_docx_path}")
    st.success(f"Переведённый TXT сохранен: {trans_txt_path}")

    # Выводим оба текста
    st.subheader("Оригинальная транскрибация")
    st.text_area("Оригинал", transcription, height=200)
    st.subheader(f"Транскрибация на {target_language.capitalize()}")
    st.text_area("Перевод", translated_text, height=200)

    # Создаём конспект по переводу
    handbook_text = None
    if create_handbook_option:
        # Используем оригинальное имя файла без префикса "Conspect_"
        handbook_text, md_processed_text = create_handbook(translated_text, file_dir, file_name, target_language)
        return transcription, handbook_text, md_processed_text

    return transcription, None, None

# Функция для обработки файлов с Яндекс Диска
def process_yandex_disk_files(url, save_path, target_language, save_txt=True, save_docx=True, create_handbook_option=False):
    """
    Скачивает и обрабатывает аудио и видео файлы с Яндекс Диска
    
    Args:
        url: URL на Яндекс Диск (файл или папку)
        save_path: Путь для сохранения результатов
        target_language: Целевой язык для перевода
        save_txt: Сохранять ли результат в TXT
        save_docx: Сохранять ли результат в DOCX
        create_handbook_option: Создавать ли конспект
        
    Returns:
        Кортеж с результатами (транскрипция, конспект, обработанный текст)
    """
    downloader = YandexDiskDownloader(output_dir=AUDIO_FILES_DIR)
    if not downloader.is_yandex_disk_url(url):
        st.error("Указанный URL не является ссылкой на Яндекс Диск.")
        return None, None, None
    
    # Отображаем прогресс загрузки
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    def update_progress(percent, message):
        progress_bar.progress(int(percent) / 100)
        status_text.text(message)
    
    # Загружаем файлы с Яндекс Диска
    with st.spinner("Загружаем файлы с Яндекс Диска..."):
        downloaded_files = downloader.process_yandex_disk_url(url, progress_callback=update_progress)
    
    if not downloaded_files:
        st.error("Не удалось загрузить файлы с Яндекс Диска.")
        return None, None, None
    
    st.success(f"Успешно загружено файлов: {len(downloaded_files)}")
    
    # Обрабатываем каждый скачанный файл
    all_transcriptions = []
    all_handbooks = []
    
    for file_path in downloaded_files:
        if file_path is None or not os.path.exists(file_path):
            st.warning(f"Пропускаем некорректный файл")
            continue
            
        file_name = Path(file_path).stem
        st.subheader(f"Обработка файла: {file_name}")
        
        # Создаем отдельную папку для файла в директории экспорта
        file_dir = os.path.join(save_path, file_name)
        os.makedirs(file_dir, exist_ok=True)
        
        # Получаем информацию об аудио файле
        try:
            audio = audio_info(file_path)
            st.write(f"Продолжительность: {audio.duration_seconds / 60:.2f} мин.")
            st.write(f"Частота дискретизации: {audio.frame_rate} Гц")
            st.write(f"Количество каналов: {audio.channels}")
        except Exception as e:
            st.error(f"Ошибка при анализе файла: {str(e)}")
            continue
        
        # Транскрибация аудио
        with st.spinner(f"Выполняем транскрибацию файла {file_name}..."):
            start_time = time.time()
            try:
                transcription, original_language = transcribe_audio_whisper(
                    audio_path=file_path,
                    file_title=file_name,
                    save_folder_path=TEMP_FILES_DIR  # Сохраняем рабочий файл во временную директорию
                )
                transcription = utils.format_transcription_paragraphs(transcription)
                elapsed_time = time.time() - start_time
            except Exception as e:
                st.error(f"Ошибка при транскрибации: {str(e)}")
                continue

        st.success(f"Транскрибация завершена за {elapsed_time / 60:.2f} минут!")
        
        # Сохраняем оригинал в папку файла
        original_txt_path = os.path.join(file_dir, f"Original_{file_name}.txt")
        with open(original_txt_path, "w", encoding="utf-8") as f:
            f.write(transcription)
        if save_docx:
            original_docx_path = os.path.join(file_dir, f"Original_{file_name}.docx")
            save_text_to_docx(transcription, original_docx_path)
            st.success(f"Оригинал Word сохранен: {original_docx_path}")
        st.success(f"Оригинал TXT сохранен: {original_txt_path}")
        
        # Добавляем в список всех транскрипций
        all_transcriptions.append((file_name, transcription, transcription))  # Временно добавляем без перевода

        # Определяем, нужен ли перевод
        # Словари для маппинга названий языков в коды и наоборот
        lang_map = {"русский": "ru", "казахский": "kk", "английский": "en"}
        lang_code_to_name = {"ru": "русский", "kk": "казахский", "en": "английский", "ko": "корейский", 
                            "ja": "японский", "zh": "китайский", "es": "испанский", "fr": "французский", 
                            "de": "немецкий", "it": "итальянский", "pt": "португальский"}
        
        # Получаем код оригинального языка
        orig_lang_code = original_language.lower() if original_language else "unknown"
        
        # Дополнительная проверка для корейского и других языков
        if orig_lang_code == "unknown" or orig_lang_code not in ["ru", "kk", "en", "ko", "ja", "zh"]:
            # Определяем язык из текста с помощью нашей улучшенной функции
            orig_lang_code = utils.detect_language(transcription)
        
        # Получаем код целевого языка
        target_lang_code = lang_map.get(target_language.lower(), "ru")
        
        # Всегда переводим с языка, отличного от целевого
        need_translate = orig_lang_code != target_lang_code
        translated_text = transcription  # По умолчанию используем оригинальный текст
        
        # Показываем информацию о языке оригинала для диагностики
        orig_lang_name = lang_code_to_name.get(orig_lang_code, f"неизвестный ({orig_lang_code})")
        st.info(f"Определен язык оригинала: {orig_lang_name}")
        
        if need_translate:
            with st.spinner(f"Переводим транскрибацию файла {file_name} с {orig_lang_name} на {target_language}..."):
                translated_text = utils.translate_text_gpt(transcription, target_language)
            st.success(f"Перевод файла {file_name} завершён!")
            # Обновляем перевод в списке транскрипций
            all_transcriptions[-1] = (file_name, transcription, translated_text)
        else:
            st.info(f"Язык оригинала ({orig_lang_name}) для файла {file_name} совпадает с целевым языком ({target_language}). Перевод не требуется.")
        
        # Сохраняем переведённую транскрипцию или оригинал, если перевод не нужен
        trans_txt_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.txt")
        with open(trans_txt_path, "w", encoding="utf-8") as f:
            f.write(translated_text)
        if save_docx:
            trans_docx_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.docx")
            save_text_to_docx(translated_text, trans_docx_path)
            st.success(f"Переведённый Word сохранен: {trans_docx_path}")
        st.success(f"Переведённый TXT сохранен: {trans_txt_path}")

        # Выводим оба текста
        st.subheader("Оригинальная транскрибация")
        st.text_area("Оригинал", transcription, height=200)
        st.subheader(f"Транскрибация на {target_language.capitalize()}")
        st.text_area("Перевод", translated_text, height=200)

        # Создаём конспект по переводу
        handbook_text = None
        if create_handbook_option:
            # Используем оригинальное имя файла без префикса "Conspect_"
            handbook_text, md_processed_text = create_handbook(translated_text, file_dir, file_name, target_language)
            all_handbooks.append((file_name, handbook_text, md_processed_text))
            st.success(f"Конспект для файла {file_name} успешно создан")
    
    # Если были созданы конспекты
    if create_handbook_option and len(all_handbooks) > 0:
        transcription = all_transcriptions[0][1] if len(all_transcriptions) > 0 else None
        return transcription, all_handbooks[0][1], all_handbooks[0][2]
    
    # Возвращаем результаты для первого файла
    if len(all_transcriptions) > 0:
        return all_transcriptions[0][1], None, None
    
    return None, None, None

# Функция для обработки Google Drive файлов
def process_gdrive_files(url, save_path, target_language, save_txt=True, save_docx=True, create_handbook_option=False):
    """
    Скачивает и обрабатывает аудио и видео файлы с Google Drive
    
    Args:
        url: URL на Google Drive (файл или папку)
        save_path: Путь для сохранения результатов
        target_language: Целевой язык для перевода
        save_txt: Сохранять ли результат в TXT
        save_docx: Сохранять ли результат в DOCX
        create_handbook_option: Создавать ли конспект
        
    Returns:
        Кортеж с результатами (транскрипция, конспект, обработанный текст)
    """
    downloader = GoogleDriveDownloader(output_dir=AUDIO_FILES_DIR)
    if not downloader.is_gdrive_url(url):
        st.error("Указанный URL не является ссылкой на Google Drive.")
        return None, None, None
    
    # Отображаем прогресс загрузки
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    def update_progress(percent, message):
        progress_bar.progress(int(percent) / 100)
        status_text.text(message)
    
    # Загружаем файлы с Google Drive
    with st.spinner("Загружаем файлы с Google Drive..."):
        downloaded_files = downloader.process_gdrive_url(url, progress_callback=update_progress)
    
    if not downloaded_files:
        st.error("Не удалось загрузить файлы с Google Drive.")
        return None, None, None
    
    st.success(f"Успешно загружено файлов: {len(downloaded_files)}")
    
    # Обрабатываем каждый скачанный файл
    all_transcriptions = []
    all_handbooks = []
    
    for file_path in downloaded_files:
        file_name = Path(file_path).stem
        st.subheader(f"Обработка файла: {file_name}")
        
        # Создаем отдельную папку для файла в директории экспорта
        file_dir = os.path.join(save_path, file_name)
        os.makedirs(file_dir, exist_ok=True)
        
        # Получаем информацию об аудио файле
        try:
            audio = audio_info(file_path)
            st.write(f"Продолжительность: {audio.duration_seconds / 60:.2f} мин.")
            st.write(f"Частота дискретизации: {audio.frame_rate} Гц")
            st.write(f"Количество каналов: {audio.channels}")
        except Exception as e:
            st.error(f"Ошибка при анализе файла: {str(e)}")
            continue
        
        # Транскрибация аудио
        with st.spinner(f"Выполняем транскрибацию файла {file_name}..."):
            start_time = time.time()
            try:
                transcription, original_language = transcribe_audio_whisper(
                    audio_path=file_path,
                    file_title=file_name,
                    save_folder_path=TEMP_FILES_DIR  # Сохраняем рабочий файл во временную директорию
                )
                transcription = utils.format_transcription_paragraphs(transcription)
                elapsed_time = time.time() - start_time
            except Exception as e:
                st.error(f"Ошибка при транскрибации: {str(e)}")
                continue

        st.success(f"Транскрибация завершена за {elapsed_time / 60:.2f} минут!")
        
        # Сохраняем оригинал в папку файла
        original_txt_path = os.path.join(file_dir, f"Original_{file_name}.txt")
        with open(original_txt_path, "w", encoding="utf-8") as f:
            f.write(transcription)
        if save_docx:
            original_docx_path = os.path.join(file_dir, f"Original_{file_name}.docx")
            save_text_to_docx(transcription, original_docx_path)
            st.success(f"Оригинал Word сохранен: {original_docx_path}")
        st.success(f"Оригинал TXT сохранен: {original_txt_path}")
        
        # Добавляем транскрипцию в список
        all_transcriptions.append((file_name, transcription))

        # Определяем, нужен ли перевод
        # Словари для маппинга названий языков в коды и наоборот
        lang_map = {"русский": "ru", "казахский": "kk", "английский": "en"}
        lang_code_to_name = {"ru": "русский", "kk": "казахский", "en": "английский", "ko": "корейский", 
                            "ja": "японский", "zh": "китайский", "es": "испанский", "fr": "французский", 
                            "de": "немецкий", "it": "итальянский", "pt": "португальский"}
        
        # Получаем код оригинального языка
        orig_lang_code = original_language.lower() if original_language else "unknown"
        
        # Дополнительная проверка для корейского и других языков
        if orig_lang_code == "unknown" or orig_lang_code not in ["ru", "kk", "en", "ko", "ja", "zh"]:
            # Повторно определяем язык из текста
            orig_lang_code = utils.detect_language(transcription)
        
        # Получаем код целевого языка
        target_lang_code = lang_map.get(target_language.lower(), "ru")
        
        # Всегда переводим с языка, отличного от целевого
        need_translate = orig_lang_code != target_lang_code
        translated_text = transcription  # По умолчанию используем оригинальный текст
        
        # Показываем информацию о языке оригинала для диагностики
        orig_lang_name = lang_code_to_name.get(orig_lang_code, f"неизвестный ({orig_lang_code})")
        st.info(f"Определен язык оригинала: {orig_lang_name}")
        
        if need_translate:
            with st.spinner(f"Переводим транскрибацию файла {file_name} с {orig_lang_name} на {target_language}..."):
                translated_text = utils.translate_text_gpt(transcription, target_language)
            st.success(f"Перевод файла {file_name} завершён!")
        else:
            st.info(f"Язык оригинала ({orig_lang_name}) для файла {file_name} совпадает с целевым языком ({target_language}). Перевод не требуется.")

        # Сохраняем переведённую транскрипцию или оригинал, если перевод не нужен
        trans_txt_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.txt")
        with open(trans_txt_path, "w", encoding="utf-8") as f:
            f.write(translated_text)
        if save_docx:
            trans_docx_path = os.path.join(file_dir, f"{target_language.capitalize()}_{file_name}.docx")
            save_text_to_docx(translated_text, trans_docx_path)
            st.success(f"Переведённый Word сохранен: {trans_docx_path}")
        st.success(f"Переведённый TXT сохранен: {trans_txt_path}")

        # Выводим оба текста
        st.subheader("Оригинальная транскрибация")
        st.text_area("Оригинал", transcription, height=200)
        st.subheader(f"Транскрибация на {target_language.capitalize()}")
        st.text_area("Перевод", translated_text, height=200)

        # Создаём конспект по переводу
        handbook_text = None
        if create_handbook_option:
            # Используем оригинальное имя файла без префикса "Conspect_"
            try:
                handbook_text, md_processed_text = create_handbook(translated_text, file_dir, file_name, target_language)
                all_handbooks.append((file_name, handbook_text, md_processed_text))
                st.success(f"Конспект для файла {file_name} успешно создан")
            except Exception as e:
                st.error(f"Ошибка при создании конспекта: {str(e)}")
    
    # Исправляем возврат результатов - добавляем проверки на пустые списки
    # Если были созданы конспекты
    if create_handbook_option and len(all_handbooks) > 0:
        transcription = all_transcriptions[0][1] if len(all_transcriptions) > 0 else None
        return transcription, all_handbooks[0][1], all_handbooks[0][2]
    
    # Возвращаем результаты для первого файла
    if len(all_transcriptions) > 0:
        return all_transcriptions[0][1], None, None
    
    return None, None, None

# Основная функция приложения
def main():
    st.title("🎤 Транскрибатор аудио и видео")
    st.markdown("### Преобразование аудио и видео в текст с помощью OpenAI Whisper API")
    
    # Боковая панель для ввода API ключа и опций
    with st.sidebar:
        st.header("Настройки")
        api_key = st.text_input("OpenAI API ключ", value=os.getenv("OPENAI_API_KEY", ""), type="password")
        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key
            openai.api_key = api_key
        else:
            st.warning("Пожалуйста, введите API ключ OpenAI")

        st.subheader("Язык транскрибации")
        target_language = st.selectbox(
            "Выберите язык для конечной транскрибации:",
            ["русский", "казахский", "английский"],
            index=0
        )
        st.subheader("Каталог сохранения")
        
        # Инициализируем session_state для пути сохранения, если его нет
        if 'save_dir' not in st.session_state:
            st.session_state['save_dir'] = TRANSCRIPTIONS_DIR
            
        # Отображаем текстовое поле с текущим значением из session_state
        save_dir = st.text_input("Путь для сохранения файлов", value=st.session_state['save_dir'])
        
        # Обновляем session_state, если пользователь изменил значение вручную
        st.session_state['save_dir'] = save_dir
        
        # Кнопка выбора папки
        if st.button("Выбрать папку"):
            folder_path = choose_folder()
            if folder_path:
                st.session_state['save_dir'] = folder_path
                st.rerun()

        st.subheader("Опции сохранения")
        save_txt = st.checkbox("Сохранить в TXT", value=False) # Изменено значение по умолчанию на False
        save_docx = st.checkbox("Сохранить в DOCX", value=True)
        create_handbook = st.checkbox("Создать конспект", value=False)
        
        st.subheader("Очистка временных файлов")
        days_old = st.number_input("Удалить файлы старше (дней):", min_value=1, max_value=30, value=7)
        if st.button("Очистить временные файлы"):
            deleted_count, freed_space = clean_temp_files(TEMP_FILES_DIR, days_old)
            st.success(f"Удалено файлов: {deleted_count}, освобождено места: {freed_space / (1024 * 1024):.2f} MB")
        
    # Основной контент с добавленной вкладкой VK video
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "Локальные файлы", 
        "YouTube", 
        "VK видео",
        "Instagram", 
        "Яндекс Диск", 
        "Google Диск"
    ])
    
    # Вкладка для локальных файлов
    with tab1:
        st.header("Загрузить локальный файл")
        uploaded_files = st.file_uploader(
            "Выберите аудио или видео файлы", 
            type=["mp3", "mp4", "wav", "m4a", "avi", "mov"],
            accept_multiple_files=True  # Включаем поддержку множественной загрузки
        )
        
        if uploaded_files:
            # Показываем счетчик загруженных файлов
            st.success(f"Загружено файлов: {len(uploaded_files)}")
            
            # Создаем аккордеон для просмотра каждого файла
            with st.expander("Просмотр загруженных файлов", expanded=False):
                for i, uploaded_file in enumerate(uploaded_files):
                    st.subheader(f"Файл #{i+1}: {uploaded_file.name}")
                    if uploaded_file.type.startswith('audio/') or uploaded_file.name.endswith(('.mp3', '.wav', '.m4a')):
                        st.audio(uploaded_file)
                    elif uploaded_file.type.startswith('video/') or uploaded_file.name.endswith(('.mp4', '.avi', '.mov')):
                        st.video(uploaded_file)
            
            if st.button("Транскрибировать выбранные файлы"):
                if not api_key:
                    st.error("Пожалуйста, введите API ключ OpenAI в настройках")
                else:
                    # Обрабатываем каждый загруженный файл по очереди
                    for i, uploaded_file in enumerate(uploaded_files):
                        # Создаем разделитель между файлами
                        if i > 0:
                            st.markdown("---")
                        
                        st.subheader(f"Обработка файла {i+1}/{len(uploaded_files)}: {uploaded_file.name}")
                        
                        # Получаем название файла без расширения
                        file_name = Path(uploaded_file.name).stem
                        
                        # Обрабатываем загруженный файл
                        process_uploaded_file(
                            uploaded_file, 
                            save_dir, 
                            file_name, 
                            target_language,
                            save_txt=save_txt,
                            save_docx=save_docx,
                            create_handbook_option=create_handbook
                        )
                    
                    st.success(f"Обработка всех файлов завершена! Всего обработано: {len(uploaded_files)}")
    
    # Вкладка для YouTube
    with tab2:
        st.header("YouTube видео")
        youtube_url = st.text_input("Введите ссылку на YouTube видео", key="youtube_url")
        if youtube_url:
            if st.button("Транскрибировать YouTube видео"):
                if not api_key:
                    st.error("Пожалуйста, введите API ключ OpenAI в настройках")
                else:
                    process_youtube_video(
                        youtube_url,
                        save_dir,
                        target_language,
                        save_txt=save_txt,
                        save_docx=save_docx,
                        create_handbook_option=create_handbook
                    )
    
    # Новая вкладка для VK видео
    with tab3:
        st.header("VK видео")
        vk_url = st.text_input("Введите ссылку на видео ВКонтакте", key="vk_url")
        
        st.info("""
        Поддерживаются следующие типы ссылок:
        - Прямые ссылки на видео: https://vk.com/video-220754053_456243260
        - Ссылки из браузера: https://vk.com/vkvideo?z=video-220754053_456243260%2Fvideos-220754053%2Fpl_-220754053_-2
        """)
        
        if vk_url:
            if st.button("Транскрибировать VK видео"):
                if not api_key:
                    st.error("Пожалуйста, введите API ключ OpenAI в настройках")
                else:
                    process_vk_video(
                        vk_url,
                        save_dir,
                        target_language,
                        save_txt=save_txt,
                        save_docx=save_docx,
                        create_handbook_option=create_handbook
                    )
    
    # Вкладка для Instagram
    with tab4:
        st.header("Instagram видео")
        instagram_url = st.text_input("Введите ссылку на Instagram видео поста или reels", key="instagram_url")
        
        if instagram_url:
            if st.button("Транскрибировать Instagram видео"):
                if not api_key:
                    st.error("Пожалуйста, введите API ключ OpenAI в настройках")
                else:
                    process_instagram_video(
                        instagram_url,
                        save_dir,
                        target_language,
                        save_txt=save_txt,
                        save_docx=save_docx,
                        create_handbook_option=create_handbook
                    )
    
    # Вкладка для Яндекс Диск
    with tab5:
        st.header("Яндекс Диск")
        yandex_url = st.text_input("Введите ссылку на файл или папку на Яндекс Диске", key="yandex_url")
        
        if yandex_url:
            if st.button("Транскрибировать файлы с Яндекс Диска"):
                if not api_key:
                    st.error("Пожалуйста, введите API ключ OpenAI в настройках")
                else:
                    process_yandex_disk_files(
                        yandex_url,
                        save_dir,
                        target_language,
                        save_txt=save_txt,
                        save_docx=save_docx,
                        create_handbook_option=create_handbook
                    )
    
    # Вкладка для Google Диск
    with tab6:
        st.header("Google Диск")
        gdrive_url = st.text_input("Введите ссылку на файл или папку на Google Диске", key="gdrive_url")
        
        st.info("""
        Поддерживаются следующие типы ссылок:
        - Ссылки на файлы: https://drive.google.com/file/d/FILE_ID/view
        - Ссылки на папки: https://drive.google.com/drive/folders/FOLDER_ID
        
        Файлы и папки должны быть открыты для доступа по ссылке.
        """)
        
        if gdrive_url:
            if st.button("Транскрибировать файлы с Google Drive"):
                if not api_key:
                    st.error("Пожалуйста, введите API ключ OpenAI в настройках")
                else:
                    process_gdrive_files(
                        gdrive_url,
                        save_dir,
                        target_language,
                        save_txt=save_txt,
                        save_docx=save_docx,
                        create_handbook_option=create_handbook
                    )

if __name__ == "__main__":
    main()