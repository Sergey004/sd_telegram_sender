import os
import re
import requests
import threading
import time
from PIL import Image
from modules import shared, script_callbacks
from transformers import pipeline

# Попытка загрузки модели NSFW
try:
    nsfw_pipeline = pipeline('image-classification', model='AdamCodd/vit-nsfw-stable-diffusion')
    print(f"\033[96m[TelegramSender]\033[0m NSFW detection model loaded successfully.")
except Exception as e:
    print(f"\033[96m[TelegramSender]\033[0m Failed to load NSFW detection model: {e}")
    nsfw_pipeline = None

COLOR_TELEGRAM = "\033[96m"
COLOR_RESET = "\033[0m"

def print_colored(message: str):
    """Печатает цветной текст с тегом [TelegramSender]."""
    print(f"{COLOR_TELEGRAM}[TelegramSender]{COLOR_RESET} {message}")

def debug_print(message: str):
    """Печатает отладочные сообщения, если включен режим отладки."""
    if shared.opts.data.get("telegram_debug_mode", False):
        print(f"{COLOR_TELEGRAM}[DEBUG]{COLOR_RESET} {message}")

def resize_image(image_path: str) -> str:
    """
    Изменяет размер изображения в зависимости от ориентации:
      - Для горизонтальных изображений, если ширина превышает telegram_landscape_max_width,
        изменяет размер так, чтобы ширина равнялась telegram_landscape_max_width.
      - Для вертикальных/квадратных изображений, если большая сторона превышает telegram_max_size,
        изменяет размер так, чтобы большая сторона равнялась telegram_max_size.
    Возвращает путь к временному файлу JPEG, если было изменение размера, иначе исходный путь.
    """
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            if width >= height:
                max_val = shared.opts.data.get("telegram_landscape_max_width", 5120)
                debug_print(f"Landscape image: max width = {max_val}")
                if width <= max_val:
                    return image_path
            else:
                max_val = shared.opts.data.get("telegram_max_size", 2560)
                debug_print(f"Non-landscape image: max size = {max_val}")
                if max(width, height) <= max_val:
                    return image_path

            ratio = max_val / max(width, height)
            new_size = (int(width * ratio), int(height * ratio))
            debug_print(f"Resizing image from {width}x{height} to {new_size}")
            img = img.resize(new_size, Image.LANCZOS)
            temp_path = os.path.splitext(image_path)[0] + "_resized.jpg"
            img.save(temp_path, "JPEG", quality=85, optimize=True)
            debug_print(f"Resized image saved as: {temp_path}")
            return temp_path
    except Exception as e:
        print_colored(f"Error resizing image: {e}")
        return image_path

def compress_image_for_telegram(image_path: str, target_size: int = 10 * 1024 * 1024) -> str:
    """
    Сжимает JPEG-изображение до размера меньше target_size (по умолчанию 10 МБ).
    Возвращает путь к временному сжатому файлу.
    """
    temp_path = os.path.splitext(image_path)[0] + "_compressed.jpg"
    quality = 85
    try:
        with Image.open(image_path) as img:
            while quality >= 30:
                img.save(temp_path, "JPEG", quality=quality, optimize=True)
                current_size = os.path.getsize(temp_path)
                debug_print(f"Compressed with quality={quality}: size={current_size} bytes")
                if current_size <= target_size:
                    return temp_path
                quality -= 10
            return temp_path
    except Exception as e:
        print_colored(f"Error compressing image: {e}")
        return image_path

def extract_key(filename: str) -> str:
    """
    Извлекает первый токен после "-lora" из имени файла.
    Пример: "0001-indigoFurryMixXL_v30-lora SomeLora" → "lora somelora"
    """
    debug_print(f"Extracting key from filename: {filename}")
    match = re.search(r"-lora\s+(\S+)", filename, re.IGNORECASE)
    if match:
        key_extracted = f"lora {match.group(1).strip()}"
        debug_print(f"Extracted key: {key_extracted}")
        return key_extracted
    debug_print("No '-lora' marker found in filename.")
    return ""

def delete_temp_file(file_path: str):
    """
    Удаляет файл, если он существует и его имя указывает на временный файл 
    (содержит "_resized" или "_compressed"). Предотвращает удаление оригиналов.
    """
    try:
        if os.path.exists(file_path):
            basename = os.path.basename(file_path)
            if "_resized" in basename or "_compressed" in basename:
                os.remove(file_path)
                debug_print(f"Temporary file '{file_path}' deleted after successful upload.")
            else:
                debug_print(f"File '{file_path}' is an original; not deleting.")
    except Exception as e:
        debug_print(f"Failed to delete temporary file '{file_path}': {e}")

