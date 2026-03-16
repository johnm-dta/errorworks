# Installation

## Prerequisites

- **Python 3.12** or later

## Install from PyPI

=== "pip"

    ```bash
    pip install errorworks
    ```

=== "uv"

    ```bash
    uv add errorworks
    ```

## Verify installation

After installing, confirm the CLI is available:

```bash
chaosllm --help
```

You should see usage information for the ChaosLLM server. You can also check
ChaosWeb:

```bash
chaosweb --help
```

## Development install

To work on errorworks itself or run the test suite:

```bash
git clone https://github.com/johnm-dta/errorworks.git
cd errorworks
uv sync --all-extras
```

This installs all dependencies including test and development extras. Run the
test suite to verify everything is working:

```bash
uv run pytest
```
