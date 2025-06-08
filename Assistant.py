import speech_recognition as sr
import pywhatkit as kit
from dotenv import load_dotenv
import os
import webbrowser
import winsound
import datetime
import time
import pygame
import io
import re
import random
import requests
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from comtypes import CLSCTX_ALL
import pvporcupine
import pyaudio
import numpy as np
from pydub import AudioSegment
import threading
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import json


API_USAGE_FILE = "api_usage.json"

# Load environment variables
load_dotenv()
API_KEY = os.getenv('GEMINI_API_KEY')
WEATHER_API_KEY = os.getenv('WEATHER_API_KEY')
#LEOPARD_ACCESS_KEY = os.getenv('LEOPARD_ACCESS_KEY')

VOICE_KEYS = [
    os.getenv('VOICE_API_KEY_1'),
    os.getenv('VOICE_API_KEY_2'),
    os.getenv('VOICE_API_KEY_3')
]

SPOTIFY_SCOPE = "user-library-read user-modify-playback-state user-read-playback-state"
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=os.getenv('SPOTIFY_CLIENT_ID'),
    client_secret=os.getenv('SPOTIFY_CLIENT_SECRET'),
    redirect_uri=os.getenv('SPOTIFY_REDIRECT_URI'),
    scope=SPOTIFY_SCOPE
))

# Global variables
usage_tracker = {key: 0 for key in VOICE_KEYS}
current_key_index = 0
pygame.mixer.init()
driver = None
conversation_history = []
reminders = []
reminder_thread_running = False
api_usage_stats = {"voice_api": 0, "gemini_api": 0}
playback_history = []

# Helper Functions

def play_audio(audio_stream):
    pygame.mixer.music.load(audio_stream, "mp3")
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)

def load_api_usage():
    if os.path.exists(API_USAGE_FILE):
        with open(API_USAGE_FILE, "r") as file:
            data = json.load(file)
            return data.get("api_usage", {"voice_api": 0, "gemini_api": 0}), data.get("current_key_index", 0)
    return {"voice_api": 0, "gemini_api": 0}, 0 

def save_api_usage():
    with open(API_USAGE_FILE, "w") as file:
        json.dump({"api_usage": api_usage_stats, "current_key_index": current_key_index}, file)

api_usage_stats, current_key_index = load_api_usage()

def log_api_usage(api_name, duration=0):
    global api_usage_stats 
    if api_name in api_usage_stats:
        api_usage_stats[api_name] += duration
        save_api_usage()  

def show_api_usage():
    stats_text = "API Usage Stats:\n"
    for api, usage in api_usage_stats.items():
        stats_text += f"{api}: {usage:.2f} seconds\n"
    print(stats_text) 
    with open("api_usage.log", "w") as log_file:
        log_file.write(stats_text)

def switch_api_key():
    global current_key_index
    current_key_index = (current_key_index + 1) % len(VOICE_KEYS)
    save_api_usage()
    return VOICE_KEYS[current_key_index]

def reset_conversation():
    global conversation_history
    conversation_history = []
    say("Conversation history reset.")

def add_reminder(reminder_text, delay_minutes):
    global reminders
    trigger_time = time.time() + delay_minutes * 60
    reminders.append((reminder_text, trigger_time))
    say(f"Reminder set for {delay_minutes} minutes from now.")

def play_alarm_sound():
    for _ in range(3):
        winsound.Beep(1000, 700) 
        time.sleep(0.3)

def check_reminders():
    global reminders
    reminder_thread_running = True
    while reminder_thread_running:
        current_time = time.time()
        for reminder in reminders[:]:
            reminder_text, trigger_time = reminder
            if current_time >= trigger_time:
                play_alarm_sound()
                say(f"Reminder: {reminder_text}")  
                reminders.remove(reminder)  
        time.sleep(1)

