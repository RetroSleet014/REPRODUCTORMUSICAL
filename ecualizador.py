import sys
import numpy as np
import traceback # Para el gancho de excepciones
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QSlider, QLabel, QPushButton, QStyle, QLineEdit, QSpacerItem, QSizePolicy, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer # Importar QTimer
from PyQt6.QtGui import QPalette, QColor, QFont # Importar QFont

class EqualizerWindow(QDialog):
    # Señal que se emite cuando los parámetros del ecualizador cambian y se aplican.
    # Emite un diccionario con 'band_idx': {'gain': value, 'q': value, 'freq': value}
    # ESTA SEÑAL SOLO SE EMITIRÁ CUANDO SE PRESIONE "APLICAR"
    eq_params_changed = pyqtSignal(dict)

    def __init__(self, parent=None, initial_settings=None):
        super().__init__(parent)
        self.setWindowTitle("Ecualizador")
        self.setFixedSize(600, 350) # Tamaño fijo para la ventana del ecualizador

        self.set_dark_theme()
        self.apply_styles()

        self.eq_bands = {} # {index: {'slider': QSlider, 'label': QLabel, 'gain': float, 'q': float, 'freq': float}}
        self.min_gain = -12.0 # -12 dB
        self.max_gain = 12.0  # +12 dB
        self.default_q = 1.0 # Factor Q predeterminado
        
        # Frecuencias de banda para un ecualizador de 10 bandas (octavas)
        # Basado en el estándar de ecualizadores gráficos (ISO 266)
        self.band_frequencies = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

        # Definición de presets de ecualizador
        # Los valores están en dB y deben estar dentro del rango [-12, 12]
        self.presets = {
            'Plano': [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            'Pop': [2, 4, 3, 1, 0, 1, 2, 3, 2, 1],
            'Rock': [3, 4, 2, 0, -2, 0, 2, 4, 5, 3],
            'Jazz': [1, 2, 1, 0, 0, 0, 1, 2, 1, 0],
            'Trova': [-2, -3, -1, 0, 1, 2, 3, 2, 1, 0],
            'Clásica': [1, 2, 2, 0, -1, -1, 0, 2, 3, 2],
            'Voz': [-3, -4, -2, 2, 4, 5, 3, 1, -1, -2],
            'Bajo Pesado': [6, 5, 3, 1, 0, -1, -2, -3, -4, -5],
            'Agudos Claros': [-3, -2, -1, 0, 1, 2, 3, 4, 5, 6],
            'Acústica': [2, 3, 1, -1, -2, -1, 0, 2, 3, 2],
            'Dance': [4, 5, 3, 0, -2, 0, 2, 4, 5, 6],
            'Hall': [1, 2, 3, 2, 1, 0, -1, -2, -3, -4],
            'En Vivo': [-1, -2, -3, -1, 0, 1, 2, 3, 4, 5],
        }

        # Almacenar las configuraciones iniciales para poder restaurarlas al cancelar
        self._initial_eq_params = {} 
        
        self.init_ui()
        self.load_settings(initial_settings)

        # Copiar el estado actual de los parámetros (después de cargar initial_settings)
        # Esto asegura que _initial_eq_params contenga los valores correctos al iniciar el diálogo.
        self._initial_eq_params = self.get_current_eq_params()

    def set_dark_theme(self):
        """Aplica un tema oscuro a la ventana y sus widgets."""
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
        """Aplica estilos CSS para una apariencia moderna."""
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                border-radius: 10px;
            }
            QLabel {
                color: #ddd;
                font-size: 13px;
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
                margin: 0 -4px; /* Centrar el handle */
            }
            QSlider::add-page:vertical {
                background: #888; /* Color de la parte "sin rellenar" del slider */
            }
            QSlider::sub-page:vertical {
                background: #50b8f0; /* Color de la parte "rellenada" del slider */
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
            QComboBox {
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 5px;
                padding: 5px;
                color: #ddd;
                font-size: 13px;
                selection-background-color: #50b8f0; /* Color de fondo al seleccionar */
                selection-color: black; /* Color del texto al seleccionar */
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left-width: 1px;
                border-left-color: #444;
                border-left-style: solid; /* just a line */
                border-top-right-radius: 3px; /* same radius as the QComboBox */
                border-bottom-right-radius: 3px;
            }
            QComboBox::down-arrow {
                image: url(data:image/svg+xml;base66,PHN2ZyB2aWV3Qm94PSIwIDAgMTAgNiIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cGF0aCBkPSJNNi43MDcgNC4yOTNMMiA4LjgyOEwwIDYuMTIyTDUuNDQ0NDQgMS42NzdMMiA1LjQ0NDQ0TDYgOS40NDQ0NEwxMCA1LjQ0NDQ0TDUgMFoiLz48L3N2Zz4=); /* Pequeña flecha SVG hacia abajo */
                width: 12px;
                height: 12px;
            }
            QComboBox QAbstractItemView {
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 5px;
                selection-background-color: #50b8f0;
                selection-color: black;
                color: #ddd;
            }
        """)

    def init_ui(self):
        """Configura la interfaz de usuario de la ventana del ecualizador."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # Combo Box para seleccionar presets
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox(self)
        for preset_name in self.presets.keys():
            self.preset_combo.addItem(preset_name)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addStretch(1) # Empuja el combo a la izquierda
        main_layout.addLayout(preset_layout)

        bands_layout = QHBoxLayout()
        bands_layout.setSpacing(10)
        bands_layout.addStretch(1) # Espacio al principio

        for i, freq in enumerate(self.band_frequencies):
            band_widget = QVBoxLayout()
            
            # Etiqueta de ganancia
            gain_label = QLabel(f"{0.0:.1f} dB")
            gain_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            gain_label.setFont(QFont("Arial", 10)) # Fuente para las etiquetas de ganancia
            band_widget.addWidget(gain_label)

            slider = QSlider(Qt.Orientation.Vertical)
            slider.setRange(int(self.min_gain * 10), int(self.max_gain * 10)) # Escala para un decimal
            slider.setValue(0) # Inicia en 0 dB
            slider.setSingleStep(1) # Pasos de 0.1 dB en la UI
            slider.setTickInterval(5) # Cada 0.5 dB
            slider.setTickPosition(QSlider.TickPosition.TicksBelow)
            # Conectar solo la actualización visual, NO la emisión de la señal principal aquí
            slider.valueChanged.connect(lambda value, idx=i: self._update_slider_label(idx, value))
            
            # Etiqueta de frecuencia
            freq_label = QLabel(f"{freq} Hz")
            freq_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            freq_label.setFont(QFont("Arial", 10, QFont.Weight.Bold)) # Fuente en negrita para frecuencias
            
            band_widget.addWidget(slider)
            band_widget.addWidget(freq_label)
            
            bands_layout.addLayout(band_widget)
            
            self.eq_bands[i] = {
                'slider': slider,
                'gain_label': gain_label,
                'gain': 0.0, # Este valor se actualizará en _update_slider_label
                'q': self.default_q,
                'freq': float(freq)
            }
        bands_layout.addStretch(1) # Espacio al final
        main_layout.addLayout(bands_layout)

        # Controles inferiores (botones)
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        
        self.btn_reset = QPushButton("Resetear")
        self.btn_reset.clicked.connect(self.load_default_settings) # Reseteará a "Plano"
        button_layout.addWidget(self.btn_reset)

        self.btn_apply = QPushButton("Aplicar")
        # Conectar el botón Aplicar al método accept() de QDialog, que también emitirá la señal
        self.btn_apply.clicked.connect(self.accept) 
        button_layout.addWidget(self.btn_apply)

        self.btn_cancel = QPushButton("Cancelar")
        # Conectar el botón Cancelar al método reject()
        self.btn_cancel.clicked.connect(self.reject) 
        button_layout.addWidget(self.btn_cancel)
        
        button_layout.addStretch(1)
        main_layout.addLayout(button_layout)

    def _update_slider_label(self, band_idx, value):
        """
        Maneja el cambio de valor de un slider, actualizando solo la etiqueta
        y el valor interno de la banda (NO emite la señal eq_params_changed).
        """
        gain_db = value / 10.0 # Convertir el valor del slider a dB
        self.eq_bands[band_idx]['gain'] = gain_db # Actualizar el valor interno
        self.eq_bands[band_idx]['gain_label'].setText(f"{gain_db:.1f} dB")


    def get_current_eq_params(self):
        """
        Retorna un diccionario con los parámetros actuales del ecualizador.
        """
        params = {}
        for idx, band_data in self.eq_bands.items():
            params[idx] = {
                'gain': band_data['gain'],
                'q': band_data['q'],
                'freq': band_data['freq']
            }
        return params

    def load_settings(self, initial_settings_list):
        """
        Carga las configuraciones iniciales o por defecto en los sliders.
        initial_settings_list: una lista de valores de ganancia (ej. [0, 2, -1, ...])
        """
        # Crear un diccionario de parámetros desde la lista para el método set_eq_params
        initial_params_dict = {}
        if initial_settings_list and len(initial_settings_list) == len(self.band_frequencies):
            for band_idx, gain_db in enumerate(initial_settings_list):
                initial_params_dict[band_idx] = {
                    'gain': float(gain_db),
                    'q': self.default_q,
                    'freq': float(self.band_frequencies[band_idx])
                }
            self.set_eq_params(initial_params_dict)
            # Intentar seleccionar el preset si coincide con la configuración
            self._select_matching_preset(initial_settings_list)
        else:
            self.load_default_settings() # Si no se proporcionan, cargar por defecto

    def _select_matching_preset(self, current_gains):
        """
        Intenta seleccionar el preset en el QComboBox que coincide con la configuración actual de los sliders.
        """
        for preset_name, preset_gains in self.presets.items():
            # Comparar las ganancias actuales con las del preset
            # Usar un pequeño epsilon para la comparación de flotantes si es necesario,
            # pero aquí los sliders usan valores discretos, así que una comparación directa es OK.
            if len(current_gains) == len(preset_gains) and all(g1 == g2 for g1, g2 in zip(current_gains, preset_gains)):
                idx = self.preset_combo.findText(preset_name)
                if idx != -1:
                    # Desconectar temporalmente para evitar el bucle de señal
                    self.preset_combo.currentIndexChanged.disconnect(self._on_preset_selected)
                    self.preset_combo.setCurrentIndex(idx)
                    self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
                    return
        
        # Si no se encuentra una coincidencia, seleccionar "Personalizado" o dejar en blanco
        # o añadir "Personalizado" si no existe
        custom_idx = self.preset_combo.findText("Personalizado")
        if custom_idx == -1:
            self.preset_combo.addItem("Personalizado")
            custom_idx = self.preset_combo.findText("Personalizado") # Obtener el índice recién añadido
        
        # Seleccionar "Personalizado" si no se encontró un preset coincidente
        self.preset_combo.currentIndexChanged.disconnect(self._on_preset_selected)
        self.preset_combo.setCurrentIndex(custom_idx)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)


    def load_default_settings(self):
        """
        Carga las configuraciones predeterminadas (Plano) para los sliders.
        Se llama al inicio o cuando se necesita resetear a un estado conocido.
        """
        default_params = {}
        for i, freq in enumerate(self.band_frequencies):
            default_params[i] = {'gain': 0.0, 'q': self.default_q, 'freq': float(freq)}
        self.set_eq_params(default_params)
        
        # Actualizar el QComboBox para que muestre "Plano"
        idx = self.preset_combo.findText('Plano')
        if idx != -1:
            self.preset_combo.currentIndexChanged.disconnect(self._on_preset_selected)
            self.preset_combo.setCurrentIndex(idx)
            self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)


    def set_eq_params(self, params_dict):
        """
        Establece los parámetros del ecualizador desde un diccionario.
        Útil para cargar presets o el estado inicial.
        """
        for idx, data in params_dict.items():
            if idx in self.eq_bands:
                slider = self.eq_bands[idx]['slider']
                gain_db = data.get('gain', 0.0)
                q_factor = data.get('q', self.default_q)
                freq = data.get('freq', self.band_frequencies[idx])

                slider_value = int(gain_db * 10)
                
                # Desconectar temporalmente para evitar que _update_slider_label se llame
                try:
                    slider.valueChanged.disconnect() 
                except TypeError: # Si ya no está conectado, ignorar
                    pass

                slider.setValue(slider_value)
                
                # Reconectar el slot
                slider.valueChanged.connect(lambda value, idx=idx: self._update_slider_label(idx, value))
                
                # Actualizar también los valores internos directamente
                self.eq_bands[idx]['gain'] = gain_db
                self.eq_bands[idx]['q'] = q_factor
                self.eq_bands[idx]['freq'] = freq
                self.eq_bands[idx]['gain_label'].setText(f"{gain_db:.1f} dB")
    
    def _on_preset_selected(self, index):
        """
        Maneja la selección de un preset en el QComboBox.
        """
        preset_name = self.preset_combo.currentText()
        if preset_name in self.presets:
            preset_gains = self.presets[preset_name]
            params_dict = {}
            for i, gain_db in enumerate(preset_gains):
                params_dict[i] = {
                    'gain': float(gain_db),
                    'q': self.default_q,
                    'freq': float(self.band_frequencies[i])
                }
            self.set_eq_params(params_dict)
        elif preset_name == "Personalizado":
            # Si se selecciona "Personalizado", no se hace nada, los sliders mantienen su estado.
            pass


    def accept(self):
        """
        Sobrescribe el método accept para emitir la señal con los parámetros finales
        antes de cerrar la ventana. Esto solo ocurre al presionar "Aplicar".
        """
        self.eq_params_changed.emit(self.get_current_eq_params())
        super().accept() # Llama al método accept() de la clase base


    def reject(self):
        """
        Sobrescribe el método reject para restaurar las configuraciones iniciales
        cuando la ventana se cierra con 'Cancelar' o la 'X'.
        """
        # Restaurar los valores iniciales de los sliders y sus etiquetas
        self.set_eq_params(self._initial_eq_params)
        
        # Intentar seleccionar el preset que coincida con _initial_eq_params
        initial_gains_list = [v['gain'] for k, v in self._initial_eq_params.items()]
        self._select_matching_preset(initial_gains_list)
        
        super().reject() # Llama al método reject() de la clase base


