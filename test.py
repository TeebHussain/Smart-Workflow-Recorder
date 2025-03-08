import os
import signal
import time
import threading
import io
import tempfile
import pyautogui
import pyaudio
import wave
import openai
from pynput import mouse
from fpdf import FPDF
from PIL import Image, ImageDraw

# OpenAI API Key
openai.api_key = "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"  # Replace with your actual API key

# Global Variables
recording = True
screenshot_count = 0
audio_frames = []
screenshots = []
chunks = []
last_capture_time = time.time()
instruction_counter = 1  

# Initialize Audio Recording
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
CHUNK_SIZE = 1024
audio = pyaudio.PyAudio()
stream = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK_SIZE)

def signal_handler(sig, frame):
    global recording, listener
    print("\nStopping recording...")
    recording = False  

    if listener.running:
        listener.stop()

    if audio_thread.is_alive():
        audio_thread.join()

    stream.stop_stream()
    stream.close()
    audio.terminate()

    process_audio_and_generate_pdf()
    print("Recording stopped successfully. Exiting...")
    exit(0)

def take_screenshot(x=None, y=None):
    global screenshot_count, last_capture_time
    screenshot = pyautogui.screenshot()
    
    if x is not None and y is not None:
        draw = ImageDraw.Draw(screenshot, "RGBA")
        radius = 30  
        overlay = Image.new("RGBA", screenshot.size, (255, 255, 255, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(255, 255, 0, 100))
        screenshot = Image.alpha_composite(screenshot.convert("RGBA"), overlay)

    screenshot_io = io.BytesIO()
    screenshot.save(screenshot_io, format="PNG")
    screenshots.append((screenshot_io, x, y))

    current_time = time.time()
    audio_chunk = save_audio_chunk(last_capture_time, current_time)
    chunks.append((audio_chunk, last_capture_time, current_time))

    last_capture_time = current_time
    print(f"Screenshot captured.")

def save_audio_chunk(start_time, end_time):
    duration = end_time - start_time
    frames_to_save = int((duration / (1 / RATE)) / CHUNK_SIZE)
    frames = audio_frames[-frames_to_save:] if frames_to_save > 0 else []

    audio_io = io.BytesIO()
    with wave.open(audio_io, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(audio.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(frames))

    print(f"Audio chunk captured ({duration:.2f} sec)")
    return audio_io

def continuous_audio_recording():
    while recording:
        try:
            data = stream.read(CHUNK_SIZE)
            if not recording:
                break
            audio_frames.append(data)
        except Exception as e:
            print(f"Error in audio recording: {e}")
            break

def on_click(x, y, button, pressed):
    if pressed and recording:
        take_screenshot(x, y)

listener = mouse.Listener(on_click=on_click)
listener.start()

def transcribe_audio(audio_io):
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
            temp_filename = temp_audio.name  
            temp_audio.write(audio_io.getvalue())  
            temp_audio.flush()  

        with open(temp_filename, "rb") as audio_file:
            response = openai.Audio.transcribe("whisper-1", audio_file, language="en")  # Forced English transcription
        
        os.remove(temp_filename)  

        raw_text = response["text"]
        
        # Debugging: Print and save transcription output
        print(f"\n### RAW TRANSCRIPTION OUTPUT ###\n{raw_text}\n")
        
        with open("transcription_debug.txt", "a", encoding="utf-8") as f:
            f.write(f"\n--- Transcription Start ---\n{raw_text}\n--- Transcription End ---\n")

        return raw_text
    except Exception as e:
        print(f"Error transcribing audio: {e}")
        return ""

def extract_important_text(text):
    try:
        print(f"\n### Input to GPT for Extraction ###\n{text}\n")

        prompt = "Extract as much useful instructional information as possible. If the steps are incomplete, retain whatever is available. Use the text given: " + text
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You extract important instructions from the provided text"},
                {"role": "user", "content": prompt}
            ]
        )

        extracted_text = response["choices"][0]["message"]["content"].strip()

        # Debugging: Print extracted instructions
        print(f"\n### Extracted Important Instructions ###\n{extracted_text}\n")

        with open("extracted_instructions_debug.txt", "a", encoding="utf-8") as f:
            f.write(f"\n--- Instruction Extraction Start ---\n{extracted_text}\n--- Instruction Extraction End ---\n")

        return extracted_text
    except Exception as e:
        print(f"Error extracting important text: {e}")
        return text

def process_audio_and_generate_pdf():
    global instruction_counter
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", size=12)

    pdf.add_page()  # Start with the first page

    img_width = 150  # Fixed width
    for i, (audio_io, start, end) in enumerate(chunks):
        print(f"Processing audio chunk {i+1}...")

        text = transcribe_audio(audio_io)
        important_text = extract_important_text(text)
        important_text = important_text.encode("latin-1", "ignore").decode("latin-1")

        if pdf.get_y() > 260:
            pdf.add_page()

        pdf.multi_cell(0, 5, f"{instruction_counter}. {important_text}")
        pdf.ln(10)
        instruction_counter += 1

        if i < len(screenshots):
            screenshot_io, x, y = screenshots[i]
            screenshot_io.seek(0)
            image = Image.open(screenshot_io)

            temp_path = f"temp_screenshot_{i}.png"
            image.save(temp_path, "PNG")

            # Calculate the correct height
            img_height = (image.height / image.width) * img_width  # Keeps aspect ratio

            if pdf.get_y() + img_height + 10 > 270:
                pdf.add_page()

            y_position = pdf.get_y()
            pdf.image(temp_path, x=10, y=y_position, w=img_width, h=img_height)
            pdf.set_y(y_position + img_height + 15)  # Adjusted spacing

            os.remove(temp_path)

    pdf_filename = "instructions_fixed.pdf"
    pdf.output(pdf_filename)
    print(f"PDF saved as {pdf_filename}")

    screenshots.clear()
    chunks.clear()
    audio_frames.clear()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)

    print("Recording started. Press ^C to stop and generate PDF.")

    audio_thread = threading.Thread(target=continuous_audio_recording)
    audio_thread.start()

    while recording:
        time.sleep(1)
