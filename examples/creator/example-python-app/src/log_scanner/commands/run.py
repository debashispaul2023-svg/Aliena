from ..registry import register


@register('run', 'Run the tool')
def run(text: str = "", upper: bool = False) -> str:
    """Starting-point handler: formats the input. Replace with real logic."""
    result = f"[run] {text}".strip()
    return result.upper() if upper else result