def get_weather():
    try:
        city_name = "Pune" 
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city_name}&appid={WEATHER_API_KEY}&units=metric"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            weather = data['weather'][0]['description']
            temperature = data['main']['temp']
            return f"The weather in Pune is {weather} with a temperature of {temperature}°C."
        else:
            return f"Error fetching weather: {response.status_code}"
    except Exception as e:
        return f"Error: {str(e)}"

# Core Functions
def say(text, voice_id="Xb7hH8MSUJpSbSDYk0k2"):
    global usage_tracker, current_key_index
    try:
        current_key = VOICE_KEYS[current_key_index]
        headers = {"xi-api-key": current_key, "Content-Type": "application/json"}
        payload = {"text": text, "voice_settings": {"stability": 0.5, "clarity": 0.5, "similarity_boost": 0.75}}
        API_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
        response = requests.post(API_URL, headers=headers, json=payload, stream=True)
        if response.status_code == 200:
            audio = AudioSegment.from_mp3(io.BytesIO(response.content))
            audio_duration = len(audio) / 1000
            log_api_usage("voice_api", audio_duration)
            usage_tracker[current_key] += audio_duration
            if usage_tracker[current_key] >= 600:
                print(f"API key {current_key} has reached the 10-minute limit.")
                switch_api_key()
                print(f"Switched to API key: {VOICE_KEYS[current_key_index]}")
            audio_stream = io.BytesIO(response.content)
            audio_thread = threading.Thread(target=play_audio, args=(audio_stream,))
            audio_thread.start()
        else:
            print(f"Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Error in generating speech: {e}")

def get_gemini_response(transcript):
    global conversation_history
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
        headers = {"Content-Type": "application/json"}
        conversation_history.append({"role": "user", "parts": [{"text": transcript}]})
        payload = {"contents": conversation_history}
        params = {"key": API_KEY}
        response = requests.post(url, json=payload, headers=headers, params=params)
        log_api_usage("gemini_api")
        if response.status_code == 200:
            data = response.json()
            if 'candidates' in data and len(data['candidates']) > 0:
                parts = data['candidates'][0].get('content', {}).get('parts', [])
                if len(parts) > 0:
                    response_text = parts[0].get("text", "No content found")
                    conversation_history.append({"role": "model", "parts": [{"text": response_text}]})
                    return response_text
            return "No candidates found in response."
        else:
            return f"Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Error occurred: {str(e)}"

#leopard = pvleopard.create(access_key=LEOPARD_ACCESS_KEY)

def takeCommand():
    r = sr.Recognizer()
    r.pause_threshold = 1.0 
    with sr.Microphone() as source:
        print("Adjusting for ambient noise...")
        r.adjust_for_ambient_noise(source, duration=0.5) 
        print("Listening for command...")
        try:
            audio = r.listen(source, timeout=8, phrase_time_limit=12)
            print("Recognizing...")
            transcript = r.recognize_google(audio, language="en-in")
            print(f"User said: {transcript}")
            return transcript
        except sr.WaitTimeoutError:
            return None  
        except Exception as e:
            print(f"Error in recognizing speech: {e}")
            return None

def set_system_volume(volume_percentage):
    volume_level = volume_percentage / 100.0
    volume_level = max(0.0, min(1.0, volume_level))
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = interface.QueryInterface(IAudioEndpointVolume)
    volume.SetMasterVolumeLevelScalar(volume_level, None)
    print(f"System volume set to {volume_percentage}%")

def process_volume_command(transcript):
    transcript = transcript.lower()
    if any(cmd in transcript for cmd in ["set volume to", "volume to", "volume"]):
        number_words = {
            "zero": 0, "ten": 10, "twenty": 20, "thirty": 30,
            "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
            "eighty": 80, "ninety": 90, "hundred": 100
        }
        match = re.search(r'(\d{1,3})%?', transcript)
        if match:
            volume_percentage = int(match.group(1))
        else:
            for word, num in number_words.items():
                if word in transcript:
                    volume_percentage = num
                    break
            else:
                volume_percentage = None

        if volume_percentage is not None and 0 <= volume_percentage <= 100:
            set_system_volume(volume_percentage)
            return True

        say("Please specify a valid percentage")
        return False

    return False


