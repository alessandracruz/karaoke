import pygame
import sys
import os
import re
import time
import random
import threading
import json
import sqlite3
import ctypes # Para DPI Awareness no Windows
from scorer import Scorer
from api_server import KaraokeAPI

# Constantes
WIDTH, HEIGHT = 1024, 768
FPS = 60
FONT_SIZE_LYRICS = 40
FONT_SIZE_INFO = 24
COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)
COLOR_HIGHLIGHT = (255, 215, 0)  # Dourado
COLOR_BG_OVERLAY = (0, 0, 0, 150) # Overlay escuro para legibilidade
COLOR_GREEN = (0, 255, 0)
COLOR_RED = (255, 0, 0)
COLOR_BLUE = (0, 100, 255)

class SongLibrary:
    """
    Gerencia a biblioteca de músicas usando SQLite.
    """
    def __init__(self, db_path="karaoke.db"):
        self.db_path = db_path
        self.conn = None
        self.connect()

    def connect(self):
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            print(f"Erro ao conectar ao banco: {e}")

    def get_song_by_code(self, code):
        """Busca música pelo código (apenas se disponível)."""
        if not self.conn: return None
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM musicas WHERE Cod = ? AND status = 'disponivel'", (code,))
            row = cursor.fetchone()
            if row:
                song_id = str(row['id'])
                base_path = os.path.join("songs", song_id)
                
                # Determina paths (prioridades)
                audio_path = os.path.join(base_path, "instrumental.mp3")
                orig_audio_path = os.path.join(base_path, "original.mp3")
                
                # Se não tiver instrumental, usa original como principal
                if not os.path.exists(audio_path) and os.path.exists(orig_audio_path):
                    audio_path = orig_audio_path
                
                return {
                    'id': song_id,
                    'title': row['Titulo'],
                    'artist': row['Cantor'],
                    'audio_path': audio_path,
                    'original_audio_path': orig_audio_path,
                    'base_path': base_path
                }
        except sqlite3.Error as e:
            print(f"Erro na busca: {e}")
        return None

    def get_song(self, song_id):
        """Busca música pelo ID."""
        if not self.conn: return None
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM musicas WHERE id = ?", (song_id,))
            row = cursor.fetchone()
            if row:
                song_id_str = str(row['id'])
                base_path = os.path.join("songs", song_id_str)
                audio_path = os.path.join(base_path, "instrumental.mp3")
                orig_audio_path = os.path.join(base_path, "original.mp3")
                
                # Verify specific file existence
                if not os.path.exists(audio_path) and os.path.exists(orig_audio_path):
                    audio_path = orig_audio_path
                
                return {
                    'id': row['id'],
                    'code': row['Cod'],
                    'title': row['Titulo'],
                    'artist': row['Cantor'],
                    'path': audio_path,
                    'lyrics_file': os.path.join(base_path, "lyrics_v1.json")
                }
        except Exception as e:
            print(f"Erro get_song: {e}")
        return None

    def get_all_songs(self):
        """Retorna todas as músicas disponíveis."""
        songs = []
        if not self.conn: return songs
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM musicas WHERE status = 'disponivel' ORDER BY Titulo")
            for row in cursor.fetchall():
                 songs.append({
                    'id': row['id'],
                    'code': row['Cod'],
                    'title': row['Titulo'],
                    'artist': row['Cantor']
                })
        except Exception as e:
            print(f"Erro get_all_songs: {e}")
        return songs

    def sync_availability(self):
        """Verifica quais músicas estão na pasta e atualiza o banco."""
        print("Iniciando sincronização da biblioteca...")
        if not self.conn: return "Erro DB"
        
        try:
            cursor = self.conn.cursor()
            
            # 1. Reseta tudo para ausente
            cursor.execute("UPDATE musicas SET status = 'ausente'")
            
            # 2. Scaneia pasta
            found_ids = []
            if os.path.exists("songs"):
                for item in os.listdir("songs"):
                    item_path = os.path.join("songs", item)
                    if os.path.isdir(item_path):
                        # Verifica se tem arquivos minimos
                        has_audio = (
                            os.path.exists(os.path.join(item_path, "instrumental.mp3")) or 
                            os.path.exists(os.path.join(item_path, "original.mp3"))
                        )
                        if has_audio:
                            if item.isdigit(): found_ids.append(item)
            
            # 3. Atualiza encontrados
            if found_ids:
                # SQLite não tem listas diretas, fazemos loop ou IN clause dinâmico
                # Para segurança e simplicidade, vamos de muitas queries (local é rápido) ou batch
                cursor.executemany("UPDATE musicas SET status = 'disponivel' WHERE id = ?", [(x,) for x in found_ids])
            
            self.conn.commit()
            count = cursor.execute("SELECT COUNT(*) FROM musicas WHERE status = 'disponivel'").fetchone()[0]
            print(f"Sincronização concluída. {count} músicas disponíveis.")
            return f"Concluído: {count} músicas."
            
        except sqlite3.Error as e:
            print(f"Erro ao sincronizar: {e}")
            return f"Erro: {e}"

