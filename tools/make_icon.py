"""產生程式圖示：assets/icon.png（1024）、packaging/icon.ico、assets/icon.ico。

資料助秘系列的深藍到青綠圓角方塊；上方「3D列印」標題列，中間是一台 3D 印表機（機框、橫樑、拓竹綠噴頭）
正在印一個有層紋的立體方塊，右上角金幣寫「AI」（代理人），左下角「資料助秘」標籤。
"""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = 1024


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def shadow(img, shape_fn, blur=18, offset=(10, 20), alpha=100):
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shape_fn(ImageDraw.Draw(sh), offset, (0, 0, 0, alpha))
    return Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(blur)))


def font(size):
    try:
        f = ImageFont.truetype(os.path.join(HERE, "assets", "fonts", "NotoSansTC-VF.ttf"), size)
        try:
            f.set_variation_by_name("Black")
        except Exception:
            pass
        return f
    except Exception:
        return ImageFont.load_default()


def main():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    c1, c2 = (15, 60, 110), (14, 150, 120)
    for y in range(S):
        gd.line([(0, y), (S, y)], fill=lerp(c1, c2, y / S) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=220, fill=255)
    img.paste(grad, (0, 0), mask)
    gloss = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).ellipse([-200, -520, S + 200, 420], fill=(255, 255, 255, 34))
    img = Image.alpha_composite(img, Image.composite(gloss, Image.new("RGBA", (S, S)), mask))

    # 標題列「3D列印」
    img = shadow(img, lambda d, o, f: d.rounded_rectangle([150 + o[0], 140 + o[1], 650 + o[0], 280 + o[1]], radius=50,
                                                          fill=f), blur=16, offset=(8, 16), alpha=90)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([150, 140, 650, 280], radius=50, fill=(30, 77, 140, 255), outline=(120, 170, 230, 255), width=6)
    d.text((400, 207), "3D列印", font=font(92), fill=(255, 255, 255, 255), anchor="mm")

    # 印表機：機框、橫樑與噴頭、列印板上正在印的立體方塊（等角圖，層紋）
    pr = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    r = ImageDraw.Draw(pr)
    frame = (226, 232, 240, 255)
    r.rounded_rectangle([150, 330, 874, 860], radius=40, outline=frame, width=34)
    r.rectangle([184, 800, 840, 826], fill=(120, 132, 150, 255))                     # 列印板
    r.rounded_rectangle([184, 392, 840, 424], radius=14, fill=(180, 190, 205, 255))  # 橫樑
    # 等角方塊
    cx, base, w, h = 512, 800, 125, 135
    hx = cx
    top = [(cx, base - h - w * 0.5), (cx + w, base - h), (cx, base - h + w * 0.5), (cx - w, base - h)]
    left = [(cx - w, base - h), (cx, base - h + w * 0.5), (cx, base + w * 0.5 - 0), (cx - w, base)]
    right = [(cx, base - h + w * 0.5), (cx + w, base - h), (cx + w, base), (cx, base + w * 0.5)]
    left = [(x, y - w * 0.5) for x, y in left]
    right = [(x, y - w * 0.5) for x, y in right]
    top = [(x, y - w * 0.5) for x, y in top]
    r.polygon(left, fill=(244, 177, 66, 255))
    r.polygon(right, fill=(214, 140, 30, 255))
    r.polygon(top, fill=(255, 214, 120, 255))
    for k in range(1, 12):                                                            # 層紋
        t = k / 12
        yl = lambda p, q: (p[0] + (q[0] - p[0]) * 0, p[1] + (q[1] - p[1]) * t)
        a1 = (left[0][0], left[0][1] + (left[3][1] - left[0][1]) * t)
        a2 = (left[1][0], left[1][1] + (left[2][1] - left[1][1]) * t)
        a3 = (right[1][0], right[1][1] + (right[2][1] - right[1][1]) * t)
        r.line([a1, a2, a3], fill=(180, 110, 20, 150), width=4)
        _ = yl
    # 噴頭（拓竹綠）與熔融的線
    r.rounded_rectangle([hx - 66, 366, hx + 66, 470], radius=18, fill=(0, 174, 66, 255))
    r.rounded_rectangle([hx - 40, 386, hx + 40, 410], radius=8, fill=(0, 140, 52, 255))
    r.polygon([(hx - 28, 470), (hx + 28, 470), (hx, 512)], fill=(70, 80, 95, 255))
    r.line([(hx, 512), (hx, top[2][1] - top[2][1] + (top[0][1] + top[2][1]) / 2)], fill=(255, 214, 120, 255), width=9)
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sh.paste((0, 0, 0, 90), (12, 22), pr.getchannel("A"))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(18)))
    img = Image.alpha_composite(img, pr)

    # 金幣「算」
    cx, cy, rr = 810, 225, 135
    img = shadow(img, lambda d, o, f: d.ellipse([cx - rr + o[0], cy - rr + o[1], cx + rr + o[0], cy + rr + o[1]],
                                                fill=f), blur=16, offset=(10, 18), alpha=110)
    d = ImageDraw.Draw(img)
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(240, 180, 40, 255), outline=(255, 226, 140, 255), width=14)
    d.ellipse([cx - rr + 30, cy - rr + 30, cx + rr - 30, cy + rr - 30], outline=(201, 138, 20, 255), width=6)
    d.text((cx, cy - 8), "AI", font=font(130), fill=(20, 50, 92, 255), anchor="mm")
    # 左下角「資料助秘」小標籤
    d.rounded_rectangle([110, 880, 440, 960], radius=40, fill=(255, 255, 255, 235))
    d.text((275, 918), "資料助秘", font=font(52), fill=(30, 77, 140, 255), anchor="mm")
    img.putalpha(Image.composite(img.getchannel("A"), Image.new("L", (S, S), 0), mask))
    out = os.path.join(HERE, "assets", "icon.png")
    img.save(out)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    for p in (os.path.join(HERE, "packaging", "icon.ico"), os.path.join(HERE, "assets", "icon.ico")):
        img.save(p, sizes=sizes)
    print("ok", out)


if __name__ == "__main__":
    main()
