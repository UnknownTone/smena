SMENA для macOS (Apple Silicon)

1. Перетащите SMENA.app в «Программы».

2. Первый запуск. Приложение не подписано сертификатом Apple, поэтому macOS один раз его блокирует:
   • macOS 15 и новее: откройте SMENA, в предупреждении нажмите «Готово», затем «Системные настройки →
     Конфиденциальность и безопасность» → внизу «Всё равно открыть» рядом со SMENA → подтвердите паролем;
   • macOS 13–14: правый клик (или Ctrl+клик) по SMENA в «Программах» → «Открыть» → «Открыть»;
   • любая версия, а также если пишет «приложение повреждено» — в Терминале:
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
2. First launch (the app is not signed with an Apple certificate), once:
   • macOS 15 and later: open SMENA, click Done, then System Settings → Privacy & Security → Open Anyway;
   • macOS 13–14: right-click SMENA → Open → Open;
   • any version, or if macOS says the app is damaged — in Terminal:
       xattr -dr com.apple.quarantine /Applications/SMENA.app
3. System audio: install BlackHole 2ch and route output through a Multi-Output Device (speakers + BlackHole);
   SMENA picks BlackHole automatically. Otherwise choose an audio input at the top of the window.
4. Allow microphone access when asked — that is how SMENA hears the music.
