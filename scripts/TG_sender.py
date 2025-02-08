import os
import re
import requests
import threading
from PIL import Image
from modules import shared, script_callbacks

def debug_print(message: str):
    if shared.opts.data.get("telegram_debug_mode", False):
        print("[TelegramSender DEBUG]", message)

def resize_image(image_path: str, max_size: int = 2560) -> str:
    """
    Resizes the image so that its larger side does not exceed max_size.
    Returns the path to a temporary resized file.
    """
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            if max(width, height) <= max_size:
                return image_path  # No resizing needed

            ratio = max_size / max(width, height)
            new_size = (int(width * ratio), int(height * ratio))
            img = img.resize(new_size, Image.LANCZOS)

            temp_path = os.path.splitext(image_path)[0] + "_resized.jpg"
            img.save(temp_path, "JPEG", quality=85, optimize=True)
            return temp_path
    except Exception as e:
        print(f"[TelegramSender] Error resizing image: {e}")
        return image_path  # Return original file in case of error

def extract_key(filename: str) -> str:
    """
    Extracts the first token after "-lora" from the filename.
    Example: "0001-indigoFurryMixXL_v30-lora SomeLora" → "lora somelora"
    """
    debug_print(f"Extracting key from filename: {filename}")
    pattern = re.compile(r"-lora\s+(\S+)", re.IGNORECASE)
    match = pattern.search(filename)
    if match:
        key_extracted = f"lora {match.group(1).strip()}"
        debug_print(f"Extracted key: {key_extracted}")
        return key_extracted
    debug_print("No -lora marker found in filename.")
    return ""

def send_to_telegram(image_path: str, chat_id: str, as_document=False):
    """
    Sends the file at image_path to the specified Telegram chat.
    If `as_document=True`, it is sent as a document, otherwise as a photo.
    """
    bot_token = shared.opts.data.get("telegram_bot_token", "YOUR_BOT_TOKEN")

    if not bot_token or bot_token == "YOUR_BOT_TOKEN":
        print("[TelegramSender] Telegram Bot Token is not configured – send canceled.")
        return

    method = "sendDocument" if as_document else "sendPhoto"
    param_name = "document" if as_document else "photo"

    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    try:
        with open(image_path, 'rb') as f:
            files = {param_name: f}
            data = {'chat_id': chat_id}
            debug_print(f"Sending request to Telegram: URL: {url}, Chat ID: {chat_id}, Mode: {method}")
            response = requests.post(url, data=data, files=files)

        if response.ok:
            print(f"[TelegramSender] File '{image_path}' sent to Telegram (chat {chat_id}) as {method}.")
        else:
            print(f"[TelegramSender] Error sending file: {response.text}")
            debug_print(f"Response details: {response.text}")
    except Exception as e:
        print(f"[TelegramSender] Exception while sending file: {e}")
        debug_print(f"Exception details: {e}")

def on_image_saved(params):
    """
    Callback function invoked after an image is saved.
    It extracts the key from the filename and routes the file accordingly.
    If no mapping is found for the extracted key, the file is not sent.
    """
    debug_print(f"on_image_saved callback invoked with params: {params}")
    image_path = params.filename if hasattr(params, "filename") else None
    if not image_path:
        print("[TelegramSender] Image path not found in callback parameters.")
        return

    filename = os.path.basename(image_path)
    key = extract_key(filename).lower()
    mapping_str = shared.opts.data.get("telegram_channel_mapping", "")
    
    mapping = {
        k.strip().lower(): v.strip() 
        for k, v in (entry.split(":", 1) for entry in mapping_str.split(";") if ":" in entry)
    }
    
    chat_id = mapping.get(key)
    if not chat_id:
        print(f"[TelegramSender] No mapping found for key '{key}'. Not sending image.")
        return

    print(f"[TelegramSender] Sending file '{image_path}' to Telegram (chat {chat_id}).")

    # Resize for sending as a photo
    resized_path = resize_image(image_path)
    is_temp_file = resized_path != image_path

    # Send resized version as a photo
    threading.Thread(target=send_to_telegram, args=(resized_path, chat_id, False)).start()

    # Send full resolution version if enabled
    if shared.opts.data.get("telegram_full_res", False):
        threading.Thread(target=send_to_telegram, args=(image_path, chat_id, True)).start()

    # Clean up resized temp file if needed
    if is_temp_file and os.path.exists(resized_path):
        os.remove(resized_path)

script_callbacks.on_image_saved(on_image_saved)

def on_ui_settings():
    """
    Adds configuration options to the Web UI.
    """
    section = ("telegram_sender", "Telegram Sender")
    shared.opts.add_option("telegram_bot_token", shared.OptionInfo(
        "YOUR_BOT_TOKEN", "Telegram Bot Token", section=section))
    shared.opts.add_option("telegram_channel_mapping", shared.OptionInfo(
        "lora somelora:CHAT_ID_FOR_SOMELORA", 
        "Telegram Channel Mapping (format: key:chat_id; separate pairs with semicolons)", 
        section=section))
    shared.opts.add_option("telegram_full_res", shared.OptionInfo(
        False, "Send Full Resolution (as Document)", section=section))
    shared.opts.add_option("telegram_debug_mode", shared.OptionInfo(
        False, "Enable Telegram Sender Debug Mode", section=section))

script_callbacks.on_ui_settings(on_ui_settings)
