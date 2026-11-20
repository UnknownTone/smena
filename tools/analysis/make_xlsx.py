"""Минимальный генератор .xlsx на zipfile (без openpyxl)."""
import sys, zipfile
from xml.sax.saxutils import escape

OUT = sys.argv[1]

# ---------------------------------------------------------------- данные
TRIG = [
    # параметр, что в звуке, т1, т2, т3, т4, сила, величина, тип
    ("Смена части (значимо сменились ≥3 признака одновременно)", "Новый раздел трека", 5, 8, 12, 4, "—", "3–5 признаков сразу", "секция"),
    ("Бас 60–150 Гц", "Вход / уход баса", 10, 4, 6, 3, "|d| 4.2", "±4 дБ", "уровень"),
    ("Яркость (центроид спектра)", "Фильтр открылся / закрылся", 6, 2, 10, 2, "|d| 4.3", "×1.7 по частоте", "уровень"),
    ("Акцент: удар выше локального фона", "Одиночный сильный удар / хит", 156, 25, 146, 37, "z ≈ 9", "80% идут сериями", "импульс"),
    ("Стерео-ширина", "Звук «раскрылся» / сузился", 5, 1, 9, 2, "|d| 4.3", "±0.2 S/M", "уровень"),
    ("Доля ударного (HPSS)", "Ударные против тянущихся звуков", 3, 4, 8, 2, "|d| 4.1", "±0.11", "уровень"),
    ("Тональная ясность", "Звучит нота / аккорд, а не шум", 3, 5, 7, 2, "|d| 3.9", "±0.12", "уровень"),
    ("Шумность (плоскостность спектра)", "Вход шумового / индустриального слоя", 4, 3, 6, 3, "|d| 4.5", "×4.8", "уровень"),
    ("Суббас 20–60 Гц", "Глубокий низ вошёл / ушёл", 4, 1, 9, 1, "|d| 4.6", "±6 дБ (до 37 дБ)", "уровень"),
    ("Верх 6–16 кГц", "Хэты, воздух, шипение", 2, 4, 7, 2, "|d| 4.3", "±7 дБ (до 29 дБ)", "уровень"),
    ("Низкая середина 150–500 Гц", "«Тело» звука, гул", 3, 5, 5, 1, "|d| 3.8", "±2.6 дБ", "уровень"),
    ("Смена гармонии", "Сменился тональный центр / аккорд", 3, 3, 1, 2, "z 5–25", "редко, но очень сильно", "секция"),
    ("Активность хэтов (атаки верха)", "Ритмичный верх появился / пропал", 1, 4, 4, 1, "|d| 3.8", "×1.3", "уровень"),
    ("Ритмичность (ясность пульса)", "Появился / пропал бит", 0, 4, 2, 2, "|d| > 2", "±0.15…0.4", "секция"),
    ("Обрывы (провал −6 дБ и сильнее, эпизоды)", "Стоп, заикание, gate", 2, 1, 0, 3, "—", "−6 дБ и сильнее", "импульс / серия"),
    ("Середина 0.5–2 кГц", "Синты, голосоподобное", 7, 2, 4, 0, "|d| 4.0", "±3.8 дБ", "уровень"),
    ("Пульсация яркости внутри такта", "LFO, «дышащий» фильтр", 0, 4, 8, 1, "|d| 3.5", "—", "уровень"),
    ("Верхняя середина 2–6 кГц", "Резкость, атака", 2, 0, 9, 1, "|d| 3.5", "±7.7 дБ", "уровень"),
    ("Громкость RMS", "Общая громкость", 2, 1, 4, 3, "|d| 4.1", "±2 дБ (мало)", "уровень"),
    ("Wobble баса (пульсация баса внутри такта)", "Качающийся бас", 0, 6, 1, 0, "|d| 3.8", "±1.8 дБ", "уровень"),
]
TRACKS = [
    ("1. Spisok Zhivotnih", 8.50, None, "сетки нет (свободное время)",
     "До 7:20 — ровная стена звука; 7:20–8:02 серия обрывов, смена гармонии, рост шумности (кульминация)"),
    ("2. ZMLTRS", 5.84, 139.6, "очень высокая (z = 91)",
     "Самый ритмичный в басу; бит появляется/исчезает ~0:54/1:08 и ~3:52/4:06; сильнейшая смена гармонии альбома — 5:36"),
    ("3. Serediny", 8.04, 120.2, "очень высокая (z = 126)",
     "Самый насыщенный событиями (12 смен частей); 0:52 входит бит; 5:47 суббас +37 дБ, смена гармонии и доли ударного"),
    ("4. Voznesenie", 6.02, None, "сетки нет (свободное время)",
     "Обрывы во вступлении (0:03–0:19) и концовке (5:41–5:50); смены гармонии 4:24 и 4:56"),
]
QUESTIONS = [
    "«Раз в 16 тактов» — это 16 тактов (64 доли, ≈30 с) или 16 долей (4 такта, ≈8 с)?",
    "Треки 1 и 4 без сетки: условные 120 BPM (фото раз в 32 с), по событию «смена части» или сетка + события?",
    "Приоритет фото: проставляете числа вручную или считать автоматически по свойствам снимка?",
]