def send_to_telegram(image_path: str, chat_id: str, as_document=False):
    """
    Отправляет файл по указанному пути в Telegram с повторными попытками.
    Если as_document=True, отправляет как документ; иначе как фото.
    В режиме фото, если размер превышает 10 МБ, дополнительно сжимает изображение.
    """
    if shared.opts.data.get("telegram_disable_sending", False):
        debug_print(f"Sending disabled. Skipping file: {image_path}")
        return

    bot_token = shared.opts.data.get("telegram_bot_token", "YOUR_BOT_TOKEN")
    if not bot_token or bot_token == "YOUR_BOT_TOKEN":
        print_colored("Telegram Bot Token is not configured – send canceled.")
        return

    if not as_document:
        try:
            size = os.path.getsize(image_path)
            threshold = 10 * 1024 * 1024  # 10MB
            debug_print(f"Initial file size for photo: {size} bytes")
            if size > threshold:
                debug_print("File size exceeds 10MB; further compressing image.")
                image_path = compress_image_for_telegram(image_path, target_size=threshold)
                debug_print(f"New file size: {os.path.getsize(image_path)} bytes")
        except Exception as e:
            print_colored(f"Error checking file size: {e}")

    method = "sendDocument" if as_document else "sendPhoto"
    param_name = "document" if as_document else "photo"
    url = f"https://api.telegram.org/bot{bot_token}/{method}"

    max_retries = int(shared.opts.data.get("telegram_retry_count", 3))
    delay = int(shared.opts.data.get("telegram_retry_delay", 5))

    for attempt in range(max_retries):
        try:
            with open(image_path, 'rb') as f:
                files = {param_name: f}
                data = {'chat_id': chat_id}
                debug_print(f"Attempt {attempt+1}/{max_retries}: Sending request to {url} with chat_id {chat_id}")
                response = requests.post(url, data=data, files=files)
            if response.ok:
                print_colored(f"File '{image_path}' sent to Telegram (chat {chat_id}) as {method}.")
                delete_temp_file(image_path)
                return
            else:
                print_colored(f"Error sending file (attempt {attempt+1}/{max_retries}): {response.text}")
        except Exception as e:
            print_colored(f"Exception on attempt {attempt+1}/{max_retries}: {e}")
        if attempt < max_retries - 1:
            print_colored(f"Retrying in {delay} seconds...")
            time.sleep(delay)
    print_colored(f"Failed to send '{image_path}' after {max_retries} attempts. File not deleted.")

def predict_nsfw(image_path):
    """Классифицирует изображение как NSFW или SFW с помощью модели."""
    if nsfw_pipeline is None:
        return {image_path: {'Label': 'SFW', 'Score': 0.0}}
    try:
        img = Image.open(image_path)
        img = img.resize((224, 224), Image.LANCZOS)  # Размер для ViT
        result = nsfw_pipeline(img)
        nsfw_label = 'NSFW' if any(d['label'] == 'NSFW' for d in result) else 'SFW'
        score = max(d['score'] for d in result if d['label'] == nsfw_label)
        return {image_path: {'Label': nsfw_label, 'Score': score}}
    except Exception as e:
        print_colored(f"Error in NSFW detection: {e}")
        return {image_path: {'Label': 'SFW', 'Score': 0.0}}

