import threading
import json
import logging
from flask import Flask, jsonify, request
from flask_cors import CORS
import os

# Configure Flask logging to be less verbose
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

class KaraokeAPI:
    def __init__(self, player_instance, port=5000):
        self.player = player_instance
        self.port = port
        self.app = Flask(__name__)
        CORS(self.app)  # Enable CORS for all routes
        self.thread = None
        self.running = False

        # Register Routes
        self.app.add_url_rule('/api/library', 'get_library', self.get_library, methods=['GET'])
        self.app.add_url_rule('/api/song/<int:song_id>', 'get_song', self.get_song, methods=['GET'])
        self.app.add_url_rule('/api/queue', 'get_queue', self.get_queue, methods=['GET'])
        self.app.add_url_rule('/api/queue/add', 'add_to_queue', self.add_to_queue, methods=['POST'])
        self.app.add_url_rule('/api/player/<action>', 'player_control', self.player_control, methods=['POST'])
        self.app.add_url_rule('/api/song/<int:song_id>/lyrics', 'get_lyrics', self.get_lyrics, methods=['GET'])

    def start(self):
        """Starts the Flask server in a separate daemon thread."""
        if self.thread is None:
            self.running = True
            self.thread = threading.Thread(target=self._run_server, daemon=True)
            self.thread.start()
            print(f"API Server started on port {self.port}")

    def _run_server(self):
        # Run Flask without the reloader to avoid main thread issues in Pygame
        try:
            self.app.run(host='0.0.0.0', port=self.port, debug=False, use_reloader=False)
        except Exception as e:
            print(f"API Server failed to start: {e}")

    # --- Endpoints ---

    def get_library(self):
        """Returns the list of songs in the library."""
        try:
            songs = self.player.library.get_all_songs()
            return jsonify({'count': len(songs), 'songs': songs})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    def get_song(self, song_id):
        """Returns details for a specific song."""
        try:
            song = self.player.library.get_song(song_id)
            if not song:
                return jsonify({'error': 'Song not found'}), 404
            
            song_data = {
                'id': getattr(song, 'id', song_id),
                'title': getattr(song, 'title', "Unknown"),
                'artist': getattr(song, 'artist', "Unknown"),
                'path': getattr(song, 'path', ""),
                'lyrics_file': getattr(song, 'lyrics_file', None),
                'audio_file': getattr(song, 'audio_file', None),
            }
            return jsonify(song_data)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    def get_queue(self):
        """Returns current playback state and queue."""
        try:
            current = None
            if self.player.current_song:
                s = self.player.current_song
                current = {
                    'id': getattr(s, 'id', None),
                    'title': getattr(s, 'title', "Unknown"),
                    'artist': getattr(s, 'artist', "Unknown")
                }

            # Serialize Queue
            queue_data = []
            for item in self.player.queue:
                # Item is likely a song code (string)
                queue_data.append({
                    'id': item, # Code
                    'title': f"Song {item}", # Placeholder or fetch if needed
                    'artist': ""
                })
            
            status = "playing"
            if hasattr(self.player, 'paused') and self.player.paused:
                status = "paused"
            if not self.player.current_song and not self.player.queue and status != "paused":
                 # If paused, it might still have a current song. 
                 # If no current song, it's idle.
                 if not self.player.current_song:
                    status = "idle"

            return jsonify({
                'status': status,
                'current_song': current,
                'queue': queue_data,
                'volume': self.player.volume if hasattr(self.player, 'volume') else 1.0
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    def add_to_queue(self):
        """Adds a song to the queue."""
        try:
            data = request.json
            if not data or 'id' not in data:
                return jsonify({'error': 'Missing song ID'}), 400
            
            song_id = data['id']
            # library.get_song might expect integer or string depending on implementation
            # Adjusting to int if it's digit
            try:
                song_id = int(song_id)
            except:
                pass

            song = self.player.library.get_song(song_id)
            
            if not song:
                return jsonify({'error': 'Song not found in library'}), 404
            
            # Appending CODE to queue because player expects strings/codes
            self.player.queue.append(str(song['code']))
            print(f"API: Added song {song['code']} to queue")
            
            return jsonify({'success': True, 'message': f"Added {song['title']} to queue"})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    def player_control(self, action):
        """Controls the player (play, pause, next, stop, etc)."""
        try:
            if action == 'play':
                if hasattr(self.player, 'paused') and self.player.paused:
                    self.player.paused = False
                    # Update start time for proper syncing might be needed in player loop
            
            elif action == 'pause':
                if hasattr(self.player, 'paused'):
                    self.player.paused = True
            
            elif action == 'next':
                self.player.skip_requested = True 

            elif action == 'stop':
                self.player.queue = []
                self.player.skip_requested = True
                # self.player.current_song = None # UNSAFE in thread, let player loop handle it
                import pygame
                pygame.mixer.music.stop()
            
            elif action == 'restart':
                self.player.restart_requested = True
            
            elif action == 'vol_up':
                if hasattr(self.player, 'volume'):
                    self.player.volume = min(1.0, self.player.volume + 0.1)
            
            elif action == 'vol_down':
                 if hasattr(self.player, 'volume'):
                    self.player.volume = max(0.0, self.player.volume - 0.1)

            return jsonify({'success': True, 'action': action})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    def get_lyrics(self, song_id):
        """Returns the lyrics for a song (V1 or V2)."""
        try:
            song = self.player.library.get_song(song_id)
            if not song:
                return jsonify({'error': 'Song not found'}), 404
            
            lyrics_data = None
            
            # Locate lyrics file
            # Logic: Look for lyrics_v1.json or similar in song's directory
            # Assuming song.path is the audio file or directory
            
            target_path = getattr(song, 'lyrics_file', None)
            
            if not target_path or not os.path.exists(target_path):
                 # Try to infer if not explicitly set
                 if hasattr(song, 'path'):
                     # stored path usually audio file? e.g. songs/17/vocals.wav
                     folder = os.path.dirname(song.path)
                     possible = os.path.join(folder, "lyrics_v1.json")
                     if os.path.exists(possible):
                         target_path = possible
            
            if target_path and os.path.exists(target_path):
                 with open(target_path, 'r', encoding='utf-8') as f:
                     lyrics_data = json.load(f)
            
            if lyrics_data:
                return jsonify(lyrics_data)
            else:
                 # Return empty structure or error? Contract says return lyrics.
                 # Let's return error 404 if really no lyrics.
                return jsonify({'error': 'Lyrics file not found'}), 404

        except Exception as e:
            return jsonify({'error': str(e)}), 500
