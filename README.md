# Telegram Sender Extension for Automatic1111

This extension automatically sends generated images from Automatic1111's web UI to a Telegram chat. It extracts a routing key from the image filename based on the "-lora" marker, then uses a mapping (set via the Web UI) to determine which Telegram chat to send the image to.

Optionally, you can enable a Full Resolution Mode that sends both a resized (Telegram-friendly) version _and_ the original full-resolution image.

---

## Features

- **Automatic Image Sending:**  
  The extension registers a callback (via `script_callbacks.on_image_saved`) that is triggered after an image is saved.

- **Routing by Filename:**  
  It searches for the `-lora` marker in the filename (e.g., `0001-indigoFurryMixXL_v30-lora SomeLora`) and extracts the first token after the marker. The extracted key (e.g., `"lora somelora"`) is then used to look up a Telegram chat ID from a mapping provided in the settings.

- **Image Resizing:**  
  By default, if the image's largest side exceeds 2560 pixels, it is resized to ensure it fits Telegram’s limits.  
  - If the resized image is over 10 MB, it is sent as a document instead of a photo.

- **Full Resolution Mode:**  
  When enabled (via a Web UI setting), the extension sends both:
  - The resized version (as a photo) for Telegram preview.
  - The original, full-resolution image (as a document) to preserve quality.

- **Debug Mode:**  
  A debug mode (configurable via Web UI) prints additional log messages, making it easier to troubleshoot issues.

---

## Installation

1. **Copy the Script:**  
   Save the file (e.g. `telegram_sender.py`) into your Automatic1111 extensions folder (for example, `extensions/telegram_sender/`).

2. **Restart the Web UI:**  
   Restart Automatic1111 to load the new extension.

3. **Configure Settings:**  
   Open the Web UI, navigate to the Settings panel, and locate the **Telegram Sender** section.

---

## Configuration via Web UI

In the **Telegram Sender** section, configure the following:

- **Telegram Bot Token:**  
  Enter your Telegram Bot Token (obtained from [BotFather](https://t.me/BotFather)).  
  *Example:* `123456:ABC-DEF1234567890ghIkl-zyx57W2v1u123ew11`

- **Telegram Channel Mapping:**  
  Define the mapping between routing keys and Telegram chat IDs. Use the following format:  
  ```
  lora somelora:CHAT_ID_FOR_SOMELORA; lora anotherkey:CHAT_ID_FOR_ANOTHER
  ```  
  The extension extracts a key from the filename (e.g. "lora somelora") and looks for it in this mapping. If a match is found, the image is sent to that Telegram chat.

- **Send Full Resolution (as Document):**  
  If enabled, the extension will send both the resized version (as a photo) and the original file (as a document).  
  *Default is OFF.*

- **Enable Telegram Sender Debug Mode:**  
  Turn this on to display additional debug messages in the console for troubleshooting.

---

## Filename Requirements

For the extension to work as intended, image filenames must contain the `-lora` marker followed by a token.  
**Example Filename:**  
```
0001-indigoFurryMixXL_v30-lora SomeLora.png
```  
In this case, the extension extracts the key `"lora somelora"` (in lowercase) and uses that to look up the Telegram chat ID in your mapping.

---

## How It Works

1. **Image Saved Callback:**  
   When an image is saved, the callback `on_image_saved` is triggered. The extension reads the filename (using `params.filename`), extracts the key using the `-lora` marker, and looks up the corresponding Telegram chat ID.

2. **Resizing (if needed):**  
   If Full Resolution Mode is not enabled, the image is resized so that its largest side does not exceed 2560 pixels.  
   - If the resized image’s size exceeds 10 MB, it is sent as a document; otherwise, it is sent as a photo.

3. **Full Resolution Mode:**  
   If Full Resolution Mode is enabled, the extension sends both:
   - The resized image as a photo.
   - The original full-resolution image as a document.

4. **Sending to Telegram:**  
   The extension makes an API call to Telegram (using either `sendPhoto` or `sendDocument`) to deliver the file. All API calls run in a separate thread to avoid blocking the main process.

---

## Debugging

If the extension does not send images as expected, enable **Telegram Sender Debug Mode** in the settings. This will print debug messages to the console, including:

- The parameters received by the callback.
- The extracted key from the filename.
- The parsed mapping from the configuration.
- Details of the Telegram API request (URL, method, chat ID).

You can also test the `send_to_telegram` function manually from a Python shell with a known image path and chat ID.

---

## Dependencies

- **Python 3.x**
- **Requests** library
- **Pillow (PIL)** for image processing

Make sure these packages are installed in your Automatic1111 environment.

---

## License

This extension is provided "as is" without warranty of any kind. You are free to use and modify it as needed.