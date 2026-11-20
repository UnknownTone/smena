"""Руководство SMENA (docs/manual/smena_manual.html) — в стиле логотипа с глазом: бирюзовый металл с ржавчиной,
жёлтое «око», пиксельные заголовки. Таблицы триггеров и фейдеров берутся из кода (smena/triggers_table.py) —
описания совпадают с подсказками программы. Запуск: .venv-smena\\Scripts\\python.exe tools\\docs\\make_manual.py"""
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from smena import VERSION                                          # noqa: E402
from smena.triggers_table import DETAILS, GLOBALS, SCENE_BY_KEY, TRIGGERS, BANK_SKIP   # noqa: E402

OUT = ROOT / "docs" / "manual" / "smena_manual.html"
FONTS = "../../smena/ui/theme/smena_pipboy/fonts"
e = html.escape


def rows(items):
    return "\n".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in items)


def fader(key):
    g = SCENE_BY_KEY[key]
    return f"<b>{e(g.label)}</b>", e(g.hint)


trig_rows = rows([(f"<span class=n>{t.n:02d}</span>", f"<b>{e(t.short)}</b><br><i>{e(t.kind)}</i>", e(t.name),
                   e(DETAILS[t.n])) for t in TRIGGERS])
glob_rows = rows([(f"<b>{e(g.label)}</b>", e(g.hint)) for g in GLOBALS if g.key not in BANK_SKIP])
img_rows = rows([fader(k) for k in ("orig", "orig.hold", "orig.flash", "strength", "gran", "bright")])
tr_rows = rows([fader(k) for k in ("tr.kind", "T", "tr.dur", "tr.curve", "tr.quant", "tr.rand", "tr.order")])
ov_rows = rows([fader(k) for k in ("ov.hold", "ov.fade", "ov.size")])
NAMES = {k: SCENE_BY_KEY[k].label for k in SCENE_BY_KEY}


def wires(name):
    d = json.loads((ROOT / "data" / "presets" / f"{name}.json").read_text(encoding="utf-8"))
    return ", ".join(f"LFO {i} → {NAMES.get(k, k)}" for i, k in d["lfo.wires"])


