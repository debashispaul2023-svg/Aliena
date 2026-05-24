# #__________required to install_________

#pip install speechrecognition pyttsx3 opencv-python numpy pywhatkit psutil pyautogui screen-brightness-control keyboard mss google-generativeai AppOpener PyQt6 Pillow

import os
import sys
import threading
import time
import speech_recognition as sr
import pyttsx3
import cv2
import numpy as np
import pywhatkit
import psutil
import pyautogui
import screen_brightness_control as sbc
import keyboard
import mss
import google.generativeai as genai
from AppOpener import open as app_open, close as app_close
from PyQt6.QtWidgets import QApplication, QLabel, QWidget
from PyQt6.QtCore import Qt
from PIL import Image

# ---------------- GEMINI CONFIG ----------------
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY_HERE"  # Replace with your actual key locally

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# ---------------- VOICE ENGINE ----------------
engine = pyttsx3.init()
voices = engine.getProperty("voices")
engine.setProperty("voice", voices[0].id)
engine.setProperty("rate", 160)
engine.setProperty("volume", 1.0)

# speak
def speak(text):
    try:
        print(f"Jarvis: {text}")
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        print(f"Error in speak: {e}")


# take_command
def take_command():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print("Listening...")
        r.pause_threshold = 1
        r.adjust_for_ambient_noise(source, duration=1)
        try:
            audio = r.listen(source, timeout=5, phrase_time_limit=8)
            print("Recognizing...")
            query = r.recognize_google(audio, language='en-in')
            print(f"User: {query}")
            return query.lower()
        except Exception as e:
            return "none"


#____________generate_code___________

def generate_code(prompt):
    try:
        full_prompt = f"Write only the clean Python code for: {prompt}. No comments, no explanations, just code."
        response = model.generate_content(full_prompt)
        code = response.text.replace("```python", "").replace("```", "").strip()
        
        with open("generated_code.py", "w") as f:
            f.write(code)
        
        print(f"--- Generated Code Saved to generated_code.py ---\n{code}")
        return code
    except Exception as e:
        print(f"Code Gen Error: {e}")
        return ""

#__________ANALYZE SCREEN___________

def analyze_screen():
    speak("Analyzing your screen, please wait a moment.")
    try:
        with mss.mss() as sct:
            filename = "sct.png"
            sct.shot(output=filename)
            img = Image.open(filename)
            
            response = model.generate_content(
                ["You are Jarvis. Look at this screenshot and explain what is happening in 2 sentences.", img]
            )
            
            description = response.text.replace("*", "").strip()
            speak(description)
            
            img.close()
            os.remove(filename)
    except Exception as e:
        speak("I encountered an error reading your screen.")

#_______________TYPE TEXT_____________

def type_text(prompt):
    speak("Generating text and preparing to type. You have 3 seconds to click on the text field.")
    try:
        # Gemini দিয়ে কন্টেন্ট জেনারেট করা
        full_prompt = f"Write a professional and concise response for: {prompt}. Provide only the text content."
        response = model.generate_content(full_prompt)
        text_to_type = response.text.replace("*", "").strip()

        # ইউজারকে ক্লিক করার সময় দেওয়া
        time.sleep(3) 

        # অটোমেটিক টাইপ করা
        keyboard.write(text_to_type)
        speak("Text typing completed, sir.")
    except Exception as e:
        print(f"Typing Error: {e}")
        speak("I encountered an error while trying to type.")

# ---------------- AUTOMATION ----------------

def automation(query):
    try:
        if "open" in query:
            app = query.replace("open", "").strip()
            speak(f"Opening {app}")
            
            try:
                # প্রথমে পিসিতে অ্যাপটা খোঁজা হবে
                app_open(app, match_closest=True, throw_error=True)
            except:
                # পিসিতে না থাকলে সরাসরি ওয়েবে সার্চ করবে
                speak(f"{app} not found on your system. Searching on web.")
                
                pywhatkit.search(app)

        elif "play" in query:
            song = query.replace("play", "").strip()
            speak(f"Playing {song} on YouTube")
            pywhatkit.playonyt(song)
        # youtube_controller
        elif any(word in query for word in ["pause", "stop", "resume"]):
            keyboard.press("space")
            speak("Done sir")
        elif "full screen" in query:
            keyboard.press("f")
        elif "mute" in query:
            keyboard.press("m")

        elif "battery" in query:
            battery = psutil.sensors_battery()
            speak(f"System is at {battery.percent} percent.")

        elif "brightness" in query:
           
            current = sbc.get_brightness()[0]
            new = min(100, current + 20) if "up" in query else max(0, current - 20)
            sbc.set_brightness(new)
            speak(f"Brightness set to {new} percent")

        elif "volume" in query:
            
            if "up" in query:
                pyautogui.press("volumeup", presses=5)
            else:
                pyautogui.press("volumedown", presses=5)
            speak("Volume adjusted")

    except Exception as e:
        print(f"Automation Error: {e}")


# ---------------- COMMAND HANDLER ----------------
def handle_command(query):
    try:
        # generate_code
        if "write code" in query:
            code_prompt = query.replace("write code", "").strip()
            generate_code(code_prompt)
        
        # type_text
        elif "type" in query:
            type_prompt = query.replace("type", "").strip()
            type_text(type_prompt)
            
        # analyze_screen
        elif "what is on my screen" in query:
            analyze_screen()
            
        # automation (ব্রাউজার ওপেন, সিস্টেম কন্ট্রোল, ভলিউম, মিউট সব এখানে)
        elif any(word in query for word in ["open", "close", "play", "battery", "brightness", "screenshot", "lock", "volume", "pause", "resume", "mute"]):
            automation(query)
            
        # google_search
        elif "google search" in query:
            search_query = query.replace("google search", "").strip()
            speak(f"Searching Google for {search_query}")
            pywhatkit.search(search_query)
            
        # ai_chat (বাকি সব প্রশ্নের উত্তর Gemini দেবে)
        else:
            response = model.generate_content(f"Respond as Jarvis: {query}")
            clean_text = response.text.replace("*", "").strip()
            speak(clean_text)
            
    except Exception as e:
        print(f"Command Handler Error: {e}")
        speak("I'm sorry sir, I couldn't process that request.")

# ---------------- WAKE WORD & MAIN -------------

def wake_word_listener():
    speak("Jarvis system online.")
    while True:
        query = take_command()
        if "jarvis" in query:
            command = query.replace("jarvis", "").strip()
            
            if "go to sleep" in command or "exit" in command:
                speak("Goodbye sir, have a productive day.")
                os._exit(0)
                
            if not command:
                speak("Yes sir")
                command = take_command()
                
            if command != "none":
                handle_command(command)

# JarvisUI
class JarvisUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JARVIS V2.1")
        self.setFixedSize(400, 200)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("""
            background-color: #0a0a0a; 
            color: #00ffff; 
            border: 2px solid #00ffff;
            font-family: 'Segoe UI', sans-serif;
        """)
        self.label = QLabel("SYSTEM ACTIVE", self)
        self.label.setGeometry(0, 80, 400, 40)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("font-size: 20px; font-weight: bold; border: none;")

# Main
if __name__ == "__main__":
    
    threading.Thread(target=wake_word_listener, daemon=True).start()
    
    app = QApplication(sys.argv)
    window = JarvisUI()
    window.show()
    sys.exit(app.exec())