import sys
import os
import random
import threading
import queue
import time
import numpy as np
import traceback

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QListWidget, QLabel, QFileDialog, QStyle,
    QSizePolicy, QSpacerItem, QLineEdit, QMenu, QMessageBox, 
    QToolButton, QWidgetAction, QDialog 
)
from PyQt6.QtGui import QPalette, QColor, QPixmap, QImage, QIcon, QPainter, QBrush, QPen
from PyQt6.QtCore import Qt, QUrl, QVariant, QTimer, QEvent, QSettings, pyqtSignal, QSize

from ecualizador import EqualizerWindow

try:
    import soundfile as sf
    import sounddevice as sd
    from scipy.signal import iirfilter, lfilter, freqz, resample # Importar resample
    # Para FFT (Fast Fourier Transform)
    from scipy.fft import fft
    print("Librerías DSP (SoundFile, SoundDevice, SciPy, NumPy) cargadas exitosamente.")
except ImportError as e:
    print(f"Advertencia: No se pudieron cargar todas las librerías DSP. El ecualizador y el visualizador no tendrán efecto audible. Error: {e}")
    # Definir marcadores/dummies si las librerías no se cargan
    class DummySoundDevice:
        def __init__(self, *args, **kwargs): pass
        def start(self): pass
        def stop(self): pass
        def close(self): pass
        def write(self, data): pass
        def active(self): return False
        def query_devices(self, *args, **kwargs): return [] # Devolver lista vacía para query_devices
        def query_supported_settings(self, *args, **kwargs): return {'samplerate': 0, 'channels': 0, 'blocksize': 0}
        def check_output_settings(self, *args, **kwargs): pass
        def default(self): # Necesario para simular sd.default.device
            class Default:
                def __init__(self):
                    self.device = (0, 0) # Default a un tupla de 0,0 para evitar errores si no hay dispositivos
            return Default()
    if 'sd' not in locals() or sd is None:
        sd = DummySoundDevice()
        sd.OutputStream = DummySoundDevice
    
    if 'iirfilter' not in locals() or iirfilter is None:
        def iirfilter(*args, **kwargs): return [1.0], [1.0]
    if 'lfilter' not in locals() or lfilter is None:
        def lfilter(b, a, x, zi=None): 
            if zi is not None: return x, zi
            return x
    if 'fft' not in locals() or fft is None:
        def fft(data): return np.zeros_like(data)
    if 'resample' not in locals() or resample is None: # Dummy para resample
        def resample(x, num, t=None, axis=0, window=None): 
            if x.ndim > 1:
                # Asegurarse de que el dummy devuelva un array 2D si el input es 2D
                return np.zeros((num, x.shape[1]), dtype=x.dtype)
            return np.zeros(num, dtype=x.dtype) # Devolver un array de ceros con el número correcto de muestras


from mutagen.mp3 import MP3
from mutagen.id3 import ID3NoHeaderError, ID3, APIC
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis


# --- GANCHO GLOBAL DE EXCEPCIONES ---
# Esta función se ejecutará para cualquier excepción no manejada en la aplicación
def custom_exception_hook(exctype, value, tb):
    # Imprimir la traza completa en la consola (para depuración)
    traceback.print_exception(exctype, value, tb)

    # Crear un mensaje detallado para el usuario
    error_message = f"Ha ocurrido un error inesperado:\n\nTipo de Error: {exctype.__name__}\n" \
                    f"Mensaje: {value}\n\n" \
                    f"La aplicación puede volverse inestable o cerrarse. " \
                    f"Por favor, contacta al soporte con los detalles a continuación:\n\n" \
                    f"Traceback:\n{''.join(traceback.format_tb(tb))}"
    
    # Mostrar el mensaje en una caja de diálogo de PyQt
    msg_box = QMessageBox()
    msg_box.setIcon(QMessageBox.Icon.Critical)
    msg_box.setWindowTitle("Error Crítico de la Aplicación")
    msg_box.setText("¡La aplicación ha encontrado un error inesperado!")
    msg_box.setInformativeText("Haz clic en 'Mostrar Detalles' para ver más información.")
    msg_box.setDetailedText(error_message)
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
        QMessageBox QPushButton#qt_msgbox_button_ShowDetails {
            background: #50b8f0;
            color: black;
        }
    """)
    msg_box.exec()

    # Luego de mostrar el mensaje, permite que la excepción termine el programa si es necesario
    # sys.__excepthook(exctype, value, tb) # Ya no es necesario, el exec() permite al usuario cerrar
    sys.exit(1) # Forzar la salida después de mostrar el error


# Sobrescribir el hook predeterminado de Python
sys.excepthook = custom_exception_hook
# --- FIN GANCHO GLOBAL DE EXCEPCIONES ---


class ClickableSlider(QSlider):
    clicked_value_set = pyqtSignal(int)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.orientation() == Qt.Orientation.Horizontal:
                value = self.minimum() + ((self.maximum() - self.minimum()) * event.pos().x()) / self.width()
            else:
                value = self.minimum() + ((self.maximum() - self.minimum()) * (self.height() - event.pos().y())) / self.height()
            
            self.setValue(int(value))
            self.clicked_value_set.emit(int(value))
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)


class AudioVisualizerWidget(QWidget):
    """
    Widget personalizado para dibujar un visualizador de audio (espectro).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(100)
        self.setMinimumWidth(150) # Asegurar un ancho mínimo para las barras
        self.fft_data = np.array([]) # Almacenará los datos de frecuencia para dibujar
        self.bar_colors = [QColor(80, 160, 220, 200), QColor(60, 140, 200, 200)] # Colores para las barras
        
        # Habilitar el buffer doble para evitar parpadeo
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._buffer = QPixmap() # Usaremos un QPixmap como buffer

    def sizeHint(self):
        """Sugiere un tamaño preferido para el widget."""
        return QSize(400, 100) # Un tamaño razonable para el visualizador

    def update_visualization_data(self, new_fft_data):
        """
        Actualiza los datos del visualizador y fuerza un redibujado.
        Esta función se llama desde el hilo principal después de recibir datos del hilo de audio.
        """
        # Asegurarse de que los datos no sean NaN o Inf antes de almacenar
        self.fft_data = np.nan_to_num(new_fft_data, nan=0.0, posinf=0.0, neginf=0.0)
        self.update() # Llama a paintEvent para redibujar el widget

    def paintEvent(self, event):
        """
        Método de dibujo del widget. Se encarga de dibujar el visualizador.
        """
        current_widget_size = self.size()

        # Evitar dibujar si el widget no tiene un tamaño válido
        if current_widget_size.width() <= 0 or current_widget_size.height() <= 0:
            return 

        # Redimensionar y limpiar el buffer si el widget ha cambiado de tamaño o si el buffer es nulo/inválido
        if self._buffer.size() != current_widget_size or self._buffer.isNull() or self._buffer.width() == 0 or self._buffer.height() == 0:
            if current_widget_size.width() > 0 and current_widget_size.height() > 0:
                self._buffer = QPixmap(current_widget_size)
                self._buffer.fill(Qt.GlobalColor.transparent) # Limpiar el buffer
            else:
                # Si el tamaño sigue siendo inválido, no podemos crear el buffer, así que salimos.
                return

        painter = QPainter(self._buffer)
        # Verificar si el pintor se inició correctamente. Si no, significa que _buffer es inválido por alguna razón.
        if not painter.isActive(): 
            return 

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Limpiar el área del buffer para el nuevo dibujo
        painter.fillRect(self.rect(), QColor(42, 42, 42)) # Color de fondo del visualizador (oscuro)

        if self.fft_data.size > 0:
            width = self.width()
            height = self.height()
            num_bars = 50 # Número de barras a dibujar (más barras, más detalle)
            bar_spacing = 2 # Espacio entre barras
            bar_width = (width - (num_bars + 1) * bar_spacing) / num_bars
            
            # Asegurarse de que el ancho de la barra sea positivo
            if bar_width <= 0:
                bar_width = 1
                bar_spacing = max(0, (width - num_bars) // (num_bars + 1))


            # Normalizar los datos FFT para ajustar a la altura del widget
            # Evitar división por cero si max_val es 0
            max_val = np.max(self.fft_data)
            if max_val <= 1e-6: # Usar un umbral pequeño para considerar que es "cero"
                normalized_data = np.zeros_like(self.fft_data)
            else:
                normalized_data = self.fft_data / max_val
            
            # Seleccionar un subconjunto de datos para las barras para cubrir el rango de frecuencias
            display_data = normalized_data[:num_bars] if normalized_data.size >= num_bars else np.pad(normalized_data, (0, num_bars - normalized_data.size))

            for i, val in enumerate(display_data):
                bar_height = val * height * 0.8 # Escalar la altura de la barra (ej. 80% de la altura del widget)
                x = i * (bar_width + bar_spacing) + bar_spacing
                y = height - bar_height # Dibujar desde la parte inferior

                # Usar colores alternos para las barras
                color = self.bar_colors[i % len(self.bar_colors)]
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(color.darker(150), 1)) # Borde un poco más oscuro

                painter.drawRoundedRect(int(x), int(y), int(bar_width), int(bar_height), 2, 2) # Barras con esquinas redondeadas
        else:
            # Dibujar un mensaje si no hay datos de audio
            painter.setPen(QPen(QColor(150, 150, 150)))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Cargando audio para visualización...")

        painter.end()

        # Dibujar el buffer en el widget real
        target_painter = QPainter(self)
        if target_painter.isActive():
            target_painter.drawPixmap(0, 0, self._buffer)
            target_painter.end()


