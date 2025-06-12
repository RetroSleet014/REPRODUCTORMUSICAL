import sys
import os
import random
import threading
import queue # Still need for general queue usage, though not explicitly used for sounddevice internal buffer
import time
import numpy as np
import traceback # Para imprimir el stack trace completo en caso de error

# Importaciones de PyQt
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QListWidget, QLabel, QFileDialog, QStyle,
    QSizePolicy, QSpacerItem, QLineEdit, QMenu, QMessageBox
)
from PyQt6.QtGui import QPalette, QColor, QPixmap, QImage, QIcon
from PyQt6.QtCore import Qt, QUrl, QVariant, QTimer, QEvent, QSettings, pyqtSignal

# Importar la ventana del ecualizador desde el archivo separado
from ecualizador import EqualizerWindow

# NUEVAS IMPORTACIONES para DSP (Reemplazan pydub y pyaudio)
# ASEGÚRATE DE HABERLAS INSTALADO EN TU ENTORNO LOCAL CON:
# pip install soundfile sounddevice scipy numpy
try:
    import soundfile as sf # Para leer/escribir archivos de audio
    import sounddevice as sd # Para la reproducción de audio de bajo nivel
    from scipy.signal import iirfilter, lfilter, freqz # Para diseño y aplicación de filtros
    print("Librerías DSP (SoundFile, SoundDevice, SciPy, NumPy) cargadas exitosamente.")
except ImportError as e:
    print(f"Advertencia: No se pudieron cargar todas las librerías DSP. El ecualizador no tendrá efecto audible. Error: {e}")
    # Define marcadores/dummies para que el código no falle si no se importan
    sf = None
    sd = None
    iirfilter = None
    lfilter = None
    # Clase dummy para simular stream de sounddevice si no se carga
    class DummySoundDevice:
        def __init__(self, *args, **kwargs): pass
        def start(self): pass
        def stop(self): pass
        def close(self): pass
        def write(self, data): pass
        def active(self): return False
        def query_devices(self): return "SoundDevice no disponible" # Add this for diagnostics
        def query_supported_settings(self, *args, **kwargs): return {'samplerate': 0, 'channels': 0, 'blocksize': 0} # Dummy
        def check_output_settings(self, *args, **kwargs): pass # Dummy
    if sd is None:
        sd = DummySoundDevice() # Asigna la clase dummy
        sd.OutputStream = DummySoundDevice # Asigna el OutputStream
    
    # Also create dummy functions for iirfilter and lfilter if not imported
    if iirfilter is None:
        def iirfilter(*args, **kwargs): return [1.0], [1.0]
    if lfilter is None:
        def lfilter(b, a, x, zi=None): 
            if zi is not None: return x, zi # Passthrough data and zi
            return x # Passthrough data
    
# Importaciones para metadatos (mutagen) - Mutagen sigue siendo útil
from mutagen.mp3 import MP3
from mutagen.id3 import ID3NoHeaderError, ID3, APIC
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis


class ClickableSlider(QSlider):
    """
    Un QSlider personalizado que permite al usuario saltar a una posición haciendo clic
    directamente en la barra del deslizador, además de arrastrarlo.
    """
    # Esta señal se emitirá cuando el valor del deslizador sea establecido por un clic directo
    clicked_value_set = pyqtSignal(int)

    def mousePressEvent(self, event):
        """
        Maneja el evento de presión del ratón. Si es un clic con el botón izquierdo,
        calcula la posición y establece el valor del deslizador.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            # Calcula el valor de la posición del clic
            if self.orientation() == Qt.Orientation.Horizontal:
                value = self.minimum() + ((self.maximum() - self.minimum()) * event.pos().x()) / self.width()
            else: # Vertical slider
                value = self.minimum() + ((self.maximum() - self.minimum()) * (self.height() - event.pos().y())) / self.height()
            
            # Establece el valor del deslizador
            self.setValue(int(value))
            
            # Emite la nueva señal para que MusicPlayer pueda reaccionar
            self.clicked_value_set.emit(int(value))
            
            event.accept()
        # Llama al método de la clase base. Esto es importante para permitir el comportamiento
        # predeterminado de QSlider (ej. establecer el estado "presionado", necesario
        # para eventos mouseMoveEvents posteriores si el usuario empieza a arrastrar).
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Maneja el evento de movimiento del ratón."""
        super().mouseMoveEvent(event)


