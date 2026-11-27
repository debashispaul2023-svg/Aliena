_COMMANDS = {}


def register(name, help_text):
    """Decorator registering a command handler under a unique name."""
    def decorator(func):
        if name in _COMMANDS:
            raise ValueError(f"command already registered: {name}")
        _COMMANDS[name] = (func, help_text)
        return func
    return decorator


def commands():
    return dict(_COMMANDS)
