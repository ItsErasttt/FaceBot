import cv2
import os
import wave
import threading
from datetime import datetime, timedelta
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import logging

# --- Настройки ---
TOKEN = "Token_from_the_bot"
CAMERA_INDEX = 0 #Изменить индекс(если камер несколько, 0 - по умолчанию)
SNAPSHOTS_FOLDER = "snapshots"
RECORDINGS_FOLDER = "recordings"
AUDIO_RECORDS_FOLDER = "audio_records"

os.makedirs(SNAPSHOTS_FOLDER, exist_ok=True)
os.makedirs(RECORDINGS_FOLDER, exist_ok=True)
os.makedirs(AUDIO_RECORDS_FOLDER, exist_ok=True)

# --- Логирование ---
logging.basicConfig(level=logging.INFO)

# --- Глобальные переменные ---
is_recording_video = False
is_recording_audio = False
cap = None
out = None
video_output_path = None
audio_output_path = None
start_time_video = None
start_time_audio = None
chat_id = None
last_task_type = None  # 'video' или 'audio'

# Для аудио
audio_frames = []
audio_stream = None
audio_interface = None

# --- Фото ---
def take_snapshot(camera_index=CAMERA_INEX):
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print(f"❌ Не удалось открыть камеру {camera_index} для фото.")
        return None

    ret, frame = cap.read()
    cap.release()

    if not ret:
        print("❌ Не удалось получить кадр для фото.")
        return None

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    image_path = os.path.join(SNAPSHOTS_FOLDER, f"snapshot_{timestamp}.jpg")
    cv2.imwrite(image_path, frame)
    return image_path

# --- Видео ---
def start_video_recording(chat_id):
    global cap, out, video_output_path

    now = datetime.now()
    video_output_path = os.path.join(RECORDINGS_FOLDER, f"recording_{now.strftime('%Y%m%d%H%M%S')}.mp4")

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print(f"❌ Не удалось открыть камеру {CAMERA_INDEX}")
        return False

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25  # fallback

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(video_output_path, fourcc, fps, (width, height))

    return True

def video_recording_loop():
    global cap, out, is_recording_video

    while is_recording_video and cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        out.write(frame)

    stop_video_recording()

def stop_video_recording():
    global cap, out
    if out:
        out.release()
        out = None
    if cap:
        cap.release()
        cap = None

# --- Аудио ---
def start_audio_recording():
    global audio_frames, audio_stream, audio_interface

    from pyaudio import PyAudio, paInt16

    audio_interface = PyAudio()
    audio_stream = audio_interface.open(
        format=paInt16,
        channels=1,
        rate=44100,
        input=True,
        frames_per_buffer=1024
    )

    audio_frames = []
    print("🎙️ Начата запись аудио...")

    def record_loop():
        global is_recording_audio
        while is_recording_audio:
            data = audio_stream.read(1024)
            audio_frames.append(data)

    threading.Thread(target=record_loop, daemon=True).start()

def stop_audio_recording(path):
    global audio_interface, audio_stream, audio_frames
    from pyaudio import paInt16

    if audio_stream:
        audio_stream.stop_stream()
        audio_stream.close()
        audio_stream = None

    if audio_interface:
        with wave.open(path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(audio_interface.get_sample_size(paInt16))
            wf.setframerate(44100)
            wf.writeframes(b''.join(audio_frames))
        audio_interface.terminate()
        audio_interface = None

# --- Команды ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот для управления камерой 📷\n"
        "Команды:\n"
        "/snapshot – сделать фото\n"
        "/record – начать запись видео\n"
        "/record_audio – начать запись аудио\n"
        "/stop – остановить запись\n"
        "/status – показать текущий статус"
    )

async def snapshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    image_path = take_snapshot()
    if image_path and os.path.exists(image_path):
        with open(image_path, 'rb') as photo_file:
            await update.message.reply_photo(photo=InputFile(photo_file))
    else:
        await update.message.reply_text("❌ Не удалось сделать фото.")

async def record(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_recording_video, chat_id, start_time_video, last_task_type

    if is_recording_video or is_recording_audio:
        await update.message.reply_text("⚠️ Уже что-то записывается.")
        return

    chat_id = update.effective_chat.id
    if start_video_recording(chat_id):
        is_recording_video = True
        start_time_video = datetime.now()
        last_task_type = 'video'
        threading.Thread(target=video_recording_loop, daemon=True).start()
        await update.message.reply_text("📹 Видео записывается...")
    else:
        await update.message.reply_text("❌ Не удалось начать запись.")

async def record_audio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_recording_audio, chat_id, start_time_audio, audio_output_path, last_task_type

    if is_recording_video or is_recording_audio:
        await update.message.reply_text("⚠️ Уже что-то записывается.")
        return

    chat_id = update.effective_chat.id
    now = datetime.now()
    audio_output_path = os.path.join(AUDIO_RECORDS_FOLDER, f"audio_{now.strftime('%Y%m%d%H%M%S')}.wav")
    start_time_audio = now
    is_recording_audio = True
    last_task_type = 'audio'
    start_audio_recording()
    await update.message.reply_text("🎙️ Аудио записывается...")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_recording_video, is_recording_audio

    if not is_recording_video and not is_recording_audio:
        await update.message.reply_text("⏹️ Ничего не записывается.")
        return

    if is_recording_video:
        is_recording_video = False
        duration = (datetime.now() - start_time_video).seconds
        stop_video_recording()

        if os.path.exists(video_output_path):
            with open(video_output_path, 'rb') as f:
                await update.message.reply_video(video=InputFile(f), caption=f"🎬 Длительность: {duration} сек.")
        else:
            await update.message.reply_text("❌ Видеофайл не создан.")

    elif is_recording_audio:
        is_recording_audio = False
        stop_audio_recording(audio_output_path)

        if os.path.exists(audio_output_path):
            with open(audio_output_path, 'rb') as f:
                await update.message.reply_voice(voice=InputFile(f), caption="🎧 Запись завершена")
        else:
            await update.message.reply_text("❌ Аудиофайл не создан.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_recording_video:
        await update.message.reply_text("📹 Идёт запись видео.")
    elif is_recording_audio:
        await update.message.reply_text("🎙️ Идёт запись аудио.")
    else:
        await update.message.reply_text("⏹️ Нет активной записи.")

# --- Основная функция ---
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("snapshot", snapshot))
    app.add_handler(CommandHandler("record", record))
    app.add_handler(CommandHandler("record_audio", record_audio_command))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("status", status))

    print("✅ Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
