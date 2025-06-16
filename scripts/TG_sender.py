import os
import re
import requests
import threading
import time
from PIL import Image
from modules import shared, script_callbacks # type: ignore

COLOR_TELEGRAM = "\033[96m"
COLOR_RESET = "\033[0m"

def print_colored(message: str):
    print(f"{COLOR_TELEGRAM}[TelegramSender]{COLOR_RESET} {message}")

def debug_print(message: str):
    if shared.opts.data.get("telegram_debug_mode", False):
        print(f"{COLOR_TELEGRAM}[DEBUG]{COLOR_RESET} {message}")

def resize_image(image_path: str) -> str:
    """
    Resizes the image based on its orientation:
      - For landscape images, if width exceeds telegram_landscape_max_width,
        resizes so that width equals telegram_landscape_max_width.
      - For portrait/square images, if the largest side exceeds telegram_max_size,
        resizes so that the largest side equals telegram_max_size.
    Returns the path to a temporary resized JPEG file if resizing occurred,
    otherwise returns the original image_path.
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

def compress_image(image_path: str, target_size: int = 10 * 1024 * 1024) -> str:
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
        print_colored(f"Compress error: {e}")
        return image_path

def delete_temp_file(path: str):
    if os.path.exists(path) and ("_resized" in path or "_compressed" in path):
        try:
            os.remove(path)
            debug_print(f"Deleted temp: {path}")
        except Exception as e:
            debug_print(f"Delete error: {e}")

def extract_parameters(image_path: str) -> str | None:
    try:
        with Image.open(image_path) as img:
            return img.info.get("parameters", "")
    except Exception as e:
        debug_print(f"Metadata read failed: {e}")
        return ""

def extract_loras(params: str) -> list[str]:
    return re.findall(r"<lora:([^:>]+)", params, re.IGNORECASE)

def send_to_telegram(image_path: str, chat_id: str, as_document=False):
    if shared.opts.data.get("telegram_disable_sending", False):
        return
    bot_token = shared.opts.data.get("telegram_bot_token", "")
    if not bot_token or bot_token == "YOUR_BOT_TOKEN":
        return
    if not as_document:
        try:
            if os.path.getsize(image_path) > 10 * 1024 * 1024:
                image_path = compress_image(image_path)
        except: pass
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
                response = requests.post(url, data=data, files=files)
            if response.ok:
                print_colored(f"Sent '{image_path}' to {chat_id} as {method}")
                delete_temp_file(image_path)
                return
            else:
                print_colored(f"[{attempt+1}/{max_retries}] Error: {response.text}")
        except Exception as e:
            print_colored(f"[{attempt+1}/{max_retries}] Exception: {e}")
        if attempt < max_retries - 1:
            time.sleep(delay)

def on_image_saved(params):
    if shared.opts.data.get("telegram_disable_sending", False):
        return
    
    image_path = getattr(params, "filename", None)
    if not image_path or "outputs/grids/" in image_path.replace("\\", "/"):
        return

    params_text = extract_parameters(image_path)
    if not params_text:
        debug_print("No parameters found in image metadata")
        return

    steps_index = params_text.find("Steps:")
    if steps_index != -1:
        params_text = params_text[:steps_index].strip()
    debug_print(f"Trimmed parameters: {params_text}")

    loras = extract_loras(params_text)
    debug_print(f"LORAs found: {loras}")

    mapping = {
        k.strip().lower(): v.strip()
        for k, v in (
            entry.split(":", 1)
            for entry in shared.opts.data.get("telegram_channel_mapping", "").split(";")
            if ":" in entry
        )
    }

    chat_id = None
    for lora in loras:
        lora_name = lora.lower()
        for mapkey in mapping:
            if mapkey.startswith("lora ") and mapkey[5:] in lora_name:
                chat_id = mapping[mapkey]
                debug_print(f"Matched '{mapkey}' to LoRA '{lora_name}'")
                break
        if chat_id:
            break


    positive_prompt = ""
    negative_prompt = ""
    

    if "Negative prompt:" in params_text:
        parts = params_text.split("Negative prompt:", 1)
        positive_prompt = parts[0].strip().lower()
        negative_prompt = parts[1].strip().lower()
    else:
        positive_prompt = params_text.strip().lower()
    
    debug_print(f"Positive prompt: {positive_prompt[:100]}...")
    debug_print(f"Negative prompt: {negative_prompt[:100]}...")
    

    nsfw_channel = shared.opts.data.get("telegram_nsfw_channel", "").strip()
    if nsfw_channel:

        if "nsfw" in negative_prompt:
            debug_print("NSFW in negative prompt - ignoring")

        elif "nsfw" in positive_prompt:
            debug_print("NSFW detected in positive prompt. Redirecting to NSFW channel.")
            chat_id = nsfw_channel

    if not chat_id:
        print_colored("No matching chat_id found. Skipping image.")
        return

    resized = resize_image(image_path)
    try:
        if os.path.getsize(resized) > 10 * 1024 * 1024:
            resized = compress_image(resized)
    except: pass

    def send_both():
        send_to_telegram(resized, chat_id, False)
        if shared.opts.data.get("telegram_full_res", False):
            send_to_telegram(image_path, chat_id, True)

    threading.Thread(target=send_both).start()

script_callbacks.on_image_saved(on_image_saved)

def on_ui_settings():
    section = ("telegram_sender", "Telegram Sender")
    shared.opts.add_option("telegram_bot_token", shared.OptionInfo("YOUR_BOT_TOKEN", "Telegram Bot Token", section=section))
    shared.opts.add_option("telegram_channel_mapping", shared.OptionInfo("lora somelora:CHAT_ID", "Channel Mapping (key:chat_id)", section=section))
    shared.opts.add_option("telegram_nsfw_channel", shared.OptionInfo("", "NSFW Channel ID", section=section))
    shared.opts.add_option("telegram_full_res", shared.OptionInfo(False, "Send original file as Document", section=section))
    shared.opts.add_option("telegram_disable_sending", shared.OptionInfo(False, "Disable sending", section=section))
    shared.opts.add_option("telegram_debug_mode", shared.OptionInfo(False, "Enable Debug", section=section))
    shared.opts.add_option("telegram_max_size", shared.OptionInfo(2560, "Max image size", section=section))
    shared.opts.add_option("telegram_landscape_max_width", shared.OptionInfo(5120, "Max width for landscape", section=section))
    shared.opts.add_option("telegram_retry_count", shared.OptionInfo(3, "Retry attempts", section=section))
    shared.opts.add_option("telegram_retry_delay", shared.OptionInfo(5, "Retry delay (s)", section=section))

script_callbacks.on_ui_settings(on_ui_settings)
