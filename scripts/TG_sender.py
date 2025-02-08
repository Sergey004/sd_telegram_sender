import os
import re
import requests
import threading
from PIL import Image
from modules import shared, script_callbacks

def debug_print(message: str):
    if shared.opts.data.get("telegram_debug_mode", False):
        print("[TelegramSender DEBUG]", message)

def resize_image(image_path: str) -> str:
    """Resizes the image for Telegram while maintaining orientation."""
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            max_width = shared.opts.data.get("telegram_landscape_max_width", 5120) if width >= height else shared.opts.data.get("telegram_max_size", 2560)
            
            if max(width, height) <= max_width:
                return image_path  # No resize needed
            
            ratio = max_width / max(width, height)
            new_size = (int(width * ratio), int(height * ratio))
            img = img.resize(new_size, Image.LANCZOS)

            temp_path = os.path.splitext(image_path)[0] + "_resized.jpg"
            img.save(temp_path, "JPEG", quality=85, optimize=True)
            return temp_path
    except Exception as e:
        print(f"[TelegramSender] Error resizing image: {e}")
        return image_path

def compress_image_for_telegram(image_path: str, target_size: int = 10 * 1024 * 1024) -> str:
    """Further compresses a JPEG until it's below the Telegram 10MB limit."""
    temp_path = os.path.splitext(image_path)[0] + "_compressed.jpg"
    quality = 85
    try:
        with Image.open(image_path) as img:
            while quality >= 30:
                img.save(temp_path, "JPEG", quality=quality, optimize=True)
                if os.path.getsize(temp_path) <= target_size:
                    return temp_path
                quality -= 10
            return temp_path
    except Exception as e:
        print(f"[TelegramSender] Error compressing image: {e}")
        return image_path

def extract_key(filename: str) -> str:
    """Extracts key from filename based on '-lora' marker."""
    match = re.search(r"-lora\s+(\S+)", filename, re.IGNORECASE)
    return f"lora {match.group(1).strip()}" if match else ""

def send_to_telegram(image_path: str, chat_id: str, as_document=False):
    """Sends a file to Telegram and deletes it after successful upload."""
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
            response = requests.post(url, data=data, files=files)

        if response.ok:
            print(f"[TelegramSender] File '{image_path}' sent to Telegram (chat {chat_id}) as {method}.")
            delete_temp_file(image_path)  # Delete only after successful send
        else:
            print(f"[TelegramSender] Error sending file: {response.text}")
    except Exception as e:
        print(f"[TelegramSender] Exception while sending file: {e}")

def delete_temp_file(file_path: str):
    """Deletes a file if it exists."""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            debug_print(f"Temporary file '{file_path}' deleted after successful upload.")
    except Exception as e:
        debug_print(f"Failed to delete temporary file '{file_path}': {e}")

def on_image_saved(params):
    """Handles image sending: extracts key, routes image, resizes, compresses, and sends."""
    image_path = params.filename if hasattr(params, "filename") else None
    if not image_path or "outputs/grids/" in image_path.replace("\\", "/"):
        return  # Ignore grids

    filename = os.path.basename(image_path)
    key = extract_key(filename).lower()
    mapping = {k.strip().lower(): v.strip() for k, v in (entry.split(":", 1) for entry in shared.opts.data.get("telegram_channel_mapping", "").split(";") if ":" in entry)}
    chat_id = mapping.get(key)

    if not chat_id:
        print(f"[TelegramSender] No mapping found for key '{key}'. Not sending image.")
        return

    print(f"[TelegramSender] Sending '{image_path}' to Telegram (chat {chat_id}).")

    # Resize image for sending as photo
    resized_path = resize_image(image_path)
    is_temp_file = (resized_path != image_path)

    # If resized version is still too big, further compress it
    try:
        if os.path.getsize(resized_path) > 10 * 1024 * 1024:
            resized_path = compress_image_for_telegram(resized_path)
    except Exception as e:
        print(f"[TelegramSender] Error checking resized image size: {e}")

    # Send compressed/resized version as photo
    threading.Thread(target=send_to_telegram, args=(resized_path, chat_id, False)).start()

    # Send original as document if full resolution mode is enabled
    if shared.opts.data.get("telegram_full_res", False):
        threading.Thread(target=send_to_telegram, args=(image_path, chat_id, True)).start()

script_callbacks.on_image_saved(on_image_saved)

def on_ui_settings():
    """Registers options in the UI settings menu."""
    section = ("telegram_sender", "Telegram Sender")
    shared.opts.add_option("telegram_bot_token", shared.OptionInfo("YOUR_BOT_TOKEN", "Telegram Bot Token", section=section))
    shared.opts.add_option("telegram_channel_mapping", shared.OptionInfo("lora somelora:CHAT_ID", "Channel Mapping (format: key:chat_id; separate pairs with semicolons)", section=section))
    shared.opts.add_option("telegram_full_res", shared.OptionInfo(False, "Send Full Resolution (as Document) along with resized copy", section=section))
    shared.opts.add_option("telegram_debug_mode", shared.OptionInfo(False, "Enable Debug Mode", section=section))
    shared.opts.add_option("telegram_max_size", shared.OptionInfo(2560, "Max size for portrait/square images (px)", section=section))
    shared.opts.add_option("telegram_landscape_max_width", shared.OptionInfo(5120, "Max width for landscape images (px)", section=section))

script_callbacks.on_ui_settings(on_ui_settings)
