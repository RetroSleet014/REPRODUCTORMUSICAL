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
from PyQt6.QtCore import Qt, QUrl, QVariant, QTimer, QEvent, QSettings, pyqtSignal, QSize, QThread

from ecualizador import EqualizerWindow

try:
    import soundfile as sf
    import sounddevice as sd
    from scipy.signal import iirfilter, lfilter, freqz, resample # Importar resample
    from scipy.fft import fft
    print("Librerías DSP (SoundFile, SoundDevice, SciPy, NumPy) cargadas exitosamente.")
except ImportError as e:
    print(f"Advertencia: No se pudieron cargar todas las librerías DSP. El ecualizador y el visualizador no tendrán efecto audible. Error: {e}")
    class DummySoundDevice:
        def __init__(self, *args, **kwargs): pass
        def start(self): pass
        def stop(self): pass
        def close(self): pass
        def write(self, data): pass
        def active(self): return False
        def query_devices(self, *args, **kwargs): return []
        def query_supported_settings(self, *args, **kwargs): return {'samplerate': 0, 'channels': 0, 'blocksize': 0}
        def default(self):
            class Default:
                def __init__(self):
                    self.device = (0, 0)
                device = (0, 0) # Añadir como atributo de clase para compatibilidad
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
    if 'resample' not in locals() or resample is None:
        def resample(x, num, t=None, axis=0, window=None):
            if x.ndim > 1:
                return np.zeros((num, x.shape[1]), dtype=x.dtype)
            return np.zeros(num, dtype=x.dtype)


# Importaciones para COM (solo en Windows)
if sys.platform == "win32":
    try:
        import comtypes, ctypes
        from comtypes import GUID, HRESULT, COMMETHOD, IUnknown
        from comtypes.client import CreateObject
        from ctypes import POINTER, c_void_p

        # GUID de IMMNotificationClient (definido por Windows)
        IID_IMMNotificationClient = GUID("{7991EEC9-7E89-4D85-8390-6C703CEC60C0}")

        # Definimos constantes de flujos y roles de dispositivo (según audiodef.h)
        EDataFlow = {"eRender": 0, "eCapture": 1, "eAll": 2}
        ERole = {"eConsole": 0, "eMultimedia": 1, "eCommunications": 2}

        # Definir la interfaz IMMNotificationClient
        class IMMNotificationClient(IUnknown):
            _iid_ = IID_IMMNotificationClient
            _methods_ = [
                COMMETHOD([], HRESULT, "OnDeviceStateChanged",
                          (['in'], ctypes.c_wchar_p, 'pwstrDeviceId'),
                          (['in'], ctypes.c_uint, 'dwNewState')),
                COMMETHOD([], HRESULT, "OnDeviceAdded",
                          (['in'], ctypes.c_wchar_p, 'pwstrDeviceId')),
                COMMETHOD([], HRESULT, "OnDeviceRemoved",
                          (['in'], ctypes.c_wchar_p, 'pwstrDeviceId')),
                COMMETHOD([], HRESULT, "OnDefaultDeviceChanged",
                          (['in'], ctypes.c_uint, 'flow'),
                          (['in'], ctypes.c_uint, 'role'),
                          (['in'], ctypes.c_wchar_p, 'pwstrDefaultDeviceId')),
                COMMETHOD([], HRESULT, "OnPropertyValueChanged",
                          (['in'], ctypes.c_wchar_p, 'pwstrDeviceId'),
                          (['in'], ctypes.c_void_p, 'key'))
            ]

        # GUID de la clase MMDeviceEnumerator (componente COM de Windows)
        CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")

        # Definir interfaz IMMDeviceEnumerator
        class IMMDeviceEnumerator(IUnknown):
            _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
            _methods_ = [
                COMMETHOD([], HRESULT, "EnumAudioEndpoints",
                          (['in'], ctypes.c_int, 'dataFlow'),
                          (['in'], ctypes.c_int, 'stateMask'),
                          (['out'], POINTER(c_void_p), 'ppDevices')),
                COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint",
                          (['in'], ctypes.c_int, 'dataFlow'),
                          (['in'], ctypes.c_int, 'role'),
                          (['out'], POINTER(c_void_p), 'ppEndpoint')),
                COMMETHOD([], HRESULT, "GetDevice",
                          (['in'], ctypes.c_wchar_p, 'pwstrId'),
                          (['out'], POINTER(c_void_p), 'ppDevice')),
                COMMETHOD([], HRESULT, "RegisterEndpointNotificationCallback",
                          (['in'], POINTER(IMMNotificationClient), 'pClient')),
                COMMETHOD([], HRESULT, "UnregisterEndpointNotificationCallback",
                          (['in'], POINTER(IMMNotificationClient), 'pClient')),
            ]

        # Clase que implementa IMMNotificationClient. Heredamos de comtypes.COMObject for COM support.
        from comtypes.client import COMObject
        class AudioEndpointNotificationCallback(COMObject):
            _com_interfaces_ = [IMMNotificationClient]

            def __init__(self, on_default_changed_callback):
                super().__init__()
                self.on_default_changed_callback = on_default_changed_callback

            def OnDeviceAdded(self, pwstrDeviceId):
                return 0
            
            def OnDeviceRemoved(self, pwstrDeviceId):
                return 0

            def OnDeviceStateChanged(self, pwstrDeviceId, dwNewState):
                return 0

            def OnDefaultDeviceChanged(self, flow, role, pwstrDefaultDeviceId):
                if flow == EDataFlow["eRender"]: # Solo nos interesan los cambios en dispositivos de salida
                    print(f"[Evento COM] Dispositivo de salida predeterminado cambiado a: ID={pwstrDefaultDeviceId}")
                    if self.on_default_changed_callback:
                        self.on_default_changed_callback(pwstrDefaultDeviceId)
                return 0

            def OnPropertyValueChanged(self, pwstrDeviceId, key):
                return 0
        
        class AudioDeviceWatcherThread(QThread):
            deviceChanged = pyqtSignal(str) # Emite el ID del nuevo dispositivo predeterminado

            def run(self):
                # Inicializar COM en este hilo como Multi-Threaded Apartment (MTA)
                comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
                print("DEBUG: AudioDeviceWatcherThread: COM inicializado como MTA.")

                try:
                    self._enumerator = CreateObject(CLSID_MMDeviceEnumerator, interface=IMMDeviceEnumerator)
                    self._callback = AudioEndpointNotificationCallback(
                        on_default_changed_callback=lambda device_id: self.deviceChanged.emit(device_id)
                    )
                    self._enumerator.RegisterEndpointNotificationCallback(self._callback)
                    print("DEBUG: AudioDeviceWatcherThread: Callback de notificación de audio registrado.")
                    self.exec() # Inicia el loop de eventos de Qt para este hilo
                except Exception as e:
                    print(f"ERROR: AudioDeviceWatcherThread: Falló la inicialización o registro de COM: {e}")
                    traceback.print_exc()
                finally:
                    if hasattr(self, '_enumerator') and self._enumerator:
                        try:
                            self._enumerator.UnregisterEndpointNotificationCallback(self._callback)
                            print("DEBUG: AudioDeviceWatcherThread: Callback de notificación de audio desregistrado.")
                        except Exception as e:
                            print(f"WARN: AudioDeviceWatcherThread: Error al desregistrar callback COM: {e}")
                    comtypes.CoUninitialize()
                    print("DEBUG: AudioDeviceWatcherThread: COM desinicializado.")

    except ImportError as e:
        print(f"Advertencia: Las librerías comtypes/ctypes no se pudieron cargar. La detección de dispositivos por eventos estará deshabilitada. Error: {e}")
        IS_WINDOWS_COM_AVAILABLE = False
    else:
        IS_WINDOWS_COM_AVAILABLE = True
