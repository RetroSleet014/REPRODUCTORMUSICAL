import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit,
    QPushButton, QMessageBox, QVBoxLayout
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

usuarios = {
    "usuario1": "contrasena123",
    "admin": "adminpass",
    "juan": "clave456"
}

class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Inicio de Sesión")
        self.setStyleSheet("background-color: #2c3e50;")
        self.init_ui()

    def init_ui(self):
        font_label = QFont("Arial", 12)
        font_input = QFont("Arial", 11)

        layout = QVBoxLayout()
        layout.setContentsMargins(100, 60, 100, 60)
        layout.setSpacing(25)

        # Título
        title = QLabel("🔐Inicio de Sesión")
        title.setFont(QFont("Arial", 20, QFont.Bold))
        title.setStyleSheet("color: white;")
        title.setAlignment(Qt.AlignCenter)

        self.input_usuario = QLineEdit()
        self.input_usuario.setPlaceholderText("Nombre de usuario")
        self.input_usuario.setFont(font_input)
        self.input_usuario.setStyleSheet(self.estilo_input())

        self.input_contrasena = QLineEdit()
        self.input_contrasena.setPlaceholderText("Contraseña")
        self.input_contrasena.setFont(font_input)
        self.input_contrasena.setEchoMode(QLineEdit.Password)
        self.input_contrasena.setStyleSheet(self.estilo_input())

        boton_login = QPushButton("Iniciar sesión")
        boton_login.setFont(QFont("Arial", 12, QFont.Bold))
        boton_login.setCursor(Qt.PointingHandCursor)
        boton_login.clicked.connect(self.verificar_login)
        boton_login.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                padding: 12px;
                border-radius: 10px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)

        layout.addWidget(title)
        layout.addWidget(self.input_usuario)
        layout.addWidget(self.input_contrasena)
        layout.addWidget(boton_login)

        self.setLayout(layout)

    def estilo_input(self):
        return """
            QLineEdit {
                background-color: #ecf0f1;
                border: none;
                border-radius: 8px;
                padding: 12px;
            }
        """

    def verificar_login(self):
        usuario = self.input_usuario.text()
        contrasena = self.input_contrasena.text()

        if usuario in usuarios and usuarios[usuario] == contrasena:
            QMessageBox.information(self, "Éxito", f"¡Bienvenido, {usuario}!")
        else:
            QMessageBox.critical(self, "Error", "Usuario o contraseña incorrectos.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ventana = LoginWindow()
    ventana.show()
    sys.exit(app.exec_())
