"""分析用户 SVG 各波浪层的几何，为精细化提供依据。

重点：
- 每层的上下边界走势（逐 x 采样）
- 层间重叠量（是否留缝）
- 太阳与白浪的遮挡关系
"""
import math

# 用户原稿的三层波浪路径（从 SVG 的 d 属性解析）
BACK = ("M188 646C244 613 298 574 363 556C425 539 481 545 530 557"
        "C585 571 626 595 682 600C738 605 780 585 820 584"
        "C838 584 854 591 856 600C859 611 846 620 828 629"
        "C785 651 743 677 700 706C655 736 617 773 571 791"
        "C527 809 475 809 429 793C376 775 328 746 278 727"
        "C243 714 207 701 184 688C171 681 173 667 188 656Z")

MID = ("M190 550C238 523 282 503 329 488C372 475 413 478 454 494"
       "C493 509 528 535 566 545C608 556 650 552 686 544"
       "C730 534 767 538 803 550C828 558 850 566 855 578"
       "C860 591 845 601 824 612C780 634 735 660 692 680"
       "C651 699 612 708 575 708C533 708 500 693 464 676"
       "C422 656 383 633 338 617C293 601 244 589 202 578"
       "C185 574 173 568 176 561C178 557 183 554 190 550Z")

FRONT = ("M198 451C249 430 291 408 331 382C367 359 401 336 438 325"
         "C472 314 507 314 539 323C574 333 604 354 635 372"
         "C668 391 699 403 735 416C770 429 804 443 832 454"
         "C846 459 854 467 854 476C854 486 845 494 831 501"
         "C800 517 767 534 735 549C701 565 673 574 641 575"
         "C605 576 576 572 545 562C511 551 482 536 450 521"
         "C416 505 384 495 349 489C312 482 274 479 239 477"
         "C220 476 201 474 192 469C186 465 189 457 198 451Z")


def parse_path(d):
    """把 SVG path 解析成 [(type, points)] 序列，支持 M/C/Z（本稿只用这些）。"""
    toks = []
    i = 0
    num = ""
    while i < len(d):
        ch = d[i]
        if ch in "MmCcZz":
            if num:
                toks.append(("num", float(num)))
                num = ""
            toks.append(("cmd", ch))
        elif ch in "0123456789.-+eE":
            num += ch
        elif ch == " ":
            if num:
                toks.append(("num", float(num)))
                num = ""
        i += 1
    if num:
        toks.append(("num", float(num)))

    segs = []
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    cmd = None
    nums = []
    for kind, val in toks:
        if kind == "cmd":
            cmd = val
            if cmd in "Zz":
                segs.append(("Z", [start]))
                cur = start
            nums = []
        else:
            nums.append(val)
            need = 6 if cmd in "Cc" else 2
            if len(nums) == need:
                if cmd == "M":
                    cur = (nums[0], nums[1])
                    start = cur
                    segs.append(("M", [cur]))
                    cmd = "L"   # 后续 M 视为隐式 L（本稿无此情况）
                elif cmd == "L":
                    cur = (nums[0], nums[1])
                    segs.append(("L", [cur]))
                elif cmd == "C":
                    p1 = (nums[0], nums[1])
                    p2 = (nums[2], nums[3])
                    p3 = (nums[4], nums[5])
                    segs.append(("C", [p1, p2, p3]))
                    cur = p3
                nums = []
    return segs


def flatten(segs, steps=24):
    """把路径离散成折线点。"""
    pts = []
    cur = (0.0, 0.0)
    for kind, ps in segs:
        if kind in ("M", "L"):
            cur = ps[0]
            if not pts:
                pts.append(cur)
        elif kind == "C":
            p0 = cur
            p1, p2, p3 = ps
            for i in range(1, steps + 1):
                u = i / steps
                w0 = (1 - u) ** 3
                w1 = 3 * (1 - u) ** 2 * u
                w2 = 3 * (1 - u) * u * u
                w3 = u ** 3
                pts.append((w0 * p0[0] + w1 * p1[0] + w2 * p2[0] + w3 * p3[0],
                            w0 * p0[1] + w1 * p1[1] + w2 * p2[1] + w3 * p3[1]))
            cur = p3
    return pts


def bounds_at_x(pts, x):
    """返回该 x 处折线的 y 区间（多条交点时取上下界）。"""
    ys = []
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        if (x0 - x) * (x1 - x) <= 0 and abs(x1 - x0) > 1e-9:
            u = (x - x0) / (x1 - x0)
            ys.append(y0 + u * (y1 - y0))
    if not ys:
        return None
    return (min(ys), max(ys))


if __name__ == "__main__":
    layers = {"深浪(back)": BACK, "暖浪(mid)": MID, "白浪(front)": FRONT}
    flat = {}
    for name, d in layers.items():
        pts = flatten(parse_path(d))
        flat[name] = pts
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        print(f"{name}: x∈[{min(xs):.0f},{max(xs):.0f}] "
              f"y∈[{min(ys):.0f},{max(ys):.0f}] 点数={len(pts)}")

    print("\n--- 各层在若干 x 处的厚度与层间距 ---")
    for x in (200, 300, 400, 500, 600, 700, 800):
        print(f"\nx={x}")
        for name in layers:
            b = bounds_at_x(flat[name], x)
            if b:
                print(f"  {name:12s} y∈[{b[0]:.0f},{b[1]:.0f}]  厚={b[1]-b[0]:.0f}")

    print("\n--- 太阳 (649,291) r=107 与白浪关系 ---")
    pts = flat["白浪(front)"]
    b = bounds_at_x(pts, 649)
    print(f"  白浪在 x=649 处 y∈[{b[0]:.0f},{b[1]:.0f}]")
    print(f"  太阳下缘 y = {291+107}   → 太阳被白浪遮住下半")