# ---------------------------------------------------------------- стили
# xf: 0 обычный, 1 шапка, 2 текст, 3 число, 4 комментарий (жёлтый), 5 заголовок,
#     6 примечание, 7 число 0.00, 8 жирный текст в ячейке, 9 число 0.0
STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="0.0"/></numFmts>
<fonts count="4">
<font><sz val="10"/><name val="Arial"/></font>
<font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Arial"/></font>
<font><b/><sz val="14"/><name val="Arial"/></font>
<font><i/><sz val="9"/><color rgb="FF666666"/><name val="Arial"/></font>
</fonts>
<fills count="4">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF2F3A4A"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="2">
<border><left/><right/><top/><bottom/><diagonal/></border>
<border><left style="thin"><color rgb="FFBFBFBF"/></left><right style="thin"><color rgb="FFBFBFBF"/></right><top style="thin"><color rgb="FFBFBFBF"/></top><bottom style="thin"><color rgb="FFBFBFBF"/></bottom><diagonal/></border>
</borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="10">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="top"/></xf>
<xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="2" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="top"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="top"/></xf>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def cell(ref, v, st):
    if v is None:
        return f'<c r="{ref}" s="{st}"/>'
    if isinstance(v, str) and v.startswith("="):
        return f'<c r="{ref}" s="{st}"><f>{escape(v[1:])}</f></c>'
    if isinstance(v, (int, float)):
        return f'<c r="{ref}" s="{st}"><v>{v}</v></c>'
    return f'<c r="{ref}" s="{st}" t="inlineStr"><is><t xml:space="preserve">{escape(v)}</t></is></c>'


