import os
import sys
import tkinter as tk
from tkinter import filedialog


def select_folder():
    """
    Открывает диалог выбора папки и возвращает выбранный путь
    """
    root = tk.Tk()
    root.withdraw()  # Скрываем основное окно tkinter
    
    # Открываем диалог выбора директории
    folder_path = filedialog.askdirectory(
        title="Выберите папку для сохранения файлов"
    )
    
    # Возвращаем выбранный путь или пустую строку, если пользователь отменил выбор
    if folder_path:
        print(folder_path)  # Выводим путь, чтобы основной скрипт мог его прочитать
    else:
        print("")  # Пустая строка, если пользователь отменил выбор
        
    # Завершаем программу
    root.destroy()


if __name__ == "__main__":
    select_folder()