class KaraokePlayer:
    """
    Classe principal do Player de Karaokê usando Pygame.
    Gerencia a interface, reprodução de áudio, letras e pontuação.
    """
    def __init__(self):
        # Configura DPI Awareness para Windows (evita borrões e coordenadas erradas em 4k)
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except AttributeError:
            pass # Não é Windows ou falhou

        pygame.init()
        # Inicializa mixer com configurações padrão explícitas para evitar conflitos com PyAudio
        # 44.1kHz, 16-bit signed, Stereo, Buffer 2048
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
        except pygame.error:
            print("Aviso: Falha ao inicializar mixer com config padrão. Tentando automático.")
            pygame.mixer.init()

        self.screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
        pygame.display.set_caption("Sistema de Karaokê Python")
        
        # Maximizar janela no Windows
        try:
            hwnd = pygame.display.get_wm_info()['window']
            ctypes.windll.user32.ShowWindow(hwnd, 3) # SW_MAXIMIZE = 3
        except Exception:
            pass
            
        self.clock = pygame.time.Clock()

        self.manager = SongLibrary()
        self.library = self.manager # Alias for API compatibility
        self.scorer = Scorer()
        
        # Iniciar API Server
        self.api = KaraokeAPI(self)
        self.api.start()
        
        # Fontes do Sistema
        self.init_fonts(1.0) # Inicializa com escala 1.0

        # Background Config
        self.cfg_bg_mode = "IMAGEM" # Opções: "IMAGEM", "GRADIENTE"
        self.bg_images = []
        self.load_bg_images()

        self.current_song = None
        self.lyrics = [] # Lista de (timestamp_ms, text)
        self.current_line_index = -1

        self.queue = []
        self.input_buffer = ""
        
        # New State Flags
        self.paused = False
        self.show_help = False

        self.state = "MENU" # MENU, PLAYING, SCORE, CONFIG
        self.background = None
        self.load_random_background()

        self.score_result = 0
        
        # --- Configurações de Estado ---
        # Padrões
        self.cfg_mic1_idx = None
        self.cfg_mic2_idx = None
        self.cfg_volume_mic1 = 1.0
        self.cfg_volume_mic2 = 1.0
        self.cfg_volume_music = 0.5
        self.cfg_monitoring = False
        self.cfg_latency_chunk = 2048 # Aumentado para 2048 para evitar crashes em monitoramento
        self.cfg_difficulty = "Fácil" # Fácil, Normal, Difícil
        self.show_rhythm_indicator = True # Config Visual
        
        # Audio Engine
        self.scorer = Scorer(chunk=self.cfg_latency_chunk)
        self.available_devices = self.scorer.get_input_devices()
        
        # Define device padrao se houver
        if self.available_devices:
            self.cfg_mic1_idx = self.available_devices[0]['index']
            
        self.apply_audio_config()
        self.scorer.start() # Inicia loop de audio (mudo se sem input)

    def init_fonts(self, scale=1.0):
        """Inicializa fontes com fator de escala base."""
        self.font_lyrics = pygame.font.Font(None, int(FONT_SIZE_LYRICS * scale))
        self.font_info = pygame.font.Font(None, int(FONT_SIZE_INFO * scale))
        self.font_small = pygame.font.Font(None, int(20 * scale))

    def draw_text_with_outline(self, text, font, color, center_pos, outline_color=(0,0,0), outline_width=2):
        """Desenha texto centralizado com borda (outline). Retorna Rect."""
        cx, cy = center_pos
        # Renderiza texto principal
        surf = font.render(text, True, color)
        rect = surf.get_rect(center=(cx, cy))
        
        # Desenha outline (8 direções simples)
        for dx in [-outline_width, 0, outline_width]:
             for dy in [-outline_width, 0, outline_width]:
                 if dx != 0 or dy != 0:
                     out_surf = font.render(text, True, outline_color)
                     out_rect = out_surf.get_rect(center=(cx + dx, cy + dy))
                     self.screen.blit(out_surf, out_rect)
        
        # Blit main text
        self.screen.blit(surf, rect)
        return rect

    def load_bg_images(self):
        """Carrega caminhos de imagens da pasta backgrounds."""
        self.bg_images = []
        if not os.path.exists("backgrounds"):
            os.makedirs("backgrounds")
            
        valid_ext = ['.jpg', '.jpeg', '.png', '.bmp']
        for f in os.listdir("backgrounds"):
            ext = os.path.splitext(f)[1].lower()
            if ext in valid_ext:
                self.bg_images.append(os.path.join("backgrounds", f))
        
        print(f"Backgrounds carregados: {len(self.bg_images)}")

    def generate_new_background(self):
        """Escolhe novo fundo (Cor ou Imagem)."""
        if self.cfg_bg_mode == "IMAGEM" and self.bg_images:
            # Modo Imagem
            img_path = random.choice(self.bg_images)
            try:
                self.current_bg_image = pygame.image.load(img_path)
                print(f"Background Imagem: {img_path}")
            except Exception as e:
                print(f"Erro ao carregar imagem {img_path}: {e}")
                self.current_bg_image = None
        else:
            self.current_bg_image = None
            
        # Sempre gera cores para fallback ou modo Gradiente
        themes = [
            # Ocean (Azul/Ciano)
            lambda: ((random.randint(0,50), random.randint(0,100), random.randint(100,200)),
                     (random.randint(0,30), random.randint(100,200), random.randint(200,255))),
            # Sunset (Laranja/Roxo)
            lambda: ((random.randint(150,255), random.randint(50,150), random.randint(0,50)),
                     (random.randint(50,100), random.randint(0,50), random.randint(100,200))),
            # Nature (Verde/Azul)
            lambda: ((random.randint(0,50), random.randint(100,200), random.randint(50,150)),
                     (random.randint(0,100), random.randint(50,100), random.randint(100,200))),
            # Neon (Pink/Roxo)
            lambda: ((random.randint(200,255), random.randint(0,100), random.randint(200,255)),
                     (random.randint(50,150), random.randint(0,50), random.randint(150,250))),
            # Dark Red (Vermelho/Preto)
            lambda: ((random.randint(100,200), random.randint(0,50), random.randint(0,50)),
                     (random.randint(50,100), random.randint(0,30), random.randint(0,30))),
            # Random Vivid
            lambda: ((random.randint(50,200), random.randint(50,200), random.randint(50,200)),
                     (random.randint(50,200), random.randint(50,200), random.randint(50,200)))
        ]
        
        generator = random.choice(themes)
        self.bg_c1, self.bg_c2 = generator()
        
        self.render_background()

    def render_background(self):
        """Renderiza o fundo usando as cores atuais na resolução atual."""
        w, h = self.screen.get_width(), self.screen.get_height()
        
        if self.cfg_bg_mode == "IMAGEM" and hasattr(self, 'current_bg_image') and self.current_bg_image:
             # Scale Image to Cover
             try:
                 # Smoothscale é pesado, então fazemos apenas quando necessário (resize/init)
                 # Calculando aspecto para "Cover"
                 img_w, img_h = self.current_bg_image.get_size()
                 scale_w = w / img_w
                 scale_h = h / img_h
                 scale = max(scale_w, scale_h)
                 
                 new_size = (int(img_w * scale), int(img_h * scale))
                 scaled_img = pygame.transform.smoothscale(self.current_bg_image, new_size)
                 
                 # Centraliza crop
                 x = (w - new_size[0]) // 2
                 y = (h - new_size[1]) // 2
                 
                 self.background = pygame.Surface((w, h)).convert()
                 self.background.blit(scaled_img, (x, y))
             except Exception as e:
                 print(f"Erro no render imagem: {e}")
                 # Fallback para gradiente se falhar
                 self._render_gradient(w, h)
        else:
             self._render_gradient(w, h)
        
        # Cria/Atualiza Overlay aqui
        self.overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        self.overlay.fill(COLOR_BG_OVERLAY)

    def _render_gradient(self, w, h):
        self.background = pygame.Surface((w, h)).convert()
        c1 = getattr(self, 'bg_c1', (0,0,100))
        c2 = getattr(self, 'bg_c2', (0,0,50))

        # Otimização: desenhar linhas horizontais
        for y in range(h):
            # Interpolação linear (float) para evitar degraus abruptos
            f = y / h
            r = int(c1[0] + (c2[0] - c1[0]) * f)
            g = int(c1[1] + (c2[1] - c1[1]) * f)
            b = int(c1[2] + (c2[2] - c1[2]) * f)
            
            # Clamp color values (just in case)
            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))
            
            pygame.draw.line(self.background, (r,g,b), (0,y), (w,y))

    def load_random_background(self):
        # Alias para compatibilidade antiga, se necessário, ou redirecionar
        self.generate_new_background()

    # ... (other methods maintained but skipped in replacement for brevity if unchanged)



    def parse_lrc(self, lrc_path):
        """
        Analisa o arquivo de letras (LRC ou JSON).
        """
        if lrc_path.endswith('.json'):
            import json
            try:
                with open(lrc_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    lines = []
                    for l in data.get('lines', []):
                         l['time'] = l['start'] * 1000
                         l['end_time'] = l['end'] * 1000
                         for w in l.get('words', []):
                             w['start_ms'] = w['start'] * 1000
                             w['end_ms'] = w['end'] * 1000
                         lines.append(l)
                    return lines
            except Exception as e:
                print(f"Erro ao analisar letras JSON: {e}")
                return []

        lyrics = []
        if not lrc_path or not os.path.exists(lrc_path):
            return []

        with open(lrc_path, 'r', encoding='utf-8') as f:
            for line in f:
                match = re.search(r'\[(\d+):(\d+\.\d+)\](.*)', line)
                if match:
                    minutes = int(match.group(1))
                    seconds = float(match.group(2))
                    text = match.group(3).strip()
                    time_ms = (minutes * 60 + seconds) * 1000
                    lyrics.append({'time': time_ms, 'text': text})
        return lyrics

    def start_song(self, song_id):
        """Inicia a reprodução."""
        # Busca no banco
        song_data = self.manager.get_song_by_code(song_id)
        if not song_data:
            print(f"Música {song_id} não encontrada ou indisponível!")
            return
            
        print(f"Iniciando música: {song_data['title']}")
        self.current_song = song_data
        
        # Detecta Lyrics Disponíveis
        base = song_data['base_path']
        self.lyrics_files = []
        
        # Prioridade de Ordem: v1 (Sincronizado Padrão), v2 (Alternativo), lrc (Linha)
        if os.path.exists(os.path.join(base, "lyrics_v1.json")):
             self.lyrics_files.append({"type": "v1", "path": os.path.join(base, "lyrics_v1.json")})
        if os.path.exists(os.path.join(base, "lyrics_v2.json")):
             self.lyrics_files.append({"type": "v2", "path": os.path.join(base, "lyrics_v2.json")})
        if os.path.exists(os.path.join(base, "lyrics.lrc")):
             self.lyrics_files.append({"type": "lrc", "path": os.path.join(base, "lyrics.lrc")})
             
        # Carrega o primeiro disponível
        self.current_lyrics_index = 0
        if self.lyrics_files:
             self._load_lyrics_by_index(0)
        else:
             self.lyrics = []

        try:
            try:
                # Carrega duração total (necessita recarregar como Sound)
                s = pygame.mixer.Sound(song_data['audio_path'])
                self.total_duration = s.get_length() * 1000
            except:
                self.total_duration = 0

            pygame.mixer.music.load(song_data['audio_path'])
            pygame.mixer.music.set_volume(self.cfg_volume_music)
            pygame.mixer.music.play()
        except pygame.error as e:
            print(f"Não foi possível carregar o áudio: {e}")
            return
        
        self.state = "PLAYING"
        self.scorer.set_paused(False) # Resume audio processing safely
        self.scorer.reset()
        self.load_random_background()

    def _load_lyrics_by_index(self, index):
        if not self.lyrics_files: return
        data = self.lyrics_files[index]
        print(f"Carregando letras: {data['type']}")
        self.lyrics = self.parse_lrc(data['path'])
        
    def switch_lyrics(self):
        """Alterna entre arquivos de letra disponíveis."""
        if not self.lyrics_files or len(self.lyrics_files) <= 1: return
        
        self.current_lyrics_index = (self.current_lyrics_index + 1) % len(self.lyrics_files)
        self._load_lyrics_by_index(self.current_lyrics_index)
        
        # Mostra feedback visual (opcional/debug)
        l_type = self.lyrics_files[self.current_lyrics_index]['type']
        print(f"Letras alteradas para: {l_type}")
        
    def get_current_time(self):
        """Retorna tempo atual em ms com compensação de offset."""
        if not hasattr(self, 'current_offset_ms'):
             self.current_offset_ms = 0
        pos = pygame.mixer.music.get_pos()
        if pos == -1: return 0
        return pos + self.current_offset_ms
        
    def seek_song(self, delta_sec):
        """Avança ou retrocede a música."""
        if not self.current_song: return
        
        curr_sec = self.get_current_time() / 1000.0
        new_pos = max(0, curr_sec + delta_sec)
        
        # Limita ao final
        if self.total_duration > 0:
             max_sec = self.total_duration / 1000.0
             if new_pos >= max_sec: new_pos = max_sec - 1
        
        try:
             pygame.mixer.music.play(start=new_pos)
             self.current_offset_ms = int(new_pos * 1000)
             
             # Re-sincroniza a página de letras (Aproximação simples)
             # Reseta para buscar do inicio
             self.page_index = 0
             # Avança paginação até encontrar o tempo atual
             target_ms = new_pos * 1000
             while self.page_index + 1 < len(self.lyrics):
                  line = self.lyrics[self.page_index + 1]
                  if target_ms > line.get('end_time', line['time'] + 5000):
                       self.page_index += 2
                  else:
                       break
                       
             print(f"Seek para {new_pos}s")
        except Exception as e:
             print(f"Erro no Seek: {e}")

    def toggle_audio_track(self):
        """Alterna entre Instrumental e Vocal."""
        if not self.current_song: return
        
        if not hasattr(self, 'current_track_type'):
            self.current_track_type = 'instrumental'
        
        inst_path = self.current_song.get('audio_path') 
        orig_path = self.current_song.get('original_audio_path')
        
        current_time_ms = self.get_current_time()
        start_sec = current_time_ms / 1000.0
        
        try:
            target_file = None
            target_type = None
            if self.current_track_type == 'instrumental':
                if orig_path and os.path.exists(orig_path):
                    target_file = orig_path
                    target_type = 'vocal'
            else:
                if inst_path and os.path.exists(inst_path):
                    target_file = inst_path
                    target_type = 'instrumental'
            
            if target_file:
                pygame.mixer.music.load(target_file)
                pygame.mixer.music.set_volume(self.cfg_volume_music)
                pygame.mixer.music.play(start=start_sec)
                self.current_offset_ms = int(start_sec * 1000)
                self.current_track_type = target_type
        except Exception as e:
            print(f"Erro ao alternar áudio: {e}")

    def toggle_pause(self):
        """Pausa ou resume a música."""
        if self.state != "PLAYING": return

        self.paused = not self.paused
        if self.paused:
            pygame.mixer.music.pause()
            self.scorer.set_paused(True) # Pause audio processing
        else:
            pygame.mixer.music.unpause()
            self.scorer.set_paused(False) # Resume audio processing

    def draw_help_screen(self):
        """Desenha overlay de ajuda."""
        W, H = self.screen.get_width(), self.screen.get_height()
        ui_scale = H / 768.0
        
        # Overlay Background
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200)) # 80% opacity black
        self.screen.blit(overlay, (0, 0))
        
        # Title
        self.draw_centered_text("COMANDOS DO KARAOKÊ", int(-200 * ui_scale), size=int(40 * ui_scale), color=COLOR_HIGHLIGHT)
        
        # Commands List
        commands = [
            ("ENTER", "Adicionar música (Menu)"),
            ("ESPAÇO", "Pausar / Retomar"),
            ("SETAS ESQ/DIR", "Retroceder / Avançar 10s"),
            ("L", "Trocar Tipo de Legenda (LRC/V1/V2)"),
            ("V", "Trocar Faixa de Áudio (Original/Instrumental)"),
            ("C", "Configurações (Audio/Video/Mic)"),
            ("H / F1", "Mostrar/Esconder esta ajuda"),
            ("ESC", "Voltar / Sair da Ajuda")
        ]
        
        start_y = int(200 * ui_scale)
        gap_y = int(40 * ui_scale)
        
        for i, (key, desc) in enumerate(commands):
            y_pos = start_y + i * gap_y
            # Draw Key (Left aligned relative to center-ish)
            key_surf = self.font_info.render(key, True, COLOR_HIGHLIGHT)
            desc_surf = self.font_info.render(desc, True, COLOR_WHITE)
            
            # Align them nicely
            key_x = W // 2 - int(250 * ui_scale)
            desc_x = W // 2 - int(100 * ui_scale)
            
            self.screen.blit(key_surf, (key_x, y_pos))
            self.screen.blit(desc_surf, (desc_x, y_pos))



    def apply_audio_config(self):
        """Envia configurações da UI para o backend de áudio (Scorer)."""
        self.scorer.set_config(
            self.cfg_mic1_idx,
            self.cfg_mic2_idx,
            self.cfg_monitoring,
            self.cfg_latency_chunk,
            self.cfg_difficulty,
            self.cfg_volume_mic1,
            self.cfg_volume_mic2
        )
        # Atualiza volume da música imediatamente se estiver tocando
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.set_volume(self.cfg_volume_music)

    def handle_input(self, event):
        """Gerencia entradas do usuário para TODOS os estados."""
        if event.type == pygame.KEYDOWN:
            if self.state == "MENU":
                if event.key == pygame.K_RETURN:
                    if self.input_buffer:
                        # Verifica no banco
                        song = self.manager.get_song_by_code(self.input_buffer)
                        if song:
                            self.queue.append(self.input_buffer)
                            print(f"Adicionado {self.input_buffer} à fila.")
                        else:
                            print("Código inválido ou indisponível.")
                            
                        self.input_buffer = ""
                elif event.key == pygame.K_BACKSPACE:
                    self.input_buffer = self.input_buffer[:-1]
                elif event.unicode.isnumeric():
                    self.input_buffer += event.unicode
                elif event.key == pygame.K_c:
                    self.state = "CONFIG"
                    self.input_buffer = "" # Limpa buffer ao entrar config

            elif self.state == "PLAYING":
                if event.key == pygame.K_SPACE:
                     self.toggle_pause()
                elif event.key == pygame.K_v:
                    self.toggle_audio_track()
                elif event.key == pygame.K_l:
                    self.switch_lyrics()
                elif event.key == pygame.K_RIGHT:
                     self.seek_song(10)
                elif event.key == pygame.K_LEFT:
                     self.seek_song(-10)
                elif event.key == pygame.K_RETURN and self.input_buffer:
                     # Adicionar à fila durante jogo
                     song = self.manager.get_song_by_code(self.input_buffer)
                     if song:
                        self.queue.append(self.input_buffer)
                        print(f"Adicionado {self.input_buffer} à fila.")
                     self.input_buffer = ""
                elif event.key == pygame.K_BACKSPACE:
                    self.input_buffer = self.input_buffer[:-1]
                elif event.unicode.isnumeric():
                    self.input_buffer += event.unicode
                elif event.key == pygame.K_h or event.key == pygame.K_F1:
                    self.show_help = not self.show_help

            elif self.state == "SCORE":
                if event.key == pygame.K_RETURN:
                    self.state = "MENU"

            elif self.state == "CONFIG":
                if event.key == pygame.K_ESCAPE or event.key == pygame.K_c:
                    self.state = "MENU" # Voltar
                pass
            
            # Global Toggle Help (if not playing or config might override)
            if self.state == "MENU":
                 if event.key == pygame.K_h or event.key == pygame.K_F1:
                    self.show_help = not self.show_help
             
            if self.show_help and event.key == pygame.K_ESCAPE:
                self.show_help = False
            

        
        if event.type == pygame.MOUSEBUTTONDOWN and self.state == "CONFIG":
            x, y = event.pos
            W, H = self.screen.get_width(), self.screen.get_height()
            ui_scale = H / 768.0
            
            # Recalcula posições base (mesma lógica do draw)
            CX = W // 2
            start_y = int(150 * ui_scale)
            gap_y = int(50 * ui_scale)
            col_ctrl_x = CX + int(50 * ui_scale)
            chk_size = int(20 * ui_scale)
            
            # Botão Atualizar Biblioteca (700, 50, 200, 50) -> Scaled
            btn_w, btn_h = int(200 * ui_scale), int(50 * ui_scale)
            btn_y = int(50 * ui_scale)
            btn_x = CX + int(200 * ui_scale)
            
            if btn_x <= x <= btn_x + btn_w and btn_y <= y <= btn_y + btn_h:
                print("Atualizando biblioteca...")
                res = self.manager.sync_availability()
                print(res)
                # Recarrega imagens também
                self.load_bg_images()

            # Botão Monitoramento (Toggle)
            y_mon = start_y
            if col_ctrl_x <= x <= col_ctrl_x + chk_size and y_mon <= y <= y_mon + chk_size:
                self.cfg_monitoring = not self.cfg_monitoring
            
            # Botão Indicador Ritmo (Toggle)
            y_rhy = start_y + gap_y
            if col_ctrl_x <= x <= col_ctrl_x + chk_size and y_rhy <= y <= y_rhy + chk_size:
                self.show_rhythm_indicator = not self.show_rhythm_indicator
                
            # Sliders (Lógica aproximada: clique na barra altera valor)
            slider_w = int(300 * ui_scale)
            padding_y = int(10 * ui_scale) # Margem de clique vertical
            
            # Volume Mic 1
            y_m1 = start_y + 2 * gap_y
            if col_ctrl_x <= x <= col_ctrl_x + slider_w and y_m1 <= y <= y_m1 + 20: # +20 tolerance
                self.cfg_volume_mic1 = (x - col_ctrl_x) / slider_w * 2.0 # Max 2.0
            
            # Volume Mic 2
            y_m2 = start_y + 3 * gap_y
            if col_ctrl_x <= x <= col_ctrl_x + slider_w and y_m2 <= y <= y_m2 + 20:
                self.cfg_volume_mic2 = (x - col_ctrl_x) / slider_w * 2.0
                
            # Volume Musica 
            y_mus = start_y + 4 * gap_y
            if col_ctrl_x <= x <= col_ctrl_x + slider_w and y_mus <= y <= y_mus + 20:
                self.cfg_volume_music = (x - col_ctrl_x) / slider_w
                pygame.mixer.music.set_volume(self.cfg_volume_music)

            # Dificuldade (Ciclar)
            y_dif = start_y + 5 * gap_y
            btn_h_small = int(30 * ui_scale)
            if col_ctrl_x <= x <= col_ctrl_x + int(200*ui_scale) and y_dif <= y <= y_dif + btn_h_small:
                modes = ["Fácil", "Normal", "Difícil"]
                curr_idx = modes.index(self.cfg_difficulty)
                self.cfg_difficulty = modes[(curr_idx + 1) % len(modes)]
            
            # Trocar Mic 1 (Ciclar)
            y_d1 = start_y + 6 * gap_y
            if col_ctrl_x <= x <= col_ctrl_x + int(300*ui_scale) and y_d1 <= y <= y_d1 + btn_h_small:
                self._cycle_mic(1)
            
             # Trocar Mic 2 (Ciclar)
            y_d2 = start_y + 7 * gap_y
            if col_ctrl_x <= x <= col_ctrl_x + int(300*ui_scale) and y_d2 <= y <= y_d2 + btn_h_small:
                self._cycle_mic(2)
                
            # Toggle Background Mode (Novo)
            y_bg = start_y + 8 * gap_y
            if col_ctrl_x <= x <= col_ctrl_x + int(200*ui_scale) and y_bg <= y <= y_bg + btn_h_small:
                self.cfg_bg_mode = "GRADIENTE" if self.cfg_bg_mode == "IMAGEM" else "IMAGEM"
                print(f"Modo Fundo alterado para: {self.cfg_bg_mode}")
                self.load_random_background()
                
            self.apply_audio_config()

    def _cycle_mic(self, mic_num):
        """Cicla entre devices disponiveis."""
        if not self.available_devices: return
        
        current_idx = self.cfg_mic1_idx if mic_num == 1 else self.cfg_mic2_idx
        
        # Encontra posição na lista
        list_idx = -1
        for i, d in enumerate(self.available_devices):
            if d['index'] == current_idx:
                list_idx = i
                break
        
        new_list_idx = (list_idx + 1) % len(self.available_devices)
        new_dev_idx = self.available_devices[new_list_idx]['index']
        
        if mic_num == 1: self.cfg_mic1_idx = new_dev_idx
        else: self.cfg_mic2_idx = new_dev_idx


    def update(self):
        """Loop lógico."""
        if self.state == "PLAYING":
            # Check for forced stop/skip first
            if getattr(self, 'skip_requested', False):
                self.skip_requested = False
                self.finish_song()
                return

            if self.paused:
                return # Skip logic update if paused

            if not pygame.mixer.music.get_busy():
                # Double check to prevent accidental finish if just buffer lag
                # But mostly fine.
                self.finish_song()
                return
            
            current_time = self.get_current_time()
            
            # Encontra linha atual
            found_index = -1
            for i, line in enumerate(self.lyrics):
                if current_time >= line['time'] - 200: found_index = i
                else: break
            
            # Paginação (Cascading Page Flip)
            if not hasattr(self, 'page_index'): self.page_index = 0
            
            if self.page_index < len(self.lyrics):
                 line = self.lyrics[self.page_index]
                 line_end = line.get('end_time', line['time'] + 5000)
                 
                 # Only advance if we have passed the end time (Immediate flip)
                 if current_time > line_end:
                     self.page_index += 1

            self.current_line_index = found_index
            
            # Sincroniza Scorer
            if 0 <= self.current_line_index < len(self.lyrics):
                l = self.lyrics[self.current_line_index]
                end_time = l.get('end_time', l['time'] + 5000)
                in_segment = l['time'] <= current_time <= end_time
                self.scorer.set_singing_segment(in_segment)
            else:
                 self.scorer.set_singing_segment(False)

        elif self.state == "SCORE":
            # Auto-advance after 10 seconds or if skip requested
            time_elapsed = time.time() - getattr(self, 'score_start_time', 0)
            
            # Check for API Skip request during Score screen
            if getattr(self, 'skip_requested', False):
                self.skip_requested = False
                time_elapsed = 999 # Force advance
                
            if time_elapsed > 10:
                if self.queue:
                     next_song = self.queue.pop(0)
                     self.start_song(next_song)
                     self.page_index = 0
                     self.current_track_type = 'instrumental'
                     self.current_offset_ms = 0
                else:
                     self.state = "MENU"

        elif self.state == "MENU":
            if self.queue:
                next_song = self.queue.pop(0)
                self.start_song(next_song)
                self.page_index = 0 
                self.current_track_type = 'instrumental'
                self.current_offset_ms = 0

    def finish_song(self):
        self.scorer.set_paused(True) # Pausa audio processamento de forma segura
        # Aguarda brevemente para thread liberar
        time.sleep(0.1) 
        self.scorer.stop_streams() # Fecha streams agora que está pausado
        self.score_result = self.scorer.get_score()
        self.state = "SCORE"
        self.score_start_time = time.time()
        self.paused = False # Reset pause state

    def draw(self):
        """Renderização."""
        W, H = self.screen.get_width(), self.screen.get_height()
        # Fundo
        if self.state == "CONFIG":
             self.screen.fill((20, 20, 30)) # Fundo escuro tecnico
        else:
            if self.background: 
                # Se mudou resolução, re-renderiza para ficar HD
                if self.background.get_size() != (W, H):
                    self.render_background()
                self.screen.blit(self.background, (0,0))
            
            # Overlay otimizado
            if hasattr(self, 'overlay'):
                 self.screen.blit(self.overlay, (0,0))
            else:
                 # Fallback temporário
                 self.render_background()
                 if hasattr(self, 'overlay'): self.screen.blit(self.overlay, (0,0))

        if self.state == "MENU":
            # Escala UI baseada na altura (768p referencia)
            ui_scale = H / 768.0
            
            self.draw_centered_text("SISTEMA DE KARAOKÊ", int(-100 * ui_scale), color=COLOR_HIGHLIGHT)
            self.draw_centered_text("Digite o código e ENTER para adicionar à fila", int(-50 * ui_scale))
            self.draw_centered_text("[C] para Configurar Áudio / Microfone", 0, size=int(30 * ui_scale), color=COLOR_BLUE)
            
            self.draw_centered_text(f"Fila: {', '.join(self.queue)}", int(80 * ui_scale))
            
            # Instrução visual substitui lista antiga
            self.draw_centered_text("Consulte o catálogo físico ou app", int(200 * ui_scale), color=(150,150,150))

            input_surf = self.font_info.render(f"Entrada: {self.input_buffer}", True, COLOR_HIGHLIGHT)
            self.screen.blit(input_surf, (50, H - 50))

        elif self.state == "PLAYING":
            # --- RENDERIZAÇÃO KARAOKE REFINADA ---
            W, H = self.screen.get_width(), self.screen.get_height()
            ui_scale = H / 768.0

            # 1. LAYOUT DEFINITIONS
            # Active Line: Center (45%)
            # Next Line: Immediately below (53%)
            active_y = int(H * 0.45)
            next_y = int(H * 0.53)
            
            current_time = self.get_current_time()
            
            # 2. TITLE CARD (0s - 5s)
            if current_time < 5000 and self.current_song:
                alpha = 255
                if current_time > 4000: # Fade out last second
                    alpha = int(255 * (1 - (current_time - 4000)/1000.0))
                
                if alpha > 10:
                    # Create a surface for the Title Card to handle Alpha
                    title_surf = pygame.Surface((W, 200), pygame.SRCALPHA)
                    title = self.current_song.get('title', '')
                    artist = self.current_song.get('artist', '')
                    
                    # Layout: Title at 18%, Lyrics at 45%
                    # Use LARGER font for Title (font_lyrics is biggest)
                    title_y = int(H * 0.18)
                    artist_y = int(H * 0.25)
                    
                    self.draw_text_with_outline(title, self.font_lyrics, COLOR_HIGHLIGHT, (W//2, title_y))
                    self.draw_text_with_outline(artist, self.font_info, COLOR_WHITE, (W//2, artist_y))

            # 3. CUE DOTS (4s Countdown)
            next_start = None
            if hasattr(self, 'page_index') and self.page_index < len(self.lyrics):
                 next_start = self.lyrics[self.page_index]['time']
            
            if next_start:
                 time_to = (next_start - current_time) / 1000.0
                 if 0 < time_to <= 4.0:
                     # Check layout validity
                     is_valid_gap = (self.page_index == 0) # Prioritize intro
                     if not is_valid_gap and self.page_index > 0:
                         prev_end = self.lyrics[self.page_index-1].get('end_time', 0)
                         if (next_start - prev_end) > 6000: is_valid_gap = True
                     
                     if is_valid_gap:
                         dot_radius = int(10 * ui_scale)
                         dot_spacing = int(40 * ui_scale)
                         start_x = W//2 - (1.5 * dot_spacing)
                         y_dots = active_y - int(60 * ui_scale)
                         
                         for i in range(4): # 0, 1, 2, 3
                             cx = int(start_x + i * dot_spacing)
                             # Time mapping: 4.0->0, 3.0->1, 2.0->2, 1.0->3
                             # i=0 lit if time <= 4.0? No, that's always.
                             # Reverse logic:
                             # 4.0 - 3.0: 1st dot (i=0) ONLY? Or 1st dot fills?
                             # Let's do: 
                             # 4s -> 0 lit
                             # 3s -> 0,1 lit
                             # 2s -> 0,1,2 lit
                             # 1s -> 0,1,2,3 lit
                             
                             threshold = 4.0 - i
                             # Example: T=3.5. 3.5 <= 4.0 (0=True). 3.5 <= 3.0 (1=False).
                             # So at 3.5s (start of count), only 1st dot is set. Correct.
                             
                             is_lit = time_to <= threshold
                             
                             # Draw Empty Circle (Stroke)
                             pygame.draw.circle(self.screen, (255,255,255), (cx, y_dots), dot_radius, 2)
                             
                             if is_lit:
                                 color = COLOR_BLUE if i < 3 else COLOR_RED
                                 pygame.draw.circle(self.screen, color, (cx, y_dots), dot_radius - 2)

            # 4. DRAW LYRICS LINES
            # Current Line (Active) - Top
            if hasattr(self, 'page_index') and self.page_index < len(self.lyrics):
                line_data = self.lyrics[self.page_index]
                
                # Check visibility: Hide if finished for > 1s
                # AND Hide if it starts too far in future (Instrumental Break)
                end_t = line_data.get('end_time', line_data['time'] + 5000)
                
                # Default visibility: 8s before start
                vis_threshold = 8000
                
                # Check if it's a long intro/break
                if self.page_index == 0:
                     vis_threshold = 4000 # Intro strict
                elif self.page_index > 0:
                     prev_end = self.lyrics[self.page_index-1].get('end_time', 0)
                     if (line_data['time'] - prev_end) > 8000:
                         vis_threshold = 4000 # Instrumental strict (sync with dots)

                is_time_to_show = (line_data['time'] - current_time <= vis_threshold)
                has_not_ended = (current_time <= end_t + 1000)
                
                if has_not_ended and is_time_to_show:
                    if 'words' in line_data: 
                        self.draw_karaoke_line(line_data, current_time, active_y, is_active=True) 
                    else: 
                         self.draw_text_with_outline(line_data['text'], self.font_lyrics, COLOR_HIGHLIGHT, (W//2, active_y))

            # Next Line (Preview) - Bottom
            if hasattr(self, 'page_index') and self.page_index + 1 < len(self.lyrics):
                line_data = self.lyrics[self.page_index + 1]
                
                # Determine visibility threshold
                # If it's a long gap (Instrumental), show only when dots appear (4s).
                # Otherwise, show early (8s) for reading.
                vis_threshold = 8000
                if hasattr(self, 'page_index') and self.page_index >= 0:
                     curr_end = self.lyrics[self.page_index].get('end_time', 0)
                     gap = line_data['time'] - curr_end
                     if gap > 8000: vis_threshold = 4000 # Sync with dots for instrumental
                
                # Check visibility
                if line_data['time'] - current_time <= vis_threshold:
                    if 'words' in line_data: 
                        self.draw_karaoke_line(line_data, current_time, next_y, is_active=False) 
                    else: 
                        self.draw_text_with_outline(line_data['text'], self.font_lyrics, (200,200,200), (W//2, next_y))

            # HUD Futurista (VU Meter e Ritmo)
            self.draw_vu_meter_hud()
            if self.show_rhythm_indicator:
                self.draw_rhythm_indicator_hud()
            
            self.draw_ui_progress()

            if self.input_buffer:
                input_surf = self.font_info.render(f"Add Fila: {self.input_buffer}", True, COLOR_WHITE)
                self.screen.blit(input_surf, (20, H - 40))

            # Instrumental Progress
            if next_start and current_time < next_start:
                 gap = next_start - current_time
                 if gap > 8000 and self.page_index > 0: # Only if not intro
                      self.draw_text_with_outline("INSTRUMENTAL", self.font_info, (100,200,255), (W//2, H//2))

        elif self.state == "SCORE":
            self.draw_centered_text("MÚSICA FINALIZADA", -50)
            self.draw_centered_text(f"Sua Pontuação: {self.score_result}/100", 20, 80, COLOR_HIGHLIGHT)
            
            # Timer Countdown
            if hasattr(self, 'score_start_time'):
                remaining = max(0, 10 - int(time.time() - self.score_start_time))
                self.draw_centered_text(f"Próxima em {remaining}s...", 150, 24, (150,150,150))

            self.draw_centered_text("Pressione ENTER para continuar", 200, 30)

        elif self.state == "CONFIG":
            self.draw_config_screen()

        # Draw Overlays at the very end
        if self.paused:
            self.draw_centered_text("PAUSADO", 0, size=80, color=COLOR_RED)
            
        if self.show_help:
            self.draw_help_screen()

        pygame.display.flip()

    def draw_karaoke_line(self, line_data, current_time, center_y, is_active=True):
        """
        Desenha linha de karaokê com Wipe (Máscara) e Outlines.
        center_y: Y absoluto central.
        """
        words = line_data.get('words', [])
        if not words: return

        W, H = self.screen.get_width(), self.screen.get_height()
        ui_scale = H / 768.0
        
        space_width = self.font_lyrics.size(" ")[0]
        margin = int(100 * ui_scale)
        max_width = W - margin
        
        # 1. Agrupar em linhas visuais
        visual_lines = []
        current_line_words = []
        current_line_width = 0
        
        for w in words:
            word_txt = w['display']
            word_surf_w = self.font_lyrics.size(word_txt)[0]
            
            if current_line_width + word_surf_w > max_width and current_line_words:
                visual_lines.append(current_line_words)
                current_line_words = []
                current_line_width = 0
            
            current_line_words.append(w)
            current_line_width += word_surf_w + space_width
            
        if current_line_words:
            visual_lines.append(current_line_words)
            
        # 2. Geometria Vertical
        line_height = self.font_lyrics.get_linesize()
        total_block_height = len(visual_lines) * line_height
        
        start_y = center_y - (total_block_height // 2)
        current_y = start_y
        
        # Cores
        inactive_color = (200, 200, 200) # Cinza claro
        if not is_active:
             inactive_color = (100, 100, 100) # Cinza escuro se for preview
        
        active_color = COLOR_HIGHLIGHT # Dourado
        outline_color = (0, 0, 0)
        
        # 3. Desenhar
        for v_line in visual_lines:
            # Largura total para centralizar
            line_w = 0
            for w in v_line:
                line_w += self.font_lyrics.size(w['display'])[0] + space_width
            line_w -= space_width
            
            start_x = (W - line_w) // 2
            current_x = start_x
            
            # Para cada palavra, renderizar Base + Wipe
            for w in v_line:
                txt = w['display']
                w_w, w_h = self.font_lyrics.size(txt)
                
                # A. Base (Inactive) com Outline
                # Desenha outline em loop
                for dx in [-2, 0, 2]:
                    for dy in [-2, 0, 2]:
                        if dx!=0 or dy!=0:
                            s_out = self.font_lyrics.render(txt, True, outline_color)
                            self.screen.blit(s_out, (current_x + dx, current_y + dy))
                
                # Inactive Fill
                s_inact = self.font_lyrics.render(txt, True, inactive_color)
                self.screen.blit(s_inact, (current_x, current_y))
                
                # B. Active Wipe (Se for a linha ativa)
                if is_active:
                    # Calcula % de preenchimento
                    # Se passou do fim: 100%
                    # Se antes do inicio: 0%
                    # No meio: interpola
                    
                    fill_pct = 0.0
                    if current_time >= w['end_ms']:
                        fill_pct = 1.0
                    elif current_time > w['start_ms']:
                        duration = w['end_ms'] - w['start_ms']
                        if duration > 0:
                            fill_pct = (current_time - w['start_ms']) / duration
                    
                    if fill_pct > 0:
                        # Renderiza Active Surface
                        s_act = self.font_lyrics.render(txt, True, active_color)
                        
                        # Cria Rect de recorte
                        # Queremos blitar s_act sobre s_inact, mas apenas os primeiros (width * fill_pct) pixels
                        fill_width = int(w_w * fill_pct)
                        if fill_width > 0:
                            area = pygame.Rect(0, 0, fill_width, w_h)
                            self.screen.blit(s_act, (current_x, current_y), area)
                
                current_x += w_w + space_width
            
            current_y += line_height
        
    def draw_countdown_indicator(self, remaining_sec):
        """Desenha um indicador circular de contagem regressiva."""
        W, H = self.screen.get_width(), self.screen.get_height()
        ui_scale = H / 768.0
        
        center_x = W // 2
        center_y = H // 2 - int(100 * ui_scale) # Um pouco acima do centro
        radius = int(40 * ui_scale)
        
        # Texto
        seconds = int(remaining_sec) + 1
        text = f"{seconds}"
        
        # Cor varia: Amarelo -> Vermelho
        color = (255, 255, 0)
        if seconds <= 2: color = (255, 50, 50)
        
        # Círculo de fundo
        pygame.draw.circle(self.screen, (50, 50, 50), (center_x, center_y), radius)
        pygame.draw.circle(self.screen, color, (center_x, center_y), radius, width=int(3*ui_scale))
        
        # Texto número
        txt_surf = self.font_info.render(text, True, color)
        txt_rect = txt_surf.get_rect(center=(center_x, center_y))
        self.screen.blit(txt_surf, txt_rect)
        
        # Label "PREPARE-SE"
        lbl_surf = self.font_info.render("PRÓXIMA FRASE", True, (200,200,200))
        lbl_rect = lbl_surf.get_rect(center=(center_x, center_y - radius - int(20 * ui_scale)))
        self.screen.blit(lbl_surf, lbl_rect)
        



    def draw_vu_meter_hud(self):
        """Desenha um VU Meter visual no canto inferior direito."""
        W, H = self.screen.get_width(), self.screen.get_height()
        ui_scale = H / 768.0
        
        # Pega volume atual do mic principal
        vol = max(self.scorer.current_volume_mic1, self.scorer.current_volume_mic2)
        # Normaliza visualmente (multiplicador escalado)
        base_h = min(150, int(vol * 5))
        height_val = int(base_h * ui_scale)
        
        offset_x = int(60 * ui_scale)
        offset_y = int(50 * ui_scale)
        base_x = W - offset_x
        base_y = H - offset_y
        
        bar_w = int(30 * ui_scale)
        max_h = int(150 * ui_scale)
        
        # Barra de Fundo
        pygame.draw.rect(self.screen, (50, 50, 50), (base_x, base_y - max_h, bar_w, max_h))
        
        # Barra Dinâmica
        if height_val > 0:
            color = COLOR_GREEN
            if height_val > max_h * 0.6: color = COLOR_HIGHLIGHT
            if height_val > max_h * 0.9: color = COLOR_RED
            
            pygame.draw.rect(self.screen, color, (base_x, base_y - height_val, bar_w, height_val))
            
            # Efeito "Glow"
            glow_w = int(50 * ui_scale)
            s = pygame.Surface((glow_w, height_val))
            s.set_alpha(50)
            s.fill(color)
            self.screen.blit(s, (base_x - int(10*ui_scale), base_y - height_val))

        # Texto "MIC"
        mic_txt = self.font_small.render("MIC", True, COLOR_WHITE)
        self.screen.blit(mic_txt, (base_x, base_y + int(5 * ui_scale)))

    def draw_rhythm_indicator_hud(self):
        """Indicador circular de precisão."""
        W, H = self.screen.get_width(), self.screen.get_height()
        ui_scale = H / 768.0
        
        acc = self.scorer.get_current_accuracy() # 0.0 a 1.0
        
        offset_x = int(120 * ui_scale)
        offset_y = int(125 * ui_scale)
        cx = W - offset_x
        cy = H - offset_y
        radius = int(40 * ui_scale)
        thickness = max(1, int(3 * ui_scale))
        
        # Círculo base
        pygame.draw.circle(self.screen, (50, 50, 50), (cx, cy), radius, thickness)
        
        # Círculo de Precisão
        if acc > 0.8: color = COLOR_GREEN
        elif acc > 0.4: color = COLOR_HIGHLIGHT
        else: color = COLOR_RED
        
        # Desenha circulo preenchido proporcional
        fill_rad = int(radius * acc)
        if fill_rad > 0:
             pygame.draw.circle(self.screen, color, (cx, cy), fill_rad)
        
        lbl = self.font_small.render("RITMO", True, COLOR_WHITE)
        self.screen.blit(lbl, (cx - int(20*ui_scale), cy + radius + int(5*ui_scale)))


    def draw_ui_progress(self):
        """Desenha barra de progresso e tempo."""
        if not self.current_song: return
        
        W, H = self.screen.get_width(), self.screen.get_height()
        ui_scale = H / 768.0
        
        curr_ms = self.get_current_time()
        curr_sec = curr_ms // 1000
        total_sec = self.total_duration // 1000 if self.total_duration > 0 else 0
        
        # Time Text
        def fmt_time(s):
            m = int(s // 60)
            sec = int(s % 60)
            return f"{m:02}:{sec:02}"
            
        txt = f"{fmt_time(curr_sec)} / {fmt_time(total_sec)}"
        surf = self.font_info.render(txt, True, COLOR_WHITE)
        self.screen.blit(surf, (int(20*ui_scale), H - int(70 * ui_scale)))
        
        # Progress Bar
        bar_w = W - int(200 * ui_scale)
        bar_h = int(10 * ui_scale)
        bar_x = int(100 * ui_scale)
        bar_y = H - int(30 * ui_scale)
        
        pygame.draw.rect(self.screen, (50,50,50), (bar_x, bar_y, bar_w, bar_h))
        
        if self.total_duration > 0:
            pct = min(1.0, curr_ms / self.total_duration)
            fill_w = int(bar_w * pct)
            pygame.draw.rect(self.screen, COLOR_HIGHLIGHT, (bar_x, bar_y, fill_w, bar_h))

    def draw_config_screen(self):
        """Desenha a tela de configuração completas."""
        W, H = self.screen.get_width(), self.screen.get_height()
        CX = W // 2
        # Escala UI baseada na altura (768p referencia)
        ui_scale = H / 768.0
        
        # Offsets verticais escalados
        self.draw_centered_text("CONFIGURAÇÃO DE ÁUDIO", int(-300 * ui_scale), color=COLOR_HIGHLIGHT)
        self.draw_centered_text("[ESC] Voltar", int(-350 * ui_scale), size=int(30 * ui_scale), color=COLOR_WHITE)
        
        # Tamanhos base escalados
        btn_w, btn_h = int(200 * ui_scale), int(50 * ui_scale)
        chk_size = int(20 * ui_scale)
        slider_w = int(300 * ui_scale)
        line_h = max(2, int(5 * ui_scale))
        radius = max(5, int(8 * ui_scale))
        btn_h_small = int(30 * ui_scale)
        
        # Botão Atualizar Library
        btn_y = int(50 * ui_scale)
        btn_rect = pygame.Rect(CX + int(200 * ui_scale), btn_y, btn_w, btn_h)
        
        pygame.draw.rect(self.screen, (0, 100, 200), btn_rect)
        btn_txt = self.font_small.render("Atualizar Biblioteca", True, COLOR_WHITE)
        t_rect = btn_txt.get_rect(center=btn_rect.center)
        self.screen.blit(btn_txt, t_rect)
        
        # Labels e Controles (Scaled layout)
        font = self.font_info
        
        start_y = int(150 * ui_scale)
        gap_y = int(50 * ui_scale)
        col_lbl_x = CX - int(400 * ui_scale)
        col_ctrl_x = CX + int(50 * ui_scale) # Ajuste horizontal também
        
        # Coluna Esq: Labels
        lbls = [
            ("Monitorar (Ouvir voz):", 0),
            ("Mostrar Ritmo:", 1),
            (f"Vol Mic 1 ({int(self.cfg_volume_mic1*100)}%):", 2),
            (f"Vol Mic 2 ({int(self.cfg_volume_mic2*100)}%):", 3),
            (f"Vol Música ({int(self.cfg_volume_music*100)}%):", 4),
            (f"Dificuldade: {self.cfg_difficulty}", 5),
            ("Mic 1 Device:", 6),
            ("Mic 2 Device:", 7),
        ]
        
        for text, idx in lbls:
            y = start_y + idx * gap_y
            s = font.render(text, True, COLOR_WHITE)
            self.screen.blit(s, (col_lbl_x, y))
            
        # Draw Controls (Simulação visual)
        
        # Checkboxes
        y_mon = start_y
        col_chk = COLOR_GREEN if self.cfg_monitoring else (100,100,100)
        pygame.draw.rect(self.screen, col_chk, (col_ctrl_x, y_mon, chk_size, chk_size))
        
        y_rhy = start_y + gap_y
        col_chk2 = COLOR_GREEN if self.show_rhythm_indicator else (100,100,100)
        pygame.draw.rect(self.screen, col_chk2, (col_ctrl_x, y_rhy, chk_size, chk_size))
        
        # Sliders (Linha + Bolinha)
        # Mic 1
        y_m1 = start_y + 2 * gap_y
        pygame.draw.rect(self.screen, (100,100,100), (col_ctrl_x, y_m1 + int(10*ui_scale), slider_w, line_h))
        pos_x1 = col_ctrl_x + (self.cfg_volume_mic1 / 2.0) * slider_w
        pygame.draw.circle(self.screen, COLOR_HIGHLIGHT, (int(pos_x1), y_m1 + int(12*ui_scale)), radius)
        
        # Mic 2
        y_m2 = start_y + 3 * gap_y
        pygame.draw.rect(self.screen, (100,100,100), (col_ctrl_x, y_m2 + int(10*ui_scale), slider_w, line_h))
        pos_x2 = col_ctrl_x + (self.cfg_volume_mic2 / 2.0) * slider_w
        pygame.draw.circle(self.screen, COLOR_HIGHLIGHT, (int(pos_x2), y_m2 + int(12*ui_scale)), radius)

        # Musica
        y_mus = start_y + 4 * gap_y
        pygame.draw.rect(self.screen, (100,100,100), (col_ctrl_x, y_mus + int(10*ui_scale), slider_w, line_h))
        pos_x_mus = col_ctrl_x + (self.cfg_volume_music) * slider_w
        pygame.draw.circle(self.screen, COLOR_HIGHLIGHT, (int(pos_x_mus), y_mus + int(12*ui_scale)), radius)
        
        # Dificuldade (Botão)
        y_dif = start_y + 5 * gap_y
        pygame.draw.rect(self.screen, (50,50,150), (col_ctrl_x, y_dif, int(200*ui_scale), btn_h_small))
        d_txt = font.render(self.cfg_difficulty.upper(), True, COLOR_WHITE)
        self.screen.blit(d_txt, (col_ctrl_x + int(20*ui_scale), y_dif + int(5*ui_scale)))
        
        # Mic 1 Sel
        def get_dev_name(idx):
            for d in self.available_devices:
                if d['index'] == idx: return d['name'][:40]
            return "Nenhum"

        y_d1 = start_y + 6 * gap_y
        pygame.draw.rect(self.screen, (50,50,50), (col_ctrl_x, y_d1, int(300*ui_scale), btn_h_small))
        n1 = font.render(get_dev_name(self.cfg_mic1_idx), True, COLOR_WHITE)
        self.screen.blit(n1, (col_ctrl_x + int(10*ui_scale), y_d1 + int(5*ui_scale)))
        
        # Mic 2 Sel
        y_d2 = start_y + 7 * gap_y
        pygame.draw.rect(self.screen, (50,50,50), (col_ctrl_x, y_d2, int(300*ui_scale), btn_h_small))
        n2 = font.render(get_dev_name(self.cfg_mic2_idx), True, COLOR_WHITE)
        self.screen.blit(n2, (col_ctrl_x + int(10*ui_scale), y_d2 + int(5*ui_scale)))
        
        # Background Mode
        lbl_bg = font.render("Modo Fundo:", True, COLOR_WHITE)
        y_bg = start_y + 8 * gap_y
        self.screen.blit(lbl_bg, (col_lbl_x, y_bg))
        
        pygame.draw.rect(self.screen, (100,0,100), (col_ctrl_x, y_bg, int(200*ui_scale), btn_h_small))
        bg_txt = font.render(self.cfg_bg_mode, True, COLOR_WHITE)
        self.screen.blit(bg_txt, (col_ctrl_x + int(20*ui_scale), y_bg + int(5*ui_scale)))
        
        # VU Meters na Config para teste
        # Mic 1
        v1 = int(min(150, int(self.scorer.current_volume_mic1 * 10)) * ui_scale)
        pygame.draw.rect(self.screen, COLOR_GREEN, (col_ctrl_x + int(320*ui_scale), y_d1, v1, btn_h_small))
        
        # Mic 2
        v2 = int(min(150, int(self.scorer.current_volume_mic2 * 10)) * ui_scale)
        pygame.draw.rect(self.screen, COLOR_GREEN, (col_ctrl_x + int(320*ui_scale), y_d2, v2, btn_h_small))


    def wrap_text(self, text, font, max_width):
        """Quebra texto em linhas que cabem em max_width."""
        words = text.split(' ')
        lines = []
        current_line = []
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            w, h = font.size(test_line)
            if w <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                    current_line = [word]
                else:
                    # Palavra sozinha maior que a largura (raro, mas evita loop)
                    lines.append(word)
                    current_line = []
        
        if current_line:
            lines.append(' '.join(current_line))
            
        return lines

    def draw_centered_text(self, text, y_offset=0, size=None, color=COLOR_WHITE):
        """
        Função auxiliar para desenhar texto centralizado com quebra de linha.
        """
        font = self.font_lyrics
        if size: font = pygame.font.Font(None, size)
        
        max_w = self.screen.get_width() - 100 # Margem
        lines = self.wrap_text(text, font, max_w)
        
        # Calcula altura total para centralizar o bloco
        line_height = font.get_linesize()
        total_height = len(lines) * line_height
        
        start_y = (self.screen.get_height() // 2) + y_offset - (total_height // 2)
        
        for i, line in enumerate(lines):
            surface = font.render(line, True, color)
            rect = surface.get_rect(center=(self.screen.get_width() // 2, start_y + i * line_height))
            self.screen.blit(surface, rect)

    def run(self):
        """Loop principal com tratamento de falhas."""
        try:
            running = True
            while running:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.VIDEORESIZE:
                         # Atualiza display surface
                         self.screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                         
                         # Calcula nova escala baseada na altura (768p base)
                         scale = event.h / 768.0
                         # Limita escala minima para não ficar ilegível
                         scale = max(0.8, scale)
                         
                         self.init_fonts(scale)
                         self.render_background() # Regenera background na nova resolução (mantendo cores)
                    self.handle_input(event)

                self.update()
                self.draw()
                self.clock.tick(FPS)
        except Exception as e:
            print(f"CRASH DETECTADO: {e}")
            import traceback
            traceback.print_exc()
        finally:
            print("Encerrando aplicação...")
            self.scorer.shutdown()
            pygame.quit()
            sys.exit()

if __name__ == "__main__":
    app = KaraokePlayer()
    app.run()
