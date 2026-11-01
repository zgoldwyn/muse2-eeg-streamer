# Python Development Setup

This initial package was created and tested with **Python 3.12.14**. It has no third-party runtime dependencies.

## 1. Create a virtual environment

From the repository root, run:

```bash
python3 -m venv .venv
```

## 2. Activate the environment

On macOS or Linux:

```bash
source .venv/bin/activate
```

## 3. Install the package in editable mode

With the virtual environment activated, run:

```bash
python3 -m pip install -e .
```

Editable mode means changes to files in `eeg_app/` are immediately used by Python without reinstalling after every edit.

## 4. Run the smoke tests

The tests use only synthetic data. They do not require a Muse headset, C scanner, live graph, or participant data.

```bash
python3 -m unittest discover -s tests -v
```

## 5. Try a simple import

```bash
python3 -c "from eeg_app import validate_eeg_window; print(validate_eeg_window({'TP9': [1.0], 'AF7': [1.0], 'AF8': [1.0], 'TP10': [1.0]}))"
```

The command should print `1`.