# Установка

Проект состоит из двух частей с разными зависимостями:

| Часть | Где работает | Зависимости |
|---|---|---|
| **Программа SMENA** (`smena/`) — звук, визуал, фейдербанк, редактор элементов | ноутбук для выступлений | лёгкие: окружение `.venv-smena` на Python 3.12, `requirements-smena.txt` |
| **Подготовка фото** (SAM 2 → отбор → LaMa) — кнопка «Подготовить фото», SAM-сервер редактора, офлайн-рендер | ноутбук с видеокартой NVIDIA | тяжёлые: отдельное окружение `.venv-prep` на Python 3.12 |

Позже (этап M5) программа будет ставиться установщиком `SMENA_Setup.exe` — без Python на машине.

## 1. Программа SMENA

```bash
py -3.12 -m venv .venv-smena
.venv-smena\Scripts\python.exe -m pip install -r requirements-smena.txt
```

Ставится только `PySide6-Essentials` (без Addons/WebEngine). Запуск — двойной клик по `SMENA.bat`
(или `.venv-smena\Scripts\python.exe -m smena`). Настройки, пресеты и журнал — `%APPDATA%\SMENA\`.

### Видеокарта для визуала — обязательно
Визуал рисует через OpenGL, и на ноутбуке с двумя видеокартами Windows по умолчанию отдаёт его **встроенной**
(проверено: без настройки визуал шёл на AMD Radeon). Python из venv — лишь запускалка базового Python 3.12,
поэтому NVIDIA назначается **обоим** (та же запись, что пишет окно «Параметры → Система → Дисплей → Графика»,
только текущий пользователь; на этой машине уже прописано):

```bash
reg add "HKCU\Software\Microsoft\DirectX\UserGpuPreferences" /v "<папка проекта>\.venv-smena\Scripts\python.exe" /t REG_SZ /d "GpuPreference=2;" /f
```

```bash
reg add "HKCU\Software\Microsoft\DirectX\UserGpuPreferences" /v "%LOCALAPPDATA%\Python\pythoncore-3.12-64\python.exe" /t REG_SZ /d "GpuPreference=2;" /f
```

То же — для `pythonw.exe` в обеих папках (SMENA.bat запускает pythonw). Проверка: вкладка **ВЫВОД** → строка
`GL_RENDERER` должна содержать NVIDIA (иначе там же жёлтое предупреждение).

Подготовке фото (PyTorch/CUDA) эта настройка не нужна: CUDA работает только на NVIDIA.

Также: **питание от сети** во время выступления; звук — loopback устройства вывода по умолчанию или выбранное
устройство (вкладка ЗВУК); Traktor/Reaper на ASIO — см. `docs/build/03_AUDIO_CAPTURE.md`.

### Старый прототип `app/` (не развивается)
`python -m pip install -r requirements.txt`, запуск `Photo VJ.bat` (основной Python 3.14, pygame + customtkinter).

## 2. Подготовка фото: окружение, LaMa, SAM 2

Всё работает **локально**; интернет нужен только для скачивания пакетов и моделей. Фото никуда не отправляются.
Установлено и проверено 2026-10-10 на RTX 3050 Laptop 4 ГБ, драйвер 566.07, Windows 11.

| Что | Куда | Размер |
|---|---|---|
| Python 3.12.10 | `%LOCALAPPDATA%\Python\` (рядом с 3.14) | ~100 МБ |
| Окружение | `vj\.venv-prep\` | ~5 ГБ (PyTorch с CUDA) |
| Модель LaMa | `vj\models\torch\hub\checkpoints\big-lama.pt` | 196 МБ |
| Модель SAM 2.1 base+ | `vj\models\sam2\sam2.1_hiera_base_plus.pt` | 324 МБ |

`.venv-prep\` и `models\` в архив проекта не включаются — на другой машине ставятся заново по шагам ниже.

### 2.1 Python 3.12 и окружение

Под Python 3.14 готовых сборок PyTorch с CUDA может не быть, поэтому подготовка фото — на 3.12.

```bash
py install 3.12
py -V:3.12 -m venv .venv-prep
.venv-prep\Scripts\python.exe -m pip install --upgrade pip
```

### 2.2 PyTorch с CUDA

```bash
.venv-prep\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
.venv-prep\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Установилось: torch 2.14.1+cu126, видеокарта видна. Для другого драйвера сверить вариант CUDA на https://pytorch.org/get-started/locally/.

