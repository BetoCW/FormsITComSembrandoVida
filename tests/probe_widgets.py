"""Sonda de solo lectura: abre el formulario y describe los widgets reales.
No llena ni envia nada. Uso: python tests/probe_widgets.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright  # noqa: E402

from autoform import guard  # noqa: E402
from autoform.paths import OUTPUT, DATA  # noqa: E402

URL = "https://ee.sembrandodatos.com/x/7kMmQETh"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(DATA / "probe_profile"), headless=True,
                                               service_workers="block", viewport={"width": 1400, "height": 900})
    guard.install(ctx)
    page = ctx.new_page()
    page.goto(URL, wait_until="networkidle", timeout=120000)
    page.wait_for_selector("form.or", timeout=60000)
    page.wait_for_timeout(4000)
    info = page.evaluate("""() => {
      const q = s => document.querySelector(s);
      const out = {};
      out.title = document.title;
      out.bootstrapSelects = [...document.querySelectorAll('.bootstrap-select')].slice(0,3).map(e => e.outerHTML.slice(0,1500));
      out.nBootstrap = document.querySelectorAll('.bootstrap-select').length;
      out.nativeSelectsVisible = [...document.querySelectorAll('select')].filter(s => s.offsetParent).map(s=>s.name).slice(0,20);
      const ruta = q('[name$="/group_eq6af71/ruta"]'); out.ruta = ruta ? ruta.closest('.question').outerHTML.slice(0,2500) : null;
      const geo = q('[name$="Registra_el_centroide_del_predio"]'); out.geo = geo ? geo.closest('.question').outerHTML.slice(0,4000) : null;
      out.repeatButtons = [...document.querySelectorAll('.add-repeat-btn, .repeat-buttons button')].slice(0,4).map(b => b.outerHTML.slice(0,400));
      out.footer = [...document.querySelectorAll('.form-footer button, .form-footer a, #save-draft, .draft')].map(b => b.outerHTML.slice(0,300));
      out.drafts = [...document.querySelectorAll('.record-list, .side-slider, #save-draft')].map(b=>b.outerHTML.slice(0,600));
      out.date = q('[name$="Fecha_de_la_entrevista"]')?.closest('.question').outerHTML.slice(0,1200);
      out.time = q('[name$="Hora_de_inicio_de_la_entrevista"]')?.closest('.question').outerHTML.slice(0,1200);
      out.multi = q('[name$="/up/disp_agua"]')?.closest('.question').outerHTML.slice(0,2500);
      out.pages = !!q('.pages') || document.body.className;
      out.login = !!q('form[action*=login]');
      out.repeatsPresent = [...document.querySelectorAll('.or-repeat')].map(r=>r.getAttribute('name')).slice(0,20);
      return out;
    }""")
    page.screenshot(path=str(OUTPUT / "probe_top.png"))
    (OUTPUT / "probe_widgets.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print("blocked:", guard.blocked_requests)
    ctx.close()
