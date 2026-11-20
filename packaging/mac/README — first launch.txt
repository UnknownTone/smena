SMENA для macOS (Apple Silicon)

1. Перетащите SMENA.app в «Программы».

2. Первый запуск. Приложение не подписано сертификатом Apple, поэтому macOS его блокирует:
   • правый клик (или Ctrl+клик) по SMENA в «Программах» → «Открыть» → «Открыть»;
   • если пишет «приложение повреждено» — в Терминале:
       xattr -dr com.apple.quarantine /Applications/SMENA.app
   Дальше SMENA открывается как обычно.

3. Звук системы. macOS не отдаёт звук других программ напрямую. Поставьте бесплатный BlackHole 2ch
   (https://existential.audio/blackhole/), затем в «Настройке Audio-MIDI» создайте «Устройство с несколькими
   выходами» (колонки + BlackHole) и выберите его для вывода звука. SMENA сама найдёт BlackHole.
   Можно и без него — вход звуковой карты или микрофон (выбор вверху окна SMENA).

4. При первом запуске macOS спросит доступ к микрофону — разрешите (так SMENA слышит музыку).

Подготовка своих фото (SAM 2 + LaMa) работает на Apple Silicon через Metal — медленнее, чем на NVIDIA, но без интернета.


SMENA for macOS (Apple Silicon)

1. Drag SMENA.app to Applications.
2. First launch (the app is not signed with an Apple certificate): right-click SMENA → Open → Open.
   If macOS says the app is damaged, run in Terminal:  xattr -dr com.apple.quarantine /Applications/SMENA.app
3. System audio: install BlackHole 2ch and route output through a Multi-Output Device (speakers + BlackHole);
   SMENA picks BlackHole automatically. Otherwise choose an audio input at the top of the window.
4. Allow microphone access when asked — that is how SMENA hears the music.
