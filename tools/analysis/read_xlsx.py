import sys, zipfile, re, xml.etree.ElementTree as ET
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
z = zipfile.ZipFile(sys.argv[1])
ss = []
if "xl/sharedStrings.xml" in z.namelist():
    for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
        ss.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
wb = ET.fromstring(z.read("xl/workbook.xml"))
rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
for sh in wb.find("m:sheets", NS):
    name = sh.get("name"); target = rels[sh.get("{%s}id" % NS["r"])]
    path = "xl/" + target.lstrip("/").replace("xl/", "")
    root = ET.fromstring(z.read(path))
    print(f"\n===== {name} =====")
    for row in root.iter("{%s}row" % NS["m"]):
        vals = []
        for c in row.findall("m:c", NS):
            t = c.get("t"); v = c.find("m:v", NS); f = c.find("m:f", NS); is_ = c.find("m:is", NS)
            if t == "s" and v is not None: val = ss[int(v.text)]
            elif t == "inlineStr" and is_ is not None: val = "".join(x.text or "" for x in is_.iter("{%s}t" % NS["m"]))
            elif v is not None: val = v.text
            elif f is not None: val = "=" + (f.text or "")
            else: continue
            vals.append(f"{c.get('r')}: {val}")
        if vals: print(" | ".join(vals))
    cm = [n for n in z.namelist() if "comments" in n.lower()]
print("\nкомментарии-примечания:", cm)
for n in cm:
    for c in ET.fromstring(z.read(n)).iter("{%s}comment" % NS["m"]):
        print(c.get("ref"), "".join(t.text or "" for t in c.iter("{%s}t" % NS["m"])))
