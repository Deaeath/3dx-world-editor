// Virtualized tree of world nodes: only the visible rows exist in the DOM, so
// worlds with tens of thousands of objects scroll without lag.
const ROW = 22;

export class Outliner {
  constructor(container, opts) {
    this.el = container;
    this.o = opts;
    this.filter = '';
    this.rows = [];
    this.spacer = document.createElement('div');
    this.spacer.className = 'ol-spacer';
    this.layer = document.createElement('div');
    this.layer.className = 'ol-layer';
    this.el.append(this.spacer, this.layer);
    this.el.addEventListener('scroll', () => this.draw());
    new ResizeObserver(() => this.draw()).observe(this.el);
  }

  setFilter(q) { this.filter = q.trim().toLowerCase(); this.refresh(true); }

  matches() {
    const root = this.o.getRoot();
    if (!root || !this.filter) return [];
    const out = [];
    for (const n of root.walk()) if (n !== root && !n.isGroup && this.test(n)) out.push(n);
    return out;
  }
  test(n) {
    const q = this.filter;
    return (n.obj.n || '').toLowerCase().includes(q) || (n.obj.m || '').toLowerCase().includes(q);
  }

  // rebuild the flat row list (cheap: only walks expanded groups)
  refresh(scrollTop = false) {
    const root = this.o.getRoot();
    this.rows = [];
    if (root) {
      if (this.filter) {
        for (const n of root.walk()) if (n !== root && !n.isGroup && this.test(n)) this.rows.push({ n, d: 0 });
      } else {
        const add = (node, d) => {
          for (const c of node.children) {
            this.rows.push({ n: c, d });
            if (c.isGroup && c.expanded) add(c, d + 1);
          }
        };
        add(root, 0);
      }
    }
    this.spacer.style.height = this.rows.length * ROW + 'px';
    if (scrollTop) this.el.scrollTop = 0;
    this.draw();
  }

  reveal(node) {
    let p = node.parent;
    while (p && p.parent) { p.expanded = true; p = p.parent; }
    this.refresh();
    const i = this.rows.findIndex(r => r.n === node);
    if (i < 0) return;
    const top = i * ROW, h = this.el.clientHeight;
    if (top < this.el.scrollTop || top > this.el.scrollTop + h - ROW) this.el.scrollTop = top - h / 3;
    this.draw();
  }

  draw() {
    const h = this.el.clientHeight, st = this.el.scrollTop;
    const first = Math.max(0, Math.floor(st / ROW) - 5), last = Math.min(this.rows.length, Math.ceil((st + h) / ROW) + 5);
    this.layer.style.transform = `translateY(${first * ROW}px)`;
    const frag = document.createDocumentFragment();
    for (let i = first; i < last; i++) frag.append(this.row(this.rows[i]));
    this.layer.replaceChildren(frag);
  }

  row({ n, d }) {
    const r = document.createElement('div');
    const selState = this.o.isSelected(n);
    r.className = 'ol-row' + (selState === 'sel' ? ' sel' : selState === 'in' ? ' insel' : '') + (n.hidden ? ' hidden' : '');
    r.style.paddingLeft = 6 + d * 14 + 'px';
    const tw = document.createElement('span');
    tw.className = 'tw';
    if (n.isGroup) {
      tw.textContent = n.expanded ? '▾' : '▸';
      tw.onclick = e => { e.stopPropagation(); n.expanded = !n.expanded; this.refresh(); };
    }
    r.append(tw);
    const lab = this.o.label(n);
    if (lab.color) { const s = document.createElement('span'); s.className = 'cs'; s.style.background = lab.color; r.append(s); }
    const t = document.createElement('span'); t.className = 'nm' + (lab.proxy ? ' proxy' : '') + (n.isGroup ? ' grp' : ''); t.textContent = lab.text;
    const sub = document.createElement('span'); sub.className = 'sub'; sub.textContent = lab.sub;
    const eye = document.createElement('span'); eye.className = 'eye'; eye.textContent = n.hidden ? '◌' : '●'; eye.title = 'Hide / show';
    eye.onclick = e => { e.stopPropagation(); this.o.onToggleHide(n); };
    r.append(t, sub, eye);
    r.onclick = e => this.o.onSelect(n, e);
    r.ondblclick = () => this.o.onFocus(n);
    return r;
  }
}