if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # Configurar hook de excepciones para depuración
    sys._excepthook = sys.excepthook
    def exception_hook(exctype, value, tb):
        print("CRITICAL ERROR: Excepción no manejada en EqualizerWindow:")
        traceback.print_exception(exctype, value, tb)
        sys._excepthook(exctype, value, tb) # Llama al hook original
    sys.excepthook = exception_hook

    # Ejemplo de uso:
    # Configuración de ejemplo para inicializar el ecualizador (10 bandas, todas a 0)
    initial_eq_settings = [0] * 10
    initial_eq_settings[2] = 5  # Ejemplo: aumenta 125 Hz en 5 dB
    initial_eq_settings[7] = -3 # Ejemplo: corta 4 kHz en 3 dB
    
    print("--- Ecualizador de prueba ---")
    dialog = EqualizerWindow(initial_settings=initial_eq_settings)
    
    # Esta función se llamará SOLO si la ventana se cierra con 'Aplicar'
    def on_settings_applied(settings):
        print("Configuraciones APLICADAS (se presionó 'Aplicar'):")
        for idx, data in settings.items():
            print(f"Banda {idx} (Freq: {data['freq']} Hz): Ganancia = {data['gain']:.1f} dB, Q = {data['q']:.1f}")

    dialog.eq_params_changed.connect(on_settings_applied) # Conectar la señal de aplicación

    # Muestra el diálogo y espera a que el usuario lo cierre
    result = dialog.exec() 

    if result == QDialog.DialogCode.Accepted:
        print("\nVentana de ecualizador cerrada con 'Aplicar'. Los cambios se han emitido.")
        # La función on_settings_applied ya se encargó de imprimir los ajustes.
    else: # QDialog.DialogCode.Rejected
        print("\nVentana de ecualizador cerrada con 'Cancelar' o 'X'. ¡Se descartaron los cambios!")
        # Para mostrar los parámetros reales que _initial_eq_params tenía (restaurados)
        print("Los ajustes restaurados visualmente en el diálogo son:")
        restored_params = dialog.get_current_eq_params()
        for idx, data in restored_params.items():
            print(f"Banda {idx} (Freq: {data['freq']} Hz): Ganancia = {data['gain']:.1f} dB")


    sys.exit(app.exec())
