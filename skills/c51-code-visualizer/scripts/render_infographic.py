"""Deterministic C51 teaching infographic renderer. Requires Pillow and Pygments."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pygments.lexers import CLexer
from pygments.token import Comment, Keyword, Number, String

WIDTH, HEIGHT = 1814, 867
BLUE, GREEN, ORANGE, CYAN = '#2164b5', '#228452', '#bb661d', '#147d90'
INK = '#213449'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def source_info(path, encoding):
    raw = Path(path).read_bytes()
    text = raw.decode(encoding, errors='strict')
    if not text or not text.strip():
        raise ValueError('Source is empty.')
    if any(ord(c) < 32 and c not in '\t\r\n' for c in text):
        raise ValueError('Unsupported control character in source; do not discard it silently.')
    lines = text.splitlines(keepends=True)
    return raw, text, lines


def read_plan(path):
    plan = load_json(path)
    raw, text, lines = source_info(Path(path).parent / plan['source_file'], plan['encoding'])
    if digest(raw) != plan['source_sha256'] or len(lines) != plan['line_count']:
        raise ValueError('Source baseline changed.')
    expected = 1
    for page in plan['pages']:
        if page['start'] != expected or page['end'] < expected or page['end'] > len(lines):
            raise ValueError('Page ranges must cover source once in original order.')
        expected = page['end'] + 1
    if expected != len(lines) + 1:
        raise ValueError('Page ranges omit source lines.')
    return plan, raw, text, lines


class Painter:
    def __init__(self, mono=None, cjk=None):
        self.mono_path = self.find_font(mono, [
            'C:/Windows/Fonts/consola.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'])
        self.cjk_path = self.find_font(cjk, [
            'C:/Windows/Fonts/msyh.ttc',
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'])
        self.fonts, self.widths = {}, {}
        self.im = Image.new('RGB', (WIDTH, HEIGHT), 'white')
        self.draw = ImageDraw.Draw(self.im)

    @staticmethod
    def find_font(explicit, candidates):
        for p in ([explicit] if explicit else candidates):
            if p and Path(p).is_file():
                return str(p)
        raise ValueError('Font unavailable; supply --mono-font and --cjk-font.')

    def font(self, ch, size, code=False):
        path = self.mono_path if code and ord(ch) < 128 else self.cjk_path
        key = (path, size)
        if key not in self.fonts:
            self.fonts[key] = ImageFont.truetype(path, size)
        return self.fonts[key]

    def advance(self, ch, size, code=False):
        key = (ch, size, code)
        if key not in self.widths:
            self.widths[key] = float(self.font(ch, size, code).getlength(ch))
        return self.widths[key]

    def length(self, text, size, code=False):
        return sum(self.advance(ch, size, code) for ch in text)

    def text(self, x, y, text, size=21, color=INK, code=False):
        for ch in str(text):
            # A shared baseline keeps punctuation in place across ASCII/CJK fonts.
            self.draw.text((x, y+size), ch, font=self.font(ch, size, code), fill=color, anchor='ls')
            x += self.advance(ch, size, code)
        return x

    def paragraph(self, x, y, text, width, bottom, size=21, color=INK, code=False):
        line, w = '', 0.0
        rows = []
        for ch in str(text):
            if ch == '\r':
                continue
            cw = self.advance(ch, size, code) if ch != '\n' else 0
            if ch == '\n' or (line and w + cw > width):
                rows.append(line)
                line, w = '', 0.0
            if ch != '\n':
                if cw > width:
                    raise ValueError('Text column is too narrow.')
                line += ch
                w += cw
        rows.append(line)
        for row in rows:
            if y + size + 5 > bottom:
                raise ValueError('Teaching text overflows its card; add pages or reduce content.')
            self.text(x, y, row, size, color, code)
            y += size + 8
        return y

    def card(self, x, y, w, h, title, color):
        self.draw.rounded_rectangle((x, y, x+w, y+h), radius=14, fill='white', outline='#d8e2ed', width=2)
        self.draw.rounded_rectangle((x+1, y+1, x+w-1, y+42), radius=12, fill=color)
        if self.length(title, 22) > w-28:
            raise ValueError('Card title is too wide.')
        self.text(x+14, y+9, title, 22, 'white')


def syntax_colors(text):
    colors = ['#263c56'] * len(text)
    pieces = []
    offset = 0
    for pos, token, value in CLexer().get_tokens_unprocessed(text):
        if pos != offset:
            raise ValueError('Lexer did not preserve source positions.')
        pieces.append(value)
        offset += len(value)
        color = GREEN if token in Comment else BLUE if token in Keyword else ORANGE if token in Number else '#824aad' if token in String else '#263c56'
        colors[pos:pos+len(value)] = [color] * len(value)
    if ''.join(pieces) != text:
        raise ValueError('Lexer changed the source.')
    return colors


def draw_code(p, plan, page, lines, colors, offsets):
    x, y, w = 24, 24, plan['code_width']
    p.card(x, y, w, 819, plan['display_name'], BLUE)
    badge = 'C语言（51单片机）'
    suffix = f"第{page['index']}页 / 共{len(plan['pages'])}页"
    bx = x+w-p.length(badge, 18)-16
    if bx < x+30+p.length(plan['display_name'], 22):
        raise ValueError('Filename overlaps code badge; use a shorter display name.')
    p.text(bx, y+12, badge, 18, 'white')
    p.text(x+16, y+52, suffix, 17, '#62768b')
    gutter = max(48, int(p.length(str(plan['line_count']), 18, True))+14)
    for row, n in enumerate(range(page['start'], page['end']+1)):
        yy = y+83+row*29
        if yy+24 > y+805:
            raise ValueError('Too many source lines on a page; re-plan pagination.')
        p.text(x+10, yy+2, str(n), 18, '#8c9caf', True)
        xx, column = x+gutter, 0
        for j, ch in enumerate(lines[n-1].rstrip('\r\n')):
            show = ' ' * (4-column % 4) if ch == '\t' else ch
            column += len(show)
            for glyph in show:
                if xx+p.advance(glyph, 22, True) > x+w-18:
                    raise ValueError(f'Source line {n} exceeds code width. Use wider code-only pages; do not truncate.')
                xx = p.text(xx, yy, glyph, 22, colors[offsets[n-1]+j], True)


def draw_leds(p, section, x, y, w, bottom):
    order = section['bit_order']
    level = section['active_level']
    if sorted(order) != list(range(8)) or level not in (0, 1):
        raise ValueError('LEDs require bit_order as a permutation of 0..7 and active_level 0 or 1.')
    y = p.paragraph(x, y, section['assumption'], w, bottom, 19, ORANGE)
    for row in section['rows']:
        value = int(row['value'], 0) if isinstance(row['value'], str) else row['value']
        if not isinstance(value, int) or not 0 <= value <= 255:
            raise ValueError('Port value must be an 8-bit integer.')
        y = p.paragraph(x, y, f"{row['label']}  0x{value:02X}", w, bottom, 19)
        if y+50 > bottom:
            raise ValueError('LED diagram overflows card.')
        step = w/8
        for i, bit in enumerate(order):
            cx, cy = x+step*(i+0.5), y+12
            on = ((value >> bit) & 1) == level
            p.draw.ellipse((cx-10, cy-10, cx+10, cy+10), fill='#f6a533' if on else '#edf0f3', outline='#bd884c')
            p.text(cx-9, cy+15, f'b{bit}', 14, '#68798a')
        y += 54
    return y


def draw_flow(p, section, x, y, w, bottom):
    nodes = {}
    for item in section['nodes']:
        if item['id'] in nodes:
            raise ValueError('Duplicate flow node id.')
        nw, nh = item.get('width', 156), item.get('height', 54)
        cx, cy = x+item['x']*w, y+item['y']*(bottom-y)
        box = (cx-nw/2, cy-nh/2, cx+nw/2, cy+nh/2)
        if box[0] < x or box[2] > x+w or box[1] < y or box[3] > bottom:
            raise ValueError('Flow node exceeds its card.')
        nodes[item['id']] = (item, box, cx, cy)
    for edge in section['edges']:
        _, a, ax, ay = nodes[edge['from']]
        _, b, bx, by = nodes[edge['to']]
        dx, dy = bx-ax, by-ay
        if dx == 0 and dy == 0:
            raise ValueError('Use distinct nodes for loop connectors.')
        sa = min((a[2]-a[0])/2/abs(dx) if dx else math.inf, (a[3]-a[1])/2/abs(dy) if dy else math.inf)
        sb = min((b[2]-b[0])/2/abs(dx) if dx else math.inf, (b[3]-b[1])/2/abs(dy) if dy else math.inf)
        start, end = (ax+dx*sa, ay+dy*sa), (bx-dx*sb, by-dy*sb)
        if sa+sb >= 1:
            raise ValueError('Flow nodes overlap or leave no room for an edge.')
        p.draw.line((start, end), fill=CYAN, width=2)
        angle = math.atan2(dy, dx)
        pts = [end, (end[0]-9*math.cos(angle-.45), end[1]-9*math.sin(angle-.45)), (end[0]-9*math.cos(angle+.45), end[1]-9*math.sin(angle+.45))]
        p.draw.polygon(pts, fill=CYAN)
        if edge.get('label'):
            lx, ly = (start[0]+end[0])/2+5, (start[1]+end[1])/2-21
            label = edge['label']
            if lx+p.length(label, 16) > x+w or ly < y or ly+18 > bottom:
                raise ValueError('Flow edge label exceeds card; adjust node positions.')
            p.text(lx, ly, label, 16, CYAN)
    for item, box, cx, cy in nodes.values():
        p.draw.rounded_rectangle(box, radius=9, fill='#effafb', outline=CYAN, width=2)
        p.paragraph(box[0]+8, box[1]+8, item['label'], box[2]-box[0]-16, box[3]-2, 17)


def draw_sections(p, sections, plan, lines):
    x, y = 24+plan['code_width']+20, 24
    w = WIDTH-x-24
    for section in sections:
        kind, h = section['kind'], section['height']
        if h < 74 or y+h > HEIGHT-24:
            raise ValueError('Teaching cards exceed page; redistribute to more pages.')
        color = {'text': BLUE, 'keys': GREEN, 'leds': ORANGE, 'flow': CYAN}[kind]
        p.card(x, y, w, h, section['title'], color)
        xx, yy, ww, bottom = x+14, y+53, w-28, y+h-10
        if kind == 'text':
            for body in section['items']:
                yy = p.paragraph(xx, yy, body, ww, bottom) + 5
        elif kind == 'keys':
            for item in section['items']:
                lo, hi = item['start'], item.get('end', item['start'])
                if not 1 <= lo <= hi <= len(lines):
                    raise ValueError('Key explanation refers to invalid source lines.')
                quote = ''.join(lines[lo-1:hi]).rstrip('\r\n').expandtabs(4)
                yy = p.paragraph(xx, yy, f'L{lo}–{hi}: '+quote, ww, bottom, 19, GREEN, True)
                yy = p.paragraph(xx, yy, item['explanation'], ww, bottom, 20)+6
        elif kind == 'leds':
            draw_leds(p, section, xx, yy, ww, bottom)
        elif kind == 'flow':
            draw_flow(p, section, xx, yy, ww, bottom)
        y += h+14


def command_plan(args):
    raw, text, lines = source_info(args.source, args.encoding)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    code_width = 1766 if args.code_only else 1100
    p = Painter(args.mono_font, args.cjk_font)
    gutter = max(48, int(p.length(str(len(lines)), 18, True))+14)
    for n, line in enumerate(lines, 1):
        if p.length(line.rstrip('\r\n').expandtabs(4), 22, True) > code_width-gutter-18:
            raise ValueError(f'Line {n} is too wide. Try --code-only or a custom wider layout.')
    minimum = math.ceil(len(lines)/25)
    count = minimum if args.pages is None else args.pages
    if count < minimum or count > len(lines):
        raise ValueError(f'Page count must be between {minimum} and {len(lines)} at this font size.')
    base, extra = divmod(len(lines), count)
    pages, start = [], 1
    for i in range(count):
        end = start+base+(i < extra)-1
        pages.append({'index': i+1, 'start': start, 'end': end})
        start = end+1
    plan = {'source_file': 'source_original.c', 'display_name': args.name or Path(args.source).name,
            'source_sha256': digest(raw), 'encoding': args.encoding, 'line_count': len(lines),
            'bracket_character_counts': {ch: text.count(ch) for ch in '{}()[]'},
            'width': WIDTH, 'height': HEIGHT, 'code_width': code_width,
            'code_only': args.code_only, 'font_size': 22, 'tab_size': 4,
            'mono_font': p.mono_path, 'cjk_font': p.cjk_path, 'pages': pages}
    (out/'source_original.c').write_bytes(raw)
    save_json(out/'plan.json', plan)
    print(json.dumps({'pages': count, 'lines': len(lines), 'plan': str(out/'plan.json')}, ensure_ascii=False))


def command_render(args):
    plan, raw, text, lines = read_plan(args.plan)
    if plan['code_only']:
        lessons = [[] for _ in plan['pages']]
    else:
        if not args.lesson:
            raise ValueError('A full infographic requires --lesson; use --code-only for code panels.')
        lesson = load_json(args.lesson)
        if lesson['source_sha256'] != plan['source_sha256']:
            raise ValueError('Lesson belongs to a different source baseline.')
        lessons = lesson['pages']
        if len(lessons) != len(plan['pages']) or any(not items for items in lessons):
            raise ValueError('Provide non-empty teaching cards for every infographic page.')
    colors = syntax_colors(text)
    offsets, pos = [], 0
    for line in lines:
        offsets.append(pos)
        pos += len(line)
    # Pre-render every page in memory so layout failure does not publish partial pages.
    rendered = []
    for page, sections in zip(plan['pages'], lessons):
        painter = Painter(plan['mono_font'], plan['cjk_font'])
        draw_code(painter, plan, page, lines, colors, offsets)
        if not plan['code_only']:
            draw_sections(painter, sections, plan, lines)
        rendered.append(painter.im)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out/'source_original.c').write_bytes(raw)
    manifest = dict(plan)
    manifest['status'] = 'code-panels' if plan['code_only'] else 'infographics-require-visual-review'
    manifest['verification_scope'] = 'source text, ordered page coverage, image integrity and dimensions; not OCR, semantic validation or visual review'
    manifest['pages'] = []
    for page, im in zip(plan['pages'], rendered):
        name = f"page-{page['index']:03d}"
        image_path, text_path = out/(name+'.png'), out/(name+'.txt')
        im.save(image_path, format='PNG')
        part = ''.join(lines[page['start']-1:page['end']])
        text_path.write_bytes(part.encode('utf-8'))
        manifest['pages'].append(dict(page, image=image_path.name, source_text=text_path.name,
                                      text_sha256=digest(part.encode('utf-8')), image_sha256=digest(image_path.read_bytes())))
    save_json(out/'manifest.json', manifest)
    verify(out/'manifest.json')


def verify(path):
    manifest, raw, text, lines = read_plan(path)
    parts = []
    root = Path(path).parent
    for page in manifest['pages']:
        part_raw = (root/page['source_text']).read_bytes()
        part = part_raw.decode('utf-8')
        expected = ''.join(lines[page['start']-1:page['end']])
        if part != expected or digest(part_raw) != page['text_sha256']:
            raise ValueError('Page source text mismatch.')
        parts.append(part)
        image_path = root/page['image']
        if digest(image_path.read_bytes()) != page['image_sha256']:
            raise ValueError('PNG changed since rendering.')
        with Image.open(image_path) as im:
            if im.size != (WIDTH, HEIGHT):
                raise ValueError('Unexpected image dimensions.')
    if ''.join(parts) != text:
        raise ValueError('Reconstructed source differs from baseline.')
    print('PASS: exact source reconstruction, contiguous coverage, PNG hashes and 1814x867 dimensions. Visual and semantic review remain separate.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('plan')
    p.add_argument('--source', required=True)
    p.add_argument('--encoding', default='utf-8-sig')
    p.add_argument('--out', required=True)
    p.add_argument('--name')
    p.add_argument('--pages', type=int)
    p.add_argument('--code-only', action='store_true')
    p.add_argument('--mono-font')
    p.add_argument('--cjk-font')
    p = commands.add_parser('render')
    p.add_argument('--plan', required=True)
    p.add_argument('--lesson')
    p.add_argument('--out', required=True)
    p = commands.add_parser('verify')
    p.add_argument('--manifest', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'plan':
            command_plan(args)
        elif args.command == 'render':
            command_render(args)
        else:
            verify(args.manifest)
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, f'ERROR: {error}\n')


if __name__ == '__main__':
    main()
