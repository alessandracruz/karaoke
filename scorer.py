import pyaudio
import numpy as np
import threading
import time
import logging

# Configuração de Logs de Depuração
logging.basicConfig(
    filename='debug_audio.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filemode='w' # Sobrescreve a cada run
)

class Scorer:
    """
    Sistema de Pontuação (Scorer) Avançado.
    
    Gerencia:
    - Entrada de até 2 microfones simultâneos.
    - Monitoramento de áudio (Retorno nas caixas).
    - Ajuste de Latência (Buffer Size).
    - Controle de Volume por software.
    - Pontuação baseada em dificuldade (Fácil, Médio, Difícil).
    
    Tudo traduzido para Português.
    """
    def __init__(self, rate=44100, chunk=2048):
        logging.info("Inicializando Scorer...")
        self.rate = rate
        self.chunk = chunk # Tamanho do Buffer (Latência)
        self.p = pyaudio.PyAudio()
        
        # Streams
        self.stream_mic1 = None
        self.stream_mic2 = None
        self.stream_output = None # Para monitoramento
        self.output_channels = 2
        
        # Configurações
        self.input_device_index_1 = None
        self.input_device_index_2 = None
        
        self.volume_mic1 = 1.0 # 0.0 a 2.0 (multiplicador)
        self.volume_mic2 = 1.0
        
        self.monitoring_enabled = False
        self.difficulty = "Normal" # Fácil, Normal, Difícil
        
        # Estado
        self.running = False
        self.is_singing_segment = False
        self.restart_requested = False # Flag para thread safety

        # Inicializa variáveis de pontuação
        self.accuracy_window_size = 43 # ~2 segundos a 44.1k/2048
        
        # Inicializa volumes para evitar AttributeError antes do loop rodar
        self.current_volume_mic1 = 0
        self.current_volume_mic2 = 0
        
        self.paused = True # Começa pausado até iniciar música
        self.reset()

    def get_input_devices(self):
        """Retorna uma lista de dispositivos de entrada disponíveis."""
        devices = []
        try:
            info = self.p.get_host_api_info_by_index(0)
            numdevices = info.get('deviceCount')
            
            for i in range(0, numdevices):
                if (self.p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
                    name = self.p.get_device_info_by_host_api_device_index(0, i).get('name')
                    devices.append({'index': i, 'name': name})
        except Exception as e:
            logging.error(f"Erro ao listar dispositivos: {e}")
        return devices

    def set_config(self, device1_idx, device2_idx, monitoring, chunk_size, difficulty, vol1, vol2):
        """Atualiza configurações em tempo real (Sinaliza restart para a thread)."""
        need_restart = (
            self.input_device_index_1 != device1_idx or
            self.input_device_index_2 != device2_idx or
            self.monitoring_enabled != monitoring or
            self.chunk != chunk_size
        )
        
        self.input_device_index_1 = device1_idx
        self.input_device_index_2 = device2_idx
        self.monitoring_enabled = monitoring
        self.chunk = chunk_size
        self.difficulty = difficulty
        self.volume_mic1 = vol1
        self.volume_mic2 = vol2
        
        if need_restart and self.running:
            # NÃO chame stop_streams aqui. Isso causa Race Condition e Crash!
            # Apenas sinalize para a thread de áudio fazer isso no momento seguro.
            logging.info("Config mudou. Solicitando restart de streams na thread...")
            self.restart_requested = True

    def start(self):
        """Inicia a thread de processamento."""
        self.running = True
        self.thread = threading.Thread(target=self._process_audio)
        self.thread.start()

    def stop(self):
        """Para o processamento de áudio (thread), mas mantém PyAudio vivo."""
        self.running = False
        if hasattr(self, 'thread') and self.thread.is_alive():
            try:
                # Aguarda thread terminar com timeout para não travar a UI
                self.thread.join(timeout=1.0)
            except RuntimeError:
                pass
        self.stop_streams()
        # NÃO terminamos self.p aqui, pois queremos reusar a instância

    def shutdown(self):
        """Encera completamente o sistema de áudio (chamado ao fechar APP)."""
        self.stop()
        if self.p:
            self.p.terminate()

    def start_streams(self):
        """Abre os canais de áudio configurados."""
        logging.info(f"Tentando abrir streams. Mic1:{self.input_device_index_1}, Mic2:{self.input_device_index_2}, Mon:{self.monitoring_enabled}")
        try:
            # Mic 1
            if self.input_device_index_1 is not None:
                self.stream_mic1 = self.p.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=self.rate,
                    input=True,
                    input_device_index=self.input_device_index_1,
                    frames_per_buffer=self.chunk
                )
            
            # Mic 2
            if self.input_device_index_2 is not None and self.input_device_index_2 != self.input_device_index_1:
                 self.stream_mic2 = self.p.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=self.rate,
                    input=True,
                    input_device_index=self.input_device_index_2,
                    frames_per_buffer=self.chunk
                )
            
            # Saída (Monitoramento)
            if self.monitoring_enabled:
                self.stream_output = None
                self.output_channels = 2 # Default attempt
                
                # Log do dispositivo de saída padrão
                try:
                    default_out = self.p.get_default_output_device_info()
                    logging.info(f"Default Output Device: {default_out['name']} (Index: {default_out['index']})")
                except Exception as e:
                    logging.warning(f"Não foi possível obter info do Default Output: {e}")

                # Lista de tentativas: (Channels, Rate)
                attempts = [
                    (2, self.rate),       # Stereo @ 44.1k (Ideal)
                    (1, self.rate),       # Mono @ 44.1k
                    (2, 48000),           # Stereo @ 48k (Windows Default)
                    (1, 48000)            # Mono @ 48k
                ]
                
                logging.info(f"Tentando monitoramento: {attempts}")
                
                for channels, rate in attempts:
                    try:
                        self.stream_output = self.p.open(
                            format=pyaudio.paInt16,
                            channels=channels, 
                            rate=rate,
                            output=True,
                            frames_per_buffer=self.chunk
                        )
                        self.output_channels = channels
                        logging.info(f"Monitoramento SUCESSO: {channels}ch @ {rate}Hz")
                        break # Sucesso!
                    except Exception as e:
                        logging.warning(f"Tentativa falhou ({channels}ch, {rate}Hz): {e}")
                        continue # Tenta próximo
                
                if self.stream_output is None:
                     logging.error("Todas tentativas de monitoramento falharam.")
                     print(f"ALERTA: Monitoramento falhou em todas as tentativas de formato.")
                     self.monitoring_enabled = False
                
        except Exception as e:
            logging.critical(f"Erro ao abrir streams: {e}")
            print(f"Erro crítico ao iniciar streams de áudio: {e}")

    def stop_streams(self):
        """Fecha os streams abertos."""
        logging.info("Fechando streams...")
        if self.stream_mic1:
            try:
                self.stream_mic1.stop_stream()
                self.stream_mic1.close()
            except: pass
            self.stream_mic1 = None
        
        if self.stream_mic2:
            try:
                self.stream_mic2.stop_stream()
                self.stream_mic2.close()
            except: pass
            self.stream_mic2 = None

        if self.stream_output:
            try:
                self.stream_output.stop_stream()
                self.stream_output.close()
            except: pass
            self.stream_output = None

    def set_singing_segment(self, is_active):
        self.is_singing_segment = is_active
        
    def set_paused(self, paused):
        """Pausa ou resume o processamento de áudio de forma segura."""
        self.paused = paused
        logging.info(f"Audio Paused set to: {paused}")

    def _process_audio(self):
        """Loop principal de processamento de áudio (Leitura -> Mixagem -> Análise -> Escrita)."""
        logging.info("Iniciando loop _process_audio")
        self.start_streams()
        
        while self.running:
            # Checa Pause (Thread Safe stop)
            if self.paused:
                if self.stream_mic1 or self.stream_output:
                    self.stop_streams()
                time.sleep(0.1)
                continue

            # Checa solicitação de restart (Thread Safety)
            if self.restart_requested:
                logging.info("Process Audio: Restart solicitado. Reiniciando streams seguramente...")
                self.stop_streams()
                self.start_streams()
                self.restart_requested = False

            # Se streams estiverem fechados mas deveriam estar abertos (ex: inicio ou falha anterior)
            # Verifica apenas se Mic1 ou Mic2 estão configurados mas streams são None
            should_run = (self.input_device_index_1 is not None and self.stream_mic1 is None)
            if should_run and not self.restart_requested:
                 logging.info("Process Audio: Streams fechados. Tentando abrir...")
                 self.start_streams()

            data1 = np.zeros(self.chunk, dtype=np.int16)
            data2 = np.zeros(self.chunk, dtype=np.int16)
            
            # Ler Mic 1
            if self.stream_mic1:
                try:
                    raw_data = self.stream_mic1.read(self.chunk, exception_on_overflow=False)
                    data1 = np.frombuffer(raw_data, dtype=np.int16)
                except Exception as e:
                    # Logs de leitura podem ser frequentes, usar debug se necessario
                    pass

            # Ler Mic 2
            if self.stream_mic2:
                try:
                    raw_data = self.stream_mic2.read(self.chunk, exception_on_overflow=False)
                    data2 = np.frombuffer(raw_data, dtype=np.int16)
                except Exception:
                    pass
            
            # Aplicar Volume (Gain)
            # Converter para float para processamento, evitar clipping imediato
            float_d1 = data1.astype(np.float32) * self.volume_mic1
            float_d2 = data2.astype(np.float32) * self.volume_mic2
            
            # Calcular Volumes para VU Meter (RMS)
            self.current_volume_mic1 = np.linalg.norm(float_d1) / self.chunk if len(float_d1) > 0 else 0
            self.current_volume_mic2 = np.linalg.norm(float_d2) / self.chunk if len(float_d2) > 0 else 0
            
            # Mixagem para Monitoramento
            mixed_float = float_d1 + float_d2
            # Clipar
            mixed_audio_mono = np.clip(mixed_float, -32768, 32767).astype(np.int16)
            
            # Enviar para Saída (Monitoramento)
            if self.stream_output and self.monitoring_enabled:
                try:
                    output_data = mixed_audio_mono.tobytes()
                    
                    # Se saída for Stereo, duplicar canais
                    if getattr(self, 'output_channels', 2) == 2:
                         stereo_vals = np.column_stack((mixed_audio_mono, mixed_audio_mono)).ravel()
                         output_data = stereo_vals.tobytes()
                    
                    self.stream_output.write(output_data, exception_on_underflow=False)
                except Exception as e:
                    logging.critical(f"CRASH EVITADO: Erro no Write: {e}")
                    print(f"Erro no monitoramento: {e}")
                    self.monitoring_enabled = False 
                    pass
            
            # --- Lógica de Pontuação ---
            
            # Definir limiar baseado na Dificuldade
            threshold = 7.0 # Normal (Reduzido de 10.0)
            if self.difficulty == "Fácil":
                threshold = 1.5 # Fácil (Reduzido de 5.0 - Muito mais sensível)
            elif self.difficulty == "Difícil":
                threshold = 15.0 # Difícil (Reduzido de 20.0)
            
            # Analisar se houve "canto" (energia combinada acima do limiar)
            combined_vol = max(self.current_volume_mic1, self.current_volume_mic2 * 0.8) # Mic1 tem prioridade leve
            
            if self.is_singing_segment:
                self.total_samples += 1
                hit = 0
                if combined_vol > threshold:
                    self.hit_samples += 1
                    hit = 1
                
                # Atualizar janela deslizante de precisão
                self.recent_hits.append(hit)
                if len(self.recent_hits) > self.accuracy_window_size:
                    self.recent_hits.pop(0)

        logging.info("Loop _process_audio encerrado clean.")
        self.stop_streams()

    def get_score(self):
        """Retorna nota 0-100."""
        if self.total_samples == 0: return 0
        acc = (self.hit_samples / self.total_samples) * 100
        return int(min(100, acc))
        
    def get_current_accuracy(self):
        """Retorna a precisão instantânea (0.0 a 1.0) baseada nos últimos frames."""
        if not self.recent_hits: return 0.0
        return sum(self.recent_hits) / len(self.recent_hits)

    def reset(self):
        self.total_samples = 0
        self.hit_samples = 0
        self.recent_hits = []