def on_image_saved(params):
    """
    Вызывается после сохранения изображения.
    Игнорирует файлы из "outputs/grids/".
    Если включено обнаружение NSFW и изображение классифицировано как NSFW, отправляет в NSFW-канал.
    Иначе извлекает ключ из имени файла по "-lora" и маршрутизирует соответственно.
    """
    image_path = params.filename if hasattr(params, "filename") else None
    if not image_path or "outputs/grids/" in image_path.replace("\\", "/"):
        return

    filename = os.path.basename(image_path)
    debug_print(f"Filename: {filename}")

    # Проверка NSFW-контента, если включено и модель доступна
    if shared.opts.data.get("enable_nsfw_detection", False) and nsfw_pipeline:
        try:
            output = predict_nsfw(image_path)
            score = output[image_path]['Score']
            label = output[image_path]['Label']
            debug_print(f"NSFW detection: Label={label}, Score={score}")
            if label == "NSFW" and score >= shared.opts.data.get("nsfw_threshold", 0.5):
                nsfw_chat_id = shared.opts.data.get("nsfw_channel_id", "")
                if nsfw_chat_id:
                    chat_id = nsfw_chat_id
                    print_colored(f"Image is NSFW (score={score}). Sending to NSFW channel {chat_id}.")
                else:
                    print_colored("NSFW detected but no NSFW channel ID configured. Proceeding with original routing.")
                    key = extract_key(filename).lower()
                    mapping_str = shared.opts.data.get("telegram_channel_mapping", "")
                    mapping = {k.strip().lower(): v.strip() for k, v in (entry.split(":", 1) for entry in mapping_str.split(";") if ":" in entry)}
                    chat_id = mapping.get(key)
                    if not chat_id:
                        print_colored(f"No mapping found for key '{key}'. Not sending image.")
                        return
            else:
                key = extract_key(filename).lower()
                mapping_str = shared.opts.data.get("telegram_channel_mapping", "")
                mapping = {k.strip().lower(): v.strip() for k, v in (entry.split(":", 1) for entry in mapping_str.split(";") if ":" in entry)}
                chat_id = mapping.get(key)
                if not chat_id:
                    print_colored(f"No mapping found for key '{key}'. Not sending image.")
                    return
        except Exception as e:
            print_colored(f"Error in NSFW detection: {e}")
            key = extract_key(filename).lower()
            mapping_str = shared.opts.data.get("telegram_channel_mapping", "")
            mapping = {k.strip().lower(): v.strip() for k, v in (entry.split(":", 1) for entry in mapping_str.split(";") if ":" in entry)}
            chat_id = mapping.get(key)
            if not chat_id:
                print_colored(f"No mapping found for key '{key}'. Not sending image.")
                return
    else:
        key = extract_key(filename).lower()
        mapping_str = shared.opts.data.get("telegram_channel_mapping", "")
        mapping = {k.strip().lower(): v.strip() for k, v in (entry.split(":", 1) for entry in mapping_str.split(";") if ":" in entry)}
        chat_id = mapping.get(key)
        if not chat_id:
            print_colored(f"No mapping found for key '{key}'. Not sending image.")
            return

    print_colored(f"Sending '{image_path}' to Telegram (chat {chat_id}).")

    # Изменение размера для отправки как фото
    resized_path = resize_image(image_path)
    try:
        if os.path.getsize(resized_path) > 10 * 1024 * 1024:
            resized_path = compress_image_for_telegram(resized_path)
    except Exception as e:
        print_colored(f"Error checking resized image size: {e}")

    # Отправка уменьшенной версии как фото
    threading.Thread(target=send_to_telegram, args=(resized_path, chat_id, False)).start()

    # Отправка оригинала как документа, если включен режим полного разрешения
    if shared.opts.data.get("telegram_full_res", False):
        threading.Thread(target=send_to_telegram, args=(image_path, chat_id, True)).start()

script_callbacks.on_image_saved(on_image_saved)

def on_ui_settings():
    """Регистрирует настройки в меню интерфейса."""
    section = ("telegram_sender", "Telegram Sender")
    shared.opts.add_option("telegram_bot_token", shared.OptionInfo("YOUR_BOT_TOKEN", "Telegram Bot Token", section=section))
    shared.opts.add_option("telegram_channel_mapping", shared.OptionInfo("lora somelora:CHAT_ID", "Channel Mapping (format: key:chat_id; separate pairs with semicolons)", section=section))
    shared.opts.add_option("telegram_full_res", shared.OptionInfo(False, "Send Full Resolution (as Document) along with resized copy", section=section))
    shared.opts.add_option("telegram_disable_sending", shared.OptionInfo(False, "Disable Sending to Telegram", section=section))
    shared.opts.add_option("telegram_debug_mode", shared.OptionInfo(False, "Enable Debug Mode", section=section))
    shared.opts.add_option("telegram_max_size", shared.OptionInfo(2560, "Max size for portrait/square images (px)", section=section))
    shared.opts.add_option("telegram_landscape_max_width", shared.OptionInfo(5120, "Max width for landscape images (px)", section=section))
    shared.opts.add_option("telegram_retry_count", shared.OptionInfo(3, "Number of retry attempts", section=section))
    shared.opts.add_option("telegram_retry_delay", shared.OptionInfo(5, "Delay between retry attempts (seconds)", section=section))
    # Новые опции для обнаружения NSFW
    shared.opts.add_option("enable_nsfw_detection", shared.OptionInfo(False, "Enable NSFW Detection", section=section))
    shared.opts.add_option("nsfw_channel_id", shared.OptionInfo("", "NSFW Channel ID", section=section))
    shared.opts.add_option("nsfw_threshold", shared.OptionInfo(0.5, "NSFW Threshold (0 to 1)", section=section))

script_callbacks.on_ui_settings(on_ui_settings)