class MusicPlayer(QMainWindow):
    # Modos de repetición
    NO_REPEAT = 0
    REPEAT_CURRENT = 1
    REPEAT_ALL = 2

    # Señales personalizadas para actualizar la UI desde otros hilos
    update_position_signal = pyqtSignal(int)
    update_duration_signal = pyqtSignal(int)
    update_playback_state_signal = pyqtSignal(str) # Ahora recibe un string para el estado

    # --- Métodos Auxiliares y de Configuración (Definidos antes de __init__) ---
    def set_dark_theme(self):
        """Configura la paleta de colores de la aplicación para un tema oscuro."""
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window, QColor(25, 25, 25))
        pal.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        pal.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 45))
        pal.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
        pal.setColor(QPalette.ColorRole.Button, QColor(35, 35, 35))
        pal.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        pal.setColor(QPalette.ColorRole.Highlight, QColor(80, 160, 220))
        pal.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
        self.setPalette(pal)

    def apply_styles(self):
        """Aplica estilos CSS personalizados a los widgets de la ventana principal."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1a1a;
            }
            QListWidget {
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 10px;
                color: #ddd;
                padding: 5px;
            }
            QListWidget::item {
                padding: 8px;
                margin-bottom: 2px;
                border-radius: 5px;
            }
            QListWidget::item:selected {
                background-color: #50b8f0;
                color: black;
            }
            QLabel {
                color: #ddd;
            }
            QLabel#albumArt {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 10px;
                qproperty-alignment: AlignCenter;
                color: #bbb;
                font-size: 16px;
            }
            QSlider::groove:horizontal {
                height: 8px;
                background: #555;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                width: 16px;
                height: 16px;
                background: #50b8f0;
                border-radius: 8px;
                margin: -4px 0;
            }
            QSlider::add-page:horizontal {
                background: #888;
            }
            QSlider::sub-page:horizontal {
                background: #50b8f0;
            }
            QSlider::groove:vertical {
                width: 8px;
                background: #555;
                border-radius: 4px;
            }
            QSlider::handle:vertical {
                width: 16px;
                height: 16px;
                background: #50b8f0;
                border-radius: 8px;
                margin: 0 -4px;
            }
            QSlider::add-page:vertical {
                background: #888;
            }
            QSlider::sub-page:vertical {
                background: #50b8f0;
            }
            QPushButton {
                background: #333;
                border: none;
                border-radius: 8px;
                padding: 10px 15px;
                color: white;
                font-size: 14px;
            }
            QPushButton:hover {
                background: #444;
            }
            QPushButton:pressed {
                background: #222;
            }
            QPushButton[checkable="true"][checked="true"] {
                background: #50b8f0;
            }
            QLineEdit {
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 8px;
                color: #ddd;
                padding: 8px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #50b8f0;
            }
        """)

    def _get_band_frequencies(self):
        """Define las frecuencias centrales para las 10 bandas del ecualizador."""
        return [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

    def _design_band_filter(self, center_freq, gain_db, Q_factor=1.0):
        """
        Diseña un filtro de pico (peaking EQ) para una banda específica.
        Devuelve los coeficientes (b, a) del filtro IIR.
        """
        if iirfilter is None or np is None or self.audio_samplerate == 0:
            return [1.0], [1.0]

        # Convierte ganancia de dB a lineal
        A = 10**(gain_db / 40.0)

        # Frecuencia angular normalizada
        w0 = 2 * np.pi * center_freq / self.audio_samplerate

        # Ancho de banda basado en Q_factor
        alpha = np.sin(w0) / (2 * Q_factor)

        # Coeficientes para el filtro de pico (peaking EQ)
        b0 = 1 + alpha * A
        b1 = -2 * np.cos(w0)
        b2 = 1 - alpha * A

        a0 = 1 + alpha / A
        a1 = -2 * np.cos(w0)
        a2 = 1 - alpha / A

        # Normaliza 'a' para que a0 sea 1
        b = np.array([b0, b1, b2]) / a0
        a = np.array([a0, a1, a2]) / a0

        return b, a

    def _update_ui_from_threads(self):
        """
        Este método es llamado por un QTimer para actualizar la UI
        de forma segura desde el hilo principal, usando los datos
        generados por los hilos de audio.
        """
        if self.total_frames > 0 and self.audio_samplerate > 0:
            current_ms = int((self.current_frame / self.audio_samplerate) * 1000)
            total_ms = int((self.total_frames / self.audio_samplerate) * 1000)
            self.update_position_signal.emit(current_ms)
            self.update_duration_signal.emit(total_ms)

        if self.playback_finished_event.is_set():
            print("DEBUG: UI Update: playback_finished_event detectado. Manejando fin de canción.")
            self.playback_finished_event.clear() # Limpia el evento inmediatamente para evitar re-procesamiento

            if self._repeat_mode == self.REPEAT_CURRENT:
                print("DEBUG: Repetir canción actual.")
                if self.current_playback_file:
                    self.load_and_play(self.current_playback_file, start_position_ms=0)
                else:
                    self.stop_playback(final_stop=True)
            elif self._repeat_mode == self.REPEAT_ALL:
                print("DEBUG: Repetir toda la playlist.")
                if self._shuffle_mode and self.shuffled_playlist:
                    current_shuffled_idx = self.current_shuffled_index
                    next_shuffled_idx = (current_shuffled_idx + 1) % len(self.shuffled_playlist)
                    
                    if next_shuffled_idx == 0 and current_shuffled_idx == len(self.shuffled_playlist) - 1:
                        # Si es el final de la playlist aleatoria y está en modo REPEAT_ALL
                        print("DEBUG: Fin de playlist aleatoria, reiniciando.")
                        self.rebuild_shuffled_playlist() # Opcional: reshuffle para una nueva secuencia
                        next_file = self.shuffled_playlist[0] # Empieza de nuevo
                        self.current_shuffled_index = 0
                    else:
                        next_file = self.shuffled_playlist[next_shuffled_idx]
                        self.current_shuffled_index = next_shuffled_idx
                    
                    self.load_and_play(next_file)
                    self.current_index = self.playlist.index(next_file) # Actualiza el índice normal para la UI
                    self.track_list.setCurrentRow(self.current_index)

                elif self.playlist: # No shuffle, REPEAT_ALL
                    current_idx = self.current_index
                    next_idx = (current_idx + 1) % len(self.playlist)
                    next_file = self.playlist[next_idx]

                    self.current_index = next_idx
                    self.load_and_play(next_file)
                    self.track_list.setCurrentRow(self.current_index)
                else:
                    self.stop_playback(final_stop=True) # Playlist vacía, detener

            else: # NO_REPEAT
                print("DEBUG: Fin de canción, no hay repetición. Deteniendo.")
                self.stop_playback(final_stop=True) 
                self.update_playback_state_signal.emit("StoppedState")

        elif self.stop_playback_event.is_set():
            print("DEBUG: UI Update: stop_playback_event detectado.")
            self.update_playback_state_signal.emit("StoppedState")
        elif self.pause_playback_event.is_set():
            print("DEBUG: UI Update: pause_playback_event detectado.")
            self.update_playback_state_signal.emit("PausedState")
        else:
            if self.audio_playback_thread and self.audio_playback_thread.is_alive():
                self.update_playback_state_signal.emit("PlayingState")
            else:
                self.update_playback_state_signal.emit("StoppedState")


    def set_and_save_volume(self, value):
        """
        Guarda el valor del volumen. El volumen real se aplicará en el hilo de salida de audio.
        """
        self.settings.setValue("last_volume", value)
        print(f"Volumen ajustado a: {value}%")

    def setup_keyboard_shortcuts(self):
        """Configura atajos de teclado globales."""
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        """Filtra eventos del teclado para atajos globales."""
        if event.type() == QEvent.Type.KeyPress:
            if QApplication.instance().focusWidget() == self.search_input and event.key() == Qt.Key.Key_Space:
                return False
            if event.key() == Qt.Key.Key_Space:
                self.toggle_play()
                return True
            elif event.key() == Qt.Key.Key_Right:
                target_pos_ms = (self.current_frame / self.audio_samplerate * 1000) + 5000
                self.seek_position_audio(target_pos_ms)
                return True
            elif event.key() == Qt.Key.Key_Left:
                target_pos_ms = (self.current_frame / self.audio_samplerate * 1000) - 5000
                self.seek_position_audio(target_pos_ms)
                return True
            elif event.key() == Qt.Key.Key_Up:
                current_volume = self.vol_slider.value()
                self.vol_slider.setValue(min(100, current_volume + 5))
                return True
            elif event.key() == Qt.Key.Key_Down:
                current_volume = self.vol_slider.value()
                self.vol_slider.setValue(max(0, current_volume - 5))
                return True
        return super().eventFilter(obj, event)

    def stop_player_during_seek(self):
        """
        Pausa la reproducción cuando el usuario comienza a arrastrar el slider de tiempo.
        """
        if self.is_playing:
            self.pause_playback_event.set() # Señaliza la pausa
            print("DEBUG: Seek: Reproducción pausada para buscar (arrastre).")

    def resume_player_after_seek(self):
        """
        Reanuda la reproducción si estaba sonando antes de que el usuario soltara el slider.
        """
        seek_ms = self.slider.value()
        print(f"DEBUG: Seek: Reanudando después de arrastre. Buscando a {seek_ms}ms...")
        # Limpiar la pausa, luego activar la búsqueda
        self.pause_playback_event.clear()
        self.seek_position_audio(seek_ms)


    def seek_position_audio(self, target_ms):
        """
        Mueve la posición de reproducción del audio.
        Para soundfile/sounddevice, esto implica reiniciar el stream desde la nueva posición.
        """
        if sf is None or sd is None or self.current_audio_data is None:
            print("DEBUG: Librerías DSP o datos de audio no disponibles para buscar.")
            return

        print(f"DEBUG: Buscando a {target_ms}ms...")

        target_frame = int((target_ms / 1000.0) * self.audio_samplerate)
        target_frame = max(0, min(target_frame, self.total_frames))

        # Captura el estado de reproducción ANTES de detener el hilo.
        # Si estaba reproduciendo, queremos reanudar la reproducción después de la búsqueda.
        # Si estaba pausado/detenido, queremos permanecer pausado/detenido después de la búsqueda (en la nueva posición).
        was_playing_before_seek_op = self.is_playing and not self.pause_playback_event.is_set()

        # Siempre detiene el hilo actual para prepararlo para el reinicio en la nueva posición.
        self.stop_playback(final_stop=False)
        print("DEBUG: seek_position_audio: stop_playback() completado.")

        self.current_frame = target_frame
        self.update_position_ui(target_ms)
        print(f"DEBUG: seek_position_audio: current_frame ajustado a {self.current_frame}.")

        if was_playing_before_seek_op:
            print("DEBUG: seek_position_audio: Era reproduciendo, reiniciando desde nueva posición.")
            # Pasa stop_current_playback=False porque ya lo detuvimos.
            self.load_and_play(self.current_playback_file, start_position_ms=target_ms, stop_current_playback=False)
        else:
            print("DEBUG: seek_position_audio: Estaba detenido/pausado, permaneciendo en ese estado en la nueva posición.")
            # Si estaba pausado/detenido, actualiza el estado de la UI en consecuencia (que podría haber sido reiniciado por stop_playback).
            self.update_playback_status_label("PausedState" if self.pause_playback_event.is_set() else "StoppedState")

    def update_position_ui(self, pos_ms):
        """Actualiza la posición del deslizador de tiempo y la etiqueta de tiempo transcurrido."""
        self.slider.blockSignals(True)
        self.slider.setValue(pos_ms)
        self.slider.blockSignals(False)
        s = pos_ms // 1000
        m, s = divmod(s, 60)
        self.lbl_elapsed.setText(f"{m:02d}:{s:02d}")

    def update_duration_ui(self, dur_ms):
        """Actualiza el rango máximo del deslizador de tiempo y la etiqueta de duración total."""
        self.slider.setRange(0, dur_ms)
        s = dur_ms // 1000
        m, s = divmod(s, 60)
        self.lbl_duration.setText(f"{m:02d}:{s:02d}")

    def update_metadata(self, file_path):
        """Extrae y muestra los metadatos (título, artista, álbum, pista) y la carátula."""
        title = os.path.splitext(os.path.basename(file_path))[0]
        artist = '-'
        album = '-'
        tracknum = '-'
        album_art_data = None
        
        # Ensure current_tracknum_raw is always defined in this scope
        current_tracknum_raw = tracknum 

        try:
            audio = None
            if file_path.lower().endswith('.mp3'):
                audio = MP3(file_path)
            elif file_path.lower().endswith('.flac'):
                audio = FLAC(file_path)
            elif file_path.lower().endswith(('.ogg', '.oga')):
                audio = OggVorbis(file_path)

            if audio and audio.tags:
                # Get Title
                title_tag = audio.tags.get('title')
                if isinstance(title_tag, list) and title_tag:
                    title = str(title_tag[0])
                elif 'TIT2' in audio.tags:
                    title = str(audio.tags.get('TIT2'))

                # Get Artist
                artist_tag = audio.tags.get('artist')
                if isinstance(artist_tag, list) and artist_tag:
                    artist = str(artist_tag[0])
                elif 'TPE1' in audio.tags:
                    artist = str(audio.tags.get('TPE1'))

                # Get Album
                album_tag = audio.tags.get('album')
                if isinstance(album_tag, list) and album_tag:
                    album = str(album_tag[0])
                elif 'TALB' in audio.tags:
                    album = str(audio.tags.get('TALB'))

                # Get Track Number
                tracknum_tag = audio.tags.get('tracknumber')
                if isinstance(tracknum_tag, list) and tracknum_tag:
                    current_tracknum_raw = str(tracknum_tag[0])
                elif 'TRCK' in audio.tags:
                    current_tracknum_raw = str(audio.tags.get('TRCK'))
                # If no tag is found, current_tracknum_raw remains its initialized value '-'

                if isinstance(audio.tags, ID3):
                    for k, v in audio.tags.items():
                        if k.startswith('APIC') and isinstance(v, APIC):
                            album_art_data = v.data
                            break
                elif hasattr(audio.tags, 'pictures') and audio.tags.pictures:
                    for pic in audio.tags.pictures:
                        if pic.type == 3: # Front Cover
                            album_art_data = pic.data
                            break

        except ID3NoHeaderError:
            print(f"Advertencia: No se encontraron etiquetas ID3 en {file_path}.")
        except Exception as e:
            print(f"Error general al leer metadatos de {file_path}: {e}")

        # Process current_tracknum_raw outside the try block
        if isinstance(current_tracknum_raw, str) and '/' in current_tracknum_raw:
            tracknum = current_tracknum_raw.split('/')[0]
        else:
            tracknum = str(current_tracknum_raw) # Ensure it's a string, even if '-'


        self.lbl_title.setText(f"Title: {title}")
        self.lbl_artist.setText(f"Artist: {artist}")
        self.lbl_album.setText(f"Album: {album}")
        self.lbl_track.setText(f"Track: {tracknum}")

        pix = None
        if album_art_data:
            image = QImage()
            if image.loadFromData(album_art_data):
                pix = QPixmap.fromImage(image)
            else:
                print("No se pudo cargar la imagen de la carátula desde los datos.")
        
        if pix and not pix.isNull():
            pix = pix.scaled(self.album_art.size(), Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            self.album_art.setPixmap(pix)
        else:
            self.album_art.clear()
            self.album_art.setText("No Album Art")

        self.update_window_title()

    def update_window_title(self):
        """Actualiza el título de la ventana principal."""
        current_title = "Modern PyQt6 Music Player"
        displayed_title_text = self.lbl_title.text()

        if displayed_title_text.startswith("Title: "):
            actual_title = displayed_title_text.replace("Title: ", "").strip()
            if actual_title and actual_title != "-":
                current_title = f"Playing: {actual_title} - Modern PyQt6 Music Player"
            elif self.current_playback_file:
                current_title = f"Playing: {os.path.basename(self.current_playback_file)} - Modern PyQt6 Music Player"
        elif self.current_playback_file:
             current_title = f"Playing: {os.path.basename(self.current_playback_file)} - Modern PyQt6 Music Player"

        self.setWindowTitle(current_title)

    def update_playback_status_label(self, state_str):
        """
        Actualiza la etiqueta de estado de reproducción en la interfaz de usuario.
        Acepta un string para el estado (ej. "PlayingState", "PausedState", "StoppedState").
        """
        if state_str == "PlayingState":
            self.lbl_status.setText("Status: Playing")
            self.lbl_status.setStyleSheet("color: #50f080; font-size: 12px; font-style: italic;")
        elif state_str == "PausedState":
            self.lbl_status.setText("Status: Paused")
            self.lbl_status.setStyleSheet("color: #f0c050; font-size: 12px; font-style: italic;")
        elif state_str == "StoppedState":
            self.lbl_status.setText("Status: Stopped")
            self.lbl_status.setStyleSheet("color: #aaa; font-size: 12px; font-style: italic;")
        else:
            self.lbl_status.setText("Status: Unknown")
            self.lbl_status.setStyleSheet("color: #aaa; font-size: 12px; font-style: italic;")

    def open_equalizer_window(self):
        """
        Abre la ventana del ecualizador como un diálogo modal.
        Pasa las configuraciones actuales y conecta la señal para recibir las nuevas.
        """
        dialog = EqualizerWindow(self, initial_settings=self.equalizer_settings)
        dialog.settings_applied.connect(self.apply_equalizer_settings)
        dialog.exec()

    def apply_equalizer_settings(self, settings):
        """
        Este método se llama cuando el usuario hace clic en "Apply" en la ventana del ecualizador.
        Guarda las nuevas configuraciones del ecualizador y recalcula los filtros.
        """
        self.equalizer_settings = settings
        self.settings.setValue("equalizer_settings", self.equalizer_settings)
        print(f"Configuraciones del ecualizador recibidas y guardadas: {self.equalizer_settings}")
        
        # Recalcular los coeficientes de los filtros con la nueva frecuencia de muestreo
        new_filters = []
        for i, gain_db in enumerate(self.equalizer_settings):
            new_filters.append(self._design_band_filter(self._get_band_frequencies()[i], gain_db))
        
        self.equalizer_filters = new_filters
        
        # Resetear los estados de los filtros para evitar artifacts de audio
        # Esto es crucial para que los filtros se apliquen correctamente a la nueva configuración
        # y no arrastren estados de la configuración anterior.
        # Asegurarse de que el número de canales en el estado de filtro coincida
        if self.audio_channels > 0: # Solo reinicializar si los canales ya se conocen
            # Re-inicializa los estados con el número de canales correcto
            self.filter_states = [np.zeros((max(len(b), len(a)) - 1, self.audio_channels)) for b, a in self.equalizer_filters]
        else:
            self.filter_states = [] # Mantener vacío si no hay audio cargado
        print("Filtros del ecualizador actualizados.")

    def add_files_to_playlist(self, files):
        """Añade los archivos de audio seleccionados a la playlist y actualiza la lista de la UI."""
        if files:
            for f in files:
                if f not in self.all_files:
                    self.all_files.append(f)
                    self.playlist.append(f)
                    
                    duration_string = "00:00"
                    if sf: # Solo intenta obtener duración si soundfile está disponible
                        try:
                            # Leer solo los metadatos para obtener la duración
                            info = sf.info(f)
                            total_seconds = int(info.duration)
                            minutes = total_seconds // 60
                            seconds = total_seconds % 60
                            duration_string = f"{minutes:02d}:{seconds:02d}"
                        except Exception as e:
                            print(f"Error al obtener la duración de {f} con soundfile: {e}")
                    
                    display_text = f"{os.path.basename(f)} ({duration_string})"
                    self.track_list.addItem(display_text)
            
            if self._shuffle_mode:
                self.rebuild_shuffled_playlist()

            if self.current_index == -1 and self.playlist:
                pass

    def open_files(self):
        """Abre un cuadro de diálogo para seleccionar archivos y los añade a la playlist."""
        files, _ = QFileDialog.getOpenFileNames(
            self, 'Open Music Files', '', 'Audio Files (*.mp3 *.wav *.ogg *.flac)'
        )
        if files:
            self.add_files_to_playlist(files)
            if files:
                last_path = os.path.dirname(files[0])
                self.settings.setValue("last_opened_path", last_path)
                self.settings.setValue("last_opened_song", files[0])
                self.settings.setValue("last_opened_position", 0)

    def open_folder(self):
        """Abre un cuadro de diálogo para seleccionar una carpeta y escanea archivos."""
        folder_path = QFileDialog.getExistingDirectory(self, 'Open Music Folder')
        if folder_path:
            self.scan_folder_recursive(folder_path)
            self.settings.setValue("last_opened_path", folder_path)
            self.settings.setValue("last_opened_song", "")
            self.settings.setValue("last_opened_position", 0)

    def scan_folder_recursive(self, folder_path):
        """Escanea una carpeta y sus subcarpetas en busca de archivos de audio."""
        supported_extensions = ('.mp3', '.wav', '.ogg', '.oga', '.flac')
        found_files = []
        for root, _, files in os.walk(folder_path):
            for file in files:
                if file.lower().endswith(supported_extensions):
                    full_path = os.path.join(root, file)
                    found_files.append(full_path)
        self.add_files_to_playlist(found_files)

    def save_playlist(self):
        """Guarda la playlist actual en un archivo M3U."""
        if not self.playlist:
            self._show_message_box("Info", "No hay canciones en la playlist para guardar.")
            return

        file_name, _ = QFileDialog.getSaveFileName(
            self, 'Save Playlist', '', 'M3U Playlists (*.m3u);;All Files (*)'
        )
        if file_name:
            try:
                with open(file_name, 'w', encoding='utf-8') as f:
                    f.write("#EXTM3U\n")
                    for file_path in self.playlist:
                        f.write(file_path + "\n")
                self._show_message_box("Éxito", f"Playlist guardada en: {file_name}")
            except Exception as e:
                self._show_message_box("Error", f"Error al guardar la playlist: {e}")

    def load_playlist(self):
        """Carga canciones desde un archivo M3U a la playlist."""
        file_name, _ = QFileDialog.getOpenFileName(
            self, 'Load Playlist', '', 'M3U Playlists (*.m3u);;All Files (*)'
        )
        if file_name:
            loaded_files = []
            try:
                with open(file_name, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            if os.path.isabs(line):
                                if os.path.exists(line):
                                    loaded_files.append(line)
                                else:
                                    print(f"Advertencia: Archivo no encontrado al cargar playlist: {line}")
                            else:
                                m3u_dir = os.path.dirname(file_name)
                                abs_path = os.path.join(m3u_dir, line)
                                if os.path.exists(abs_path):
                                    loaded_files.append(abs_path)
                                else:
                                    print(f"Advertencia: Archivo relativo no encontrado al cargar playlist: {line} (buscado en {abs_path})")
                
                if loaded_files:
                    self.stop_playback()
                    self.playlist.clear()
                    self.track_list.clear()
                    self.all_files.clear()
                    self.current_index = -1
                    self.current_shuffled_index = -1
                    self.add_files_to_playlist(loaded_files)
                    self._show_message_box("Éxito", f"Playlist cargada desde: {file_name}")

                    self.settings.setValue("last_opened_path", os.path.dirname(file_name))
                    self.settings.setValue("last_opened_song", "")
                    self.settings.setValue("last_opened_position", 0)
                else:
                    self._show_message_box("Info", "No se encontraron canciones válidas en la playlist.")
            except Exception as e:
                self._show_message_box("Error", f"Error al cargar la playlist: {e}")

    def remove_selected_tracks(self):
        """Elimina las pistas seleccionadas de la QListWidget y de las listas de reproducción internas."""
        selected_items = self.track_list.selectedItems()
        if not selected_items:
            self._show_message_box("Info", "No hay canciones seleccionadas para eliminar.")
            return

        indices_to_remove = sorted([self.track_list.row(item) for item in selected_items], reverse=True)
        
        current_playing_file = self.current_playback_file
        stop_current_playback = False

        for idx in indices_to_remove:
            file_path = self.playlist[idx]
            if file_path == current_playing_file:
                stop_current_playback = True

            self.track_list.takeItem(idx)
            self.playlist.pop(idx)
            if file_path in self.all_files: self.all_files.remove(file_path)
            if file_path in self.shuffled_playlist: self.shuffled_playlist.remove(file_path)
        
        if stop_current_playback:
            self.stop_playback(final_stop=True) # Es una parada definitiva
            self._show_message_box("Info", "La canción actual fue eliminada. Reproducción detenida.")

        if self.current_index >= len(self.playlist):
            self.current_index = len(self.playlist) - 1
            if self.current_index == -1:
                self.stop_playback(final_stop=True)
                self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
                self.update_window_title()
                self.album_art.clear()
                self.album_art.setText("No Album Art")
                self.lbl_title.setText("Title: -")
                self.lbl_artist.setText("Artist: -")
                self.lbl_album.setText("Album: -")
                self.lbl_track.setText("Track: -")
                self.slider.setRange(0, 0)
                self.slider.setValue(0)
                self.lbl_elapsed.setText("00:00")
                self.lbl_duration.setText("00:00")
                self.update_playback_status_label("StoppedState")
                return

        if self._shuffle_mode:
            self.rebuild_shuffled_playlist()
            if self.current_playback_file and self.current_playback_file in self.shuffled_playlist:
                self.current_shuffled_index = self.shuffled_playlist.index(self.current_playback_file)
            else:
                self.current_shuffled_index = -1

        print("Pistas seleccionadas eliminadas.")

    def clear_playlist(self):
        """Vacía completamente la lista de reproducción, detiene la reproducción y resetea la UI."""
        if not self.playlist:
            self._show_message_box("Info", "La playlist ya está vacía.")
            return

        self.stop_playback(final_stop=True)
        self.playlist.clear()
        self.shuffled_playlist.clear()
        self.all_files.clear()
        self.track_list.clear()
        self.current_index = -1
        self.current_shuffled_index = -1

        self.lbl_title.setText("Title: -")
        self.lbl_artist.setText("Artist: -")
        self.lbl_album.setText("Album: -")
        self.lbl_track.setText("Track: -")
        self.album_art.clear()
        self.album_art.setText("No Album Art")
        self.slider.setRange(0, 0)
        self.slider.setValue(0)
        self.lbl_elapsed.setText("00:00")
        self.lbl_duration.setText("00:00")
        
        self.update_window_title()
        self.update_playback_status_label("StoppedState")

        self._show_message_box("Info", "Playlist vaciada.")

    def move_track_up(self):
        """Mueve la pista seleccionada una posición hacia arriba en la playlist y en la UI."""
        current_row = self.track_list.currentRow()
        if current_row > 0:
            item = self.track_list.takeItem(current_row)
            self.track_list.insertItem(current_row - 1, item)
            self.track_list.setCurrentRow(current_row - 1)

            track_to_move = self.playlist.pop(current_row)
            self.playlist.insert(current_row - 1, track_to_move)

            if self.current_index == current_row:
                self.current_index -= 1
            elif self.current_index == current_row + 1:
                self.current_index -= 1
            
            if self._shuffle_mode:
                self.rebuild_shuffled_playlist()
                if self.current_playback_file in self.shuffled_playlist:
                    self.current_shuffled_index = self.shuffled_playlist.index(self.current_playback_file)

    def move_track_down(self):
        """Mueve la pista seleccionada una posición hacia abajo en la playlist y en la UI."""
        current_row = self.track_list.currentRow()
        if current_row != -1 and current_row < len(self.playlist) - 1:
            item = self.track_list.takeItem(current_row)
            self.track_list.insertItem(current_row + 1, item)
            self.track_list.setCurrentRow(current_row + 1)

            track_to_move = self.playlist.pop(current_row)
            self.playlist.insert(current_row + 1, track_to_move)

            if self.current_index == current_row:
                self.current_index += 1
            elif self.current_index == current_row + 1:
                self.current_index -= 1

            if self._shuffle_mode:
                self.rebuild_shuffled_playlist()
                if self.current_playback_file in self.shuffled_playlist:
                    self.current_shuffled_index = self.shuffled_playlist.index(self.current_playback_file)

    def load_and_play(self, file_path, start_position_ms=0, stop_current_playback=True):
        """
        Carga y reproduce la canción especificada usando soundfile y sounddevice.
        Inicia el hilo de reproducción/procesamiento.
        :param file_path: Ruta al archivo de audio.
        :param start_position_ms: Posición de inicio en milisegundos.
        :param stop_current_playback: Si es True, detiene la reproducción actual antes de cargar la nueva.
                                      Establecer a False si ya fue detenida por la función llamante (ej. seek).
        """
        if sf is None or sd is None:
            self._show_message_box("Error", "Las librerías DSP (SoundFile, SoundDevice) no están cargadas. El reproductor no puede funcionar.")
            self.update_playback_status_label("StoppedState")
            return

        if not file_path or not os.path.exists(file_path):
            self._show_message_box("Error", f"Ruta de archivo inválida o no encontrada: {file_path}")
            self.update_playback_status_label("StoppedState")
            return
        
        # Detener cualquier reproducción en curso (para la canción anterior, si la había)
        if stop_current_playback:
            print("DEBUG: load_and_play: Llamando stop_playback para limpiar reproducción anterior.")
            # La parada no es definitiva, solo para preparar la nueva carga
            self.stop_playback(final_stop=False) 

        try:
            self.current_playback_file = file_path
            data, samplerate = sf.read(file_path, dtype='float32') 

            if data.ndim == 1: 
                self.current_audio_data = np.stack([data, data], axis=-1)
            else:
                self.current_audio_data = data
            
            self.audio_samplerate = samplerate
            self.audio_channels = self.current_audio_data.shape[1] 

            self.total_frames = len(self.current_audio_data) 
            self.current_frame = int((start_position_ms / 1000.0) * self.audio_samplerate) 
            self.current_frame = max(0, min(self.current_frame, self.total_frames))
            print(f"DEBUG: load_and_play: current_frame after setting based on start_position_ms: {self.current_frame}")

            # Reiniciar eventos de hilos
            self.stop_playback_event.clear()
            self.pause_playback_event.clear() # Asegurarse de que el evento de pausa esté claro al iniciar la reproducción
            self.playback_finished_event.clear()
            print("DEBUG: load_and_play: Eventos de hilo reseteados.")

            # Reiniciar estados de los filtros (importante al cargar nueva canción)
            if self.audio_channels > 0: 
                self.filter_states = [np.zeros((max(len(b), len(a)) - 1, self.audio_channels)) for b, a in self.equalizer_filters]
            else:
                self.filter_states = [] 
            print("DEBUG: load_and_play: Estados de filtro reseteados.")

            # Iniciar el hilo de reproducción/procesamiento de audio
            print("DEBUG: load_and_play: Iniciando nuevo hilo de audio.")
            self.audio_playback_thread = threading.Thread(target=self._audio_playback_thread_main, daemon=True)
            self.audio_playback_thread.start()

            self.is_playing = True
            self.ui_update_timer.start()

            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
            
            try:
                self.current_index = self.playlist.index(file_path)
                self.track_list.setCurrentRow(self.current_index)
            except ValueError:
                self.current_index = -1
            self.update_metadata(file_path)
            self.update_playback_status_label("PlayingState")
            print(f"DEBUG: load_and_play: Preparada y lista para reproducir: {os.path.basename(file_path)}")

        except Exception as e:
            print(f"ERROR: load_and_play: No se pudo reproducir el archivo: {e}")
            self._show_message_box("Error de Reproducción", f"No se pudo reproducir el archivo: {e}")
            self.stop_playback(final_stop=True) # Si hay un error, sí es una parada final
            self.update_playback_status_label("StoppedState")

    def _audio_playback_thread_main(self):
        """
        Hilo principal que maneja la lectura, el procesamiento DSP y la salida de audio.
        """
        if sd is None or self.current_audio_data is None:
            print("ERROR: _audio_playback_thread_main: sd o current_audio_data es None al iniciar el hilo.")
            self.playback_finished_event.set() 
            return

        print("DEBUG: _audio_playback_thread_main: Hilo de reproducción de audio iniciado.")
        
        blocksize = 1024 

        try:
            print(f"DEBUG: _audio_playback_thread_main: Intentando abrir stream con samplerate={self.audio_samplerate}, channels={self.audio_channels}, blocksize={blocksize}, device_index={self.selected_output_device_index}")
            try:
                sd.check_output_settings(
                    device=self.selected_output_device_index,
                    samplerate=self.audio_samplerate,
                    channels=self.audio_channels,
                    dtype='float32'
                )
                print("DEBUG: _audio_playback_thread_main: Configuración de salida de audio verificada: soportada.")
            except sd.PortAudioError as pa_err:
                print(f"ERROR: _audio_playback_thread_main: ERROR DE CONFIGURACIÓN DE SALIDA: {pa_err}")
                self.playback_finished_event.set()
                return

            with sd.OutputStream(device=self.selected_output_device_index, 
                                 samplerate=self.audio_samplerate,
                                 channels=self.audio_channels,
                                 dtype='float32',
                                 blocksize=blocksize) as stream:
                self.audio_stream = stream 
                stream.start() 
                print("DEBUG: _audio_playback_thread_main: Stream de audio de sounddevice iniciado.")

                current_frame_pos = self.current_frame 
                print(f"DEBUG: _audio_playback_thread_main: Starting playback from current_frame_pos: {current_frame_pos}")
                print_counter = 0 
                # Print interval, if total_frames is very small (e.g., a few blocks)
                # Ensure print_interval doesn't become 0, min 1
                print_interval = max(1, self.total_frames // blocksize // 20) # print about 20 times per song
                if self.total_frames < blocksize * 20: # For very short songs, print more often
                    print_interval = 1


                while not self.stop_playback_event.is_set():
                    # PAUSE LOGIC: While the pause_playback_event is set, keep the thread waiting.
                    while self.pause_playback_event.is_set():
                        print("DEBUG: _audio_playback_thread_main: Hilo pausado. Durmiendo...")
                        time.sleep(0.05) # Sleep for 50ms to avoid busy-waiting
                        if self.stop_playback_event.is_set(): # Check for stop signal while paused
                            print("DEBUG: _audio_playback_thread_main: Stop detectado durante pausa. Saliendo.")
                            break # Break from inner while loop to exit thread
                    
                    # If the outer loop's condition was met (stop_playback_event is set)
                    if self.stop_playback_event.is_set(): 
                        print("DEBUG: _audio_playback_thread_main: stop_playback_event detectado después de pausa. Saliendo.")
                        break # Break from outer while loop

                    if current_frame_pos >= self.total_frames:
                        print("DEBUG: _audio_playback_thread_main: Fin de la canción (current_frame_pos >= total_frames). Señalando finalización.")
                        self.playback_finished_event.set()
                        break 

                    frames_to_read = min(blocksize, self.total_frames - current_frame_pos)
                    # If frames_to_read is 0 or negative, it means we are at the end, break
                    if frames_to_read <= 0:
                        print("DEBUG: _audio_playback_thread_main: No más frames para leer. Fin de la canción.")
                        self.playback_finished_event.set()
                        break

                    input_block = self.current_audio_data[current_frame_pos : current_frame_pos + frames_to_read]

                    if len(input_block) < blocksize:
                        padding = np.zeros((blocksize - len(input_block), self.audio_channels), dtype='float32')
                        input_block = np.vstack((input_block, padding))
                        print(f"DEBUG: _audio_playback_thread_main: Bloque de audio rellenado. Original: {frames_to_read}, con padding: {len(input_block)}")

                    processed_block = input_block.copy() 
                    current_filter_states = [arr.copy() for arr in self.filter_states] 
                    current_equalizer_filters = list(self.equalizer_filters) 

                    for i, (b, a) in enumerate(current_equalizer_filters):
                        # Only apply filter if it's not a passthrough (b=[1], a=[1])
                        if not (len(b) == 1 and np.isclose(b[0], 1.0) and len(a) == 1 and np.isclose(a[0], 1.0)):
                            for channel_idx in range(self.audio_channels):
                                if current_filter_states[i].shape[0] > 0: 
                                    zi_channel = current_filter_states[i][:, channel_idx] 
                                else:
                                    zi_channel = None 

                                processed_block[:, channel_idx], updated_zi = \
                                    lfilter(b, a, processed_block[:, channel_idx], zi=zi_channel)
                                
                                if updated_zi is not None:
                                    current_filter_states[i][:, channel_idx] = updated_zi 
                    
                    self.filter_states = current_filter_states 

                    current_volume_linear = self.settings.value("last_volume", 50, type=int) / 100.0
                    output_block = processed_block * current_volume_linear

                    output_block = np.clip(output_block, -1.0, 1.0)

                    stream.write(output_block)
                    
                    current_frame_pos += frames_to_read
                    self.current_frame = current_frame_pos 
                    
                    print_counter += 1
                    if print_counter % print_interval == 0 or current_frame_pos >= self.total_frames:
                        print(f"DEBUG: _audio_playback_thread_main: Escribiendo frames. Pos: {self.current_frame}/{self.total_frames}. Vol: {self.vol_slider.value()}%")


                stream.stop() 
                print("DEBUG: _audio_playback_thread_main: Stream de audio de sounddevice detenido explícitamente.")

        except Exception as e:
            print(f"ERROR: _audio_playback_thread_main: Error fatal en hilo de reproducción de audio: {e}")
            self.playback_finished_event.set() 
        finally:
            print("DEBUG: _audio_playback_thread_main: Hilo de reproducción de audio finalizado (finally block).")

    def stop_playback(self, final_stop=True):
        """
        Detiene la reproducción de audio y termina el hilo de reproducción.
        :param final_stop: True si es una parada definitiva (fin de canción, cierre de app),
                           False si es una parada temporal (para buscar o cambiar canción).
        """
        print("DEBUG: stop_playback: Iniciando proceso de detención.")
        if self.ui_update_timer.isActive():
            self.ui_update_timer.stop()
            print("DEBUG: stop_playback: UI Timer detenido.")

        self.stop_playback_event.set() # Signal the audio thread to stop
        self.pause_playback_event.clear() # Ensure not paused (so it can respond to stop_playback_event)
        print("DEBUG: stop_playback: Eventos de detención y pausa configurados.")

        # Save player state only if a song was actually loaded and playing/paused
        # And only if current_playback_file is not None and exists
        if self.current_playback_file and os.path.exists(self.current_playback_file) and self.total_frames > 0:
            self.save_player_state_on_stop("StoppedState" if final_stop else "SeekingStop")
        else:
            print("DEBUG: stop_playback: No se guarda el estado del reproductor (no hay canción activa).")

        if self.audio_playback_thread and self.audio_playback_thread.is_alive():
            print("DEBUG: stop_playback: Esperando que el hilo de audio termine...")
            self.audio_playback_thread.join(timeout=1.0) 
            if self.audio_playback_thread.is_alive(): 
                print("Advertencia: El hilo de reproducción de audio no terminó a tiempo.")
            else:
                print("DEBUG: stop_playback: El hilo de reproducción de audio ha terminado limpiamente.")
        else:
            print("DEBUG: stop_playback: No hay hilo de audio activo para detener.")


        self.stop_playback_event.clear() 
        self.playback_finished_event.clear() 
        self.is_playing = False 

        # Limpiar estos datos solo si es una parada definitiva
        if final_stop:
            self.current_frame = 0
            self.total_frames = 0
            self.current_playback_file = None 
            self.current_audio_data = None 

        self.update_position_ui(0 if final_stop else int((self.current_frame / self.audio_samplerate) * 1000) if self.audio_samplerate > 0 else 0)
        self.update_duration_ui(0 if final_stop else int((self.total_frames / self.audio_samplerate) * 1000) if self.audio_samplerate > 0 else 0)
        self.update_playback_status_label("StoppedState")
        self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))

        print("DEBUG: Reproducción detenida y hilos terminados (fin de stop_playback).")

    # Métodos de funcionalidad del reproductor
    def toggle_play(self):
        """Alterna entre reproducir y pausar la canción actual."""
        if not self.playlist:
            self._show_message_box("Info", "La playlist está vacía. Añade canciones para reproducir.")
            return

        if self.current_playback_file is None:
            # If nothing is playing, start from the first song or the last saved
            if self.current_index == -1 and self.playlist:
                self.current_index = 0
            if self.playlist:
                file_to_play = self.playlist[self.current_index]
                self.load_and_play(file_to_play, start_position_ms=0)
            else:
                return # No songs to play

        elif self.is_playing:
            self.pause_playback_event.set()
            self.is_playing = False
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            self.update_playback_status_label("PausedState")
            print("DEBUG: Pausado.")
        else:
            self.pause_playback_event.clear() # Resume
            self.is_playing = True
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
            self.update_playback_status_label("PlayingState")
            print("DEBUG: Reanudado.")

    def prev_track(self):
        """Reproduce la pista anterior en la playlist."""
        if not self.playlist: return
        self.stop_playback(final_stop=False) # Stop current track to allow seamless transition

        if self._shuffle_mode and self.shuffled_playlist:
            self.current_shuffled_index = (self.current_shuffled_index - 1) % len(self.shuffled_playlist)
            next_file = self.shuffled_playlist[self.current_shuffled_index]
            self.load_and_play(next_file)
            self.current_index = self.playlist.index(next_file) # Update normal index for UI selection
            self.track_list.setCurrentRow(self.current_index)
        else:
            self.current_index = (self.current_index - 1 + len(self.playlist)) % len(self.playlist)
            self.load_and_play(self.playlist[self.current_index])
            self.track_list.setCurrentRow(self.current_index)

    def next_track(self):
        """Reproduce la siguiente pista en la playlist."""
        if not self.playlist: return
        self.stop_playback(final_stop=False) # Stop current track to allow seamless transition

        if self._repeat_mode == self.REPEAT_CURRENT:
            # If repeating current, just replay the same song
            self.load_and_play(self.current_playback_file or self.playlist[self.current_index])
            return

        if self._shuffle_mode and self.shuffled_playlist:
            self.current_shuffled_index = (self.current_shuffled_index + 1) % len(self.shuffled_playlist)
            next_file = self.shuffled_playlist[self.current_shuffled_index]
            self.load_and_play(next_file)
            self.current_index = self.playlist.index(next_file) # Update normal index for UI selection
            self.track_list.setCurrentRow(self.current_index)
        else:
            self.current_index = (self.current_index + 1) % len(self.playlist)
            self.load_and_play(self.playlist[self.current_index])
            self.track_list.setCurrentRow(self.current_index)

    def toggle_shuffle_mode(self):
        """Activa/desactiva el modo aleatorio."""
        self._shuffle_mode = not self._shuffle_mode
        self.btn_shuffle.setChecked(self._shuffle_mode)
        if self._shuffle_mode:
            self.rebuild_shuffled_playlist()
            self._show_message_box("Modo Aleatorio", "Reproducción aleatoria activada.")
        else:
            # If shuffle is off, reset to the current song's position in the original playlist
            if self.current_playback_file and self.current_playback_file in self.playlist:
                self.current_index = self.playlist.index(self.current_playback_file)
                self.track_list.setCurrentRow(self.current_index)
            self._show_message_box("Modo Aleatorio", "Reproducción aleatoria desactivada.")

    def rebuild_shuffled_playlist(self):
        """Reconstruye la playlist aleatoria manteniendo la canción actual (si la hay)."""
        if not self.playlist:
            self.shuffled_playlist = []
            return

        current_song = self.current_playback_file
        temp_playlist = list(self.playlist)

        if current_song and current_song in temp_playlist:
            temp_playlist.remove(current_song)
            random.shuffle(temp_playlist)
            self.shuffled_playlist = [current_song] + temp_playlist
            self.current_shuffled_index = 0
        else:
            random.shuffle(temp_playlist)
            self.shuffled_playlist = temp_playlist
            self.current_shuffled_index = self.playlist.index(self.current_playback_file) if self.current_playback_file in self.playlist else 0
        print("DEBUG: Playlist aleatoria reconstruida.")

    def toggle_repeat_mode(self):
        """Cambia entre los modos de repetición (desactivado, repetir canción actual, repetir todo)."""
        self._repeat_mode = (self._repeat_mode + 1) % 3
        if self._repeat_mode == self.NO_REPEAT:
            self.btn_repeat.setIcon(self.icon_repeat_off)
            self._show_message_box("Modo Repetición", "Repetición desactivada.")
        elif self._repeat_mode == self.REPEAT_CURRENT:
            self.btn_repeat.setIcon(self.icon_repeat_single)
            self._show_message_box("Modo Repetición", "Repetir canción actual.")
        else: # REPEAT_ALL
            self.btn_repeat.setIcon(self.icon_repeat_all)
            self._show_message_box("Modo Repetición", "Repetir toda la playlist.")

    def play_selected(self):
        """Reproduce la canción seleccionada en la lista."""
        selected_items = self.track_list.selectedItems()
        if selected_items:
            # Get the actual file path from the playlist based on the selected row
            index = self.track_list.row(selected_items[0])
            if 0 <= index < len(self.playlist):
                selected_file_path = self.playlist[index]
                self.current_index = index
                self.load_and_play(selected_file_path)
            else:
                self._show_message_box("Error", "La selección no es válida. Por favor, selecciona una canción de la lista.")
        else:
            self._show_message_box("Info", "Ninguna canción seleccionada para reproducir.")

    def filter_track_list(self, text):
        """Filtra la lista de pistas basándose en el texto de búsqueda."""
        if not text:
            for i in range(self.track_list.count()):
                self.track_list.item(i).setHidden(False)
        else:
            for i in range(self.track_list.count()):
                item = self.track_list.item(i)
                file_path = self.playlist[i] # Get the original file path
                
                # Extract metadata for a more robust search
                title = os.path.splitext(os.path.basename(file_path))[0]
                artist = ''
                album = ''
                try:
                    audio = None
                    if file_path.lower().endswith('.mp3'): audio = MP3(file_path)
                    elif file_path.lower().endswith('.flac'): audio = FLAC(file_path)
                    elif file_path.lower().endswith(('.ogg', '.oga')): audio = OggVorbis(file_path)

                    if audio and audio.tags:
                        if 'title' in audio.tags and isinstance(audio.tags['title'], list):
                            title = str(audio.tags['title'][0])
                        elif 'TIT2' in audio.tags:
                            title = str(audio.tags['TIT2'])

                        if 'artist' in audio.tags and isinstance(audio.tags['artist'], list):
                            artist = str(audio.tags['artist'][0])
                        elif 'TPE1' in audio.tags:
                            artist = str(audio.tags['TPE1'])

                        if 'album' in audio.tags and isinstance(audio.tags['album'], list):
                            album = str(audio.tags['album'][0])
                        elif 'TALB' in audio.tags:
                            album = str(audio.tags['TALB'])

                except Exception:
                    pass # Ignore errors, fall back to filename

                search_string = f"{title} {artist} {album} {os.path.basename(file_path)}".lower()
                if text.lower() in search_string:
                    item.setHidden(False)
                else:
                    item.setHidden(True)

    def show_context_menu(self, position):
        """Muestra un menú contextual para la lista de pistas."""
        menu = QMenu()
        play_action = menu.addAction("Play")
        remove_action = menu.addAction("Remove")
        clear_all_action = menu.addAction("Clear All")
        
        action = menu.exec(self.track_list.mapToGlobal(position))
        
        if action == play_action:
            self.play_selected()
        elif action == remove_action:
            self.remove_selected_tracks()
        elif action == clear_all_action:
            self.clear_playlist()

    def _show_message_box(self, title, message):
        """Muestra un cuadro de mensaje simple (reemplazo para alert/confirm)."""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.setStyleSheet("""
            QMessageBox {
                background-color: #2b2b2b;
                color: #ddd;
                font-size: 14px;
            }
            QMessageBox QLabel {
                color: #ddd;
            }
            QMessageBox QPushButton {
                background: #333;
                border: none;
                border-radius: 5px;
                padding: 5px 10px;
                color: white;
            }
            QMessageBox QPushButton:hover {
                background: #444;
            }
        """)
        msg_box.exec()

    def load_last_session_state(self):
        """Carga la última ruta abierta y la última canción reproducida."""
        last_path = self.settings.value("last_opened_path", "")
        last_song = self.settings.value("last_opened_song", "")
        last_position = self.settings.value("last_opened_position", 0, type=int)

        if last_path and os.path.exists(last_path):
            print(f"Cargando la última ruta abierta: {last_path}")
            if os.path.isdir(last_path):
                self.scan_folder_recursive(last_path)
            elif os.path.isfile(last_path):
                self.add_files_to_playlist([last_path])
        
        if last_song and os.path.exists(last_song):
            if last_song in self.playlist:
                self.current_index = self.playlist.index(last_song)
                self.track_list.setCurrentRow(self.current_index)
                self.update_metadata(last_song)
                self.update_position_ui(last_position)
                print(f"Última canción preparada: {os.path.basename(last_song)} desde {last_position}ms")
            else:
                print(f"Advertencia: La última canción '{last_song}' no se encontró en la playlist cargada.")
        elif self.playlist:
            # If no last song, select the first one
            self.current_index = 0
            self.track_list.setCurrentRow(self.current_index)
            self.update_metadata(self.playlist[self.current_index])
            self.update_position_ui(0)
            print(f"Seleccionada primera canción de la playlist: {os.path.basename(self.playlist[self.current_index])}")
        else:
            print("No se encontró ninguna canción ni playlist anterior para cargar.")

    def save_player_state_on_stop(self, reason="stopped"):
        """Guarda el estado actual del reproductor al detenerse o cerrar."""
        if self.current_playback_file:
            self.settings.setValue("last_opened_song", self.current_playback_file)
            # Store position in milliseconds
            current_ms = int((self.current_frame / self.audio_samplerate) * 1000) if self.audio_samplerate > 0 else 0
            self.settings.setValue("last_opened_position", current_ms)
            print(f"Estado del reproductor guardado: {os.path.basename(self.current_playback_file)} a {current_ms}ms (razón: {reason})")
        else:
            # Clear saved state if no song is playing
            self.settings.remove("last_opened_song")
            self.settings.remove("last_opened_position")
            print("Estado del reproductor limpiado (no hay canción activa).")

    def closeEvent(self, event):
        """Maneja el evento de cierre de la ventana para detener la reproducción y guardar el estado."""
        print("Cerrando la aplicación. Deteniendo hilos de audio...")
        self.stop_playback(final_stop=True) # Siempre es una parada definitiva al cerrar la app
        self.save_player_state_on_stop("application_closed")
        event.accept()

    # --- Constructor de la clase MusicPlayer ---
    def __init__(self):
        """Constructor de la clase MusicPlayer."""
        super().__init__()
        print("DEBUG: __init__: Super constructor llamado.")
        self.setWindowTitle("Modern PyQt6 Music Player")
        print("DEBUG: __init__: Título de ventana establecido.")
        self.setGeometry(300, 100, 900, 700)
        
        self.set_dark_theme()
        print("DEBUG: __init__: Tema oscuro aplicado.")
        self.apply_styles()
        print("DEBUG: __init__: Estilos aplicados.")

        self.settings = QSettings("MyMusicPlayerCompany", "MusicPlayer")
        print("DEBUG: __init__: QSettings inicializado.")

        # Inicializar la configuración del ecualizador.
        try:
            loaded_settings = self.settings.value("equalizer_settings", [0] * 10, type=list)
            self.equalizer_settings = [int(x) for x in loaded_settings]
            if len(self.equalizer_settings) != 10:
                raise ValueError("La longitud de la configuración del ecualizador no es 10.")
            print("DEBUG: __init__: Configuración de ecualizador cargada o inicializada.")
        except (ValueError, TypeError):
            print("Advertencia: Configuración de ecualizador inválida o corrupta. Reiniciando a valores por defecto.")
            self.equalizer_settings = [0] * 10
            self.settings.setValue("equalizer_settings", self.equalizer_settings)
        
        # --- Configuración para DSP con SoundFile y SoundDevice ---
        self.audio_stream = None # Stream de sounddevice
        self.current_playback_file = None
        self.current_audio_data = None # Datos de audio cargados en un array numpy
        self.audio_samplerate = 44100 # Frecuencia de muestreo (se actualiza al cargar archivo)
        self.audio_channels = 2 # Número de canales (se actualiza al cargar archivo)
        self.selected_output_device_index = -1 # Índice del dispositivo de salida seleccionado
        print("DEBUG: __init__: Variables de audio inicializadas.")

        # Eventos y hilos para controlar la reproducción
        self.stop_playback_event = threading.Event()
        self.pause_playback_event = threading.Event()
        self.playback_finished_event = threading.Event()

        self.audio_playback_thread = None # Hilo principal de reproducción/procesamiento

        self.current_frame = 0 # Posición actual en frames
        self.total_frames = 0 # Duración total en frames

        # Flag para controlar el estado de reproducción
        self.is_playing = False # True si está reproduciendo, False si está pausado o detenido
        print("DEBUG: __init__: Eventos y flags de hilos inicializados.")

        # Inicializar los filtros del ecualizador (coeficientes, no dependen de channels)
        print("DEBUG: __init__: Diseñando filtros de ecualizador iniciales...")
        self.equalizer_filters = [self._design_band_filter(freq, 0) for freq in self._get_band_frequencies()]
        print("DEBUG: __init__: Filtros de ecualizador diseñados.")
        self.filter_states = [] # Inicializar como lista vacía aquí
        print("DEBUG: __init__: Filter states inicializados.")

        # Diagnóstico de dispositivos de audio y selección
        if sd:
            print("DEBUG: __init__: sd es True. Iniciando bloque de consulta de dispositivos de audio...")
            try:
                print("Dispositivos de audio disponibles:")
                devices = sd.query_devices()
                print("DEBUG: __init__: sd.query_devices() completado.")
                
                # Intentar encontrar un dispositivo de salida estéreo preferido (WASAPI, DirectSound)
                preferred_hostapis = ["Windows WASAPI", "Windows DirectSound", "MME"]
                for hostapi_name in preferred_hostapis:
                    for i, dev in enumerate(devices):
                        if dev['max_output_channels'] >= 2 and dev['hostapi'] == hostapi_name:
                            self.selected_output_device_index = i
                            print(f"Seleccionado dispositivo de salida estéreo preferido: {self.selected_output_device_index} ({dev['name']}, {dev['hostapi']})")
                            break
                    if self.selected_output_device_index != -1:
                        break # Ya encontramos uno

                # Si no se encontró un dispositivo estéreo preferido, buscar cualquier estéreo
                if self.selected_output_device_index == -1:
                    for i, dev in enumerate(devices):
                        if dev['max_output_channels'] >= 2:
                            self.selected_output_device_index = i
                            print(f"Seleccionado primer dispositivo de salida estéreo: {self.selected_output_device_index} ({dev['name']}, {dev['hostapi']})")
                            break

                # Si no hay estéreo, buscar el primer dispositivo de salida mono
                if self.selected_output_device_index == -1:
                    for i, dev in enumerate(devices):
                        if dev['max_output_channels'] >= 1:
                            self.selected_output_device_index = i
                            print(f"Seleccionado primer dispositivo de salida mono: {self.selected_output_device_index} ({dev['name']}, {dev['hostapi']})")
                            break

                if self.selected_output_device_index != -1:
                    selected_device_info = sd.query_devices(self.selected_output_device_index, 'output')
                    print(f"Dispositivo de salida configurado a índice: {self.selected_output_device_index} ({selected_device_info['name']})")
                    try:
                        supported_rates = []
                        common_rates = [44100, 48000, 88200, 96000, 192000] 
                        for rate in common_rates:
                            try:
                                sd.check_output_settings(device=self.selected_output_device_index, samplerate=rate, channels=selected_device_info['max_output_channels'], dtype='float32')
                                supported_rates.append(rate)
                            except sd.PortAudioError:
                                pass # This sample rate is not supported
                        print(f"Sample rates soportadas por el dispositivo ({selected_device_info['name']}): {supported_rates}")
                    except Exception as e:
                        print(f"ERROR: __init__: Error al verificar sample rates soportadas: {e}")

                else:
                    print("Advertencia: No se encontró ningún dispositivo de salida de audio válido. La reproducción podría fallar.")
                    self.audio_channels = 2 # Fallback (default to stereo if no device found)
                
            except Exception as e:
                print(f"ERROR: __init__: EXCEPCIÓN DETECTADA AL CONSULTAR DISPOSITIVOS DE AUDIO: {e}")
                traceback.print_exc() # Imprimir el stack trace completo para este error
                self.selected_output_device_index = -1 # Asegurar que esté marcado como inválido
                self.audio_channels = 2 # Fallback
        else:
            print("DEBUG: __init__: sd es False. Librerías DSP no disponibles. No se consultarán dispositivos de audio.")
        
        print("DEBUG: __init__: Configuración de dispositivos de audio completada.")

        self.playlist = []
        self.shuffled_playlist = []
        self.current_index = -1
        self.current_shuffled_index = -1
        self.all_files = []
        print("DEBUG: __init__: Listas de reproducción inicializadas.")

        self._shuffle_mode = False
        self._repeat_mode = self.NO_REPEAT

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        print("DEBUG: __init__: Layout principal y central widget configurados.")

        top_layout = QHBoxLayout()

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Search title, artist, or album...")
        self.search_input.textChanged.connect(self.filter_track_list) 
        search_layout.addWidget(self.search_input)

        self.btn_clear_search = QPushButton(self)
        self.btn_clear_search.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton))
        self.btn_clear_search.setToolTip("Clear search")
        self.btn_clear_search.setFixedSize(30, 30)
        self.btn_clear_search.clicked.connect(self.search_input.clear)
        search_layout.addWidget(self.btn_clear_search)
        layout.addLayout(search_layout)
        print("DEBUG: __init__: Barra de búsqueda configurada.")

        self.track_list = QListWidget(self)
        self.track_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.track_list.doubleClicked.connect(self.play_selected)
        self.track_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.track_list.customContextMenuRequested.connect(self.show_context_menu)

        self.album_art = QLabel(self)
        self.album_art.setObjectName("albumArt")
        self.album_art.setFixedSize(300, 300)
        self.album_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.album_art.setText("No Album Art")

        top_layout.addWidget(self.track_list)
        top_layout.addWidget(self.album_art)
        layout.addLayout(top_layout)
        print("DEBUG: __init__: Lista de pistas y arte de álbum configurados.")

        meta_layout = QVBoxLayout()
        self.lbl_title = QLabel("Title: -", self)
        self.lbl_artist = QLabel("Artist: -", self)
        self.lbl_album = QLabel("Album: -", self)
        self.lbl_track = QLabel("Track: -", self)
        for lbl in (self.lbl_title, self.lbl_artist, self.lbl_album, self.lbl_track):
            lbl.setStyleSheet("color: #ddd; font-size: 14px;")
            meta_layout.addWidget(lbl)
        layout.addLayout(meta_layout)
        print("DEBUG: __init__: Etiquetas de metadatos configuradas.")

        self.lbl_status = QLabel("Status: Stopped", self)
        self.lbl_status.setStyleSheet("color: #aaa; font-size: 12px; font-style: italic;")
        layout.addWidget(self.lbl_status)
        print("DEBUG: __init__: Etiqueta de estado configurada.")

        time_layout = QHBoxLayout()
        self.lbl_elapsed = QLabel("00:00", self)
        self.slider = ClickableSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, 0)
        # Conecta la señal personalizada para clics directos (desde ClickableSlider)
        self.slider.clicked_value_set.connect(self.seek_position_audio) 
        # Conecta para la funcionalidad de arrastrar y soltar
        self.slider.sliderPressed.connect(self.stop_player_during_seek)
        self.slider.sliderReleased.connect(self.resume_player_after_seek)
        self.lbl_duration = QLabel("00:00", self)
        time_layout.addWidget(self.lbl_elapsed)
        time_layout.addWidget(self.slider)
        time_layout.addWidget(self.lbl_duration)
        layout.addLayout(time_layout)
        print("DEBUG: __init__: Slider de tiempo configurado.")

        ctrl_layout = QHBoxLayout()
        
        self.btn_open = QPushButton(self)
        self.btn_open.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self.btn_open.clicked.connect(self.open_files)

        self.btn_open_folder = QPushButton(self)
        self.btn_open_folder.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.btn_open_folder.clicked.connect(self.open_folder)

        self.btn_save_playlist = QPushButton(self)
        self.btn_save_playlist.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.btn_save_playlist.setText("Save Playlist")
        self.btn_save_playlist.clicked.connect(self.save_playlist)

        self.btn_load_playlist = QPushButton(self)
        self.btn_load_playlist.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self.btn_load_playlist.setText("Load Playlist")
        self.btn_load_playlist.clicked.connect(self.load_playlist)

        self.btn_remove_selected = QPushButton(self)
        self.btn_remove_selected.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self.btn_remove_selected.setText("Remove Selected")
        self.btn_remove_selected.clicked.connect(self.remove_selected_tracks)

        self.btn_clear_playlist = QPushButton(self)
        self.btn_clear_playlist.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogResetButton))
        self.btn_clear_playlist.setText("Clear Playlist")
        self.btn_clear_playlist.clicked.connect(self.clear_playlist)

        self.btn_move_up = QPushButton(self)
        self.btn_move_up.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        self.btn_move_up.setToolTip("Move selected track up")
        self.btn_move_up.clicked.connect(self.move_track_up)

        self.btn_move_down = QPushButton(self)
        self.btn_move_down.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown))
        self.btn_move_down.setToolTip("Move selected track down")
        self.btn_move_down.clicked.connect(self.move_track_down)

        self.btn_equalizer = QPushButton(self)
        self.btn_equalizer.setText("Equalizer")
        self.btn_equalizer.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume))
        self.btn_equalizer.clicked.connect(self.open_equalizer_window)

        self.btn_prev = QPushButton(self)
        self.btn_prev.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward))
        self.btn_prev.clicked.connect(self.prev_track)

        self.btn_play = QPushButton(self)
        self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.btn_play.clicked.connect(self.toggle_play)

        self.btn_next = QPushButton(self)
        self.btn_next.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward))
        self.btn_next.clicked.connect(self.next_track)

        self.btn_shuffle = QPushButton(self)
        self.btn_shuffle.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.btn_shuffle.setCheckable(True)
        self.btn_shuffle.clicked.connect(self.toggle_shuffle_mode)

        self.btn_repeat = QPushButton(self)
        self.icon_repeat_off = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogNoButton)
        self.icon_repeat_single = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogYesButton)
        self.icon_repeat_all = self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        self.btn_repeat.setIcon(self.icon_repeat_off)
        self.btn_repeat.clicked.connect(self.toggle_repeat_mode)

        self.vol_slider = ClickableSlider(Qt.Orientation.Horizontal, self)
        self.vol_slider.setRange(0, 100)
        last_volume = self.settings.value("last_volume", 50, type=int)
        self.vol_slider.setValue(last_volume)
        # El volumen se aplicará en el hilo de salida de audio ahora
        self.vol_slider.valueChanged.connect(self.set_and_save_volume)
        self.vol_slider.setFixedWidth(120)

        for w in (self.btn_open, self.btn_open_folder, self.btn_save_playlist, self.btn_load_playlist,
                  self.btn_remove_selected, self.btn_clear_playlist,
                  self.btn_move_up, self.btn_move_down,
                  self.btn_equalizer,
                  self.btn_prev, self.btn_play, self.btn_next,
                  self.btn_shuffle, self.btn_repeat,
                  QSpacerItem(20, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum),
                  self.vol_slider):
            if isinstance(w, QSpacerItem):
                ctrl_layout.addItem(w)
            else:
                ctrl_layout.addWidget(w)
        layout.addLayout(ctrl_layout)
        print("DEBUG: __init__: Controles de reproducción configurados.")

        # Conectar señales personalizadas a los slots de actualización de UI
        self.update_position_signal.connect(self.update_position_ui)
        self.update_duration_signal.connect(self.update_duration_ui)
        self.update_playback_state_signal.connect(self.update_playback_status_label)

        # QTimer para actualizar la posición en la UI
        self.ui_update_timer = QTimer(self)
        self.ui_update_timer.setInterval(100) # Actualizar cada 100 ms
        self.ui_update_timer.timeout.connect(self._update_ui_from_threads)
        print("DEBUG: __init__: Señales de UI y timer configurados.")
        
        # Elimina esta bandera, ya no es necesaria con la lógica unificada en seek_position_audio
        # self._was_playing_before_seek = False 
        self.setup_keyboard_shortcuts()
        print("DEBUG: __init__: Atajos de teclado configurados.")

        self.load_last_session_state()
        print("DEBUG: __init__: Estado de sesión cargado.")
        self.update_window_title()
        self.update_playback_status_label("StoppedState")
        print("DEBUG: __init__: Título y estado de reproducción iniciales de la ventana actualizados.")
        print("DEBUG: __init__: Inicialización de MusicPlayer completada.")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    try:
        win = MusicPlayer()
        win.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"FATAL ERROR: La aplicación falló durante el inicio: {e}")
        traceback.print_exc() # Imprimir el stack trace completo
        sys.exit(1)