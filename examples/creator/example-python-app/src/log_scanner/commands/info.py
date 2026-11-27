from ..registry import register


@register('info', 'Show information')
def run(text: str = "", upper: bool = False) -> str:
    """Starting-point handler: formats the input. Replace with real logic."""
    result = f"[info] {text}".strip()
    return result.upper() if upper else result