class MusicPlayer(QMainWindow):
    NO_REPEAT = 0
    REPEAT_CURRENT = 1
    REPEAT_ALL = 2

    update_position_signal = pyqtSignal(int)
    update_duration_signal = pyqtSignal(int)
    update_playback_state_signal = pyqtSignal(str)
    update_visualizer_signal = pyqtSignal(np.ndarray)
    devices_updated_signal = pyqtSignal()

    def set_dark_theme(self):
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
            /* Removido el estilo para visualizerLabel ya que ahora usamos un widget personalizado */
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
            /* Removido estilo para QComboBox */
            /* Removido estilo para QComboBox::drop-down */
            /* Removido estilo para QComboBox::down-arrow */
            /* Removido estilo para QComboBox QAbstractItemView */
            QToolButton {
                background: #333;
                border: none;
                border-radius: 8px;
                padding: 10px 15px;
                color: white;
                font-size: 14px;
            }
            QToolButton:hover {
                background: #444;
            }
            QToolButton:pressed {
                background: #222;
            }
            QToolButton::menu-indicator {
                /* Eliminar el indicador de menú por defecto para que se vea como un botón normal */
                image: none;
            }
            QMenu {
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 5px;
                color: #ddd;
            }
            QMenu::item {
                padding: 8px 20px 8px 15px; /* Arriba, derecha, abajo, izquierda */
                background-color: transparent;
            }
            QMenu::item:selected {
                background-color: #50b8f0;
                color: black;
            }
        """)

    def _get_band_frequencies(self):
        return [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

    def _design_band_filter(self, center_freq, gain_db, Q_factor=1.0):
        if iirfilter is None or np is None or self._file_samplerate == 0: # Usar _file_samplerate para diseñar filtros
            return [1.0], [1.0]

        A = 10**(gain_db / 40.0)
        w0 = 2 * np.pi * center_freq / self._file_samplerate # Los filtros se diseñan para la frecuencia original del archivo
        alpha = np.sin(w0) / (2 * Q_factor)

        b0 = 1 + alpha * A
        b1 = -2 * np.cos(w0)
        b2 = 1 - alpha * A

        a0 = 1 + alpha / A
        a1 = -2 * np.cos(w0)
        a2 = 1 - alpha / A

        b = np.array([b0, b1, b2]) / a0
        a = np.array([a0, a1, a2]) / a0

        return b, a

    def _update_ui_from_threads(self):
        # La posición y duración de la UI se basan en el samplerate original del archivo
        if self.total_frames > 0 and self._file_samplerate > 0:
            current_ms = int((self.current_frame / self._file_samplerate) * 1000)
            total_ms = int((self.total_frames / self._file_samplerate) * 1000)
            self.update_position_signal.emit(current_ms)
            self.update_duration_signal.emit(total_ms)

        if self.playback_finished_event.is_set():
            print("DEBUG: UI Update: playback_finished_event detectado. Manejando fin de canción.")
            self.playback_finished_event.clear()
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
                    if next_shuffled_idx == len(self.shuffled_playlist) and current_shuffled_idx == len(self.shuffled_playlist) - 1:
                        # Si es la última y se completó
                        print("DEBUG: Fin de playlist aleatoria, reiniciando al principio.")
                        self.rebuild_shuffled_playlist() # Regenera y reordena
                        next_file = self.shuffled_playlist[0] # Empieza de nuevo
                        self.current_shuffled_index = 0
                    else:
                        next_file = self.shuffled_playlist[next_shuffled_idx]
                        self.current_shuffled_index = next_shuffled_idx
                    self.load_and_play(next_file)
                    self.current_index = self.playlist.index(next_file)
                    self.track_list.setCurrentRow(self.current_index)
                elif self.playlist:
                    current_idx = self.current_index
                    next_idx = (current_idx + 1) % len(self.playlist)
                    next_file = self.playlist[next_idx]
                    self.current_index = next_idx
                    self.load_and_play(next_file)
                    self.track_list.setCurrentRow(self.current_index)
                else:
                    self.stop_playback(final_stop=True) # En caso de playlist vacía incluso en repeat_all
            else: # self._repeat_mode == self.NO_REPEAT
                print("DEBUG: Fin de canción. Modo no repetición.")
                next_song_exists = False
                next_file = None
                next_ui_index = -1
                if self._shuffle_mode and self.shuffled_playlist:
                    current_shuffled_idx = self.current_shuffled_index
                    next_shuffled_idx = current_shuffled_idx + 1
                    if next_shuffled_idx < len(self.shuffled_playlist):
                        next_song_exists = True
                        next_file = self.shuffled_playlist[next_shuffled_idx]
                        self.current_shuffled_index = next_shuffled_idx
                        next_ui_index = self.playlist.index(next_file) # Obtener el índice en la playlist original
                        print(f"DEBUG: Reproduciendo siguiente en modo aleatorio: {os.path.basename(next_file)}")
                    else:
                        print("DEBUG: Fin de playlist aleatoria (NO_REPEAT).")
                elif self.playlist: # Not shuffled, check sequential next song
                    current_idx = self.current_index
                    next_idx = current_idx + 1
                    if next_idx < len(self.playlist):
                        next_song_exists = True
                        next_file = self.playlist[next_idx]
                        self.current_index = next_idx
                        next_ui_index = next_idx # El índice UI es el mismo que el de la playlist
                        print(f"DEBUG: Reproduciendo siguiente en modo secuencial: {os.path.basename(next_file)}")
                    else:
                        print("DEBUG: Fin de playlist secuencial (NO_REPEAT).")

                if next_song_exists and next_file:
                    self.load_and_play(next_file)
                    if next_ui_index != -1:
                        self.track_list.setCurrentRow(next_ui_index)
                else:
                    print("DEBUG: No hay más canciones para reproducir. Deteniendo reproducción.")
                    self.stop_playback(final_stop=True)
                    self.update_playback_status_label("StoppedState")
        elif self.stop_playback_event.is_set():
            print("DEBUG: UI Update: stop_playback detectado. Deteniendo hilo de audio y UI.")
            self.stop_playback_event.clear()
            # No se necesita _audio_thread_stopper.set() aquí directamente, stop_playback ya lo hace
            self.current_frame = 0
            self.update_position_signal.emit(0)
            self.update_duration_signal.emit(0)
            self.update_visualizer_signal.emit(np.array([])) # Limpiar el visualizador
            self.update_playback_status_label("StoppedState")

        # Asegurarse de que el thread de audio se detenga limpiamente
        if self.audio_playback_thread and not self.audio_playback_thread.is_alive() and not self.stop_playback_event.is_set():
            print("DEBUG: Hilo de audio terminó inesperadamente o completó su tarea.")
            # Restablecer el estado de reproducción si el hilo ha terminado y no es por una parada explícita.
            # Aquí se debería llamar a stop_playback(final_stop=True) si se quiere una detención completa.
            # Por ahora, solo se limpia la referencia al hilo si ya no está vivo.
            self.audio_playback_thread = None # Resetear referencia al hilo


    def set_and_save_volume(self, value):
        self.settings.setValue("last_volume", value)
        # No se necesita manejar sounddevice.set_volume() directamente aquí.
        # El volumen se aplica en el hilo de reproducción de audio.
        print(f"Volumen ajustado a: {value}%")

    def setup_keyboard_shortcuts(self):
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            # Permitir espacio en el campo de búsqueda
            if QApplication.instance().focusWidget() == self.search_input and event.key() == Qt.Key.Key_Space:
                return False
            if event.key() == Qt.Key.Key_Space:
                self.toggle_play()
                return True
            elif event.key() == Qt.Key.Key_Right:
                target_pos_ms = (self.current_frame / self._file_samplerate * 1000) + 5000
                self.seek_position_audio(target_pos_ms)
                return True
            elif event.key() == Qt.Key.Key_Left:
                target_pos_ms = (self.current_frame / self._file_samplerate * 1000) - 5000
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
        if self.is_playing:
            self.pause_playback_event.set()
            print("DEBUG: Seek: Reproducción pausada para buscar (arrastre).")

    def resume_player_after_seek(self):
        seek_ms = self.slider.value()
        print(f"DEBUG: Seek: Reanudando después de arrastre. Buscando a {seek_ms}ms...")
        self.pause_playback_event.clear()
        self.seek_position_audio(seek_ms)

    def seek_position_audio(self, target_ms):
        if sf is None or sd is None or self.current_audio_data_original is None:
            print("DEBUG: Librerías DSP o datos de audio no disponibles para buscar.")
            return

        print(f"DEBUG: Buscando a {target_ms}ms...")

        # La búsqueda se basa en la frecuencia de muestreo original del archivo
        target_frame = int((target_ms / 1000.0) * self._file_samplerate)
        target_frame = max(0, min(target_frame, self.total_frames))

        # Captura el estado 'is_playing' ANTES de llamar a stop_playback
        was_playing_before_seek_op = self.is_playing and not self.pause_playback_event.is_set()

        self.stop_playback(final_stop=False) # Detención temporal para la búsqueda
        print("DEBUG: seek_position_audio: stop_playback() completado.")

        self.current_frame = target_frame
        self.update_position_ui(target_ms)
        print(f"DEBUG: seek_position_audio: current_frame ajustado a {self.current_frame}.")

        if was_playing_before_seek_op:
            print("DEBUG: seek_position_audio: Era reproduciendo, reiniciando desde nueva posición.")
            # Reinicia la reproducción desde la nueva posición sin detener la reproducción anterior de forma definitiva
            self.load_and_play(self.current_playback_file, start_position_ms=target_ms, stop_current_playback=False)
        else:
            print("DEBUG: seek_position_audio: Estaba detenido/pausado, permaneciendo en ese estado en la nueva posición.")
            self.update_playback_status_label("PausedState" if self.pause_playback_event.is_set() else "StoppedState")

    def update_position_ui(self, pos_ms):
        self.slider.blockSignals(True)
        self.slider.setValue(pos_ms)
        self.slider.blockSignals(False)
        s = pos_ms // 1000
        m, s = divmod(s, 60)
        self.lbl_elapsed.setText(f"{m:02d}:{s:02d}")

    def update_duration_ui(self, dur_ms):
        self.slider.setRange(0, dur_ms)
        s = dur_ms // 1000
        m, s = divmod(s, 60)
        self.lbl_duration.setText(f"{m:02d}:{s:02d}")

    def update_metadata(self, file_path):
        title = os.path.splitext(os.path.basename(file_path))[0]
        artist = '-'
        album = '-'
        tracknum = '-'
        album_art_data = None
        
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
                title_tag = audio.tags.get('title')
                if isinstance(title_tag, list) and title_tag:
                    title = str(title_tag[0])
                elif 'TIT2' in audio.tags:
                    title = str(audio.tags.get('TIT2'))

                artist_tag = audio.tags.get('artist')
                if isinstance(artist_tag, list) and artist_tag:
                    artist = str(artist_tag[0])
                elif 'TPE1' in audio.tags:
                    artist = str(audio.tags.get('TPE1'))

                album_tag = audio.tags.get('album')
                if isinstance(album_tag, list) and album_tag:
                    album = str(album_tag[0])
                elif 'TALB' in audio.tags:
                    album = str(audio.tags.get('TALB'))

                tracknum_tag = audio.tags.get('tracknumber')
                if isinstance(tracknum_tag, list) and tracknum_tag:
                    current_tracknum_raw = str(tracknum_tag[0])
                elif 'TRCK' in audio.tags:
                    current_tracknum_raw = str(audio.tags.get('TRCK'))

                if isinstance(audio.tags, ID3):
                    for k, v in audio.tags.items():
                        if k.startswith('APIC') and isinstance(v, APIC):
                            album_art_data = v.data
                            break
                elif hasattr(audio.tags, 'pictures') and audio.tags.pictures:
                    for pic in audio.tags.pictures:
                        if pic.type == 3:
                            album_art_data = pic.data
                            break

        except ID3NoHeaderError:
            print(f"Advertencia: No se encontraron etiquetas ID3 en {file_path}.")
        except Exception as e:
            print(f"Error general al leer metadatos de {file_path}: {e}")

        if isinstance(current_tracknum_raw, str) and '/' in current_tracknum_raw:
            tracknum = current_tracknum_raw.split('/')[0]
        else:
            tracknum = str(current_tracknum_raw)

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
        # Pasar los ajustes actuales del ecualizador a la ventana del ecualizador
        dialog = EqualizerWindow(self, initial_settings=self.equalizer_settings)
        # Conectar la señal eq_params_changed (que emite el diccionario completo)
        dialog.eq_params_changed.connect(self.apply_equalizer_settings)
        dialog.exec()

    def apply_equalizer_settings(self, settings):
        # 'settings' ahora es el diccionario completo que la EqualizerWindow emite
        # Necesitamos extraer solo las ganancias para self.equalizer_settings
        self.equalizer_settings = [val['gain'] for key, val in settings.items()] 
        self.settings.setValue("equalizer_settings", self.equalizer_settings)
        print(f"Configuraciones del ecualizador recibidas y guardadas: {self.equalizer_settings}")
        
        new_filters = []
        for i, gain_db in enumerate(self.equalizer_settings):
            # Usar self._get_band_frequencies()[i] para obtener la frecuencia de la banda
            new_filters.append(self._design_band_filter(self._get_band_frequencies()[i], gain_db))
        
        self.equalizer_filters = new_filters
        
        # Reiniciar estados de filtro para los nuevos datos y canales
        # Esto solo se hace si audio_channels_original es conocido (después de cargar una canción)
        if self.audio_channels_original > 0:
            self.filter_states = [np.zeros((max(len(b), len(a)) - 1, self.audio_channels_original)) for b, a in self.equalizer_filters]
        else:
            # Si no hay audio cargado, los estados se reinician como vacíos
            self.filter_states = []
        print("Filtros del ecualizador actualizados.")

    def add_files_to_playlist(self, files):
        # Validate and filter files before adding
        valid_files = []
        for f in files:
            if os.path.isfile(f) and f not in self.all_files and f.lower().endswith(('.mp3', '.wav', '.ogg', '.oga', '.flac')):
                valid_files.append(f)
            elif f in self.all_files:
                print(f"Advertencia: Archivo ya en la playlist: {os.path.basename(f)}")
            else:
                print(f"Advertencia: Archivo no válido o no soportado: {os.path.basename(f)}")

        if valid_files:
            for f in valid_files:
                self.all_files.append(f)
                self.playlist.append(f)
                
                duration_string = "00:00"
                if sf:
                    try:
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
            print(f"Añadidos {len(valid_files)} archivos a la playlist.")
        else:
            print("No se añadieron archivos válidos a la playlist.")


    def open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, 'Abrir Archivos de Música', '', 'Audio Files (*.mp3 *.wav *.ogg *.flac)'
        )
        if files:
            self.add_files_to_playlist(files)
            if files:
                last_path = os.path.dirname(files[0])
                self.settings.setValue("last_opened_path", last_path)
                self.settings.setValue("last_opened_song", files[0])
                self.settings.setValue("last_opened_position", 0)

    def open_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, 'Abrir Carpeta de Música')
        if folder_path:
            self.scan_folder_recursive(folder_path)
            self.settings.setValue("last_opened_path", folder_path)
            self.settings.setValue("last_opened_song", "")
            self.settings.setValue("last_opened_position", 0)

    def scan_folder_recursive(self, folder_path):
        supported_extensions = ('.mp3', '.wav', '.ogg', '.oga', '.flac')
        found_files = []
        for root, _, files in os.walk(folder_path):
            for file in files:
                if file.lower().endswith(supported_extensions):
                    full_path = os.path.join(root, file)
                    found_files.append(full_path)
        self.add_files_to_playlist(found_files)

    def save_playlist(self):
        if not self.playlist:
            self._show_message_box("Info", "No hay canciones en la playlist para guardar.")
            return

        file_name, _ = QFileDialog.getSaveFileName(
            self, 'Guardar Playlist', '', 'M3U Playlists (*.m3u);;All Files (*)'
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
        file_name, _ = QFileDialog.getOpenFileName(
            self, 'Cargar Playlist', '', 'M3U Playlists (*.m3u);;All Files (*)'
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
            self.stop_playback(final_stop=True)
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
                # Reset visualizer usando el nuevo widget
                self.visualizer_widget.update_visualization_data(np.array([])) 
                return

        if self._shuffle_mode:
            self.rebuild_shuffled_playlist()
            if self.current_playback_file and self.current_playback_file in self.shuffled_playlist:
                self.current_shuffled_index = self.shuffled_playlist.index(self.current_playback_file)
            else:
                self.current_shuffled_index = -1
                
        print("Pistas seleccionadas eliminadas.")

    def clear_playlist(self):
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
        # Reset visualizer usando el nuevo widget
        self.visualizer_widget.update_visualization_data(np.array([])) 

        self._show_message_box("Info", "Playlist vaciada.")

    def move_track_up(self):
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

    def _handle_playlist_rows_moved(self, parent, start, end, destination, row):
        # For a single item move (InternalMove), start == end.
        old_index = start
        new_index = row # The 'row' parameter in rowsMoved is the new destination index

        if old_index == new_index or old_index == new_index - 1: # No actual move happened or moving to its own spot
            return

        # Pop the item from its old position in the internal list
        moved_file = self.playlist.pop(old_index)
        
        # Adjust new_index if the item was moved downwards
        # because the list shrinks when an item is removed.
        if new_index > old_index:
            self.playlist.insert(new_index - 1, moved_file)
            new_index_for_logic = new_index - 1
        else:
            self.playlist.insert(new_index, moved_file)
            new_index_for_logic = new_index

        print(f"DEBUG: Playlist reordenada: {os.path.basename(moved_file)} movido de {old_index} a {new_index_for_logic}.")

        # Update current_index if the currently playing song was affected
        if self.current_playback_file:
            try:
                # Find the new index of the current playing file
                new_current_index = self.playlist.index(self.current_playback_file)
                if new_current_index != self.current_index:
                    self.current_index = new_current_index
                    self.track_list.setCurrentRow(self.current_index) # Update UI selection if needed
                    print(f"DEBUG: current_index actualizado a {self.current_index}")
            except ValueError:
                print("Advertencia: Canción actual no encontrada en la playlist después del reordenamiento (esto no debería ocurrir).")

        # Rebuild shuffled playlist if shuffle mode is active
        if self._shuffle_mode:
            self.rebuild_shuffled_playlist()
            if self.current_playback_file and self.current_playback_file in self.shuffled_playlist:
                self.current_shuffled_index = self.shuffled_playlist.index(self.current_playback_file)
            else:
                self.current_shuffled_index = -1 # Should not happen if current_playback_file is valid

    def _find_optimal_device_samplerate(self, file_samplerate, device_index, num_channels):
        """
        Encuentra la frecuencia de muestreo óptima que el dispositivo de salida puede manejar,
        priorizando la frecuencia del archivo.
        """
        if sd is None:
            return file_samplerate # Fallback si sounddevice no está disponible

        try:
            device_info = sd.query_devices(device_index)
            
            # Frecuencias de muestreo comunes y prioritarias a probar
            prioritized_samplerates = [file_samplerate, 48000, 44100, 96000, 88200]
            # Eliminar duplicados y mantener el orden de prioridad
            seen_sr = set()
            unique_prioritized_samplerates = []
            for sr in prioritized_samplerates:
                if sr not in seen_sr:
                    unique_prioritized_samplerates.append(sr)
                    seen_sr.add(sr)
            
            for sr in unique_prioritized_samplerates:
                try:
                    sd.check_output_settings(
                        device=device_index,
                        samplerate=sr,
                        channels=num_channels, 
                        dtype='float32'
                    )
                    print(f"DEBUG: Dispositivo {device_index} soporta samplerate: {sr} Hz (para {num_channels} canales).")
                    return sr
                except sd.PortAudioError:
                    pass # Continuar con la siguiente frecuencia

            # Si ninguna de las anteriores funciona, intentar con la frecuencia por defecto del dispositivo
            default_sr = int(device_info['default_samplerate'])
            try:
                sd.check_output_settings(
                    device=device_index,
                    samplerate=default_sr,
                    channels=num_channels,
                    dtype='float32'
                )
                print(f"DEBUG: Dispositivo {device_index} soporta su samplerate por defecto: {default_sr} Hz.")
                return default_sr
            except sd.PortAudioError:
                pass

            # Fallback si no se encuentra ninguna frecuencia compatible
            print(f"ADVERTENCIA: No se encontró una frecuencia de muestreo compatible para el dispositivo {device_index} y {num_channels} canales. Usando la del archivo {file_samplerate}.")
            return file_samplerate

        except Exception as e:
            print(f"ERROR: No se pudo consultar las capacidades del dispositivo {device_index}: {e}")
            return file_samplerate # Fallback en caso de error al consultar


    def load_and_play(self, file_path, start_position_ms=0, stop_current_playback=True):
        if sf is None or sd is None or resample is None:
            self._show_message_box("Error", "Las librerías DSP (SoundFile, SoundDevice, SciPy) no están cargadas. El reproductor no puede funcionar.")
            self.update_playback_status_label("StoppedState")
            return

        if not file_path or not os.path.exists(file_path):
            self._show_message_box("Error", f"Ruta de archivo inválida o no encontrada: {file_path}")
            self.update_playback_status_label("StoppedState")
            return
        
        if stop_current_playback:
            print("DEBUG: load_and_play: Llamando stop_playback para limpiar reproducción anterior.")
            self.stop_playback(final_stop=False) 

        try:
            self.current_playback_file = file_path
            
            # Leer datos y samplerate original del archivo
            data_from_file, file_samplerate = sf.read(file_path, dtype='float32') 

            # Determinar canales y asegurar que los datos originales sean 2D (stereo)
            if data_from_file.ndim == 1: 
                self.current_audio_data_original = np.stack([data_from_file, data_from_file], axis=-1)
                self.audio_channels_original = 2 # Se fuerza a 2 canales para una salida estéreo
            else:
                self.current_audio_data_original = data_from_file
                self.audio_channels_original = self.current_audio_data_original.shape[1]
            
            self._file_samplerate = file_samplerate # Guardar la frecuencia original del archivo

            # Determinar la frecuencia de muestreo óptima para el *dispositivo de salida*
            # Ahora, self.selected_output_device_index siempre será el default actual del sistema
            self.audio_samplerate_output = self._find_optimal_device_samplerate(
                self._file_samplerate, self.selected_output_device_index, self.audio_channels_original
            )
            
            # self.audio_samplerate (para UI) se mantiene como la del archivo original
            self.audio_samplerate = self._file_samplerate 
            self.total_frames = len(self.current_audio_data_original) # Frames totales del archivo original

            # Los datos `self.current_audio_data` ya no son necesarios aquí
            # Se leerán `self.current_audio_data_original` y se remuestrearán en el hilo.

            # La posición inicial se calcula en base al samplerate original del archivo
            self.current_frame = int((start_position_ms / 1000.0) * self._file_samplerate) 
            self.current_frame = max(0, min(self.current_frame, self.total_frames))
            print(f"DEBUG: load_and_play: current_frame after setting based on start_position_ms: {self.current_frame}")

            self.stop_playback_event.clear()
            self.pause_playback_event.clear()
            self.playback_finished_event.clear()
            print("DEBUG: load_and_play: Eventos de hilo reseteados.")

            # Reiniciar estados de filtro para los nuevos datos y canales
            if self.audio_channels_original > 0: 
                # Re-diseñar los filtros si el samplerate de la fuente ha cambiado,
                # para que los coeficientes sean correctos para la frecuencia de la fuente.
                # Aunque ya se diseñan en __init__, es bueno asegurarse si cambian las propiedades.
                # Los filtros se aplican a los datos *antes* del remuestreo.
                self.equalizer_filters = [self._design_band_filter(freq, gain) 
                                          for freq, gain in zip(self._get_band_frequencies(), self.equalizer_settings)]
                self.filter_states = [np.zeros((max(len(b), len(a)) - 1, self.audio_channels_original)) 
                                      for b, a in self.equalizer_filters]
            else:
                self.filter_states = [] 
            print("DEBUG: load_and_play: Estados de filtro reseteados.")

            print("DEBUG: load_and_play: Iniciando nuevo hilo de audio.")
            # Pasar la frecuencia de muestreo de salida deseada al hilo
            self.audio_playback_thread = threading.Thread(
                target=self._audio_playback_thread_main, 
                args=(start_position_ms, self.audio_samplerate_output, self.audio_channels_original), 
                daemon=True
            ) 
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
            traceback.print_exc() # Imprimir el stack trace
            self._show_message_box("Error de Reproducción", f"No se pudo reproducir el archivo: {e}")
            self.stop_playback(final_stop=True)
            self.update_playback_status_label("StoppedState")

    def _audio_playback_thread_main(self, initial_position_ms, output_samplerate, output_channels):
        if sd is None or self.current_audio_data_original is None:
            print("ERROR: _audio_playback_thread_main: sd o current_audio_data_original es None al iniciar el hilo.")
            self.playback_finished_event.set() 
            return

        print("DEBUG: _audio_playback_thread_main: Hilo de reproducción de audio iniciado.")
        
        # El blocksize se refiere a los frames que el dispositivo de salida consume en cada iteración.
        blocksize_output = 1024 

        try:
            # Siempre usar el dispositivo de salida predeterminado del sistema.
            # self.selected_output_device_index se mantiene actualizado por update_default_audio_device_display.
            current_default_device_id = self.selected_output_device_index
            if current_default_device_id == -1:
                print("ERROR: No se encontró un dispositivo de audio de salida predeterminado válido.")
                self.playback_finished_event.set()
                return

            print(f"DEBUG: _audio_playback_thread_main: Intentando abrir stream con samplerate={output_samplerate}, channels={output_channels}, blocksize={blocksize_output}, device_index={current_default_device_id}")
            try:
                sd.check_output_settings(
                    device=current_default_device_id, # Usar el ID del dispositivo predeterminado
                    samplerate=output_samplerate, 
                    channels=output_channels,
                    dtype='float32'
                )
                print("DEBUG: _audio_playback_thread_main: Configuración de salida de audio verificada: soportada.")
            except sd.PortAudioError as pa_err:
                print(f"ERROR: _audio_playback_thread_main: ERROR DE CONFIGURACIÓN DE SALIDA: {pa_err}")
                self.playback_finished_event.set()
                return

            with sd.OutputStream(device=current_default_device_id, # Usar el ID del dispositivo predeterminado
                                 samplerate=output_samplerate,
                                 channels=output_channels,
                                 dtype='float32',
                                 blocksize=blocksize_output) as stream:
                self.audio_stream = stream 
                stream.start() 
                print("DEBUG: _audio_playback_thread_main: Stream de audio de sounddevice iniciado.")

                current_frame_pos = self.current_frame # Posición en frames del archivo original
                print(f"DEBUG: _audio_playback_thread_main: Starting playback from current_frame_pos: {current_frame_pos}")
                
                print_counter = 0 
                # Se ajusta el intervalo de impresión basado en la frecuencia del archivo original
                print_interval = max(1, self.total_frames // blocksize_output // 20) 
                if self.total_frames < blocksize_output * 20:
                    print_interval = 1

                is_initial_fade_in = (initial_position_ms == 0) 
                fade_in_duration_frames_original = int(self.crossfade_duration_seconds * self._file_samplerate) 
                
                while not self.stop_playback_event.is_set():
                    while self.pause_playback_event.is_set():
                        print("DEBUG: _audio_playback_thread_main: Hilo pausado. Durmiendo...")
                        time.sleep(0.05)
                        if self.stop_playback_event.is_set():
                            print("DEBUG: _audio_playback_thread_main: Stop detectado durante pausa. Saliendo.")
                            break
                    
                    if self.stop_playback_event.is_set(): 
                        print("DEBUG: _audio_playback_thread_main: stop_playback_event detectado después de pausa. Saliendo.")
                        break

                    if current_frame_pos >= self.total_frames:
                        print("DEBUG: _audio_playback_thread_main: Fin de la canción (current_frame_pos >= total_frames). Señalando finalización.")
                        self.playback_finished_event.set()
                        break 

                    # Calcular cuántos frames leer del archivo original para producir blocksize_output frames
                    input_frames_to_read_original = int(np.ceil(blocksize_output * (self._file_samplerate / output_samplerate)))
                    if input_frames_to_read_original == 0: input_frames_to_read_original = 1 

                    # Asegurarse de no leer más allá del final del archivo original
                    frames_available_original = self.total_frames - current_frame_pos
                    actual_input_frames_read = min(input_frames_to_read_original, frames_available_original)
                    
                    if actual_input_frames_read <= 0:
                        print("DEBUG: _audio_playback_thread_main: No más frames para leer de archivo original. Fin de la canción.")
                        self.playback_finished_event.set()
                        break

                    # Leer bloque de datos original
                    input_block_original = self.current_audio_data_original[current_frame_pos : current_frame_pos + actual_input_frames_read]

                    # APLICAR GANANCIA MAESTRA ANTES DEL ECUALIZADOR (PARA PREVENIR CLIPPING)
                    processed_block = input_block_original * self.eq_master_gain_factor # Aplica la atenuación global
                    
                    # Aplicar filtros del ecualizador a los datos originales (ahora atenuados)
                    # processed_block = input_block_original.copy() # Ya no es necesario el .copy() si se aplica master gain
                    current_filter_states = [arr.copy() for arr in self.filter_states] 
                    current_equalizer_filters = list(self.equalizer_filters) 

                    for i, (b, a) in enumerate(current_equalizer_filters):
                        # Solo aplicar el filtro si no es un filtro de paso (b=1, a=1)
                        if not (len(b) == 1 and np.isclose(b[0], 1.0) and len(a) == 1 and np.isclose(a[0], 1.0)):
                            for channel_idx in range(self.audio_channels_original):
                                if current_filter_states[i].shape[0] > 0: 
                                    zi_channel = current_filter_states[i][:, channel_idx] 
                                else:
                                    zi_channel = None 

                                processed_block[:, channel_idx], updated_zi = \
                                    lfilter(b, a, processed_block[:, channel_idx], zi=zi_channel)
                                
                                if updated_zi is not None:
                                    current_filter_states[i][:, channel_idx] = updated_zi 
                    
                    self.filter_states = current_filter_states # Guardar los estados actualizados de los filtros

                    # --- Remuestreo en tiempo real si es necesario ---
                    if self._file_samplerate != output_samplerate:
                        if resample is None: # Comprobación de seguridad si resample no se cargó
                            output_block = processed_block
                            print("ADVERTENCIA: resample no disponible, no se pudo remuestrear el bloque de audio. Salida sin remuestreo.")
                        else:
                            # Remuestrear al sample rate del dispositivo de salida, al tamaño del bloque de salida
                            if processed_block.ndim == 1:
                                resampled_data_block = resample(processed_block, num=blocksize_output)
                                if output_channels == 2: # Si la salida es estéreo, duplicar el canal mono
                                    resampled_data_block = np.stack([resampled_data_block, resampled_data_block], axis=-1)
                            else: # Estéreo
                                resampled_data_block = np.zeros((blocksize_output, output_channels), dtype='float32')
                                for i in range(output_channels):
                                    resampled_data_block[:, i] = resample(processed_block[:, i], num=blocksize_output)
                            output_block = resampled_data_block
                    else:
                        # Si no hay remuestreo, solo asegúrate de que el bloque tenga el tamaño correcto (rellenando si es necesario)
                        output_block = processed_block
                        if len(output_block) < blocksize_output:
                            padding = np.zeros((blocksize_output - len(output_block), output_channels), dtype='float32')
                            output_block = np.vstack((output_block, padding))
                        elif len(output_block) > blocksize_output:
                            output_block = output_block[:blocksize_output] # Recortar si es demasiado largo

                    # Aplicar volumen del slider de la aplicación.
                    # Este es el único factor de escala de volumen de la aplicación.
                    # El volumen maestro del sistema operativo DEBERÍA aplicarse después de esto
                    # si el sounddevice está en modo compartido (por defecto).
                    current_volume_linear = self.settings.value("last_volume", 50, type=int) / 100.0
                    output_block = output_block * current_volume_linear

                    # Aplicar fade-in si es el inicio de la canción
                    if is_initial_fade_in and current_frame_pos < fade_in_duration_frames_original:
                        # Calcular los factores de fade-in para la porción remuestreada que se va a reproducir.
                        segment_fade_factors_original = np.linspace(
                            (current_frame_pos / fade_in_duration_frames_original),
                            ((current_frame_pos + actual_input_frames_read) / fade_in_duration_frames_original),
                            actual_input_frames_read, # Basado en los frames originales leídos
                            dtype='float32'
                        )
                        # Remuestrear los factores de fade-in para que coincidan con el bloque de salida.
                        if resample is None:
                            resampled_fade_factors = segment_fade_factors_original # Fallback
                        else:
                            resampled_fade_factors = resample(segment_fade_factors_original, num=blocksize_output)

                        resampled_fade_factors = np.clip(resampled_fade_factors, 0, 1) # Asegurarse que estén entre 0 y 1

                        if output_block.ndim > 1:
                            output_block[:, :] *= resampled_fade_factors[:, np.newaxis]
                        else:
                            output_block[:] *= resampled_fade_factors
                        
                    elif is_initial_fade_in and current_frame_pos >= fade_in_duration_frames_original:
                        is_initial_fade_in = False # Fade-in completado
                        print("DEBUG: Fade-in completado.")


                    # Asegurar que los valores estén dentro del rango válido [-1.0, 1.0] para evitar clipping digital.
                    # Esto NO es para control de volumen, sino para prevenir distorsión.
                    output_block = np.clip(output_block, -1.0, 1.0) 
                    
                    # --- Procesamiento para el Visualizador ---
                    # El visualizador usa los datos remuestreados ya listos para la salida
                    if fft is not None and output_samplerate > 0:
                        mono_block = output_block[:, 0] if output_block.ndim > 1 else output_block
                        N = len(mono_block)
                        
                        window = np.hanning(N)
                        windowed_block = mono_block * window
                        
                        yf = fft(windowed_block)
                        
                        magnitudes = np.abs(yf[0:N//2])
                        
                        # Manejar log de cero o valores muy pequeños
                        magnitudes_log = 20 * np.log10(magnitudes + 1e-9) # Añadir un pequeño valor para evitar log(0)
                        
                        min_db = -80 
                        max_db = 0   
                        normalized_magnitudes = np.clip((magnitudes_log - min_db) / (max_db - min_db), 0, 1)
                        # Asegurarse que no haya NaNs o Infs después del procesamiento
                        normalized_magnitudes = np.nan_to_num(normalized_magnitudes, nan=0.0, posinf=0.0, neginf=0.0)

                        self.update_visualizer_signal.emit(normalized_magnitudes)
                    # ----------------------------------------

                    stream.write(output_block)
                    
                    # Actualizar la posición de reproducción basándose en los frames leídos del archivo ORIGINAL
                    current_frame_pos += actual_input_frames_read
                    self.current_frame = current_frame_pos 
                    
                    print_counter += 1
                    if print_counter % print_interval == 0 or current_frame_pos >= self.total_frames:
                        print(f"DEBUG: _audio_playback_thread_main: Escribiendo frames. Pos: {self.current_frame}/{self.total_frames} (original). Vol: {self.vol_slider.value()}%")


                stream.stop() 
                print("DEBUG: _audio_playback_thread_main: Stream de audio de sounddevice detenido explícitamente.")

        except Exception as e:
            print(f"ERROR: _audio_playback_thread_main: Error fatal en hilo de reproducción de audio: {e}")
            traceback.print_exc() # Imprimir el stack trace completo
            self.playback_finished_event.set() 
        finally:
            print("DEBUG: _audio_playback_thread_main: Hilo de reproducción de audio finalizado (finally block).")

    def stop_playback(self, final_stop=True):
        print("DEBUG: stop_playback: Iniciando proceso de detención.")
        if self.ui_update_timer.isActive():
            self.ui_update_timer.stop()
            print("DEBUG: stop_playback: UI Timer detenido.")

        self.stop_playback_event.set()
        self.pause_playback_event.clear()
        print("DEBUG: stop_playback: Eventos de detención y pausa configurados.")

        # Guardar el estado del reproductor antes de detener
        if self.current_playback_file and os.path.exists(self.current_playback_file) and self.total_frames > 0:
            self.save_player_state_on_stop("StoppedState" if final_stop else "SeekingStop")
        else:
            self.settings.remove("last_opened_song")
            self.settings.remove("last_opened_position")
            print("DEBUG: stop_playback: No se guarda el estado del reproductor (no hay canción activa).")

        # Esperar a que el hilo de audio termine
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

        # Actualizar UI y estado solo si es una detención final
        if final_stop:
            self.is_playing = False # Establecer a False solo en detención final
            self.current_frame = 0
            self.total_frames = 0
            self.current_playback_file = None 
            self.current_audio_data_original = None # Limpiar los datos originales también
            self.visualizer_widget.update_visualization_data(np.array([])) # Resetear visualizador en detención final
            self.update_position_ui(0)
            self.update_duration_ui(0)
            self.update_playback_status_label("StoppedState")
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        # Si no es una detención final (ej. buscando), el estado (is_playing) y la UI
        # serán manejados por load_and_play, que se llama inmediatamente después
        # en seek_position_audio si la reproducción estaba activa.

        print("DEBUG: Reproducción detenida y hilos terminados (fin de stop_playback).")

    def toggle_play(self):
        if not self.playlist:
            self._show_message_box("Info", "La playlist está vacía. Añade canciones para reproducir.")
            return

        if self.current_playback_file is None:
            if self.current_index == -1 and self.playlist:
                self.current_index = 0
            if self.playlist:
                file_to_play = self.playlist[self.current_index]
                self.load_and_play(file_to_play, start_position_ms=0)
            else:
                return

        elif self.is_playing:
            self.pause_playback_event.set()
            self.is_playing = False
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            self.update_playback_status_label("PausedState")
            print("DEBUG: Pausado.")
        else:
            self.pause_playback_event.clear()
            self.is_playing = True
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
            self.update_playback_status_label("PlayingState")
            print("DEBUG: Reanudado.")

    def prev_track(self):
        if not self.playlist: return
        self.stop_playback(final_stop=False)

        if self._shuffle_mode and self.shuffled_playlist:
            self.current_shuffled_index = (self.current_shuffled_index - 1) % len(self.shuffled_playlist)
            next_file = self.shuffled_playlist[self.current_shuffled_index]
            self.load_and_play(next_file)
            self.current_index = self.playlist.index(next_file)
            self.track_list.setCurrentRow(self.current_index)
        else:
            self.current_index = (self.current_index - 1 + len(self.playlist)) % len(self.playlist)
            self.load_and_play(self.playlist[self.current_index])
            self.track_list.setCurrentRow(self.current_index)

    def next_track(self):
        if not self.playlist: return
        self.stop_playback(final_stop=False)

        if self._repeat_mode == self.REPEAT_CURRENT:
            self.load_and_play(self.current_playback_file or self.playlist[self.current_index])
            return

        if self._shuffle_mode and self.shuffled_playlist:
            self.current_shuffled_index = (self.current_shuffled_index + 1) % len(self.shuffled_playlist)
            next_file = self.shuffled_playlist[self.current_shuffled_index]
            self.load_and_play(next_file)
            self.current_index = self.playlist.index(next_file)
            self.track_list.setCurrentRow(self.current_index)
        else:
            self.current_index = (self.current_index + 1) % len(self.playlist)
            self.load_and_play(self.playlist[self.current_index])
            self.track_list.setCurrentRow(self.current_index)

    def toggle_shuffle_mode(self):
        self._shuffle_mode = not self._shuffle_mode
        self.btn_shuffle.setChecked(self._shuffle_mode)
        if self._shuffle_mode:
            self.rebuild_shuffled_playlist()
            self._show_message_box("Modo Aleatorio", "Reproducción aleatoria activada.")
        else:
            if self.current_playback_file and self.current_playback_file in self.playlist:
                self.current_index = self.playlist.index(self.current_playback_file)
                self.track_list.setCurrentRow(self.current_index)
            self._show_message_box("Modo Aleatorio", "Reproducción aleatoria desactivada.")

    def rebuild_shuffled_playlist(self):
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
        self._repeat_mode = (self._repeat_mode + 1) % 3
        if self._repeat_mode == self.NO_REPEAT:
            self.btn_repeat.setIcon(self.icon_repeat_off)
            self._show_message_box("Modo Repetición", "Repetición desactivada.")
        elif self._repeat_mode == self.REPEAT_CURRENT:
            self.btn_repeat.setIcon(self.icon_repeat_single)
            self._show_message_box("Modo Repetición", "Repetir canción actual.")
        else:
            self.btn_repeat.setIcon(self.icon_repeat_all)
            self._show_message_box("Modo Repetición", "Repetir toda la playlist.")

    def play_selected(self):
        selected_items = self.track_list.selectedItems()
        if selected_items:
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
        if not text:
            for i in range(self.track_list.count()):
                self.track_list.item(i).setHidden(False)
        else:
            for i in range(self.track_list.count()):
                item = self.track_list.item(i)
                file_path = self.playlist[i]
                
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
                    pass

                search_string = f"{title} {artist} {album} {os.path.basename(file_path)}".lower()
                if text.lower() in search_string:
                    item.setHidden(False)
                else:
                    item.setHidden(True)

    def show_context_menu(self, position):
        menu = QMenu()
        play_action = menu.addAction("Reproducir")
        remove_action = menu.addAction("Eliminar")
        clear_all_action = menu.addAction("Borrar todo")
        
        action = menu.exec(self.track_list.mapToGlobal(position))
        
        if action == play_action:
            self.play_selected()
        elif action == remove_action:
            self.remove_selected_tracks()
        elif action == clear_all_action:
            self.clear_playlist()

    def _show_message_box(self, title, message):
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
            self.current_index = 0
            self.track_list.setCurrentRow(self.current_index)
            self.update_metadata(self.playlist[self.current_index])
            self.update_position_ui(0)
            print(f"Seleccionada primera canción de la playlist: {os.path.basename(self.playlist[self.current_index])}")
        else:
            print("No se encontró ninguna canción ni playlist anterior para cargar.")

    def save_player_state_on_stop(self, reason="stopped"):
        if self.current_playback_file:
            self.settings.setValue("last_opened_song", self.current_playback_file)
            current_ms = int((self.current_frame / self._file_samplerate) * 1000) if self._file_samplerate > 0 else 0
            self.settings.setValue("last_opened_position", current_ms)
            print(f"Estado del reproductor guardado: {os.path.basename(self.current_playback_file)} a {current_ms}ms (razón: {reason})")
        else:
            self.settings.remove("last_opened_song")
            self.settings.remove("last_opened_position")
            print("Estado del reproductor limpiado (no hay canción activa).")

    def closeEvent(self, event):
        print("Cerrando la aplicación. Deteniendo hilos de audio...")
        self.stop_playback(final_stop=True)
        self.save_player_state_on_stop("application_closed")
        event.accept()

    # --- Métodos de Drag & Drop ---
    def dragEnterEvent(self, event):
        """
        Maneja el evento de arrastrar entrada.
        Acepta el evento si contiene URLs (archivos).
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            # print("DEBUG: dragEnterEvent: URL(s) detectada(s).")
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        """
        Maneja el evento de arrastrar movimiento.
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        """
        Maneja el evento de soltar.
        Procesa las URLs de los archivos soltados y los añade a la playlist.
        """
        if event.mimeData().hasUrls():
            file_paths = []
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    file_paths.append(url.toLocalFile())
            if file_paths:
                print(f"DEBUG: dropEvent: Archivos soltados: {file_paths}")
                self.add_files_to_playlist(file_paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
            
    def update_default_audio_device_display(self):
        """
        Obtiene el dispositivo de salida de audio predeterminado del sistema y actualiza la etiqueta de la UI.
        Si el dispositivo predeterminado cambia mientras se reproduce una canción, reinicia la reproducción en el nuevo dispositivo.
        """
        if not sd:
            self.lbl_output_device.setText("Dispositivo: No SoundDevice")
            print("DEBUG: update_default_audio_device_display: SoundDevice no disponible.")
            # Si SoundDevice no está disponible, no hay nada más que hacer.
            self.selected_output_device_index = -1
            self.lbl_output_device.setStyleSheet("color: #ff6666;") # Color de error
            return

        try:
            # Obtener el ID del dispositivo de salida predeterminado del sistema
            new_default_output_id = sd.default.device[1] 
            
            # Obtener la información completa del dispositivo para su nombre
            device_info = sd.query_devices(new_default_output_id)
            new_default_device_name = device_info['name']
            
            # Actualizar la etiqueta de la UI con el nombre del dispositivo
            self.lbl_output_device.setText(f"Dispositivo: {new_default_device_name}")
            self.lbl_output_device.setStyleSheet("color: #ddd;") # Restaurar color normal

            # Comprobar si el dispositivo predeterminado ha cambiado
            if new_default_output_id != self.selected_output_device_index:
                old_device_name = "desconocido"
                try:
                    if self.selected_output_device_index != -1:
                        old_device_name = sd.query_devices(self.selected_output_device_index)['name']
                except Exception:
                    pass

                print(f"DEBUG: Dispositivo predeterminado cambiado de '{old_device_name}' (ID: {self.selected_output_device_index}) a '{new_default_device_name}' (ID: {new_default_output_id}).")
                
                # Actualizar el ID del dispositivo que se está usando
                self.selected_output_device_index = new_default_output_id
                
                # Si una canción está reproduciéndose, reiniciarla en el nuevo dispositivo
                if self.current_playback_file and self.is_playing:
                    current_pos_ms = int((self.current_frame / self._file_samplerate) * 1000) if self._file_samplerate > 0 else 0
                    print(f"DEBUG: Reiniciando reproducción en el nuevo dispositivo desde {current_pos_ms}ms.")
                    # Detener el stream actual y luego reiniciar la reproducción
                    self.stop_playback(final_stop=False) # Esto detendrá el hilo existente
                    self.load_and_play(self.current_playback_file, start_position_ms=current_pos_ms, stop_current_playback=False)
                    self._show_message_box("Dispositivo de Audio Cambiado", f"Reproducción movida a: {new_default_device_name}")
                elif self.current_playback_file: # Si hay una canción cargada pero no reproduciendo
                    print(f"DEBUG: Dispositivo cambiado a {new_default_device_name}, canción cargada pero no reproduciendo. No se reinicia el stream.")
                    self.stop_playback(final_stop=False) # Asegurar que cualquier stream pendiente se cierra
                    self._show_message_box("Dispositivo de Audio Cambiado", f"Dispositivo de salida ahora es: {new_default_device_name}")
                else: # Si no hay canción cargada
                    print(f"DEBUG: Dispositivo cambiado a {new_default_device_name}. No hay canción para reproducir.")


            # Si es la primera vez que se carga o si no había un dispositivo seleccionado antes
            elif self.selected_output_device_index == -1 and new_default_output_id != -1:
                self.selected_output_device_index = new_default_output_id
                print(f"DEBUG: Primer dispositivo predeterminado detectado: '{new_default_device_name}' (ID: {new_default_output_id}).")


        except Exception as e:
            self.lbl_output_device.setText("Dispositivo: Error al cargar")
            self.lbl_output_device.setStyleSheet("color: #ff6666;") # Color de error
            print(f"ERROR: update_default_audio_device_display: No se pudo obtener el dispositivo predeterminado: {e}")
            self.selected_output_device_index = -1 # Marcar como no disponible

    # --- Constructor de la clase MusicPlayer ---
    def __init__(self):
        super().__init__()
        print("DEBUG: __init__: Super constructor llamado.")
        self.setWindowTitle("Modern PyQt6 Music Player")
        print("DEBUG: __init__: Título de ventana establecido.")
        self.setGeometry(300, 100, 900, 700) # Tamaño inicial
        self.setMinimumSize(800, 600) # Establecer un tamaño mínimo para evitar que se vea mal en tamaños pequeños
        
        self.set_dark_theme()
        print("DEBUG: __init__: Tema oscuro aplicado.")
        self.apply_styles()
        print("DEBUG: __init__: Estilos aplicados.")

        self.settings = QSettings("MyMusicPlayerCompany", "MusicPlayer")
        print("DEBUG: __init__: QSettings inicializado.")

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
        
        self.audio_stream = None
        self.current_playback_file = None
        self.current_audio_data_original = None # Almacenará los datos originales del archivo
        self._file_samplerate = 0 # Samplerate original del archivo
        self.audio_samplerate_output = 0 # Samplerate al que el audio será remuestreado para el dispositivo de salida
        self.audio_channels_original = 0 # Canales del archivo original (o forzado a 2 si es mono)

        # Variables para la UI, siempre se referirán a los datos originales para la duración y posición
        self.audio_samplerate = 0 # Esto es ahora alias de _file_samplerate para compatibilidad con UI
        self.total_frames = 0

        # selected_output_device_index ahora siempre rastreará el ID del dispositivo predeterminado del sistema
        # Su valor inicial se establecerá en la primera llamada a update_default_audio_device_display
        self.selected_output_device_index = -1 
        print(f"DEBUG: __init__: Dispositivo de audio seleccionado inicialmente (se buscará el default).")
        print("DEBUG: __init__: Variables de audio inicializadas.")

        self.stop_playback_event = threading.Event()
        self.pause_playback_event = threading.Event()
        self.playback_finished_event = threading.Event()

        self.audio_playback_thread = None

        self.current_frame = 0 # Posición actual en frames del archivo ORIGINAL

        self.is_playing = False
        print("DEBUG: __init__: Eventos y flags de hilos inicializados.")
        
        self.crossfade_duration_seconds = 2.0 # Duración del fundido de entrada/salida en segundos

        # --- AÑADIDO PARA LA CORRECCIÓN DE DISTORSIÓN ---
        self.eq_master_gain_db = -9.0 # dB de atenuación por defecto para evitar clipping
        self.eq_master_gain_factor = 10**(self.eq_master_gain_db / 20.0)
        print(f"DEBUG: __init__: Ganancia maestra del ecualizador establecida a {self.eq_master_gain_db} dB ({self.eq_master_gain_factor:.2f} lineal).")
        # ------------------------------------------------

        print("DEBUG: __init__: Diseñando filtros de ecualizador iniciales...")
        # Los filtros se diseñan en base a una frecuencia de muestreo por defecto inicial
        # Serán rediseñados en load_and_play si es necesario con _file_samplerate
        self.equalizer_filters = [self._design_band_filter(freq, 0) for freq in self._get_band_frequencies()]
        print("DEBUG: __init__: Filtros de ecualizador diseñados.")
        self.filter_states = []
        print("DEBUG: __init__: Filter states inicializados.")

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

        # Habilitar el arrastrar y soltar para la ventana principal
        self.setAcceptDrops(True)

        top_layout = QHBoxLayout()

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Buscar título, artista o álbum...")
        self.search_input.textChanged.connect(self.filter_track_list) 
        self.search_input.setMinimumWidth(200) # Añadido para dar más espacio a la barra de búsqueda
        search_layout.addWidget(self.search_input)

        self.btn_clear_search = QPushButton(self)
        self.btn_clear_search.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton))
        self.btn_clear_search.setToolTip("Borrar búsqueda")
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
        # Habilitar el arrastrar y soltar también para el QListWidget
        self.track_list.setAcceptDrops(True)
        self.track_list.setDragEnabled(True) # Para permitir arrastrar elementos FUERA de la lista también (opcional)
        self.track_list.setDropIndicatorShown(True)
        self.track_list.setDragDropMode(QListWidget.DragDropMode.InternalMove) # Para reordenar dentro de la lista
        # Conectar la señal rowsMoved para actualizar la playlist interna
        self.track_list.model().rowsMoved.connect(self._handle_playlist_rows_moved)


        self.album_art = QLabel(self)
        self.album_art.setObjectName("albumArt")
        self.album_art.setFixedSize(300, 300)
        self.album_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.album_art.setText("No Album Art")

        # Visualizador de Audio (Nuevo Widget)
        self.visualizer_widget = AudioVisualizerWidget(self)
        self.visualizer_widget.setObjectName("visualizerWidget") # Asignar un ObjectName para posibles estilos CSS futuros
        self.visualizer_widget.setFixedSize(300, 100) # Tamaño fijo para el visualizador
        
        # Layout para el arte del álbum y el visualizador
        right_panel_layout = QVBoxLayout()
        right_panel_layout.addWidget(self.album_art)
        right_panel_layout.addWidget(self.visualizer_widget) # Añadir el nuevo widget de visualización


        top_layout.addWidget(self.track_list)
        top_layout.addLayout(right_panel_layout)
        layout.addLayout(top_layout)
        print("DEBUG: __init__: Lista de pistas, arte de álbum y visualizador configurados.")

        meta_layout = QVBoxLayout()
        self.lbl_title = QLabel("Título: -", self)
        self.lbl_artist = QLabel("Artista: -", self)
        self.lbl_album = QLabel("Álbum: -", self)
        self.lbl_track = QLabel("Pista: -", self)
        for lbl in (self.lbl_title, self.lbl_artist, self.lbl_album, self.lbl_track):
            lbl.setStyleSheet("color: #ddd; font-size: 14px;")
            meta_layout.addWidget(lbl)
        layout.addLayout(meta_layout)
        print("DEBUG: __init__: Etiquetas de metadatos configuradas.")

        self.lbl_status = QLabel("Estado: Detenido", self)
        self.lbl_status.setStyleSheet("color: #aaa; font-size: 12px; font-style: italic;")
        layout.addWidget(self.lbl_status)
        print("DEBUG: __init__: Etiqueta de estado configurada.")

        time_layout = QHBoxLayout()
        self.lbl_elapsed = QLabel("00:00", self)
        self.slider = ClickableSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, 0)
        self.slider.clicked_value_set.connect(self.seek_position_audio) 
        self.slider.sliderPressed.connect(self.stop_player_during_seek)
        self.slider.sliderReleased.connect(self.resume_player_after_seek)
        self.lbl_duration = QLabel("00:00", self)
        time_layout.addWidget(self.lbl_elapsed)
        time_layout.addWidget(self.slider)
        time_layout.addWidget(self.lbl_duration)
        layout.addLayout(time_layout)
        print("DEBUG: __init__: Slider de tiempo configurado.")

        ctrl_layout = QHBoxLayout()
        
        # --- Instanciación de todos los botones y el control de volumen ANTES de añadirlos al layout ---
        # Botones de control de reproducción principales
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
        self.icon_repeat_single = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogYesButton) # Usar otro icono si es posible, o crear uno
        self.icon_repeat_all = self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload) # Usar otro icono si es posible
        self.btn_repeat.setIcon(self.icon_repeat_off)
        self.btn_repeat.clicked.connect(self.toggle_repeat_mode)

        # Barra de volumen
        self.vol_slider = ClickableSlider(Qt.Orientation.Horizontal, self)
        self.vol_slider.setRange(0, 100)
        last_volume = self.settings.value("last_volume", 50, type=int)
        self.vol_slider.setValue(last_volume)
        self.vol_slider.valueChanged.connect(self.set_and_save_volume)
        self.vol_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum) # Permitir que se expanda

        # Nuevo botón de volumen que actuará como un "pop-up" para el slider
        self.btn_volume_menu = QToolButton(self)
        self.btn_volume_menu.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume))
        self.btn_volume_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup) # Muestra el menú al presionar

        # Crear el menú para el botón de volumen
        self.volume_menu = QMenu(self)
        self.volume_slider_action = QWidgetAction(self.volume_menu)
        volume_slider_widget = QWidget(self.volume_menu)
        volume_slider_layout = QHBoxLayout(volume_slider_widget)
        volume_slider_layout.setContentsMargins(5, 5, 5, 5)
        volume_slider_layout.addWidget(QLabel("Volumen:"))
        volume_slider_layout.addWidget(self.vol_slider) # Añadir el slider existente
        volume_slider_widget.setLayout(volume_slider_layout)
        self.volume_slider_action.setDefaultWidget(volume_slider_widget)
        self.volume_menu.addAction(self.volume_slider_action)
        self.btn_volume_menu.setMenu(self.volume_menu)


        self.btn_equalizer = QPushButton(self)
        self.btn_equalizer.setText("Ecualizador")
        self.btn_equalizer.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume))
        self.btn_equalizer.clicked.connect(self.open_equalizer_window)

        # Botón de menú para "Archivo"
        self.btn_menu_file = QToolButton(self)
        self.btn_menu_file.setText("Archivo")
        self.btn_menu_file.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup) # Mostrar menú al presionar
        file_menu = QMenu(self)
        self.action_open_files = file_menu.addAction("Abrir Archivos...")
        self.action_open_files.triggered.connect(self.open_files)
        self.action_open_folder = file_menu.addAction("Abrir Carpeta...")
        self.action_open_folder.triggered.connect(self.open_folder)
        self.action_save_playlist = file_menu.addAction("Guardar Playlist...")
        self.action_save_playlist.triggered.connect(self.save_playlist)
        self.action_load_playlist = file_menu.addAction("Cargar Playlist...")
        self.action_load_playlist.triggered.connect(self.load_playlist)
        # Eliminada la acción de "Refrescar Dispositivos" del menú, ya que la detección es automática.
        self.btn_menu_file.setMenu(file_menu)

        # Botón de menú para "Playlist"
        self.btn_menu_playlist = QToolButton(self)
        self.btn_menu_playlist.setText("Playlist")
        self.btn_menu_playlist.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup) # Mostrar menú al presionar
        playlist_menu = QMenu(self)
        self.action_remove_selected = playlist_menu.addAction("Eliminar Seleccionadas")
        self.action_remove_selected.triggered.connect(self.remove_selected_tracks)
        self.action_clear_playlist = playlist_menu.addAction("Borrar Playlist")
        self.action_clear_playlist.triggered.connect(self.clear_playlist)
        self.action_move_up = playlist_menu.addAction("Mover Arriba")
        self.action_move_up.triggered.connect(self.move_track_up)
        self.action_move_down = playlist_menu.addAction("Mover Abajo")
        self.action_move_down.triggered.connect(self.move_track_down)
        self.btn_menu_playlist.setMenu(playlist_menu)

        # --- Reemplazar QComboBox por QLabel para mostrar el dispositivo de audio ---
        self.lbl_output_device = QLabel("Dispositivo: Cargando...", self) 
        self.lbl_output_device.setStyleSheet("color: #ddd; font-size: 14px;")
        self.lbl_output_device.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_output_device.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Preferred)


        # --- Fin de Instanciación ---

        # Layout para los botones de menú y controles principales
        # Agrupar los botones de menú al inicio
        ctrl_layout.addWidget(self.btn_menu_file)
        ctrl_layout.addWidget(self.btn_menu_playlist)
        ctrl_layout.addWidget(self.btn_equalizer)
        
        # Espaciador flexible para empujar los controles de audio/volumen y reproducción a la derecha
        ctrl_layout.addItem(QSpacerItem(20, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        # Controles de dispositivo de audio
        device_layout = QHBoxLayout()
        device_layout.addWidget(self.lbl_output_device) # Usar la nueva etiqueta
        
        # Add the device layout to the main control layout
        ctrl_layout.addLayout(device_layout)
        
        # Otro espaciador para separar los controles de audio del resto de reproducción
        ctrl_layout.addItem(QSpacerItem(20, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        # Botón de volumen con su menú
        ctrl_layout.addWidget(self.btn_volume_menu)
        
        # Controles de reproducción principales (Prev, Play, Next, Shuffle, Repeat)
        ctrl_layout.addWidget(self.btn_prev)
        ctrl_layout.addWidget(self.btn_play)
        ctrl_layout.addWidget(self.btn_next)
        ctrl_layout.addWidget(self.btn_shuffle)
        ctrl_layout.addWidget(self.btn_repeat)

        layout.addLayout(ctrl_layout)
        print("DEBUG: __init__: Controles de reproducción configurados.")

        self.update_position_signal.connect(self.update_position_ui)
        self.update_duration_signal.connect(self.update_duration_ui)
        self.update_playback_state_signal.connect(self.update_playback_status_label)
        # Conectar la señal del visualizador al nuevo widget de visualización
        self.update_visualizer_signal.connect(self.visualizer_widget.update_visualization_data)


        self.ui_update_timer = QTimer(self)
        self.ui_update_timer.setInterval(100)
        self.ui_update_timer.timeout.connect(self._update_ui_from_threads)
        print("DEBUG: __init__: Señales de UI y timer configurados.")
        
        # Temporizador para refrescar el dispositivo de audio predeterminado periódicamente
        self.device_check_timer = QTimer(self)
        self.device_check_timer.setInterval(5000) # Chequear cada 5 segundos
        self.device_check_timer.timeout.connect(self.update_default_audio_device_display) 
        self.device_check_timer.start()
        print("DEBUG: __init__: Temporizador para refrescar dispositivos iniciado.")

        self.setup_keyboard_shortcuts()
        print("DEBUG: __init__: Atajos de teclado configurados.")

        # Realizar la primera actualización del dispositivo al iniciar la aplicación
        self.update_default_audio_device_display() 
        # Cargar estado de sesión DESPUÉS de poblar dispositivos para que el ID se mapee correctamente
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
        print(f"ERROR FATAL: La aplicación falló durante el inicio: {e}")
        traceback.print_exc()
        sys.exit(1)