### 2.3 LaMa

```bash
.venv-prep\Scripts\python.exe -m pip install simple-lama-inpainting
```

- Пакет понижает numpy до 1.26 и Pillow до 9.5 — в отдельном окружении это не мешает.
- Модель скачивается при первом запуске в `%TORCH_HOME%\hub\checkpoints\` — задавать `TORCH_HOME=vj\models\torch`.
- **Пути с кириллицей**: `torch.jit.load` (C++) не открывает файл, если в пути есть кириллица
  (так было со старым именем папки «Смена - Человечество», теперь `SMENA`). Загрузка через байты работает при любом пути:
  ```python
  import io, torch
  from simple_lama_inpainting import SimpleLama
  lama = SimpleLama.__new__(SimpleLama)
  dev = torch.device("cuda")
  with open(model_path, "rb") as f:
      lama.model = torch.jit.load(io.BytesIO(f.read()), map_location=dev)
  lama.model.eval(); lama.model.to(dev); lama.device = dev
  result = lama(pil_image, pil_mask)   # маска: белое — что дорисовать
  ```
- Замер: ~3 с на фото 1280×848, пик видеопамяти 1.1 ГБ.
- Особенность: LaMa продолжает структуру фона — на месте двери на фасаде дорисовала окно из соседнего ряда.

Опционально — IOPaint (веб-интерфейс LaMa для ручных правок кистью), не установлен:

```bash
.venv-prep\Scripts\python.exe -m pip install iopaint
.venv-prep\Scripts\iopaint.exe start --model=lama --device=cuda --port=8080
```

### 2.4 SAM 2

```bash
set SAM2_BUILD_CUDA=0
.venv-prep\Scripts\python.exe -m pip install "git+https://github.com/facebookresearch/sam2.git"
```

- Нужен git. `SAM2_BUILD_CUDA=0` — не собирать необязательное CUDA-расширение (не нужен компилятор).
  Без него SAM 2 печатает предупреждение о пропуске постобработки масок — на результат почти не влияет.
- Модель (скачать в `vj\models\sam2\`):
  https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_base_plus.pt
- Загрузка: `build_sam2("configs/sam2.1/sam2.1_hiera_b+.yaml", ckpt_path, device="cuda")` +
  `SAM2AutomaticMaskGenerator` (проверено: `points_per_side=32, pred_iou_thresh=0.8, stability_score_thresh=0.92`,
  вычисления в `torch.autocast("cuda", dtype=torch.bfloat16)`). Путь с кириллицей здесь работает.
- Замер: ~5 с на фото 1280×848, 56 масок, пик видеопамяти 1.4 ГБ.
- Изображения читать через PIL/numpy (OpenCV `imread` не открывает пути с кириллицей на Windows).

### 2.5 Кто использует `.venv-prep` (2026-10-17)
- **«Подготовить фото»** (вкладка ФОТО программы): `tools/prep/candidates.py` (SAM 2, до 48 кандидатов,
  ~13 с/фото) → `auto_select.py` (правила v2, крупные куски с рваным краем, или `--model`) → `build_elements.py`
  (только LaMa, ~3 с/фото). Пути к python и скриптам — на вкладке ФОТО.
- **Редактор элементов**: `tools/prep/sam_server.py` — SAM 2 фоновым процессом (загрузка ~10 с, маска по клику
  0.04–0.3 с); «Собрать фото» — `build_elements.py`. SAM-сервер и сборка вместе укладываются в 4 ГБ VRAM.
- **Офлайн-рендер видео**: `tools/render/render_demo.py ТРЕК КЕШ ВЫХОД.mp4 [--dur …] [--photos …] [--flicker-in 0.15] [--news 12]`.

## 3. Анализ музыки (опционально)

См. `docs/ANALYSIS.md` → «Как воспроизвести». Нужны только numpy и pygame-ce (уже в `requirements.txt`).
Порядок фото под треки — `tools/analysis/photo_order.py` и `order_gradient.py` (окружение `.venv-prep`).
