import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QListWidget, QLabel, QFileDialog, QStyle, QSizePolicy, QSpacerItem
)
from PyQt5.QtGui import QPalette, QColor, QPixmap
from PyQt5.QtMultimedia import QMediaPlayer, QMediaPlaylist, QMediaContent
from PyQt5.QtCore import Qt, QUrl

class MusicPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modern PyQt Music Player")
        self.setGeometry(300, 100, 900, 650)
        self.set_dark_theme()
        self.apply_styles()

        # Core playback objects
        self.player = QMediaPlayer()
        self.playlist = QMediaPlaylist()
        self.player.setPlaylist(self.playlist)

        # Central widget and layout
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        # Top area: track list + album art
        top_layout = QHBoxLayout()
        self.track_list = QListWidget()
        self.track_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.track_list.doubleClicked.connect(self.play_selected)

        self.album_art = QLabel()
        self.album_art.setObjectName("albumArt")
        self.album_art.setFixedSize(350, 350)
        self.album_art.setAlignment(Qt.AlignCenter)
        self.album_art.setText("Album Art")

        top_layout.addWidget(self.track_list)
        top_layout.addWidget(self.album_art)
        main_layout.addLayout(top_layout)

        # Mid area: time slider + labels
        time_layout = QHBoxLayout()
        self.lbl_elapsed = QLabel("00:00")
        self.lbl_duration = QLabel("00:00")
        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderMoved.connect(self.seek_position)

        time_layout.addWidget(self.lbl_elapsed)
        time_layout.addWidget(self.position_slider)
        time_layout.addWidget(self.lbl_duration)
        main_layout.addLayout(time_layout)

        # Bottom controls
        control_layout = QHBoxLayout()
        control_layout.setSpacing(15)

        # Open files/folder
        self.btn_open = QPushButton()
        self.btn_open.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        self.btn_open.clicked.connect(self.open_files)
        self.btn_open.setToolTip("Open Files")

        self.btn_open_folder = QPushButton()
        self.btn_open_folder.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.btn_open_folder.clicked.connect(self.open_folder)
        self.btn_open_folder.setToolTip("Open Folder")

        # Playback navigation
        self.btn_prev = QPushButton()
        self.btn_prev.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipBackward))
        self.btn_prev.clicked.connect(self.prev_track)
        self.btn_prev.setToolTip("Previous / Restart")

        self.btn_play = QPushButton()
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_play.setToolTip("Play / Pause")

        self.btn_next = QPushButton()
        self.btn_next.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipForward))
        self.btn_next.clicked.connect(self.playlist.next)
        self.btn_next.setToolTip("Next")

        # Volume
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(50)
        self.player.setVolume(50)
        self.vol_slider.setFixedWidth(120)
        self.vol_slider.valueChanged.connect(self.player.setVolume)
        self.vol_slider.setToolTip("Volume")

        # Add spacers and widgets
        control_layout.addWidget(self.btn_open)
        control_layout.addWidget(self.btn_open_folder)
        control_layout.addItem(QSpacerItem(20, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))
        control_layout.addWidget(self.btn_prev)
        control_layout.addWidget(self.btn_play)
        control_layout.addWidget(self.btn_next)
        control_layout.addItem(QSpacerItem(20, 0, QSizePolicy.Expanding, QSizePolicy.Minimum))
        control_layout.addWidget(self.vol_slider)
        main_layout.addLayout(control_layout)

        # Signals
        self.player.positionChanged.connect(self.update_position)
        self.player.durationChanged.connect(self.update_duration)
        self.playlist.currentMediaChanged.connect(self.reset_album_art)

    def set_dark_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(25, 25, 25))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(35, 35, 35))
        palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
        palette.setColor(QPalette.ToolTipBase, Qt.white)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(35, 35, 35))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.Highlight, QColor(80, 160, 220))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        self.setPalette(palette)

    def apply_styles(self):
        self.setStyleSheet("""
            QListWidget {
                background-color: #2b2b2b;
                border: none;
                border-radius: 10px;
                padding: 8px;
                color: #ddd;
                font-size: 14px;
            }
            QLabel#albumArt {
                background-color: #444;
                border-radius: 10px;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #555;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 14px;
                background: #50b8f0;
                border-radius: 7px;
                margin: -4px 0;
            }
            QPushButton {
                background-color: #333;
                border: none;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #444;
            }
        """)

    def open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Open Music Files", "", "Audio Files (*.mp3 *.wav *.ogg)"
        )
        self.add_to_playlist(files)

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Open Music Folder", "")
        if folder:
            files = [os.path.join(folder, f) for f in os.listdir(folder)
                     if f.lower().endswith(('.mp3', '.wav', '.ogg'))]
            self.add_to_playlist(files)

    def add_to_playlist(self, files):
        for file in files:
            url = QUrl.fromLocalFile(file)
            self.playlist.addMedia(QMediaContent(url))
            self.track_list.addItem(url.fileName())
        if files:
            self.playlist.setCurrentIndex(0)
            self.player.play()
            self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))

    def play_selected(self, index):
        self.playlist.setCurrentIndex(index.row())
        self.player.play()
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))

    def prev_track(self):
        if self.player.position() >= 4000:
            self.player.setPosition(0)
        else:
            self.playlist.previous()
        self.player.play()
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))

    def toggle_play(self):
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        else:
            self.player.play()
            self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))

    def update_position(self, position):
        self.position_slider.setValue(position)
        self.lbl_elapsed.setText(self.format_time(position))

    def update_duration(self, duration):
        self.position_slider.setRange(0, duration)
        self.lbl_duration.setText(self.format_time(duration))

    def seek_position(self, position):
        self.player.setPosition(position)

    def reset_album_art(self, media):
        self.album_art.setText("Album Art")
        self.album_art.setPixmap(QPixmap())

    @staticmethod
    def format_time(ms):
        seconds = ms // 1000
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MusicPlayer()
    window.show()
    sys.exit(app.exec_())