PAGE = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SMENA — руководство смены</title>
<style>
@font-face {{ font-family: VT323; src: url("{FONTS}/VT323-Regular.ttf"); }}
@font-face {{ font-family: "PT Mono"; src: url("{FONTS}/PTMono-Regular.ttf"); }}
@font-face {{ font-family: "PT Sans Narrow"; src: url("{FONTS}/PT_Sans-Narrow-Web-Regular.ttf"); }}
@font-face {{ font-family: "PT Sans Narrow"; font-weight: 700; src: url("{FONTS}/PT_Sans-Narrow-Web-Bold.ttf"); }}
:root {{ --teal:#5f9a93; --teal-d:#3d6f6a; --rust:#9a4f22; --rust-d:#5a2a10; --yel:#f2e21c; --yel-d:#b9a510;
        --ink:#ecebdf; --dim:#a7a690; --bg:#0d0c09; --panel:#16150f; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; color:var(--ink); font:16px/1.55 "PT Sans Narrow", sans-serif;
        background:#0a0907 url("tin.png"); background-size:520px; }}
.wrap {{ max-width: 980px; margin: 0 auto; padding: 28px 16px 60px; }}
header {{ text-align:center; padding: 26px 18px 18px; background: rgba(8,8,6,.86);
          border: 3px solid var(--teal-d); outline: 3px solid #000; box-shadow: 0 0 0 6px var(--rust-d), 0 10px 30px #000; }}
header img {{ width: 220px; image-rendering: pixelated; filter: drop-shadow(0 0 14px rgba(242,226,28,.35)); }}
h1 {{ font: 54px/1 VT323, monospace; letter-spacing: 6px; margin: 10px 0 0; color: var(--yel);
      text-shadow: 3px 3px 0 #000, 0 0 18px rgba(242,226,28,.35); }}
.sub {{ color: var(--dim); letter-spacing: 3px; font-weight:700; }}
.hazard {{ height: 10px; margin: 16px -18px 0; background: repeating-linear-gradient(135deg, var(--yel) 0 12px, #111 12px 24px); }}
section {{ margin-top: 26px; background: rgba(14,13,10,.93); border: 3px solid var(--teal-d); outline: 3px solid #000;
           box-shadow: 0 0 0 5px var(--rust-d); padding: 18px 22px; position: relative; }}
section::before, section::after {{ content:""; position:absolute; top:8px; width:10px; height:10px; border-radius:50%;
           background: radial-gradient(circle at 35% 35%, #c9c4b0, #3b3a30); box-shadow: 0 0 0 1px #000; }}
section::before {{ left: 8px; }} section::after {{ right: 8px; }}
h2 {{ font: 34px/1.1 VT323, monospace; color: var(--yel); letter-spacing: 3px; margin: 2px 0 12px;
      border-bottom: 2px dashed var(--yel-d); padding-bottom: 6px; }}
h2 .eye {{ color: var(--teal); }}
h3 {{ font: 24px/1.1 VT323, monospace; color: #9fd3c9; letter-spacing: 2px; margin: 18px 0 6px; }}
b {{ color: var(--yel); }} i {{ color: var(--dim); }}
table {{ width: 100%; border-collapse: collapse; margin: 8px 0 4px; font-size: 15px; }}
td, th {{ border: 1px solid #2b3a35; padding: 6px 8px; vertical-align: top; }}
th {{ background: var(--teal-d); color: #071210; text-align: left; font-weight: 700; letter-spacing: 1px; }}
tr:nth-child(even) td {{ background: rgba(95,154,147,.06); }}
.n {{ font: 22px VT323, monospace; color: var(--yel); }}
.note {{ border-left: 4px solid var(--yel); padding: 8px 12px; background: rgba(242,226,28,.06); margin: 10px 0; }}
.warn {{ border-left: 4px solid #c4221a; background: rgba(196,34,26,.08); padding: 8px 12px; }}
code, kbd {{ font-family: "PT Mono", monospace; background: #000; color: #3dff7a; padding: 0 5px; border: 1px solid #1e8a44; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
.card {{ border: 2px solid var(--teal-d); background: rgba(0,0,0,.35); padding: 10px 12px; }}
.card h3 {{ margin-top: 0; }}
ul {{ margin: 6px 0; padding-left: 20px; }}
footer {{ text-align:center; color: var(--dim); margin-top: 26px; font-size: 13px; }}
</style></head><body><div class="wrap">

<header>
  <img src="eye.png" alt="">
  <h1>SMENA {VERSION}</h1>
  <div class="sub">ЛОМО · VJ &nbsp;·&nbsp; РУКОВОДСТВО СМЕНЫ &nbsp;·&nbsp; powered by Unknown_Tone</div>
  <div class="hazard"></div>
</header>

<section>
<h2><span class="eye">◉</span> Как это устроено</h2>
<p>SMENA слушает музыку и собирает картинку из <b>элементов фотографий</b>: каждое фото разрезано на куски
(элементы) и чистый фон. Фото идут по кругу: <b>past</b> (уходящее), <b>master</b> (текущее), <b>future</b>
(следующее). Элементы въезжают, уезжают, поворачиваются, скользят — и всё это по командам <b>триггеров</b>:
20 датчиков, каждый слушает свой признак звука.</p>
<p>Это руководство — не инструкция «как правильно». Ручек много специально: крутите, соединяйте, ломайте.
Ничего не испортится — есть <b>СБРОС</b>, <b>RND</b> и три заводских пресета.</p>
<div class="warn"><b>Перед подключением:</b> громкость источника — в ноль; HDMI — при выключенном проекторе;
аудио — только в свой вход карты; кабели не дёргать на громкости; не допускать CLIP; проектор выключать штатно,
дождавшись охлаждения.</div>
</section>

<section>
<h2><span class="eye">◉</span> Таблица триггеров</h2>
<p>Вкладка <b>ТРИГГЕРЫ</b> и левый фейдербанк (крышка «СМЕНА», клавиша <kbd>B</kbd>). У каждого триггера:</p>
<ul>
  <li><b>ВКЛ</b> — включён или нет;</li>
  <li><b>СИЛА</b> (фейдер) — насколько сильно он действует, 0–200 %;</li>
  <li><b>ЧУВСТВ.</b> (ручка) — порог: больше — срабатывает чаще и от более тихого звука;</li>
  <li><b>▶</b> — запустить действие вручную (у событийных триггеров);</li>
  <li>лампа — вспышка при срабатывании, столбик — уровень признака прямо сейчас.</li>
</ul>
<p>Тип: <i>уровень</i> — действует непрерывно, пока признак есть; <i>импульс</i> — короткий удар на атаку;
<i>событие</i> — редкая крупная перемена (смена части трека, смена гармонии).</p>
<table><tr><th>№</th><th>триггер</th><th>признак звука</th><th>что делает со сценой</th></tr>
{trig_rows}</table>
<div class="note">Таблица (ВКЛ / СИЛА / ЧУВСТВ.) сохраняется <b>отдельно от пресетов</b> — файлом в кеше набора фото
(<code>&lt;кеш&gt;\\triggers\\*.json</code>). Так у каждого набора фото своя «чувствительность», а пресет —
свой «характер».</div>
<h3>RND и СБРОС</h3>
<p>На правом краю левого банка — <b>⚄ RND</b>: случайный набор ручек обоих банков, <b>каждый раз новый</b>
(в разумных пределах — без полного хаоса). Нажимайте, пока не зацепит, потом <b>SAVE</b>.
<b>↺ СБРОС</b> — все каналы и отсек управления по умолчанию. Передумали — <kbd>Ctrl+Z</kbd>.</p>
</section>

<section>
<h2><span class="eye">◉</span> Верхняя панель</h2>
<table><tr><th>что</th><th>зачем</th></tr>
<tr><td><b>ЗВУК · ИСТОЧНИК</b></td><td>что слушать: системный выход (loopback — всё, что играет компьютер) или вход
звуковой карты. Traktor / Reaper на ASIO в loopback не видны — берите вход карты или виртуальный кабель.</td></tr>
<tr><td><b>SUB · MID · HI</b></td><td>эквалайзер выхода (100 Гц · 1 кГц · 8 кГц, ±12 дБ) — для звука, который играет
сама SMENA (режим «файл»), и для записи REC. На триггеры не влияет.</td></tr>
<tr><td><b>VOL</b></td><td>громкость выхода. Лампочка: <b>красная</b> — 0 (звук выключен), <b>зелёная</b> — тем ярче,
чем громче.</td></tr>
<tr><td><b>ЗАДЕРЖКА</b></td><td>сдвиг визуала относительно звука, мс: крутите, пока вспышки не совпадут с бочкой.</td></tr>
<tr><td><b>FX</b></td><td>общий множитель силы всех движений от триггеров.</td></tr>
<tr><td><b>|◀◀ · ▶ · ▶▶|</b></td><td>к первому фото · пуск / стоп (<kbd>Пробел</kbd>) · следующее фото
(<kbd>→</kbd>, на ближайшей сильной доле).</td></tr>
<tr><td><b>◀ 003/054 ▶</b></td><td>счётчик кадров: номер фото / всего, стрелки — назад / вперёд.</td></tr>
<tr><td><b>BPM · TAP · RESET</b></td><td>темп находится сам. Промахнулся — TAP (4+ удара, <kbd>T</kbd>),
RESET — обратно в авто.</td></tr>
<tr><td><b>HUD</b></td><td>служебные подписи поверх превью (на HDMI не идут), <kbd>H</kbd>.</td></tr>
<tr><td><b>SAVE</b></td><td>сохранить всё в текущий пресет (подпись под кнопкой) + таблицу триггеров, <kbd>Ctrl+S</kbd>.</td></tr>
<tr><td><b>REC</b></td><td>запись того, что идёт на HDMI, в mp4 со звуком (Видео\\SMENA). Лампа горит — пишет.</td></tr>
<tr><td><b>▼ сверху над картинкой</b></td><td>шторка с правилами подключения и ссылкой на это руководство.</td></tr>
</table>
<h3>Верхнее фото</h3>
<p>Колонка слева от картинки: <b>ВКЛ</b> и <b>ФАЙЛ…</b> — картинка поверх показа (логотип, надпись — лучше PNG
с прозрачностью).</p>
<table>{ov_rows}</table>
</section>

<section>
<h2><span class="eye">◉</span> Вкладка ФЕЙДЕРЫ</h2>
<h3>Образ</h3>
<p><b>РЕЗКО / ПЛАВНО</b> — новые положения сразу или со следующего фото, мягко.
<b>ПРОЗР. ВКЛ / ВЫКЛ</b> — при малой силе элементы полупрозрачные или всегда целиком (тогда меньше силы —
меньше элементов в игре).</p>
<table>{img_rows}</table>
<h3>Смена кадров · морфинг</h3>
<p><b>ON / OFF</b> — OFF возвращает смену кадров первых версий (элементы, на такт, по папке).
Кнопки РЕЗ · ЭЛЕМ. · НАПЛЫВ · ШТОРКА · МЕРЦ · ЧЁРН ставят фейдер ВИД.</p>
<table>{tr_rows}</table>
<h3>LFO · осциллограф</h3>
<p>Четыре генератора: форма (∿ синус · △ треугольник · ⊿ пила · ⊓ меандр · S&amp;H случайная ступенька),
<b>СКОРОСТЬ</b> (в режиме <b>BPM</b> — от 1/4 доли до 256 тактов на цикл, в режиме <b>Гц</b> — свободно),
<b>ГЛУБИНА</b> (100 % — на половину хода фейдера в обе стороны). Кривые над панелями — форма и фаза прямо сейчас.</p>
<p><b>Провода:</b> тяните от «ВЫХ» к гнезду под <b>любым</b> фейдером — на вкладке, в отсеке управления, под СИЛОЙ
любого триггера. На одно гнездо можно несколько проводов — складываются. Правый клик по гнезду — снять.
Оранжевая черта на фейдере — где он сейчас с учётом LFO.</p>
<h3>Идеи патчей</h3>
<div class="cards">
<div class="card"><h3>Дыхание</h3>LFO ∿, 16 тактов, глубина 20 % → ЯРКОСТЬ. Картинка медленно светлеет и темнеет.</div>
<div class="card"><h3>Прилив</h3>LFO △, 32 такта, 60 % → ЭЛЕМЕНТЫ. Фото то почти целое, то рассыпается на куски.</div>
<div class="card"><h3>Рулетка переходов</h3>LFO S&amp;H, 4 такта, 100 % → ВИД. Каждая смена фото — другим способом.</div>
<div class="card"><h3>Память</h3>LFO ∿, 64 такта → ОРИГИНАЛ + ВСПЫШКА 30 %. Иногда сквозь эффект проступает исходное фото.</div>
<div class="card"><h3>Нерв</h3>LFO ⊓, 1 такт, 40 % → СИЛА № 4 АКЦН. Встряски через такт: сильно — тихо — сильно.</div>
<div class="card"><h3>Сбой</h3>LFO ⊿ в Гц, быстро → ДЛИТ. и КРИВАЯ. Переходы то рвутся, то тянутся.</div>
</div>
</section>

<section>
<h2><span class="eye">◉</span> Отсек управления</h2>
<p>Правый фейдербанк (клавиша <kbd>N</kbd>) — устройство цикла смены фото.</p>
<table>{glob_rows}</table>
</section>

<section>
<h2><span class="eye">◉</span> Три заводских пресета</h2>
<div class="cards">
<div class="card"><h3>slow</h3>Очень мягко: мало элементов (8), фото сменяется раз в 32 такта наплывом по 16 долей,
полосы скользят медленно, FX 45 %, образ плавно, вспышек нет.<br><i>LFO:</i> {e(wires("slow"))} — всё
очень медленное (32–128 тактов).</div>
<div class="card"><h3>medium</h3>Середина: не скучно, не хаос. 20 элементов, смена раз в 16 тактов, иногда
случайный вид перехода, вспышки оригинала 20 %.<br><i>LFO:</i> {e(wires("medium"))} — 2–16 тактов.</div>
<div class="card"><h3>trance</h3>Максимум: все 32 элемента, ОРИГИНАЛ 0, смена раз в 4 такта мерцанием,
60 % случайных переходов, полосы и FX 200 %, вспышки 50 %.<br><i>LFO:</i> {e(wires("trance"))} — быстрые,
от 1/4 такта.</div>
</div>
<p>Пресет хранит всё, кроме таблицы триггеров. Загрузка — вкладка ПРЕСЕТЫ, двойной клик.</p>
</section>

<section>
<h2><span class="eye">◉</span> Вывод на проектор</h2>
<ul>
<li><b>ВЫВОД ▶</b> — окно вывода на выбранный монитор. В окне <kbd>F</kbd> — полный экран, <kbd>Esc</kbd> — в окно.</li>
<li><b>BLACKOUT</b> — чёрный на выходе. <b>фото на весь кадр</b> — без полос по бокам.</li>
<li><b>Калибровка:</b> СЕТКА — тяните узлы (кривой экран, угол стены), плотность 2×2…8×8;
<b>ШИР. · ВЫС. · X · Y</b> — размер и положение картинки.</li>
<li><b>Маска</b> — вырезать картинку под объект: ▭ прямоугольник, ⬠ многоугольник (двойной клик — замкнуть),
✎ кисть, ⌫ ластик, ⇆ инверсия; РАСТ. — мягкий край, ОТСТ. — расширить / сузить.</li>
<li>Калибровка хранится по монитору, отдельно от пресетов. <b>↺ СБРОС</b> — всё ровно.</li>
</ul>
</section>

<section>
<h2><span class="eye">◉</span> Фото и редактор элементов</h2>
<p><b>Вкладка ФОТО:</b> папка фото и папка кеша. Новые фото — «Подготовить фото»: нейросеть SAM 2 находит
объекты, отбор выбирает элементы, LaMa дорисовывает чистый фон (≈ 20 с на фото). Порядок показа — по номерам
в именах файлов.</p>
<p><b>Редактор элементов</b> (кнопка на вкладке ФОТО) — поправить, что стало элементом:</p>
<ul>
<li><b>✦ SAM</b>: клик по элементу — убрать; по серому контуру кандидата — сделать элементом; в пустое место —
нейросеть сама найдёт объект. <kbd>Shift</kbd>+клик — добавить точку, <kbd>Alt</kbd>+клик — исключить.</li>
<li><b>✎ РУКА</b> — обвести от руки; <b>⬠ ТОЧКИ</b> — многоугольник; <b>⌫ ЛАСТИК</b> — срезать лишнее.</li>
<li><b>Фигуры</b> ▭ ◯ △ ▬ ▮ ◔ — тянуть мышью: прямоугольник, эллипс, треугольник, полосы на всю ширину / высоту,
сектор.</li>
<li><b>⟲ ⟳ ⇋ ⊾</b> — повернуть, отразить фото, выровнять горизонт (оригинал сохраняется в
«_SMENA_оригиналы», элементы готовятся заново).</li>
<li>Свойства элемента: <b>верх / низ</b> (<kbd>H</kbd>) — какие триггеры на него действуют; <b>маска / прям.</b>
(<kbd>R</kbd>) — по силуэту или прямоугольником; <b>ось X / Y</b> (<kbd>X</kbd>) — куда скользит содержимое.
Красная пунктирная линия — граница «верх / низ», тянется мышью.</li>
<li><b>Объединить</b> (<kbd>G</kbd>), <b>Убрать</b> (<kbd>Del</kbd>), отмена <kbd>Ctrl+Z</kbd>.
<b>Собрать фото</b> (<kbd>B</kbd>) — пересобрать элементы. <b>Проверено и дальше</b> (<kbd>Пробел</kbd>) — фото
размечено; по разметке можно <b>обучить модель</b>, и следующие наборы она будет резать «под вас».</li>
</ul>
</section>

<section>
<h2><span class="eye">◉</span> Клавиши</h2>
<table>
<tr><td><kbd>Пробел</kbd></td><td>пуск / стоп</td><td><kbd>← →</kbd></td><td>фото назад / вперёд</td></tr>
<tr><td><kbd>Home</kbd></td><td>к первому фото</td><td><kbd>T</kbd></td><td>tap темпа</td></tr>
<tr><td><kbd>B</kbd> / <kbd>N</kbd></td><td>левый / правый банк</td><td><kbd>H</kbd></td><td>HUD</td></tr>
<tr><td><kbd>M</kbd></td><td>беззвучно</td><td><kbd>Ctrl+S</kbd></td><td>SAVE</td></tr>
<tr><td><kbd>Ctrl+Z</kbd></td><td>отмена СБРОС / RND</td><td></td><td></td></tr>
</table>
<p>У каждой ручки и кнопки есть подсказка — наведите курсор. Всё, что вы делаете, пишется во вкладку ЖУРНАЛ.</p>
</section>

<footer>SMENA {VERSION} · ЛОМО · VJ · powered by Unknown_Tone</footer>
</div></body></html>
"""
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(PAGE, encoding="utf-8")
print(OUT)
