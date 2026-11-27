# Architecture: Log Scanner

- `cli.py`: argument parsing, dispatch
- `registry.py`: command registry
- `commands/`: one module per command (starting-point handlers)
- `config.py`: TOML configuration
- `logging_setup.py`: logging
