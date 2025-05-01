#!/bin/bash

# Установка ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "Устанавливаем FFmpeg..."
    sudo apt update
    sudo apt install -y ffmpeg
else
    echo "FFmpeg уже установлен"
fi

# Проверка версии Python
python_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
required_version="3.9"

if (( $(echo "$python_version < $required_version" | bc -l) )); then
    echo "Требуется Python версии $required_version или выше. Установлена версия: $python_version"
    echo "Устанавливаем Python 3.9..."
    sudo apt install -y python3.9 python3.9-venv
    # Устанавливаем Python 3.9 как стандартный Python3
    sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.9 1
    python_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    echo "Установлен Python версии: $python_version"
fi

# Создание виртуальной среды
echo "Создание виртуальной среды Python..."
python3 -m venv venv
source venv/bin/activate

# Установка зависимостей
echo "Установка зависимостей..."
pip install --upgrade pip
pip install -r requirements.txt

echo "Установка завершена. Для запуска приложения выполните:"
echo "source venv/bin/activate && streamlit run app.py"