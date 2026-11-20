import os, sys, pygame
os.environ["SDL_VIDEODRIVER"] = "dummy"; pygame.init()
D = sys.argv[1]; out = sys.argv[2]
fs = sorted(f for f in os.listdir(D) if f.lower().endswith(".jpg"))
TW, TH, C = 240, 160, 10
rows = (len(fs) + C - 1) // C
sheet = pygame.Surface((C * TW, rows * (TH + 16))); sheet.fill((20, 20, 20))
font = pygame.font.SysFont("segoeui", 12)
for i, f in enumerate(fs):
    im = pygame.image.load(os.path.join(D, f)); w, h = im.get_size(); k = min(TW / w, TH / h)
    t = pygame.transform.smoothscale(im, (int(w * k), int(h * k)))
    x, y = (i % C) * TW, (i // C) * (TH + 16)
    sheet.blit(t, (x + (TW - t.get_width()) // 2, y)); sheet.blit(font.render(f, True, (200, 200, 200)), (x + 4, y + TH))
pygame.image.save(sheet, out); print(len(fs), sheet.get_size())
