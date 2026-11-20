# SMENA — сборка установщика и окружение запуска

## 1. Где будет работать (ноутбук автора)
| | |
|---|---|
| ОС | Windows 11 Pro (сборка 26200), x64 |
| Видеокарты | **NVIDIA GeForce RTX 3050 Laptop, 4 ГБ** (драйвер 566.07) + встроенная AMD Radeon |
| Память | 16 ГБ |
| Python | 3.14 (основной) и 3.12 (программа `.venv-smena` и подготовка фото `.venv-prep`) — **установщику не нужен**, программа несёт свой |
| Подготовка фото | `<папка проекта>\.venv-prep` (PyTorch cu126, SAM 2, LaMa) + `vj\models` |
| Папка фото | альбом: `<папка фото>` (56 фото в корне), позже `...\VK-photo\SMENA`; London: `...\London` |
| Готовый кеш элементов | альбом: `...\vj\cache\sel56v2` (кандидаты — `vj\cache\sel54`); London: `...\London\_smena_cache` |
| Пути | содержат **кириллицу и пробелы** — всё тестировать на таких путях |

## 2. Сборка (на ноутбуке автора — решение 2026-10-16)
- Python **3.12** x64 — окружение `.venv-smena` (`requirements-smena.txt`: PySide6-Essentials, numpy, soundcard,
  moderngl, imageio-ffmpeg) + PyInstaller.
- **PyInstaller 6** в режиме **onedir** (быстрый старт, меньше ложных срабатываний антивируса) → папка `dist\SMENA\`.
- **Inno Setup 6** (поставить по команде автора) → `SMENA_Setup.exe` из `dist\SMENA\`.
- В сборку включить: тему `smena/ui/theme/smena_pipboy/` (QSS, palette.json, текстура, шрифты PT Mono, VT323,
  PT Sans Narrow — OFL, с лицензиями), иконку, ffmpeg из `imageio-ffmpeg` (режим «файл»), `data/sample_cache` —
  **как демо-набор**. Шейдеры — внутри `smena/render/gl.py`.
- **Не включать**: PyTorch, SAM 2, LaMa, модели, `tools/prep` (подготовка, SAM-сервер редактора и сборка фото —
  внешние процессы из `.venv-prep`, пути — в настройках; `01_BUILD_BRIEF.md` §6).
- Учесть при сборке: `settings.ROOT` берёт `sys._MEIPASS`; `editor/data.py` пишет разметку в `ROOT\data\labels` —
  в установленной программе перенести в `%APPDATA%\SMENA\labels`; `editor/data.py` импортирует `torn.py` из
  `ROOT\tools\prep` — положить `torn.py` (numpy, без PyTorch) в сборку.
- Ожидаемый размер установщика: ~150–250 МБ (Qt + numpy + moderngl + ffmpeg).

## 3. Установка
- **Для текущего пользователя, без прав администратора**: `%LOCALAPPDATA%\Programs\SMENA\`.
- Ярлыки: меню Пуск + рабочий стол (по галочке).
- Настройки: `%APPDATA%\SMENA\settings.json`; пресеты: `%APPDATA%\SMENA\presets\*.json`; лог: `%APPDATA%\SMENA\logs\`.
- Деинсталлятор — стандартный Inno Setup (настройки и пресеты не удалять без вопроса).
- Без цифровой подписи Windows SmartScreen покажет предупреждение — это нормально для тестовой версии, сказать автору.

## 4. Видеокарта — обязательно
На этом ноутбуке Windows по умолчанию отдаёт OpenGL **встроенной AMD** (проверено: прототип рисовал на AMD).
Установщик должен прописать предпочтение NVIDIA для `SMENA.exe` (та же запись, что пишет окно «Параметры → Графика»):
```
HKCU\Software\Microsoft\DirectX\UserGpuPreferences
  "<путь установки>\SMENA.exe" = "GpuPreference=2;"     (REG_SZ)
```
Программа при старте показывает `GL_RENDERER`; если это не NVIDIA — предупреждение с инструкцией.

## 5. Настройки по умолчанию (`settings.json`, как в `smena/settings.py`)
```json
{
  "photos_dir": "<папка фото>",
  "cache_dir": "<папка проекта>\\cache\\sel56v2",
  "prep_python": "<папка проекта>\\.venv-prep\\Scripts\\python.exe",
  "prep_scripts": "<папка проекта>\\tools\\prep",
  "audio_device": null,
  "output_monitor": 1,
  "output_fullscreen": true,
  "render_size": [1920, 1080],
  "hud": false,
  "theme": "smena_pipboy",
  "theme_effects": true,
  "last_preset": null,
  "sync_ms": 0.0,
  "test_file": null,
  "window_geometry": null
}
```
Плюс по ходу работы: `prep_use_model` (галочка редактора — отбор моделью при «Подготовить фото»).
Если папок нет (например, на машине сборки) — предложить демо-набор `sample_cache`.

## 6. Как проверить на машине сборки (без данных автора)
1. Тестовый режим «файл»: любой mp3/flac → анализ и рендер на `sample_cache`.
2. Сравнить с `data/reference_render.mp4` (поведение цикла: past+master → моно master → въезд future → смена фона).
3. Проверить пути с кириллицей: положить `sample_cache` в папку с русским именем.
