# Credits / Авторы и лицензии чужих материалов

## Demo photos / Демо-фото (`data/demo_photos/`, `data/sample_cache/`)

All three photos are dedicated to the public domain under
[CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/). Attribution is not required, but given with thanks.
Все три снимка — CC0 1.0 (общественное достояние); авторство указано из благодарности.

| File | Original | Author | License |
|---|---|---|---|
| `01 - панельки Дигоми.jpg` | [A Soviet-era high-rise block of flats in Dighomi neighborhood. Tbilisi, Georgia. 2023](https://commons.wikimedia.org/wiki/File:A_Soviet-era_high-rise_block_of_flats_in_Dighomi_neighborhood._Tbilisi,_Georgia._2023.jpg) | Kober, Wikimedia Commons | CC0 1.0 |
| `02 - сталинка Бараташвили.jpg` | [Stalinist architecture building, Baratashivili street, Tbilisi, Georgia](https://commons.wikimedia.org/wiki/File:Stalinist_architecture_building,_Baratashivili_street,_Tbilisi,_Georgia.JPG) | Brejnev, Wikimedia Commons | CC0 1.0 |
| `03 - Банк Грузии.jpg` | [Architecture of Tbilisi, Part II](https://commons.wikimedia.org/wiki/File:Architecture_of_Tbilisi,_Part_II_-_TbilisiArchitecture8017.jpg) (Bank of Georgia HQ, former Ministry of Highways) | lumoplank (Flickr), via Wikimedia Commons | CC0 1.0 |

Changes: photo 01 rotated by its EXIF orientation; `data/sample_cache` is derived from these photos by SMENA's
preparation pipeline (SAM 2 segments, LaMa background), one element with a car licence plate removed.
Изменения: 01 повёрнут по EXIF; `sample_cache` получен из снимков подготовкой SMENA, элемент с номером машины удалён.

`data/demo_drawn/` — procedurally generated images (`tools/build/make_demo_photos.py`), part of this project.

## Neural networks / Нейросети (downloaded separately, not stored in the repository)

| Model | Authors | License |
|---|---|---|
| [SAM 2.1](https://github.com/facebookresearch/sam2) (hiera base+) | Meta AI | Apache 2.0 |
| [LaMa](https://github.com/advimman/lama) (big-lama, via `simple-lama-inpainting`) | Samsung AI Center, Suvorov et al. | Apache 2.0 |

## Fonts / Шрифты (SIL Open Font License 1.1)

| Font | Authors |
|---|---|
| PT Mono, PT Sans Narrow | ParaType |
| VT323 | Peter Hull |
| Poiret One | Denis Masharov |
| UnifrakturMaguntia | Peter Wiegel |

## Libraries / Библиотеки

PySide6 / Qt (LGPL-3.0), moderngl (MIT), numpy (BSD-3), soundcard (BSD-3), Pillow (MIT-CMU), OpenCV (Apache 2.0),
PyTorch (BSD-3), ffmpeg via imageio-ffmpeg (LGPL/GPL — see the license shipped with the binary).