else:
    IS_WINDOWS_COM_AVAILABLE = False
    print("DEBUG: No se requiere COM para la detección de dispositivos de audio en este sistema operativo.")


from mutagen.mp3 import MP3
from mutagen.id3 import ID3NoHeaderError, ID3, APIC
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis


def custom_exception_hook(exctype, value, tb):
    traceback.print_exception(exctype, value, tb)
    error_message = f"Ha ocurrido un error inesperado:\n\nTipo de Error: {exctype.__name__}\n" \
                    f"Mensaje: {value}\n\n" \
                    f"La aplicación puede volverse inestable o cerrarse. " \
                    f"Por favor, contacta al soporte con los detalles a continuación:\n\n" \
                    f"Traceback:\n{''.join(traceback.format_tb(tb))}"

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
    sys.exit(1)


sys.excepthook = custom_exception_hook


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
        self.setMinimumWidth(150)
        self.fft_data = np.array([])
        self.bar_colors = [QColor(80, 160, 220, 200), QColor(60, 140, 200, 200)]

        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._buffer = QPixmap()

    def sizeHint(self):
        return QSize(400, 100)

    def update_visualization_data(self, new_fft_data):
        self.fft_data = np.nan_to_num(new_fft_data, nan=0.0, posinf=0.0, neginf=0.0)
        self.update()

    def paintEvent(self, event):
        current_widget_size = self.size()

        if current_widget_size.width() <= 0 or current_widget_size.height() <= 0 or not self.isVisible():
            return

        if self._buffer.size() != current_widget_size or self._buffer.isNull():
            if current_widget_size.width() > 0 and current_widget_size.height() > 0:
                self._buffer = QPixmap(current_widget_size)
                self._buffer.fill(Qt.GlobalColor.transparent)
                print(f"DEBUG: AudioVisualizerWidget: Buffer de visualizador redimensionado a {current_widget_size.width()}x{current_widget_size.height()}.")
            else:
                print(f"WARN: AudioVisualizerWidget: Tamaño de widget inválido ({current_widget_size.width()}x{current_widget_size.height()}). No se pudo crear el buffer.")
                return

        painter = QPainter(self._buffer)
        # Add check if painter is active before drawing operations
        if not painter.isActive():
            print("ERROR: AudioVisualizerWidget: QPainter no está activo en paintEvent. Abortando dibujo.")
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(42, 42, 42))

        # Initialize display_data to an empty array to prevent UnboundLocalError
        display_data = np.array([])

        if self.fft_data.size > 0:
            width = self.width()
            height = self.height()
            num_bars = 50
            bar_spacing = 2
            bar_width = (width - (num_bars + 1) * bar_spacing) / num_bars

            if bar_width <= 0:
                bar_width = 1
                bar_spacing = max(0, (width - num_bars) // (num_bars + 1))

            # self.fft_data already contains the normalized magnitudes (0 to 1)
            # So we directly use it, and pad if necessary
            if self.fft_data.size >= num_bars:
                display_data = self.fft_data[:num_bars]
            else:
                display_data = np.pad(self.fft_data, (0, num_bars - self.fft_data.size), 'constant', constant_values=0)
            
            for i, val in enumerate(display_data):
                bar_height = val * height * 0.8
                x = i * (bar_width + bar_spacing) + bar_spacing
                y = height - bar_height

                color = self.bar_colors[i % len(self.bar_colors)]
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(color.darker(150), 1))

                painter.drawRoundedRect(int(x), int(y), int(bar_width), int(bar_height), 2, 2)
        else:
            painter.setPen(QPen(QColor(150, 150, 150)))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Cargando audio para visualización...")

        painter.end()

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
    audio_error_signal = pyqtSignal(str, str) # New signal for audio errors (title, message)
    restart_playback_signal = pyqtSignal(int) # New signal to trigger delayed restart

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
                image: none;
            }
            QMenu {
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 5px;
                color: #ddd;
            }
            QMenu::item {
                padding: 8px 20px 8px 15px;
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
        if iirfilter is None or np is None or self._file_samplerate == 0:
            return [1.0], [1.0]

        A = 10**(gain_db / 40.0)
        w0 = 2 * np.pi * center_freq / self._file_samplerate
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
        if self.total_frames > 0 and self._file_samplerate > 0:
            current_ms = int((self.current_frame / self._file_samplerate) * 1000)
            total_ms = int((self.total_frames / self._file_samplerate) * 1000)
            self.update_position_signal.emit(current_ms)
            self.update_duration_signal.emit(total_ms)

        if self.playback_finished_event.is_set():
            print("DEBUG: UI Update: playback_finished_event detectado. Manejando fin de canción.")
            self.playback_finished_event.clear()
            # ... (existing repeat/next track logic) ...
            if self._repeat_mode == self.REPEAT_CURRENT:
                print("DEBUG: Repetir canción actual.")
                if self.current_playback_file:
                    self.load_and_play(self.current_playback_file, start_position_ms=0, auto_start_playback=True)
                else:
                    self.stop_playback(final_stop=True)
            elif self._repeat_mode == self.REPEAT_ALL:
                print("DEBUG: Repetir toda la playlist.")
                if self._shuffle_mode and self.shuffled_playlist:
                    current_shuffled_idx = self.current_shuffled_index
                    next_shuffled_idx = (current_shuffled_idx + 1) % len(self.shuffled_playlist)
                    if next_shuffled_idx == len(self.shuffled_playlist) and current_shuffled_idx == len(self.shuffled_playlist) - 1:
                        print("DEBUG: Fin de playlist aleatoria, reiniciando al principio.")
                        self.rebuild_shuffled_playlist()
                        next_file = self.shuffled_playlist[0]
                        self.current_shuffled_index = 0
                    else:
                        next_file = self.shuffled_playlist[next_shuffled_idx]
                        self.current_shuffled_index = next_shuffled_idx
                    self.load_and_play(next_file, auto_start_playback=True)
                    self.current_index = self.playlist.index(next_file)
                    self.track_list.setCurrentRow(self.current_index)
                elif self.playlist:
                    current_idx = self.current_index
                    next_idx = (current_idx + 1) % len(self.playlist)
                    next_file = self.playlist[next_idx]
                    self.current_index = next_idx
                    self.load_and_play(next_file, auto_start_playback=True)
                    self.track_list.setCurrentRow(self.current_index)
                else:
                    self.stop_playback(final_stop=True)
            else:
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
                        next_ui_index = self.playlist.index(next_file)
                        print(f"DEBUG: Reproduciendo siguiente en modo aleatorio: {os.path.basename(next_file)}")
                    else:
                        print("DEBUG: Fin de playlist aleatoria (NO_REPEAT).")
                elif self.playlist:
                    current_idx = self.current_index
                    next_idx = current_idx + 1
                    if next_idx < len(self.playlist):
                        next_song_exists = True
                        next_file = self.playlist[next_idx]
                        self.current_index = next_idx
                        next_ui_index = next_idx
                        print(f"DEBUG: Reproduciendo siguiente en modo secuencial: {os.path.basename(next_file)}")
                    else:
                        print("DEBUG: Fin de playlist secuencial (NO_REPEAT).")

                if next_song_exists and next_file:
                    self.load_and_play(next_file, auto_start_playback=True)
                    if next_ui_index != -1:
                        self.track_list.setCurrentRow(next_ui_index)
                else:
                    print("DEBUG: No hay más canciones para reproducir. Deteniendo reproducción.")
                    self.stop_playback(final_stop=True)
                    self.update_playback_status_label("StoppedState")
        elif self.stop_playback_event.is_set():
            print("DEBUG: UI Update: stop_playback detectado. Deteniendo hilo de audio y UI.")
            self.stop_playback_event.clear()
            self.current_frame = 0
            self.update_position_signal.emit(0)
            self.update_duration_signal.emit(0)
            self.update_visualizer_signal.emit(np.array([]))
            self.update_playback_status_label("StoppedState")

        if self.audio_playback_thread and not self.audio_playback_thread.is_alive() and not self.stop_playback_event.is_set():
            print("DEBUG: Hilo de audio terminó inesperadamente o completó su tarea.")
            self.audio_playback_thread = None


    def set_and_save_volume(self, value):
        self.settings.setValue("last_volume", value)
        print(f"Volumen ajustado a: {value}%")

    def setup_keyboard_shortcuts(self):
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
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

        target_frame = int((target_ms / 1000.0) * self._file_samplerate)
        target_frame = max(0, min(target_frame, self.total_frames))

        was_playing_before_seek_op = self.is_playing and not self.pause_playback_event.is_set()

        self.stop_playback(final_stop=False)
        print("DEBUG: seek_position_audio: stop_playback() completado.")

        self.current_frame = target_frame
        self.update_position_ui(target_ms)
        print(f"DEBUG: seek_position_audio: current_frame ajustado a {self.current_frame}.")

        if was_playing_before_seek_op:
            print("DEBUG: seek_position_audio: Era reproduciendo, reiniciando desde nueva posición.")
            self.load_and_play(self.current_playback_file, start_position_ms=target_ms, stop_current_playback=False, auto_start_playback=True)
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
        self.lbl_album.setText("Álbum: -")
        self.lbl_track.setText("Pista: -")
        self.album_art.clear()
        self.album_art.setText("No Album Art")
        self.slider.setRange(0, 0)
        self.slider.setValue(0)
        self.lbl_elapsed.setText("00:00")
        self.lbl_duration.setText("00:00")

        self.update_window_title()
        self.update_playback_status_label("StoppedState")
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
        old_index = start
        new_index = row

        if old_index == new_index or old_index == new_index - 1:
            return

        moved_file = self.playlist.pop(old_index)

        if new_index > old_index:
            self.playlist.insert(new_index - 1, moved_file)
            new_index_for_logic = new_index - 1
        else:
            self.playlist.insert(new_index, moved_file)
            new_index_for_logic = new_index

        print(f"DEBUG: Playlist reordenada: {os.path.basename(moved_file)} movido de {old_index} a {new_index_for_logic}.")

        if self.current_playback_file:
            try:
                new_current_index = self.playlist.index(self.current_playback_file)
                if new_current_index != self.current_index:
                    self.current_index = new_current_index
                    self.track_list.setCurrentRow(self.current_index)
                    print(f"DEBUG: current_index actualizado a {self.current_index}")
            except ValueError:
                print("Advertencia: Canción actual no encontrada en la playlist después del reordenamiento (esto no debería ocurrir).")

        if self._shuffle_mode:
            self.rebuild_shuffled_playlist()
            if self.current_playback_file and self.current_playback_file in self.shuffled_playlist:
                self.current_shuffled_index = self.shuffled_playlist.index(self.current_playback_file)
            else:
                self.current_shuffled_index = -1

    def _find_optimal_device_samplerate(self, file_samplerate, device_index, num_channels):
        if sd is None:
            return file_samplerate

        try:
            device_info = sd.query_devices(device_index)

            prioritized_samplerates = [file_samplerate, 48000, 44100, 96000, 88200]
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
                    pass

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

            print(f"ADVERTENCIA: No se encontró una frecuencia de muestreo compatible para el dispositivo {device_index} y {num_channels} canales. Usando la del archivo {file_samplerate}.")
            return file_samplerate

        except Exception as e:
            print(f"ERROR: No se pudo consultar las capacidades del dispositivo {device_index}: {e}")
            return file_samplerate


    def load_and_play(self, file_path, start_position_ms=0, stop_current_playback=True, auto_start_playback=False):
        if sf is None or sd is None or resample is None:
            print("ERROR: load_and_play: Las librerías DSP (SoundFile, SoundDevice, SciPy) no están cargadas. El reproductor no puede funcionar.")
            self.update_playback_status_label("StoppedState")
            return

        if not file_path or not os.path.exists(file_path):
            self.update_playback_status_label("StoppedState")
            return

        if stop_current_playback:
            print("DEBUG: load_and_play: Llamando stop_playback para limpiar reproducción anterior.")
            self.stop_playback(final_stop=False)

        try:
            self.current_playback_file = file_path

            data_from_file, file_samplerate = sf.read(file_path, dtype='float32')

            if data_from_file.ndim == 1:
                self.current_audio_data_original = np.stack([data_from_file, data_from_file], axis=-1)
                self.audio_channels_original = 2
            else:
                self.current_audio_data_original = data_from_file
                self.audio_channels_original = self.current_audio_data_original.shape[1]

            self._file_samplerate = file_samplerate

            self.audio_samplerate_output = self._find_optimal_device_samplerate(
                self._file_samplerate, self.selected_output_device_index, self.audio_channels_original
            )

            self.audio_samplerate = self._file_samplerate
            self.total_frames = len(self.current_audio_data_original)

            self.current_frame = int((start_position_ms / 1000.0) * self._file_samplerate)
            self.current_frame = max(0, min(self.current_frame, self.total_frames))
            print(f"DEBUG: load_and_play: current_frame after setting based on start_position_ms: {self.current_frame}")

            if self.audio_channels_original > 0:
                self.equalizer_filters = [self._design_band_filter(freq, gain)
                                          for freq, gain in zip(self._get_band_frequencies(), self.equalizer_settings)]
                self.filter_states = [np.zeros((max(len(b), len(a)) - 1, self.audio_channels_original))
                                      for b, a in self.equalizer_filters]
            else:
                self.filter_states = []
            print("DEBUG: load_and_play: Estados de filtro reseteados.")

            try:
                self.current_index = self.playlist.index(file_path)
                self.track_list.setCurrentRow(self.current_index)
            except ValueError:
                self.current_index = -1
            self.update_metadata(file_path)
            self.update_position_ui(start_position_ms)

            if auto_start_playback:
                print("DEBUG: load_and_play: Iniciando nuevo hilo de audio para auto_play.")
                self.stop_playback_event.clear()
                self.pause_playback_event.clear()
                self.playback_finished_event.clear()
                self.audio_playback_thread = threading.Thread(
                    target=self._audio_playback_thread_main,
                    args=(start_position_ms, self.audio_samplerate_output, self.audio_channels_original),
                    daemon=True
                )
                self.audio_playback_thread.start()
                self.is_playing = True
                self.ui_update_timer.start()
                self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
                self.update_playback_status_label("PlayingState")
            else:
                print("DEBUG: load_and_play: Canción cargada y preparada, pero no auto-reproducida.")
                if self.audio_playback_thread and self.audio_playback_thread.is_alive():
                    self.stop_playback(final_stop=False) # Ensure previous thread is stopped
                self.is_playing = False
                self.pause_playback_event.set() # Ensure paused state is set
                self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
                self.update_playback_status_label("StoppedState")

            print(f"DEBUG: load_and_play: Preparada: {os.path.basename(file_path)}")

        except Exception as e:
            print(f"ERROR: load_and_play: No se pudo reproducir el archivo: {e}")
            traceback.print_exc()
            if self._current_device_status != 'disconnected':
                self.audio_error_signal.emit("Error de Reproducción", f"No se pudo reproducir el archivo: {e}")
            self.stop_playback(final_stop=True)
            self.update_playback_status_label("StoppedState")


    def _audio_playback_thread_main(self, initial_position_ms, output_samplerate, output_channels):
        critical_audio_thread_error_for_ui = False
        error_title = ""
        error_message = ""

        if sd is None or self.current_audio_data_original is None:
            print("ERROR: _audio_playback_thread_main: sd o current_audio_data_original es None al iniciar el hilo.")
            self.playback_finished_event.set()
            return
        
        print("DEBUG: _audio_playback_thread_main: Hilo de reproducción de audio iniciado.")

        blocksize_output = 1024
        stream = None

        try:
            current_default_device_id = self.selected_output_device_index
            if current_default_device_id == -1:
                print("ERROR: No se encontró un dispositivo de audio de salida predeterminado válido al iniciar el hilo.")
                if self._current_device_status == 'disconnected':
                    print("DEBUG: Hilo de audio: Dispositivo ya marcado como desconectado. Saliendo limpiamente.")
                    return
                else:
                    critical_audio_thread_error_for_ui = True
                    error_title = "Error de Audio"
                    error_message = "No se encontró un dispositivo de audio de salida predeterminado válido."
                    return

            stream_opened = False
            retry_attempts = 3
            for attempt in range(retry_attempts):
                try:
                    sd.check_output_settings(
                        device=current_default_device_id,
                        samplerate=output_samplerate,
                        channels=output_channels,
                        dtype='float32'
                    )
                    print(f"DEBUG: _audio_playback_thread_main: Configuración de salida de audio verificada: soportada (Intento {attempt + 1}).")

                    stream = sd.OutputStream(device=current_default_device_id,
                                             samplerate=output_samplerate,
                                             channels=output_channels,
                                             dtype='float32',
                                             blocksize=blocksize_output)
                    stream.start()
                    self.audio_stream = stream
                    stream_opened = True
                    print(f"DEBUG: _audio_playback_thread_main: Stream de audio de sounddevice iniciado (Intento {attempt + 1}).")
                    break
                except sd.PortAudioError as pa_err:
                    print(f"WARN: _audio_playback_thread_main: PortAudioError durante la apertura del stream (Intento {attempt + 1}/{retry_attempts}): {pa_err}")
                    if stream:
                        try:
                            stream.stop()
                            stream.close()
                        except Exception as exc:
                            print(f"WARN: _audio_playback_thread_main: Error al limpiar stream en reintento: {exc}")
                        finally:
                            stream = None

                    if attempt < retry_attempts - 1:
                        time.sleep(0.1 * (attempt + 1))
                    else:
                        if self._current_device_status != 'disconnected':
                            raise
                        else:
                            print("DEBUG: Apertura de stream fallida pero dispositivo ya desconectado. Saliendo.")
                            return

            if not stream_opened:
                if self._current_device_status != 'disconnected':
                    critical_audio_thread_error_for_ui = True
                    error_title = "Error de Dispositivo de Audio"
                    error_message = f"No se pudo iniciar la reproducción después de {retry_attempts} intentos. Verifique sus dispositivos de audio."
                return

            current_frame_pos = self.current_frame
            print(f"DEBUG: _audio_playback_thread_main: Starting playback from current_frame_pos: {current_frame_pos}")

            print_counter = 0
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

                # CRITICAL CHECK: Before writing to the stream, check if the device is still connected
                if self._current_device_status == 'disconnected':
                    print("DEBUG: _audio_playback_thread_main: Dispositivo desconectado durante la reproducción. Pausando y saliendo del hilo.")
                    self.pause_playback_event.set() # Ensure playback is paused
                    return # Exit the thread immediately and gracefully

                if current_frame_pos >= self.total_frames:
                    print("DEBUG: _audio_playback_thread_main: Fin de la canción (current_frame_pos >= total_frames). Señalando finalización.")
                    self.playback_finished_event.set()
                    break

                input_frames_to_read_original = int(np.ceil(blocksize_output * (self._file_samplerate / output_samplerate)))
                if input_frames_to_read_original == 0: input_frames_to_read_original = 1

                frames_available_original = self.total_frames - current_frame_pos
                actual_input_frames_read = min(input_frames_to_read_original, frames_available_original)

                if actual_input_frames_read <= 0:
                    print("DEBUG: _audio_playback_thread_main: No más frames para leer de archivo original. Fin de la canción.")
                    self.playback_finished_event.set()
                    break

                input_block_original = self.current_audio_data_original[current_frame_pos : current_frame_pos + actual_input_frames_read]

                processed_block = input_block_original * self.eq_master_gain_factor

                current_filter_states = [arr.copy() for arr in self.filter_states]
                current_equalizer_filters = list(self.equalizer_filters)

                for i, (b, a) in enumerate(current_equalizer_filters):
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

                self.filter_states = current_filter_states

                if self._file_samplerate != output_samplerate:
                    if resample is None:
                        output_block = processed_block
                        print("ADVERTENCIA: resample no disponible, no se pudo remuestrear el bloque de audio. Salida sin remuestreo.")
                    else:
                        if processed_block.ndim == 1:
                            resampled_data_block = resample(processed_block, num=blocksize_output)
                            if output_channels == 2:
                                resampled_data_block = np.stack([resampled_data_block, resampled_data_block], axis=-1)
                        else:
                            resampled_data_block = np.zeros((blocksize_output, output_channels), dtype='float32')
                            for i in range(output_channels):
                                resampled_data_block[:, i] = resample(processed_block[:, i], num=blocksize_output)
                        output_block = resampled_data_block
                else:
                    output_block = processed_block
                    if len(output_block) < blocksize_output:
                        padding = np.zeros((blocksize_output - len(output_block), output_channels), dtype='float32')
                        output_block = np.vstack((output_block, padding))
                    elif len(output_block) > blocksize_output:
                        output_block = output_block[:blocksize_output]

                current_volume_linear = self.settings.value("last_volume", 50, type=int) / 100.0
                output_block = output_block * current_volume_linear

                if is_initial_fade_in and current_frame_pos < fade_in_duration_frames_original:
                    segment_fade_factors_original = np.linspace(
                        (current_frame_pos / fade_in_duration_frames_original),
                        ((current_frame_pos + actual_input_frames_read) / fade_in_duration_frames_original),
                        actual_input_frames_read,
                        dtype='float32'
                    )
                    if resample is None:
                        resampled_fade_factors = segment_fade_factors_original
                    else:
                        resampled_fade_factors = resample(segment_fade_factors_original, num=blocksize_output)

                    resampled_fade_factors = np.clip(resampled_fade_factors, 0, 1)

                    if output_block.ndim > 1:
                        output_block[:, :] *= resampled_fade_factors[:, np.newaxis]
                    else:
                        output_block[:] *= resampled_fade_factors

                elif is_initial_fade_in and current_frame_pos >= fade_in_duration_frames_original:
                    is_initial_fade_in = False
                    print("DEBUG: Fade-in completado.")

                output_block = np.clip(output_block, -1.0, 1.0)

                if fft is not None and output_samplerate > 0:
                    mono_block = output_block[:, 0] if output_block.ndim > 1 else output_block
                    N = len(mono_block)

                    window = np.hanning(N)
                    windowed_block = mono_block * window

                    yf = fft(windowed_block)

                    magnitudes = np.abs(yf[0:N//2])

                    magnitudes_log = 20 * np.log10(magnitudes + 1e-9)

                    min_db = -80
                    max_db = 0
                    normalized_magnitudes = np.clip((magnitudes_log - min_db) / (max_db - min_db), 0, 1)
                    normalized_magnitudes = np.nan_to_num(normalized_magnitudes, nan=0.0, posinf=0.0, neginf=0.0)

                    self.update_visualizer_signal.emit(normalized_magnitudes)
                try:
                    stream.write(output_block)
                except sd.PortAudioError as pa_err_inner:
                    # Catch PortAudioError here to differentiate from external device changes
                    print(f"ERROR: _audio_playback_thread_main: PortAudioError durante stream.write: {pa_err_inner}")
                    # Check for specific error code by inspecting the error message string
                    if '[PaErrorCode -9999]' in str(pa_err_inner):
                        print(f"DEBUG: Unanticipated host error (-9999) detected. Signalling restart.")
                        if stream and stream.active: # Ensure stream is stopped before exiting thread
                            try:
                                stream.stop()
                                stream.close()
                                print("DEBUG: Problematic audio stream stopped and closed.")
                            except Exception as exc:
                                print(f"WARN: Error stopping stream during -9999 error handling: {exc}")
                        self.audio_stream = None # Clear reference managed by this thread
                        current_pos_ms = int((self.current_frame / self._file_samplerate) * 1000) if self._file_samplerate > 0 else 0
                        self.restart_playback_signal.emit(current_pos_ms) # Signal UI thread for recovery
                        self.pause_playback_event.set() # Ensure current thread pauses
                        return # Exit the audio thread cleanly
                    else: # Other PortAudioErrors
                        try:
                            # Re-query the default device to check if it's still available
                            _ = sd.default.device[1] # This will raise PortAudioError if no device
                            # If we get here, it means a device is still default but something else broke the stream
                            critical_audio_thread_error_for_ui = True
                            error_title = "Error de Dispositivo de Audio"
                            error_message = f"Un error inesperado ocurrió con el dispositivo de audio: {pa_err_inner}. Por favor, verifica que tus auriculares/altavoces estén conectados y los drivers estén actualizados."
                            self.pause_playback_event.set()
                            return
                        except sd.PortAudioError:
                            print("DEBUG: _audio_playback_thread_main: Dispositivo de audio desconectado (detectado en stream.write). Pausando y saliendo del hilo.")
                            self.pause_playback_event.set()
                            return
                        except Exception as inner_e:
                            print(f"ERROR: _audio_playback_thread_main: Error al verificar dispositivo interno: {inner_e}")
                            critical_audio_thread_error_for_ui = True
                            error_title = "Error de Audio Crítico"
                            error_message = f"Fallo al verificar dispositivo: {inner_e}. Original: {pa_err_inner}"
                            self.pause_playback_event.set()
                            return


                current_frame_pos += actual_input_frames_read
                self.current_frame = current_frame_pos

                print_counter += 1
                if print_counter % print_interval == 0 or current_frame_pos >= self.total_frames:
                    print(f"DEBUG: _audio_playback_thread_main: Escribiendo frames. Pos: {self.current_frame}/{self.total_frames} (original). Vol: {self.vol_slider.value()}%")

            if stream and stream.active:
                stream.stop()
                print("DEBUG: _audio_playback_thread_main: Stream de audio de sounddevice detenido explícitamente.")

        except sd.PortAudioError as pa_err:
            print(f"ERROR: _audio_playback_thread_main: Error de PortAudio (captura externa): {pa_err}")
            traceback.print_exc()
            
            # This outer catch should ideally only catch if the stream failed to even open,
            # or if an unexpected PortAudioError happened *outside* the write loop.
            # If the device was already detected as disconnected, don't trigger UI message.
            if self._current_device_status != 'disconnected':
                critical_audio_thread_error_for_ui = True
                error_title = "Error de Dispositivo de Audio"
                error_message = f"Un error inesperado ocurrió con el dispositivo de audio: {pa_err}. Por favor, verifica que tus auriculares/altavoces estén conectados y los drivers estén actualizados."
            
            self.pause_playback_event.set()
            if stream and stream.active:
                try:
                    stream.stop()
                    stream.close()
                    print("DEBUG: _audio_playback_thread_main: Stream de audio de sounddevice detenido y cerrado por error.")
                except Exception as exc:
                    print(f"ERROR: _audio_playback_thread_main: Error al intentar limpiar stream después de PortAudioError (externa): {exc}")
            self.audio_stream = None

        except Exception as e:
            print(f"ERROR: _audio_playback_thread_main: Error fatal en hilo de reproducción de audio: {e}")
            traceback.print_exc()
            critical_audio_thread_error_for_ui = True
            error_title = "Error de Reproducción"
            error_message = f"Ocurrió un error inesperado durante la reproducción: {e}. La reproducción ha sido detenida."
            self.playback_finished_event.set()
        finally:
            print("DEBUG: _audio_playback_thread_main: Hilo de reproducción de audio finalizado (finally block).")
            # Only close stream if it was opened locally in this thread and is still active
            if stream and stream.active: 
                try:
                    stream.stop()
                    stream.close()
                    print("DEBUG: _audio_playback_thread_main: Stream de audio de sounddevice detenido y cerrado en finally.")
                except Exception as exc:
                    print(f"ERROR: _audio_playback_thread_main: Error al intentar detener/cerrar stream en finally: {exc}")
            # Do NOT set self.audio_stream = None here. This is managed by the main thread's stop_playback
            # or by load_and_play starting a new thread/stream.
            # Setting it to None here might cause race conditions if the main thread still expects it.
            # The main thread (via stop_playback) is responsible for nullifying self.audio_stream if needed.


        if critical_audio_thread_error_for_ui:
            self.audio_error_signal.emit(error_title, error_message)

    def _handle_audio_error_in_ui(self, title, message):
        """Slot para mostrar mensajes de error de audio de forma segura en el hilo de UI y actualizar estado."""
        print(f"DEBUG: _handle_audio_error_in_ui: Recibido error: {title} - {message}")
        self.update_playback_status_label("PausedState")
        self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self._show_message_box(title, message)

    def _delayed_restart_playback(self, start_position_ms):
        """Slot para manejar el reinicio demorado de la reproducción (usado para auto-reconexión)."""
        print(f"DEBUG: _delayed_restart_playback: Intentando reiniciar la reproducción desde {start_position_ms}ms.")
        if self.current_playback_file and self._current_device_status == 'connected': # Only restart if device is connected
            self.load_and_play(self.current_playback_file, start_position_ms=start_position_ms, auto_start_playback=True)
        else:
            print("DEBUG: _delayed_restart_playback: No hay archivo para reiniciar o dispositivo no conectado.")
            self.stop_playback(final_stop=True) # Ensure full stop if nothing to play

    def _on_system_audio_device_changed(self, new_device_id_str):
        """
        Slot que se activa cuando el AudioDeviceWatcherThread detecta un cambio en el dispositivo de audio por defecto.
        Este slot corre en el hilo principal (UI).
        """
        print(f"DEBUG: _on_system_audio_device_changed: Notificación de cambio de dispositivo del sistema recibida. Nuevo ID: {new_device_id_str}")
        self.update_default_audio_device_display()


    def stop_playback(self, final_stop=True):
        print("DEBUG: stop_playback: Iniciando proceso de detención.")
        if self.ui_update_timer.isActive():
            self.ui_update_timer.stop()
            print("DEBUG: stop_playback: UI Timer detenido.")

        self.stop_playback_event.set()
        self.pause_playback_event.clear()
        print("DEBUG: stop_playback: Eventos de detención y pausa configurados.")

        if final_stop and self.current_playback_file and os.path.exists(self.current_playback_file) and self.total_frames > 0:
            self.save_player_state_on_stop("StoppedState")
        elif not final_stop and self.current_playback_file and os.path.exists(self.current_playback_file) and self.total_frames > 0:
            print(f"DEBUG: stop_playback: No se guarda el estado de reproducción persistente en detención temporal ('{os.path.basename(self.current_playback_file)}', razón: SeekingStop).")
        else:
            self.settings.remove("last_opened_song")
            self.settings.remove("last_opened_position")
            self.settings.remove("last_playback_state_playing")
            print("DEBUG: stop_playback: No se guarda el estado del reproductor (no hay canción activa).")

        if self.audio_playback_thread and self.audio_playback_thread.is_alive():
            print("DEBUG: stop_playback: Esperando que el hilo de audio termine...")
            self.audio_playback_thread.join(timeout=2.0)
            if self.audio_playback_thread.is_alive():
                print("Advertencia: El hilo de reproducción de audio no terminó a tiempo. Puede estar colgado.")
                if self.audio_stream and self.audio_stream.active:
                    try:
                        self.audio_stream.stop()
                        self.audio_stream.close()
                        print("DEBUG: stop_playback: Stream de audio forzado a detener y cerrar.")
                    except Exception as exc:
                        print(f"ERROR: stop_playback: Error al forzar la detención del stream: {exc}")
                self.audio_stream = None # Ensure it's set to None regardless of success or failure
            else:
                print("DEBUG: stop_playback: El hilo de reproducción de audio ha terminado limpiamente.")
        else:
            print("DEBUG: stop_playback: No hay hilo de audio activo para detener.")

        self.stop_playback_event.clear()
        self.playback_finished_event.clear()

        if final_stop:
            self.is_playing = False
            self.current_frame = 0
            self.total_frames = 0
            self.current_playback_file = None
            self.current_audio_data_original = None
            self.visualizer_widget.update_visualization_data(np.array([]))
            self.update_position_ui(0)
            self.update_duration_ui(0)
            self.update_playback_status_label("StoppedState")
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))

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
                self.load_and_play(file_to_play, start_position_ms=0, auto_start_playback=True)
            else:
                return

        elif self.is_playing:
            self.pause_playback_event.set()
            self.is_playing = False
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            self.update_playback_status_label("PausedState")
            print("DEBUG: Pausado.")
        else:
            if self.current_playback_file:
                print("DEBUG: Reanudando desde estado pausado/detenido.")
                current_pos_ms = int((self.current_frame / self._file_samplerate) * 1000) if self._file_samplerate > 0 else 0
                self.load_and_play(self.current_playback_file, start_position_ms=current_pos_ms, auto_start_playback=True)
            else:
                if self.playlist:
                    self.current_index = 0
                    file_to_play = self.playlist[self.current_index]
                    self.load_and_play(file_to_play, start_position_ms=0, auto_start_playback=True)
                else:
                    self._show_message_box("Info", "La playlist está vacía. No hay nada que reanudar.")
                    return
            print("DEBUG: Reanudado (vía toggle_play).")

    def prev_track(self):
        if not self.playlist: return
        self.stop_playback(final_stop=False)

        if self._shuffle_mode and self.shuffled_playlist:
            self.current_shuffled_index = (self.current_shuffled_index - 1) % len(self.shuffled_playlist)
            next_file = self.shuffled_playlist[self.current_shuffled_index]
            self.load_and_play(next_file, auto_start_playback=True)
            self.current_index = self.playlist.index(next_file)
            self.track_list.setCurrentRow(self.current_index)
        else:
            self.current_index = (self.current_index - 1 + len(self.playlist)) % len(self.playlist)
            self.load_and_play(self.playlist[self.current_index], auto_start_playback=True)
            self.track_list.setCurrentRow(self.current_index)

    def next_track(self):
        if not self.playlist: return
        self.stop_playback(final_stop=False)

        if self._repeat_mode == self.REPEAT_CURRENT:
            self.load_and_play(self.current_playback_file or self.playlist[self.current_index], auto_start_playback=True)
            return

        if self._shuffle_mode and self.shuffled_playlist:
            self.current_shuffled_index = (self.current_shuffled_index + 1) % len(self.shuffled_playlist)
            next_file = self.shuffled_playlist[self.current_shuffled_index]
            self.load_and_play(next_file, auto_start_playback=True)
            self.current_index = self.playlist.index(next_file)
            self.track_list.setCurrentRow(self.current_index)
        else:
            self.current_index = (self.current_index + 1) % len(self.playlist)
            self.load_and_play(self.playlist[self.current_index], auto_start_playback=True)
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
                self.load_and_play(selected_file_path, auto_start_playback=True)
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
                self.is_playing = False
                self.load_and_play(last_song, start_position_ms=last_position, auto_start_playback=False)
                self.update_playback_status_label("StoppedState")
                self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            else:
                print(f"Advertencia: La última canción '{last_song}' no se encontró en la playlist cargada.")
        elif self.playlist:
            self.current_index = 0
            self.track_list.setCurrentRow(self.current_index)
            self.update_metadata(self.playlist[self.current_index])
            self.update_position_ui(0)
            self.is_playing = False
            self.load_and_play(self.playlist[self.current_index], start_position_ms=0, auto_start_playback=False)
            self.update_playback_status_label("StoppedState")
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            print(f"Seleccionada primera canción de la playlist: {os.path.basename(self.playlist[self.current_index])}")
        else:
            print("No se encontró ninguna canción ni playlist anterior para cargar.")


    def save_player_state_on_stop(self, reason="stopped"):
        if self.current_playback_file:
            self.settings.setValue("last_opened_song", self.current_playback_file)
            current_ms = int((self.current_frame / self._file_samplerate) * 1000) if self._file_samplerate > 0 else 0
            self.settings.setValue("last_opened_position", current_ms)
            self.settings.setValue("last_playback_state_playing", self.is_playing and not self.pause_playback_event.is_set())
            print(f"Estado del reproductor guardado: {os.path.basename(self.current_playback_file)} a {current_ms}ms, Playing: {self.is_playing and not self.pause_playback_event.is_set()} (razón: {reason})")
        else:
            self.settings.remove("last_opened_song")
            self.settings.remove("last_opened_position")
            self.settings.remove("last_playback_state_playing")
            print("Estado del reproductor limpiado (no hay canción activa).")

    def closeEvent(self, event):
        print("Cerrando la aplicación. Deteniendo hilos de audio...")
        self.save_player_state_on_stop("application_closed")
        
        self.stop_playback(final_stop=True)
        
        # Detener el hilo de monitoreo de dispositivos si está activo
        if IS_WINDOWS_COM_AVAILABLE and hasattr(self, 'deviceWatcher') and self.deviceWatcher.isRunning():
            self.deviceWatcher.quit()
            self.deviceWatcher.wait(2000) # Espera hasta 2 segundos para que el hilo termine

        event.accept()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
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
        if not sd:
            self.lbl_output_device.setText("Dispositivo: No SoundDevice")
            print("DEBUG: update_default_audio_device_display: SoundDevice no disponible.")
            self.selected_output_device_index = -1
            self.lbl_output_device.setStyleSheet("color: #ff6666;")
            self._current_device_status = 'disconnected'
            return

        try:
            # sd.default.device will try to query the default device.
            # If it fails (e.g., due to no device or PortAudio error), it will raise an exception.
            new_default_output_id = sd.default.device[1] # Output device ID

            if new_default_output_id == -1:
                raise sd.PortAudioError("No default output device found (ID -1).")
            
            device_info = sd.query_devices(new_default_output_id)
            new_default_device_name = device_info['name']
            
            # Scenario 1: Device was disconnected and now a valid device is found/reconnected
            # OR first time a device is detected after app start
            if new_default_output_id != self.selected_output_device_index or self._current_device_status != 'connected':
                old_device_name = "desconocido"
                try:
                    if self.selected_output_device_index != -1:
                        old_device_info = sd.query_devices(self.selected_output_device_index)
                        old_device_name = old_device_info['name']
                except Exception:
                    pass # Ignore if old device info cannot be retrieved

                print(f"DEBUG: Dispositivo predeterminado cambiado de '{old_device_name}' (ID: {self.selected_output_device_index}) a '{new_default_device_name}' (ID: {new_default_output_id}).")
                self.selected_output_device_index = new_default_output_id
                self.lbl_output_device.setText(f"Dispositivo: {new_default_device_name}")
                self.lbl_output_device.setStyleSheet("color: #ddd;")
                self._current_device_status = 'connected'

                # Reconfigurar sounddevice para que apunte al nuevo por defecto
                try:
                    sd.default.device = (sd.default.device[0], new_default_output_id)
                    print(f"DEBUG: sounddevice: default output device set to ID {new_default_output_id}")
                except Exception as e:
                    print(f"WARN: no se pudo reconfigurar sd.default.device: {e}")

                # If a song was loaded and was playing or paused due to device issue, try to resume
                if self.current_playback_file and self._is_app_initialized_for_playback_state:
                    current_pos_ms = int((self.current_frame / self._file_samplerate) * 1000) if self._file_samplerate > 0 else 0
                    
                    self.stop_playback(final_stop=False) # Pause cleanly before restarting

                    print(f"DEBUG: Reiniciando canción en el nuevo dispositivo desde {current_pos_ms}ms (auto-reanudación).")
                    self.load_and_play(self.current_playback_file,
                                    start_position_ms=current_pos_ms,
                                    stop_current_playback=False, # Don't stop entirely, just restart stream
                                    auto_start_playback=True)
            # Scenario 2: Current device is still the default and connected (no change in default device)
            elif new_default_output_id == self.selected_output_device_index and self._current_device_status == 'connected':
                self.lbl_output_device.setText(f"Dispositivo: {new_default_device_name}")
                self.lbl_output_device.setStyleSheet("color: #ddd;")

        except sd.PortAudioError as pa_err:
            print(f"ERROR: update_default_audio_device_display: PortAudioError al obtener el dispositivo predeterminado: {pa_err}")
            if self._current_device_status == 'connected':
                print("DEBUG: Error de dispositivo detectado mientras estaba conectado. Transicionando a estado desconectado.")
                if self.current_playback_file and (self.is_playing or not self.pause_playback_event.is_set()):
                    print("DEBUG: Dispositivo desconectado. Pausando reproducción activa.")
                    self.stop_playback(final_stop=False) # Pause cleanly
                    self.update_playback_status_label("PausedState")
                self.lbl_output_device.setText("Dispositivo: Desconectado")
                self.lbl_output_device.setStyleSheet("color: #ff6666;")
                self._current_device_status = 'disconnected'
            else:
                self.lbl_output_device.setText("Dispositivo: Desconectado") # Keep disconnected status if already was
                self.lbl_output_device.setStyleSheet("color: #ff6666;")
                self._current_device_status = 'disconnected'
            self.selected_output_device_index = -1
        
        except Exception as e:
            print(f"ERROR: update_default_audio_device_display: Error inesperado: {e}")
            self.lbl_output_device.setText("Dispositivo: Error")
            self.lbl_output_device.setStyleSheet("color: #ff6666;")
            self._current_device_status = 'unknown' # Or 'error' state
            self.selected_output_device_index = -1


    def __init__(self):
        super().__init__()
        print("DEBUG: __init__: Super constructor llamado.")
        self.setWindowTitle("Modern PyQt6 Music Player")
        print("DEBUG: __init__: Título de ventana establecido.")
        self.setGeometry(300, 100, 900, 700)
        self.setMinimumSize(800, 600)

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
        self.current_audio_data_original = None
        self._file_samplerate = 0
        self.audio_samplerate_output = 0
        self.audio_channels_original = 0

        self._is_app_initialized_for_playback_state = False
        self._current_device_status = 'unknown' # 'unknown', 'connected', 'disconnected'

        self.audio_samplerate = 0
        self.total_frames = 0

        self.selected_output_device_index = -1
        print(f"DEBUG: __init__: Dispositivo de audio seleccionado inicialmente (se buscará el default).")
        print("DEBUG: __init__: Variables de audio inicializadas.")

        self.stop_playback_event = threading.Event()
        self.pause_playback_event = threading.Event()
        self.playback_finished_event = threading.Event()

        self.audio_playback_thread = None

        self.current_frame = 0

        self.is_playing = False
        print("DEBUG: __init__: Eventos y flags de hilos inicializados.")

        self.crossfade_duration_seconds = 2.0

        self.eq_master_gain_db = -9.0
        self.eq_master_gain_factor = 10**(self.eq_master_gain_db / 20.0)
        print(f"DEBUG: __init__: Ganancia maestra del ecualizador establecida a {self.eq_master_gain_db} dB ({self.eq_master_gain_factor:.2f} lineal).")

        print("DEBUG: __init__: Diseñando filtros de ecualizador iniciales...")
        self.equalizer_filters = [self._design_band_filter(freq, 0) for freq in self._get_band_frequencies()]
        print("DEBUG: __init__: Filtros del ecualizador diseñados.")
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

        self.setAcceptDrops(True)

        top_layout = QHBoxLayout()

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Buscar título, artista o álbum...")
        self.search_input.textChanged.connect(self.filter_track_list)
        self.search_input.setMinimumWidth(200)
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
        self.track_list.setAcceptDrops(True)
        self.track_list.setDragEnabled(True)
        self.track_list.setDropIndicatorShown(True)
        self.track_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.track_list.model().rowsMoved.connect(self._handle_playlist_rows_moved)


        self.album_art = QLabel(self)
        self.album_art.setObjectName("albumArt")
        self.album_art.setFixedSize(300, 300)
        self.album_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.album_art.setText("No Album Art")

        self.visualizer_widget = AudioVisualizerWidget(self)
        self.visualizer_widget.setObjectName("visualizerWidget")
        self.visualizer_widget.setFixedSize(300, 100)

        right_panel_layout = QVBoxLayout()
        right_panel_layout.addWidget(self.album_art)
        right_panel_layout.addWidget(self.visualizer_widget)


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
        self.vol_slider.valueChanged.connect(self.set_and_save_volume)
        self.vol_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.btn_volume_menu = QToolButton(self)
        self.btn_volume_menu.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume))
        self.btn_volume_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self.volume_menu = QMenu(self)
        self.volume_slider_action = QWidgetAction(self.volume_menu)
        volume_slider_widget = QWidget(self.volume_menu)
        volume_slider_layout = QHBoxLayout(volume_slider_widget)
        volume_slider_layout.setContentsMargins(5, 5, 5, 5)
        volume_slider_layout.addWidget(QLabel("Volumen:"))
        volume_slider_layout.addWidget(self.vol_slider)
        volume_slider_widget.setLayout(volume_slider_layout)
        self.volume_slider_action.setDefaultWidget(volume_slider_widget)
        self.volume_menu.addAction(self.volume_slider_action)
        self.btn_volume_menu.setMenu(self.volume_menu)


        self.btn_equalizer = QPushButton(self)
        self.btn_equalizer.setText("Ecualizador")
        self.btn_equalizer.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume))
        self.btn_equalizer.clicked.connect(self.open_equalizer_window)

        self.btn_menu_file = QToolButton(self)
        self.btn_menu_file.setText("Archivo")
        self.btn_menu_file.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        file_menu = QMenu(self)
        self.action_open_files = file_menu.addAction("Abrir Archivos...")
        self.action_open_files.triggered.connect(self.open_files)
        self.action_open_folder = file_menu.addAction("Abrir Carpeta...")
        self.action_open_folder.triggered.connect(self.open_folder)
        self.action_save_playlist = file_menu.addAction("Guardar Playlist...")
        self.action_save_playlist.triggered.connect(self.save_playlist)
        self.action_load_playlist = file_menu.addAction("Cargar Playlist...")
        self.action_load_playlist.triggered.connect(self.load_playlist)
        self.btn_menu_file.setMenu(file_menu)

        self.btn_menu_playlist = QToolButton(self)
        self.btn_menu_playlist.setText("Playlist")
        self.btn_menu_playlist.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
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

        self.lbl_output_device = QLabel("Dispositivo: Cargando...", self)
        self.lbl_output_device.setStyleSheet("color: #ddd; font-size: 14px;")
        self.lbl_output_device.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_output_device.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Preferred)

        ctrl_layout.addWidget(self.btn_menu_file)
        ctrl_layout.addWidget(self.btn_menu_playlist)
        ctrl_layout.addWidget(self.btn_equalizer)

        ctrl_layout.addItem(QSpacerItem(20, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        device_layout = QHBoxLayout()
        device_layout.addWidget(self.lbl_output_device)

        ctrl_layout.addLayout(device_layout)

        ctrl_layout.addItem(QSpacerItem(20, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        ctrl_layout.addWidget(self.btn_volume_menu)

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
        self.update_visualizer_signal.connect(self.visualizer_widget.update_visualization_data)
        self.audio_error_signal.connect(self._handle_audio_error_in_ui)
        self.restart_playback_signal.connect(self._delayed_restart_playback)
        # Connect the new system audio device changed signal
        if IS_WINDOWS_COM_AVAILABLE:
            self.deviceWatcher = AudioDeviceWatcherThread()
            self.deviceWatcher.deviceChanged.connect(self._on_system_audio_device_changed)
            self.deviceWatcher.start()
            print("DEBUG: __init__: AudioDeviceWatcherThread iniciado para detección de eventos COM.")
        else:
            print("INFO: La detección de cambios de dispositivo de audio basada en eventos de Windows no está disponible.")


        self.ui_update_timer = QTimer(self)
        self.ui_update_timer.setInterval(100)
        self.ui_update_timer.timeout.connect(self._update_ui_from_threads)
        print("DEBUG: __init__: Señales de UI y timer configurados.")

        self.setup_keyboard_shortcuts()
        print("DEBUG: __init__: Atajos de teclado configurados.")

        # Realizar la primera actualización del dispositivo al iniciar la aplicación
        self.update_default_audio_device_display() 
        # Cargar estado de sesión DESPUÉS de poblar dispositivos para que el ID se mapee correctamente
        self.load_last_session_state() 

        self._is_app_initialized_for_playback_state = True

        # Eliminar el temporizador de sondeo si la detección de eventos COM está disponible
        if not IS_WINDOWS_COM_AVAILABLE:
            # Si COM no está disponible, mantener el temporizador de sondeo como respaldo.
            self.device_check_timer = QTimer(self)
            self.device_check_timer.setInterval(2000) # Chequear cada 5 segundos
            self.device_check_timer.timeout.connect(self.update_default_audio_device_display) 
            self.device_check_timer.start()
            print("DEBUG: __init__: Temporizador para refrescar dispositivos iniciado (modo sondeo).")
        else:
            # Si COM está disponible, este temporizador ya no es necesario
            if hasattr(self, 'device_check_timer'):
                self.device_check_timer.stop()
                del self.device_check_timer
            print("DEBUG: __init__: Temporizador de sondeo de dispositivos deshabilitado (usando detección por eventos COM).")


        print("DEBUG: __init__: Estado de sesión cargado.")
        self.update_window_title()
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