def wakeUp():
    porcupine = pvporcupine.create(
        access_key=os.getenv('PORC_API_KEY'),
        keyword_paths=[r"C:\Users\mangr\OneDrive\Desktop\Assistant\Hey-Grace_en_windows_v3_0_0.ppn"]
    )
    p = pyaudio.PyAudio()
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        frames_per_buffer=512
    )
    print("Listening for wake word...")
    while True:
        try:
            audio_data = stream.read(512)
            audio_data = np.frombuffer(audio_data, dtype=np.int16)
            result = porcupine.process(audio_data)
            if result >= 0:
                say("uh huh...")
                print("Wake word detected!")
                return True
            time.sleep(0.01) 
        except Exception as e:
            print(f"Error: {e}")
            continue

def selenium_play_pause():
    try:
        script = """
        var video = document.querySelector('video');
        if(video){
            if(video.paused) {
                video.play();
            } else {
                video.pause();
            }
            return video.paused;
        }
        return null;
        """
        paused_state = driver.execute_script(script)
        print("Toggled play/pause on YouTube. Now paused:", paused_state)
    except Exception as e:
        print("Error toggling play/pause:", e)

def selenium_next_video():
    try:
        next_button = driver.find_element(By.CSS_SELECTOR, 'a.ytp-next-button')
        next_button.click()
        print("Clicked the next button.")
    except Exception as e:
        print("Error clicking next button:", e)

def initialize_driver():
    global driver
    if driver is not None:
        try:
            driver.title 
            return
        except:
            pass  
    chrome_options = uc.ChromeOptions()
    chrome_options.binary_location = r"C:\Users\mangr\AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe"
    #chrome_options.add_argument("--load-extension=C:\\Users\\LEGION\\OneDrive\\Desktop\\Python Shit\\A.I Assistant\\uBlock")
    #chrome_options.add_argument("--disable-extensions-except=C:\\Users\\LEGION\\OneDrive\\Desktop\\Python Shit\\A.I Assistant\\uBlock")
    #chrome_options.add_argument("--disable-features=PreloadMediaEngagementData,MediaEngagementBypassAutoplayPolicies")
   #chrome_options.add_argument("--window-size=1200,800")
    driver = uc.Chrome(options=chrome_options)

def play_on_youtube(search_transcript):
    try:
        initialize_driver()  
        search_url = f"https://www.youtube.com/results?search_query={search_transcript.replace(' ', '+')}"
        driver.get(search_url)
        wait = WebDriverWait(driver, 10)  
        first_video = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "a#video-title")))
        first_video.click()
        print(f"Playing: {search_transcript}")
    except Exception as e:
        print("Error playing video:", e)

def play_track_on_spotify(track_name, artist_name=""):
    try:
        search_transcript = f"track:{track_name}"
        if artist_name:
            search_transcript += f" artist:{artist_name}"
        results = sp.search(q=search_transcript, type='track', limit=5)
        items = results.get('tracks', {}).get('items', [])
        if not items:
            say(f"I couldn't find {track_name} on Spotify.")
            return False
        best_match = next((track for track in items if track['name'].lower() == track_name.lower()), items[0])
        track_uri = best_match['uri']
        track_id = best_match['id']  
        artist_id = best_match['artists'][0]['id']
        artist_name = best_match['artists'][0]['name']
        devices_info = sp.devices()
        devices = devices_info.get('devices', [])
        if not devices:
            say("No active Spotify.")
            return False
        device_id = devices[0]['id']
        sp.start_playback(device_id=device_id, uris=[track_uri])
        say(f"Playing {best_match['name']} by {artist_name} on Spotify.")
        time.sleep(5)
        seed_tracks = [track_id] if track_id else []
        seed_artists = [artist_id] if artist_id else []
        try:
            available_genres = sp.recommendation_genre_seeds()["genres"]
        except Exception as e:
            available_genres = ["pop"] 
        seed_genres = [random.choice(available_genres)] if available_genres else ["pop"]
        recommended_uris = []
        for attempt in range(2):  
            try:
                recommendations = sp.recommendations(
                    seed_tracks=seed_tracks if seed_tracks else None,
                    seed_artists=seed_artists if seed_artists else None,
                    seed_genres=seed_genres,
                    limit=20
                )
                recommended_uris = [track["uri"] for track in recommendations["tracks"]]
                if recommended_uris:
                    break  
            except spotipy.exceptions.SpotifyException as e:
                time.sleep(2)
        if recommended_uris:
            for track_uri in recommended_uris:
                sp.add_to_queue(track_uri, device_id=device_id)
        return True
    except Exception as e:
        print(f"Spotify playback error: {e}")
        return False

