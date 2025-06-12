# ecualizador.py
import sys
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QSlider, QLabel, QPushButton, QSpacerItem, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal # Importa pyqtSignal para señales personalizadas
from PyQt6.QtGui import QPalette, QColor # Necesario para el tema oscuro

class EqualizerWindow(QDialog):
    # Define una señal para emitir las configuraciones del ecualizador cuando se apliquen.
    # Esta señal llevará una lista de valores enteros de ganancia (ej. [0, 2, -1, ...]).
    settings_applied = pyqtSignal(list)

    def __init__(self, parent=None, initial_settings=None):
        """
        Inicializa la ventana del ecualizador.
        
        Args:
            parent (QWidget, opcional): El widget padre de esta ventana.
            initial_settings (list, opcional): Una lista de valores de ganancia iniciales para los sliders.
                                                Debe tener 10 elementos, uno por cada banda de frecuencia.
        """
        super().__init__(parent)
        self.setWindowTitle("Equalizer Settings")
        self.setGeometry(400, 200, 500, 450) # Tamaño y posición de la ventana
        self.set_dark_theme() # Aplica el tema oscuro
        self.apply_styles()   # Aplica estilos CSS

        # Definición de las bandas de frecuencia
        self.frequency_bands = [
            "31 Hz", "62 Hz", "125 Hz", "250 Hz", "500 Hz",
            "1 kHz", "2 kHz", "4 kHz", "8 kHz", "16 kHz"
        ]
        self.sliders = [] # Lista para almacenar los widgets QSlider
        self.value_labels = [] # Lista para almacenar las etiquetas QLabel que muestran el valor del slider

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20) # Márgenes internos
        main_layout.setSpacing(10) # Espacio entre elementos

        # Crea los sliders para cada banda de frecuencia
        for i, band_name in enumerate(self.frequency_bands):
            band_layout = QHBoxLayout() # Layout horizontal para cada banda (etiqueta + slider + valor)
            
            # Etiqueta de Frecuencia
            freq_label = QLabel(band_name)
            freq_label.setStyleSheet("color: #ddd; font-size: 14px; min-width: 60px;")
            freq_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            band_layout.addWidget(freq_label)

            # Slider
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-12, 12) # Rango de ganancia de +/- 12 dB
            slider.setValue(0) # Valor predeterminado a 0 dB de ganancia
            slider.setSingleStep(1) # Incremento/decremento de 1 dB
            slider.setPageStep(3) # Salto de 3 dB al hacer clic en la barra
            slider.setTickPosition(QSlider.TickPosition.TicksBelow) # Marcas de ticks debajo
            slider.setTickInterval(3) # Intervalo de los ticks (cada 3 dB)
            self.sliders.append(slider)
            band_layout.addWidget(slider)

            # Etiqueta de Valor (muestra el valor actual del slider)
            value_label = QLabel(f"{slider.value():+d} dB") # Formato "+X dB" o "-X dB"
            value_label.setStyleSheet("color: #50b8f0; font-size: 14px; min-width: 50px;")
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.value_labels.append(value_label)
            band_layout.addWidget(value_label)

            # Conecta el cambio de valor del slider a la actualización de su etiqueta de valor
            # Usamos un lambda para pasar la etiqueta correcta a cada conexión.
            slider.valueChanged.connect(lambda value, l=value_label: l.setText(f"{value:+d} dB"))

            main_layout.addLayout(band_layout)

        # Layout para los botones (Reset y Apply)
        button_layout = QHBoxLayout()
        button_layout.addItem(QSpacerItem(20, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)) # Espaciador para alinear a la derecha

        self.btn_reset = QPushButton("Reset")
        self.btn_reset.clicked.connect(self.reset_settings)
        button_layout.addWidget(self.btn_reset)

        self.btn_apply = QPushButton("Apply")
        self.btn_apply.clicked.connect(self.apply_settings)
        button_layout.addWidget(self.btn_apply)

        main_layout.addLayout(button_layout)
        self.setLayout(main_layout) # Establece el layout principal de la ventana

        # Establece las configuraciones iniciales si se proporcionan y son válidas
        if initial_settings and len(initial_settings) == len(self.sliders):
            for i, gain in enumerate(initial_settings):
                self.sliders[i].setValue(gain)
        else:
            self.reset_settings() # Si no se proporcionan o son inválidas, restablece a 0 dB

    def get_equalizer_settings(self):
        """
        Retorna una lista con los valores de ganancia actuales de cada banda del ecualizador.
        """
        return [slider.value() for slider in self.sliders]

    def reset_settings(self):
        """
        Restablece todos los sliders del ecualizador a 0 dB de ganancia.
        """
        for slider in self.sliders:
            slider.setValue(0)
        print("Equalizer settings reset to 0 dB.")

    def apply_settings(self):
        """
        Emite la señal `settings_applied` con la configuración actual del ecualizador
        y cierra el diálogo.
        """
        current_settings = self.get_equalizer_settings()
        self.settings_applied.emit(current_settings) # Emite la señal
        print(f"Equalizer settings applied: {current_settings}")
        self.accept() # Cierra el diálogo con un resultado "aceptado"

    def set_dark_theme(self):
        """
        Configura la paleta de colores para un tema oscuro.
        """
        pal = self.palette()
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
        """
        Aplica estilos CSS personalizados a los widgets de la ventana.
        """
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                border-radius: 10px;
            }
            QLabel {
                color: #ddd;
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
            QPushButton {
                background: #333;
                border: none;
                border-radius: 8px;
                padding: 8px 12px;
                color: white;
                font-size: 13px;
                min-width: 60px;
            }
            QPushButton:hover {
                background: #444;
            }
            QPushButton:pressed {
                background: #222;
            }
        """)

if __name__ == '__main__':
    # Este bloque solo se ejecuta si corres ecualizador.py directamente.
    # Sirve para probar la ventana del ecualizador de forma independiente.
    app = QApplication(sys.argv)
    
    # Ejemplo de uso:
    # Configuración de ejemplo para inicializar el ecualizador (10 bandas, todas a 0)
    eq_settings = [0] * 10
    eq_settings[2] = 5  # Ejemplo: aumenta 125 Hz en 5 dB
    eq_settings[7] = -3 # Ejemplo: corta 4 kHz en 3 dB
    
    dialog = EqualizerWindow(initial_settings=eq_settings)
    
    # Conecta una función para imprimir las configuraciones cuando se apliquen
    def on_settings_applied(settings):
        print("Configuraciones aplicadas recibidas en el ejemplo principal:", settings)

    dialog.settings_applied.connect(on_settings_applied)
    
    dialog.exec() # Usa exec() para mostrar un diálogo modal (bloquea la ejecución hasta que se cierra)
    sys.exit(app.exec())