def sheet(rows, widths, freeze=None, heights=None, merges=()):
    """rows: {номер_строки: [(значение, стиль), ...]}"""
    x = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
         '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">']
    if freeze:
        x.append(f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{freeze - 1}" topLeftCell="A{freeze}" '
                 f'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>')
    x.append("<cols>" + "".join(f'<col min="{i+1}" max="{i+1}" width="{w}" customWidth="1"/>'
                                for i, w in enumerate(widths)) + "</cols><sheetData>")
    for r in sorted(rows):
        ht = (heights or {}).get(r)
        attr = f' ht="{ht}" customHeight="1"' if ht else ""
        x.append(f'<row r="{r}"{attr}>' + "".join(cell(f"{col(i)}{r}", v, s) for i, (v, s) in enumerate(rows[r])) + "</row>")
    x.append("</sheetData>")
    if merges:
        x.append(f'<mergeCells count="{len(merges)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in merges) + "</mergeCells>")
    x.append("</worksheet>")
    return "".join(x)


# ---------------------------------------------------------------- лист 1: триггеры
r1 = {
    1: [("Триггерные параметры альбома «Unknown Tone» (по значимости)", 5)],
    2: [("Значимо = t-тест Уэлча 8 тактов до/после, p < 0.01 с поправкой Бонферрони, |d| > 2 и изменение выше порога слышимости. "
         "Для треков 1 и 4 вместо такта — отрезок 2 с. Сила: |d| — эффект Коэна, z — робастный z-балл. "
         "Общая длительность альбома (мин) — ячейка O3.", 6)],
    3: [("Жёлтый столбец «Комментарий» — для ваших заметок. Пример: «на смену части — новое фото с прожигом, шлейфы ×2».", 6)]
       + [(None, 0)] * 13 + [("=SUM(Треки!B2:B5)", 9)],
    4: [(h, 1) for h in ["№", "Параметр", "Что это в звуке", "Трек 1", "Трек 2", "Трек 3", "Трек 4",
                         "Всего событий", "В минуту", "Сила", "Типичная величина", "Тип триггера", "Комментарий"]]
       + [(None, 0), ("Мин. альбома", 1)],
}
for i, (p, what, a, b, c, d, eff, mag, typ) in enumerate(TRIG):
    r = 5 + i
    r1[r] = [(i + 1, 3), (p, 8), (what, 2), (a, 3), (b, 3), (c, 3), (d, 3),
             (f"=SUM(D{r}:G{r})", 3), (f"=IFERROR(H{r}/$O$3,0)", 7), (eff, 3), (mag, 2), (typ, 3), (None, 4)]
last = 5 + len(TRIG)
r1[last + 1] = [("Не вошли: нарастания/дропы (4 случая, все во вступлениях/концовках), пик-фактор, плотность атак, атаки бочки (3–6 событий в 1–2 треках).", 6)]
r1[last + 2] = [("Обрывы — считаются эпизоды (серии провалов), без учёта первых 3 с трека.", 6)]
ws1 = sheet(r1, [5, 38, 32, 8, 8, 8, 8, 10, 10, 10, 20, 15, 45, 2, 12], freeze=5,
            heights={4: 30}, merges=("A1:M1", "A2:M2", "A3:M3"))

# ---------------------------------------------------------------- лист 2: треки
r2 = {1: [(h, 1) for h in ["Трек", "Длительность, мин", "Темп, BPM", "Надёжность темпа",
                           "16 тактов, с", "Ключевые моменты", "Комментарий"]]}
for i, (t, dur, bpm, rel, note) in enumerate(TRACKS):
    r = 2 + i
    r2[r] = [(t, 8), (dur, 7), (bpm if bpm else "—", 9 if bpm else 3), (rel, 2),
             (f"=IFERROR(16*4*60/C{r},\"—\")", 9), (note, 2), (None, 4)]
r2[7] = [("16 тактов = 16 × 4 доли × 60 / BPM. Длительность — по декодированному аудио.", 6)]
ws2 = sheet(r2, [24, 12, 11, 26, 12, 70, 40], freeze=2, heights={1: 30})

# ---------------------------------------------------------------- лист 3: вопросы
r3 = {1: [("№", 1), ("Вопрос", 1), ("Ваш ответ", 1)]}
for i, q in enumerate(QUESTIONS):
    r3[2 + i] = [(i + 1, 3), (q, 2), (None, 4)]
ws3 = sheet(r3, [5, 80, 50], freeze=2)

SHEETS = [("Триггеры", ws1), ("Треки", ws2), ("Вопросы", ws3)]

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("[Content_Types].xml",
               '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
               '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
               '<Default Extension="xml" ContentType="application/xml"/>'
               '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
               '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
               + "".join(f'<Override PartName="/xl/worksheets/sheet{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                         for i in range(len(SHEETS))) + "</Types>")
    z.writestr("_rels/.rels",
               '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
               '</Relationships>')
    z.writestr("xl/workbook.xml",
               '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
               'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
               + "".join(f'<sheet name="{n}" sheetId="{i+1}" r:id="rId{i+1}"/>' for i, (n, _) in enumerate(SHEETS))
               + '</sheets><calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>')
    z.writestr("xl/_rels/workbook.xml.rels",
               '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               + "".join(f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i+1}.xml"/>'
                         for i in range(len(SHEETS)))
               + f'<Relationship Id="rId{len(SHEETS)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
               '</Relationships>')
    z.writestr("xl/styles.xml", STYLES)
    for i, (_, ws) in enumerate(SHEETS):
        z.writestr(f"xl/worksheets/sheet{i+1}.xml", ws)
print("ok", OUT)
