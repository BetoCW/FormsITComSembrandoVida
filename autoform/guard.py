"""Guardias contra el envio del formulario.

La app NUNCA envia. Hay tres capas:
1. Red: toda peticion POST/PUT/PATCH/DELETE se aborta, salvo la descarga del
   formulario (/transform/) y el login manual (/login).
2. DOM: el boton "Enviar" (#submit-form) se deshabilita y se oculta por script.
3. Codigo: `safe_click` lanza SubmitForbidden si el selector apunta al boton
   de envio.
"""
from __future__ import annotations

import re

SUBMIT_SELECTORS = ("#submit-form", "button.submit", "[data-i18n='formfooter.submit.btn']")
_ALLOWED_WRITE = re.compile(r"/(transform|login|authenticate)(/|$|\?)")


class SubmitForbidden(RuntimeError):
    pass


blocked_requests: list[str] = []


def _route_handler(route, request):
    if request.method.upper() in ("POST", "PUT", "PATCH", "DELETE") and not _ALLOWED_WRITE.search(request.url):
        blocked_requests.append(f"{request.method} {request.url}")
        return route.abort("blockedbyclient")
    return route.continue_()


def install(context) -> None:
    """Instala las guardias en un BrowserContext de Playwright."""
    context.route("**/*", _route_handler)
    context.add_init_script("""
(() => {
  const kill = () => document.querySelectorAll('#submit-form, button.submit').forEach(b => {
      b.disabled = true; b.style.display = 'none'; b.setAttribute('data-autoform-blocked', '1');
  });
  document.addEventListener('DOMContentLoaded', kill);
  new MutationObserver(kill).observe(document, {subtree: true, childList: true});
  // si algo intenta enviar el <form>, se cancela
  document.addEventListener('submit', e => {
      if (e.target && e.target.matches && e.target.matches('form.or')) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
})();
""")


def check_selector(selector: str) -> None:
    s = selector.lower()
    if any(x in s for x in ("submit", "enviar")):
        raise SubmitForbidden(f"Prohibido interactuar con el boton de envio: {selector!r}")


def safe_click(locator_or_page, selector: str | None = None, **kw):
    """Click que se niega a tocar el boton de envio."""
    if selector is not None:
        check_selector(selector)
        loc = locator_or_page.locator(selector)
    else:
        loc = locator_or_page
    el_id = (loc.first.get_attribute("id") or "") + " " + (loc.first.get_attribute("class") or "")
    txt = (loc.first.inner_text(timeout=2000) or "") if loc.first.is_visible() else ""
    if "submit" in el_id.lower() or txt.strip().lower() in ("enviar", "submit"):
        raise SubmitForbidden(f"Prohibido presionar Enviar ({el_id.strip()!r})")
    return loc.first.click(**kw)
