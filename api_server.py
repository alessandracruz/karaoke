import threading
import json
import logging
from flask import Flask, jsonify, request, send_from_directory
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
        
        # Static media serving
        # Assuming we run from 'E:\karaoke\karaoke', songs are in 'songs/'
        self.SONGS_DIR = os.path.join(os.getcwd(), 'songs')
        self.app.add_url_rule('/media/<path:filename>', 'serve_media', self.serve_media, methods=['GET'])

    def serve_media(self, filename):
        """Serves files from the songs directory."""
        return send_from_directory(self.SONGS_DIR, filename)

    def _generate_urls(self, song_data):
        """Generates full URLs for song assets."""
        host = request.host_url.rstrip('/')
        
        # Helper to convert absolute path to relative 'songs/...' path for URL
        def to_url_path(abs_path):
            if not abs_path: return None
            # Normalize paths
            norm_abs = os.path.normpath(os.path.abspath(abs_path))
            norm_root = os.path.normpath(self.SONGS_DIR)
            
            is_match = False
            if os.name == 'nt':
                # Windows is case-insensitive
                if norm_abs.lower().startswith(norm_root.lower()):
                    is_match = True
            else:
                if norm_abs.startswith(norm_root):
                    is_match = True
            
            if is_match:
                # Calculate relative path safely
                # os.path.relpath handles '..' if outside, but we checked startswith
                # simpler: slice if we are sure, but relpath is safer
                rel = os.path.relpath(norm_abs, norm_root)
                return f"{host}/media/{rel.replace(os.path.sep, '/')}"
            return None

        # Resolve paths
        # path -> normally instrumental or audio root
        # We need specific files: instrumental.mp3, original.mp3, lyrics_v1.json, lyrics.lrc
        
        # Try to deduce folder from known path
        base_folder = None
        if song_data.get('path'):
            if os.path.isfile(song_data['path']):
                base_folder = os.path.dirname(song_data['path'])
            else:
                base_folder = song_data['path']
        
        if not base_folder: return song_data

        song_data['url_instrumental'] = to_url_path(os.path.join(base_folder, 'instrumental.mp3'))
        song_data['url_original'] = to_url_path(os.path.join(base_folder, 'original.mp3'))
        
        # Lyrics V1 JSON
        json_path = song_data.get('lyrics_file')
        if not json_path: json_path = os.path.join(base_folder, 'lyrics_v1.json')
        song_data['url_lyrics_json'] = to_url_path(json_path)

        # LRC
        lrc_path = os.path.join(base_folder, 'lyrics.lrc') # Standard naming?
        # Check if exists? For URL gen, maybe just gen it.
        # But let's check existence to be nice if possible, or just generate.
        # Checking existence is slow for list. Let's just generate standard paths.
        song_data['url_lyrics_lrc'] = to_url_path(lrc_path)
        
        return song_data

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
            # Enrich with URLs (might be slow for many songs? - optimizing: do minimal path calc)
            # For get_all_songs, 'path' might not be fully populated in the dict returned by library?
            # Library.get_all_songs returns {id, code, title, artist}. NO PATH.
            # We need to fetch details or update library.get_all_songs to include path?
            # Or just return basic info here. User asked for URLs in library too.
            # We'll need to fetch path.
            
            enrich_songs = []
            for s in songs:
                 # We need path to generate URLs.
                 # Optimization: library should provide relative path or folder code.
                 # Assuming songs are stored as 'songs/<id>/'
                 # We can construct path manually if we trust the structure.
                 s_id = s['id']
                 # Reconstruct standard path: songs/{id}
                 # CAUTION: ID logic differs. db ID vs folder name.
                 # Previously: defined as str(row['id'])
                 
                 # Let's peek at library logic or just instantiate path.
                 # Easiest: call library.get_song for full details? Too slow for loop.
                 # Best check: modify get_all_songs to return path?
                 # Hack for now: assume standard 'songs/<id>' structure if standard.
                 
                 # Better: Use the 'code' or 'id' to guess.
                 # Actually, get_song checks 'songs/str(id)'.
                 
                 folder = os.path.join(self.SONGS_DIR, str(s_id))
                 s['path'] = folder # Fake path for generator
                 enrich_songs.append(self._generate_urls(s))

            return jsonify({'count': len(enrich_songs), 'songs': enrich_songs})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    def get_song(self, song_id):
        """Returns details for a specific song."""
        try:
            song = self.player.library.get_song(song_id)
            if not song:
                return jsonify({'error': 'Song not found'}), 404
            
            song_data = {
                'id': song.get('id', song_id),
                'title': song.get('title', "Unknown"),
                'artist': song.get('artist', "Unknown"),
                'path': song.get('path', ""),
                'lyrics_file': song.get('lyrics_file', None),
                'audio_file': song.get('audio_file', None),
            }
            song_data = self._generate_urls(song_data)
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
                    # Resume if paused
                    if hasattr(self.player, 'toggle_pause'):
                        self.player.toggle_pause()
                    else:
                        self.player.paused = False
            
            elif action == 'pause':
                 if hasattr(self.player, 'paused') and not self.player.paused:
                    # Pause if playing
                    if hasattr(self.player, 'toggle_pause'):
                        self.player.toggle_pause()
                    else:
                        self.player.paused = True

            elif action == 'toggle_pause':
                 if hasattr(self.player, 'toggle_pause'):
                     self.player.toggle_pause()
            
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
