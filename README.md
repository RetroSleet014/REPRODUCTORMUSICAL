# REPRODUCTORMUSICAL
PROYECTO FINAL

Reproductor Musical Moderno (PyQt6)

Características Destacadas
Reproducción de Audio de Alta Calidad: Soporte para formatos comunes como MP3, WAV, OGG y FLAC, con procesamiento DSP (Digital Signal Processing) avanzado.

Ecualizador Gráfico de 10 Bandas: Ajusta tu sonido con precisión, con presets predefinidos y la opción de guardar tus propias configuraciones.

Visualizador de Espectro: Observa tus canciones cobrar vida con un visualizador de audio en tiempo real.

Gestión de Playlist Completa: Añade archivos o carpetas, guarda y carga tus playlists (.m3u), reordena pistas, y elimina canciones individualmente o borra toda la lista.

Control de Reproducción Avanzado: Funciones de reproducción, pausa, siguiente/anterior pista, modo aleatorio (shuffle) y repetición (canción actual o toda la playlist).

Búsqueda Rápida: Encuentra tus canciones favoritas en la playlist por título, artista o álbum.

Detección Automática de Dispositivo de Audio: La aplicación detecta automáticamente el dispositivo de salida de audio predeterminado de tu sistema y se adapta a los cambios en tiempo real.

Metadatos y Carátulas: Muestra información detallada de la canción (título, artista, álbum, número de pista) y la carátula del álbum si está disponible.

Arrastrar y Soltar (Drag & Drop): Añade canciones fácilmente arrastrando y soltando archivos o carpetas directamente en la ventana de la aplicación.

Controles por Teclado: Atajos de teclado para las funciones principales de reproducción y volumen.

Tema Oscuro Elegante: Una interfaz moderna y agradable a la vista, optimizada para una experiencia de usuario cómoda.

Manejo de Errores Robustos: Notificaciones claras al usuario en caso de errores inesperados.

Instalación
Para ejecutar este reproductor de música, necesitas tener Python instalado en tu sistema. Luego, instala las librerías necesarias usando pip:

pip install PyQt6 soundfile sounddevice scipy numpy mutagen

Nota Importante: PyQt6, soundfile, sounddevice, scipy, numpy y mutagen son esenciales para el funcionamiento del reproductor. Asegúrate de que se instalen correctamente.

Cómo Ejecutar
Una vez que hayas instalado todas las dependencias, puedes ejecutar la aplicación principal:

python main.py

Desarrollo
Este reproductor ha sido desarrollado utilizando:

Python: El lenguaje de programación principal.

PyQt6: Para la creación de la interfaz gráfica de usuario.

soundfile / sounddevice: Para la lectura, procesamiento y reproducción de audio de bajo nivel.

SciPy / NumPy: Para operaciones de procesamiento de señales digitales (DSP), incluyendo el ecualizador y el visualizador.

mutagen: Para la lectura de metadatos de archivos de audio (ID3 Tags, FLAC, Ogg Vorbis).

¡Esperamos que disfrutes de tu experiencia musical con este reproductor!