def play_spotify_liked_songs():
    try:
        results = sp.current_user_saved_tracks(limit=50)
        track_uris = [item['track']['uri'] for item in results['items']]
        sp.start_playback(uris=track_uris)
        print("Playing liked songs on Spotify")
        return True
    except Exception as e:
        print(f"Error playing liked songs: {e}")
        return False

def next_track_spotify():
    try:
        devices_info = sp.devices()
        devices = devices_info.get('devices', [])
        if not devices:
            print("No active device found.")
            say("No active Spotify.")
            return False
        device_id = devices[0]['id'] 
        sp.next_track(device_id=device_id)
        print("Skipped to next track on Spotify.")
        return True
    except Exception as e:
        print(f"Error skipping track: {e}")
        say("error.")
        return False
    
playback_history = []

def previous_track_spotify():
    try:
        devices_info = sp.devices()
        devices = devices_info.get('devices', [])
        if not devices:
            say("No active Spotify.")
            return False
        device_id = devices[0]['id']
        sp.previous_track(device_id=device_id)
        say("Playing the previous track on Spotify.")
        return True
    except Exception as e:
        say("Couldn't go back.")
        return False

def play_pause_spotify():
    try:
        current_playback = sp.current_playback()
        if current_playback:
            if current_playback["is_playing"]:
                sp.pause_playback()
            else:
                sp.start_playback()
            return True
        else:
            say("No active Spotify.")
            return False
    except Exception as e:
        say("Make sure Spotify is active.")
        return False
    
def play_spotify_saved_playlist(playlist_name=None, shuffle=False):
    try:
        devices_info = sp.devices()
        devices = devices_info.get('devices', [])
        if not devices:
            say("No active Spotify.")
            return False
        device_id = devices[0]['id']
        if playlist_name and "liked" in playlist_name.lower():
            results = sp.current_user_saved_tracks(limit=50)
            track_uris = [item['track']['uri'] for item in results['items']]
            if not track_uris:
                say("Your liked songs list is empty.")
                return False
            if shuffle:
                random.shuffle(track_uris)
            sp.shuffle(shuffle, device_id=device_id)
            sp.start_playback(device_id=device_id, uris=track_uris)
            say(f"Playing your liked songs {'on shuffle' if shuffle else ''}.")
            return True
        playlists = sp.current_user_playlists(limit=50)['items']
        matching_playlist = next((p for p in playlists if p['name'].lower() == playlist_name.lower()), None)
        if not matching_playlist:
            say(f"I couldn't find a playlist named {playlist_name}.")
            return False
        playlist_uri = matching_playlist['uri']
        sp.shuffle(shuffle, device_id=device_id)
        sp.start_playback(device_id=device_id, context_uri=playlist_uri)
        say(f"Playing your playlist {playlist_name} {'on shuffle' if shuffle else ''}.")
        return True
    except Exception as e:
        print(f"Error playing playlist: {e}")
        return False
    
