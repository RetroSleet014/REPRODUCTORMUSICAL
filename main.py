import sys
import os
import random
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QListWidget, QLabel, QFileDialog, QStyle,
    QSizePolicy, QSpacerItem, QLineEdit
)
from PyQt6.QtGui import QPalette, QColor, QPixmap, QImage
from PyQt6.QtCore import Qt, QUrl, QEvent

# Importaciones de QtMultimedia
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtMultimedia import QAudioOutput

# Importaciones para metadatos (mutagen)
from mutagen.mp3 import MP3
from mutagen.id3 import ID3NoHeaderError, ID3, APIC
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis


class ClickableSlider(QSlider):
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.orientation() == Qt.Orientation.Horizontal:
                value = self.minimum() + ((self.maximum() - self.minimum()) * event.pos().x()) / self.width()
            else:
                value = self.minimum() + ((self.maximum() - self.minimum()) * (self.height() - event.pos().y())) / self.height()
            self.setValue(int(value))
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)


class MusicPlayer(QMainWindow):
    NO_REPEAT = 0
    REPEAT_CURRENT = 1
    REPEAT_ALL = 2

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modern PyQt6 Music Player")
        self.setGeometry(300, 100, 900, 700)
        self.set_dark_theme()
        self.apply_styles()

        # Configuración del reproductor de audio
        self.audio_output = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)

        self.playlist = []
        self.shuffled_playlist = []
        self.current_index = -1
        self.current_shuffled_index = -1
        self.all_files = []

        self._shuffle_mode = False
        self._repeat_mode = self.NO_REPEAT

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Barra de búsqueda
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Search title, artist, or album...")
        self.search_input.textChanged.connect(self.filter_track_list)
        layout.addWidget(self.search_input)

        # Lista de pistas y carátula
        top_layout = QHBoxLayout()
        self.track_list = QListWidget(self)
        self.track_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.track_list.doubleClicked.connect(self.play_selected)

        self.album_art = QLabel(self)
        self.album_art.setObjectName("albumArt")
        self.album_art.setFixedSize(300, 300)
        self.album_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.album_art.setText("No Album Art")

        top_layout.addWidget(self.track_list)
        top_layout.addWidget(self.album_art)
        layout.addLayout(top_layout)

        # Metadatos
        meta_layout = QVBoxLayout()
        self.lbl_title = QLabel("Title: -", self)
        self.lbl_artist = QLabel("Artist: -", self)
        self.lbl_album = QLabel("Album: -", self)
        self.lbl_track = QLabel("Track: -", self)
        for lbl in (self.lbl_title, self.lbl_artist, self.lbl_album, self.lbl_track):
            lbl.setStyleSheet("color: #ddd; font-size: 14px;")
            meta_layout.addWidget(lbl)
        layout.addLayout(meta_layout)

        # Deslizador de tiempo
        time_layout = QHBoxLayout()
        self.lbl_elapsed = QLabel("00:00", self)
        self.slider = ClickableSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self.seek_position)
        self.slider.sliderPressed.connect(self.stop_player_during_seek)
        self.slider.sliderReleased.connect(self.resume_player_after_seek)
        self.lbl_duration = QLabel("00:00", self)
        time_layout.addWidget(self.lbl_elapsed)
        time_layout.addWidget(self.slider)
        time_layout.addWidget(self.lbl_duration)
        layout.addLayout(time_layout)

        # Controles de reproducción
        ctrl_layout = QHBoxLayout()
        self.btn_open = QPushButton(self)
        self.btn_open.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self.btn_open.clicked.connect(self.open_files)

        self.btn_open_folder = QPushButton(self)
        self.btn_open_folder.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.btn_open_folder.clicked.connect(self.open_folder)

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
        self.vol_slider.setValue(50)
        self.audio_output.setVolume(0.5)
        self.vol_slider.valueChanged.connect(lambda v: self.audio_output.setVolume(v/100))
        self.vol_slider.setFixedWidth(120)

        for w in (self.btn_open, self.btn_open_folder, self.btn_prev, self.btn_play, self.btn_next,
                  self.btn_shuffle, self.btn_repeat,
                  QSpacerItem(20, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum),
                  self.vol_slider):
            if isinstance(w, QSpacerItem):
                ctrl_layout.addItem(w)
            else:
                ctrl_layout.addWidget(w)
        layout.addLayout(ctrl_layout)

        # Conexiones de señales
        self.player.positionChanged.connect(self.update_position)
        self.player.durationChanged.connect(self.update_duration)
        self.player.mediaStatusChanged.connect(self.media_status_changed)

        self._was_playing_before_seek = False
        self.setup_keyboard_shortcuts()

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
                self.next_track()
                return True
            elif event.key() == Qt.Key.Key_Left:
                self.prev_track()
                return True
            elif event.key() == Qt.Key.Key_Up:
                self.vol_slider.setValue(min(100, self.vol_slider.value() + 5))
                return True
            elif event.key() == Qt.Key.Key_Down:
                self.vol_slider.setValue(max(0, self.vol_slider.value() - 5))
                return True
        return super().eventFilter(obj, event)

    def stop_player_during_seek(self):
        self._was_playing_before_seek = (self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        if self._was_playing_before_seek:
            self.player.pause()

    def resume_player_after_seek(self):
        if self._was_playing_before_seek:
            self.player.play()
            self._was_playing_before_seek = False

    def update_metadata(self, file_path):
        title = os.path.splitext(os.path.basename(file_path))[0]
        artist = '-'
        album = '-'
        tracknum = '-'
        album_art_data = None

        try:
            audio = None
            if file_path.lower().endswith('.mp3'):
                audio = MP3(file_path)
            elif file_path.lower().endswith('.flac'):
                audio = FLAC(file_path)
            elif file_path.lower().endswith(('.ogg', '.oga')):
                audio = OggVorbis(file_path)

            if audio and audio.tags:
                if 'title' in audio.tags and audio.tags['title']:
                    title = str(audio.tags['title'][0])
                elif 'TIT2' in audio.tags and audio.tags['TIT2']:
                    title = str(audio.tags['TIT2'])
                if 'artist' in audio.tags and audio.tags['artist']:
                    artist = str(audio.tags['artist'][0])
                elif 'TPE1' in audio.tags and audio.tags['TPE1']:
                    artist = str(audio.tags['TPE1'])
                if 'album' in audio.tags and audio.tags['album']:
                    album = str(audio.tags['album'][0])
                elif 'TALB' in audio.tags and audio.tags['TALB']:
                    album = str(audio.tags['TALB'])
                if 'tracknumber' in audio.tags and audio.tags['tracknumber']:
                    tracknum = str(audio.tags['tracknumber'][0]).split('/')[0]
                elif 'TRCK' in audio.tags:
                    tracknum = str(audio.tags['TRCK']).split('/')[0]

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
            print(f"No ID3 header: {file_path}")
        except Exception as e:
            print(f"Error reading tags: {e}")

        self.lbl_title.setText(f"Title: {title}")
        self.lbl_artist.setText(f"Artist: {artist}")
        self.lbl_album.setText(f"Album: {album}")
        self.lbl_track.setText(f"Track: {tracknum}")

        pix = None
        if album_art_data:
            image = QImage()
            if image.loadFromData(album_art_data):
                pix = QPixmap.fromImage(image)
        if pix and not pix.isNull():
            pix = pix.scaled(self.album_art.size(), Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            self.album_art.setPixmap(pix)
        else:
            self.album_art.clear()
            self.album_art.setText("No Album Art")

    def add_files_to_playlist(self, files):
        if files:
            for f in files:
                if f not in self.all_files:
                    self.all_files.append(f)
                    self.playlist.append(f)
                    self.track_list.addItem(os.path.basename(f))
            if self._shuffle_mode:
                self.rebuild_shuffled_playlist()
            if self.current_index == -1 and self.playlist:
                if self._shuffle_mode and self.shuffled_playlist:
                    self.load_and_play(self.shuffled_playlist[0])
                else:
                    self.load_and_play(self.playlist[0])

    def open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, 'Open Music Files', '', 'Audio Files (*.mp3 *.wav *.ogg *.flac)'
        )
        self.add_files_to_playlist(files)

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Open Music Folder')
        if folder:
            self.scan_folder_recursive(folder)

    def scan_folder_recursive(self, folder):
        exts = ('.mp3', '.wav', '.ogg', '.oga', '.flac')
        found = []
        for root, _, files in os.walk(folder):
            for fn in files:
                if fn.lower().endswith(exts):
                    found.append(os.path.join(root, fn))
        self.add_files_to_playlist(found)

    def load_and_play(self, file_path):
        if not file_path or file_path not in self.playlist:
            return
        self.current_index = self.playlist.index(file_path)
        if self._shuffle_mode:
            try:
                self.current_shuffled_index = self.shuffled_playlist.index(file_path)
            except ValueError:
                self.rebuild_shuffled_playlist()
                self.current_shuffled_index = 0 if self.shuffled_playlist else -1

        url = QUrl.fromLocalFile(file_path)
        self.player.setSource(url)
        self.player.play()
        self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        self.track_list.setCurrentRow(self.current_index)
        self.update_metadata(file_path)

    def rebuild_shuffled_playlist(self):
        self.shuffled_playlist = list(self.playlist)
        random.shuffle(self.shuffled_playlist)

    def play_selected(self, idx):
        fp = self.playlist[idx.row()]
        self.load_and_play(fp)

    def seek_position(self, pos):
        self.player.setPosition(pos)

    def update_position(self, pos):
        self.slider.blockSignals(True)
        self.slider.setValue(pos)
        self.slider.blockSignals(False)
        s = pos // 1000
        m, s = divmod(s, 60)
        self.lbl_elapsed.setText(f"{m:02d}:{s:02d}")

    def update_duration(self, dur):
        self.slider.setRange(0, dur)
        s = dur // 1000
        m, s = divmod(s, 60)
        self.lbl_duration.setText(f"{m:02d}:{s:02d}")

    def prev_track(self):
        if not self.playlist: return
        if self.player.position() >= 4000 and self._repeat_mode != self.REPEAT_CURRENT:
            self.player.setPosition(0)
            return
        if self._shuffle_mode:
            if not self.shuffled_playlist: return
            self.current_shuffled_index = (self.current_shuffled_index - 1) % len(self.shuffled_playlist)
            next_fp = self.shuffled_playlist[self.current_shuffled_index]
        else:
            if self.current_index > 0:
                self.current_index -= 1
                next_fp = self.playlist[self.current_index]
            elif self._repeat_mode == self.REPEAT_ALL:
                self.current_index = len(self.playlist) - 1
                next_fp = self.playlist[self.current_index]
            else:
                self.player.stop()
                self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
                return
        self.load_and_play(next_fp)

    def next_track(self):
        if not self.playlist: return
        if self._shuffle_mode:
            if not self.shuffled_playlist: return
            self.current_shuffled_index = (self.current_shuffled_index + 1) % len(self.shuffled_playlist)
            next_fp = self.shuffled_playlist[self.current_shuffled_index]
        else:
            if self.current_index < len(self.playlist) - 1:
                self.current_index += 1
                next_fp = self.playlist[self.current_index]
            elif self._repeat_mode == self.REPEAT_ALL:
                self.current_index = 0
                next_fp = self.playlist[self.current_index]
            else:
                self.player.stop()
                self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
                return
        self.load_and_play(next_fp)

    def toggle_play(self):
        state = self.player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        else:
            if self.player.source() and self.player.source().isValid():
                self.player.play()
                self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
            elif self.playlist:
                file_to_play = (
                    self.shuffled_playlist[self.current_shuffled_index]
                    if self._shuffle_mode and self.shuffled_playlist
                    else self.playlist[self.current_index if self.current_index != -1 else 0]
                )
                self.load_and_play(file_to_play)

    def media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self._repeat_mode == self.REPEAT_CURRENT:
                self.player.setPosition(0)
                self.player.play()
            elif self._repeat_mode == self.REPEAT_ALL:
                self.next_track()
            else:
                if self._shuffle_mode:
                    if self.current_shuffled_index < len(self.shuffled_playlist) - 1:
                        self.next_track()
                    else:
                        self.player.stop()
                        self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
                        self.current_shuffled_index = -1
                else:
                    if self.current_index < len(self.playlist) - 1:
                        self.next_track()
                    else:
                        self.player.stop()
                        self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
                        self.current_index = -1

    def toggle_shuffle_mode(self):
        self._shuffle_mode = self.btn_shuffle.isChecked()
        if self._shuffle_mode:
            self.rebuild_shuffled_playlist()
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState and self.playlist:
                fp = self.playlist[self.current_index]
                try:
                    self.current_shuffled_index = self.shuffled_playlist.index(fp)
                except ValueError:
                    self.current_shuffled_index = 0
        else:
            self.current_shuffled_index = -1
        self.update_shuffle_button_icon()

    def update_shuffle_button_icon(self):
        if self._shuffle_mode:
            self.btn_shuffle.setStyleSheet("background: #50b8f0;")
        else:
            self.btn_shuffle.setStyleSheet("")

    def toggle_repeat_mode(self):
        self._repeat_mode = (self._repeat_mode + 1) % 3
        if self._repeat_mode == self.NO_REPEAT:
            self.btn_repeat.setIcon(self.icon_repeat_off)
        elif self._repeat_mode == self.REPEAT_CURRENT:
            self.btn_repeat.setIcon(self.icon_repeat_single)
        else:
            self.btn_repeat.setIcon(self.icon_repeat_all)
        self.update_repeat_button_style()

    def update_repeat_button_style(self):
        if self._repeat_mode != self.NO_REPEAT:
            self.btn_repeat.setStyleSheet("background: #50b8f0;")
        else:
            self.btn_repeat.setStyleSheet("")

    def filter_track_list(self, text):
        self.track_list.clear()
        st = text.lower()
        for f in self.playlist:
            name = os.path.splitext(os.path.basename(f))[0]
            if not st:
                self.track_list.addItem(os.path.basename(f))
            else:
                try:
                    tags = None
                    if f.lower().endswith('.mp3'):
                        tags = MP3(f).tags
                    elif f.lower().endswith('.flac'):
                        tags = FLAC(f).tags
                    elif f.lower().endswith(('.ogg', '.oga')):
                        tags = OggVorbis(f).tags
                    title = tags.get('title',[name])[0] if tags and 'title' in tags else name
                    artist = tags.get('artist',[''])[0] if tags and 'artist' in tags else ''
                    album = tags.get('album',[''])[0] if tags and 'album' in tags else ''
                except:
                    title, artist, album = name, '', ''
                if st in title.lower() or st in artist.lower() or st in album.lower():
                    self.track_list.addItem(os.path.basename(f))

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
            QMainWindow { background-color: #1a1a1a; }
            QListWidget { background-color: #2b2b2b; border: 1px solid #444;
                          border-radius: 10px; color: #ddd; padding: 5px; }
            QListWidget::item { padding: 8px; margin-bottom: 2px; border-radius: 5px; }
            QListWidget::item:selected { background-color: #50b8f0; color: black; }
            QLabel { color: #ddd; }
            QLabel#albumArt { background-color: #3a3a3a; border: 1px solid #555;
                              border-radius: 10px; qproperty-alignment: AlignCenter;
                              color: #bbb; font-size: 16px; }
            QSlider::groove:horizontal { height: 8px; background: #555; border-radius: 4px; }
            QSlider::handle:horizontal { width: 16px; height: 16px; background: #50b8f0;
                                         border-radius: 8px; margin: -4px 0; }
            QSlider::add-page:horizontal { background: #888; }
            QSlider::sub-page:horizontal { background: #50b8f0; }
            QSlider::groove:vertical { width: 8px; background: #555; border-radius: 4px; }
            QSlider::handle:vertical { width: 16px; height: 16px; background: #50b8f0;
                                       border-radius: 8px; margin: 0 -4px; }
            QSlider::add-page:vertical { background: #888; }
            QSlider::sub-page:vertical { background: #50b8f0; }
            QPushButton { background: #333; border: none; border-radius: 8px;
                          padding: 10px 15px; color: white; font-size: 14px; }
            QPushButton:hover { background: #444; }
            QPushButton:pressed { background: #222; }
            QPushButton[checkable="true"][checked="true"] { background: #50b8f0; }
            QLineEdit { background-color: #2b2b2b; border: 1px solid #444;
                        border-radius: 8px; color: #ddd; padding: 8px; font-size: 14px; }
            QLineEdit:focus { border: 1px solid #50b8f0; }
        """)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = MusicPlayer()
    win.show()
    sys.exit(app.exec())
