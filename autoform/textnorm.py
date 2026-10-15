import re
import unicodedata


def norm(s) -> str:
    """Mayusculas, sin acentos, espacios colapsados (para comparar textos)."""
    if s is None:
        return ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("×", "X")
    return re.sub(r"\s+", " ", s).strip().upper()


def norm_loose(s) -> str:
    """Como norm() pero quitando puntuacion (para etiquetas de opciones)."""
    return re.sub(r"[^A-Z0-9% ]+", "", norm(s)).replace("  ", " ").strip()