def play_song(transcript):
    song_transcript = transcript.lower().replace("play", "").strip()
    if "on youtube" in transcript.lower():
        song_transcript = song_transcript.replace("on youtube", "").strip()
        say(f"Playing {song_transcript} on YouTube.")
        play_on_youtube(song_transcript)
    elif "on spotify" in transcript.lower():
        song_transcript = song_transcript.replace("on spotify", "").strip()
        say(f"Playing {song_transcript} on Spotify.")
        play_track_on_spotify(song_transcript)
    else:
        say("Where do you want to play it? YouTube or Spotify?")
        response = takeCommand()
        if response:
            response = response.lower()
            if "youtube" in response:
                say(f"Playing {song_transcript} on YouTube.")
                play_on_youtube(song_transcript)
            elif "spotify" in response:
                say(f"Playing {song_transcript} on Spotify.")
                play_track_on_spotify(song_transcript)
            else:
                say("I didn't get that. Please say YouTube or Spotify.")
        else:
            say("I didn't hear your response. Please try again.")


if __name__ == '__main__':
    reminder_thread = threading.Thread(target=check_reminders, daemon=True)
    reminder_thread.start()
    #say("Grace here, what's up?")
    while True:
        if wakeUp():
            start_time = time.time()
            while True:
                transcript = takeCommand()
                
                if transcript:
                    sites = [
                        ["youtube on chrome", "https://www.youtube.com"],
                        ["wikipedia", "https://www.wikipedia.com"],
                        ["google", "https://www.google.com"]
                    ]
                    found_site = False
                    for site in sites:
                        if f"open {site[0]}".lower() in transcript.lower():
                            say(f"Opening {site[0]}")
                            webbrowser.open(site[1])
                            found_site = True
                            break
                    if found_site:
                        break

                    if "open my books" in transcript.lower():
                        say("Ok")
                        os.system(r'"C:\Users\LEGION\Downloads\Books"')
                        break

                    if "remind me" in transcript.lower():
                        match = re.search(r'remind me in (\d+)\s*(?:minutes?|mins?|m)?(?: about (.+))?', transcript.lower())
                        if match:
                            delay_minutes = int(match.group(1))  # Extract minutes
                            reminder_text = match.group(2) if match.group(2) else "your reminder"  # Extract text if available
                            add_reminder(reminder_text, delay_minutes) 
                        else:
                            say("Please specify a valid time.")
                        break

                    elif "the time" in transcript.lower():
                        now = datetime.datetime.now()
                        hour, minute = now.strftime("%H"), now.strftime("%M")
                        say(f"The time is {hour} and {minute} minutes")
                        break

                    elif "open youtube music" in transcript.lower():
                        say("Opening YouTube Music")
                        os.system(r'"C:\Users\LEGION\AppData\Local\Google\Chrome\Application\chrome_proxy.exe" --profile-directory=Default --app-id=cinhimbnkkaeohfgghhklpknlkffjgod')
                        break

                    elif "play" in transcript.lower() and ("on youtube" in transcript.lower() or "youtube" in transcript.lower()):
                        music_transcript = transcript.lower().replace("play", "").replace("on youtube", "").replace("youtube", "").strip()
                        if music_transcript:
                            say(f"Playing {music_transcript} on YouTube.")
                            play_on_youtube(music_transcript)
                        else:
                            say("Please specify what to play.")
                        break

                    elif process_volume_command(transcript):
                        say("Ok.")
                        break

                    elif "pause youtube" in transcript.lower() or "resume youtube" in transcript.lower():
                        say("Done.")
                        selenium_play_pause()
                        break

                    elif "play" in transcript.lower() and "on spotify" in transcript.lower():
                        track_or_playlist_transcript = transcript.lower().replace("play", "").replace("on spotify", "").strip()
                        shuffle = "shuffle" in track_or_playlist_transcript  
                        track_or_playlist_transcript = track_or_playlist_transcript.replace("shuffle", "").strip()
                        user_playlists = sp.current_user_playlists(limit=50)['items']
                        saved_playlist_names = {p['name'].lower(): p['uri'] for p in user_playlists}
                        if "my liked songs" in track_or_playlist_transcript:
                            if play_spotify_saved_playlist("liked songs", shuffle):
                                say("Playing your liked songs on shuffle." if shuffle else "Playing your liked songs.")
                            else:
                                print("Couldn't play your liked songs.")
                        elif track_or_playlist_transcript in saved_playlist_names: 
                            playlist_uri = saved_playlist_names[track_or_playlist_transcript]
                            if play_spotify_saved_playlist(playlist_uri, shuffle):
                                say(f"Playing your playlist {track_or_playlist_transcript} on shuffle." if shuffle else f"Playing your playlist {track_or_playlist_transcript}.")
                            else:
                                print(f"Couldn't find your playlist {track_or_playlist_transcript}.")
                        else:  
                            if play_track_on_spotify(track_or_playlist_transcript):
                                print(f"Playing {track_or_playlist_transcript} on Spotify.")
                            else:
                                print(f"Couldn't find {track_or_playlist_transcript} on Spotify.")
                        break

                    elif "next song" in transcript.lower() or "skip" in transcript.lower():
                        try:
                            current_playback = sp.current_playback()

                            if current_playback: 
                                if next_track_spotify():
                                    say("next track on Spotify.")
                                    if not current_playback["is_playing"]:
                                        time.sleep(1) 
                                        try:
                                            sp.start_playback()
                                        except Exception as e:
                                            print(f"Error resuming playback: {e}")
                                            say("I skipped the track, but I couldn't resume playback.")
                                else:
                                    say("Couldn't skip track.")
                            else:
                                say("next YouTube video.")
                                selenium_next_video()
                        except Exception as e:
                            print(f"Error detecting playback state: {e}")
                            say("I couldn't determine where to skip. Try again.")
                        break

                    elif "previous track" in transcript.lower() or "repeat that song" in transcript.lower():
                        try:
                            current_playback = sp.current_playback()
                            devices_info = sp.devices()
                            devices = devices_info.get('devices', [])

                            if current_playback or devices:
                                if previous_track_spotify():
                                    say("Replaying the previous track.")
                                    time.sleep(1)  
                                    updated_playback = sp.current_playback()
                                    if updated_playback and not updated_playback["is_playing"]:
                                        try:
                                            sp.start_playback()
                                        except Exception as e:
                                            print(f"Error resuming playback: {e}")
                                            say("I couldn't resume the track, but it has been skipped back.")
                                else:
                                    say("Couldn't go back.")
                            else:
                                say("Spotify is not open.")
                        except Exception as e:
                            print(f"Error in repeat that song: {e}")
                            say("Something went wrong.")
                        break

                    elif "play" in transcript.lower():
                        play_song(transcript)
                        break

                    elif "pause spotify" in transcript.lower() or "play spotify" in transcript.lower() or "pause songs" in transcript.lower() or "resume songs" in transcript.lower():
                        if play_pause_spotify():
                            say("Done.")
                        else:
                            say("Couldn't toggle Spotify playback.")
                        break

                    elif "weather" in transcript.lower() or "weather now" in transcript.lower():
                        weather_info = get_weather() 
                        say(weather_info)
                        break

                    elif "api time" in transcript.lower():
                        show_api_usage()
                        break

                    elif "quit yourself" in transcript.lower():
                        say("Hope to see you again.")
                        driver.quit()
                        exit()

                    elif "reset chat" in transcript.lower():
                        say("Chat history reset.")
                        break

                    elif "nothing" in transcript.lower():
                        say("Ok, call if you need any help.")
                        break

                    elif any(trigger in transcript.lower() for trigger in ["search for", "ask ai", "tell me about"]):
                        for trigger in ["search for", "ask ai", "tell me about"]:
                            if trigger in transcript.lower():
                                search_transcript = transcript.lower().split(trigger, 1)[1].strip()
                                break
                        gemini_response = get_gemini_response(search_transcript)
                        print(gemini_response)
                        say(gemini_response)
                        break

                    else:
                     say("I didn't catch that, say Grace to wake me up.")
                     break  

                elif time.time() - start_time > 5:
                    say("I didn't catch that")
                    break

        else:
            continue
