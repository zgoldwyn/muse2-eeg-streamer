"""Retrieve and verify only the four selected Part 3 public trace examples.

Run from the repo: python -m scratch.samuel.public_trace_examples --download
Raw files and analyst-only plots remain under ignored data/public_muse/.
"""

import argparse
import hashlib
import html
import io
import json
import math
from pathlib import Path, PurePosixPath
import subprocess
import sys
import types
import urllib.request
import zipfile


ROOT = Path("data/public_muse")
RUN = ROOT / "part3-2s"
IMPORTER_REF = "54ad8e17a2e8036f2ad03041df8084f12bfddfee"
ARCHIVES = (("sourcedata", 58088461, 400410665, "_task-BT_acq-Muse2_eeg.edf"),
            ("derivatives", 61393426, 679195668, "_task-BT_acq-BLP_eeg.mat"))


class RangeArchive(io.RawIOBase):
    """Read only ZIP directory/member byte ranges from the public archive."""

    def __init__(self, url, size):
        self.url, self.size, self.position = url, size, 0
        self.cache_start, self.cache = 0, b""

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = offset + (0 if whence == 0 else self.position if whence == 1 else self.size)
        if self.position < 0:
            raise ValueError("Negative ZIP offset")
        return self.position

    def read(self, size=-1):
        if size < 0:
            size = self.size - self.position
        size = min(size, self.size - self.position)
        if size <= 0:
            return b""
        start = self.position
        if not (self.cache_start <= start and start + size <= self.cache_start + len(self.cache)):
            end = min(self.size - 1, start + max(size, 65536) - 1)
            request = urllib.request.Request(f"{self.url}?range={start}-{end}",
                                             headers={"Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(request, timeout=60) as response:
                expected = f"bytes {start}-{end}/{self.size}"
                if response.status != 206 or response.headers.get("Content-Range") != expected:
                    raise IOError("Public archive server did not honor the requested byte range")
                self.cache = response.read()
                self.cache_start = start
                if len(self.cache) != end - start + 1:
                    raise IOError("Incomplete archive byte range")
        offset = start - self.cache_start
        data = self.cache[offset:offset + size]
        self.position += len(data)
        return data


def download_examples(participants):
    manifest_path = ROOT / "trace-inputs/download-manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    manifest = {entry["path"]: entry for entry in manifest}
    for folder, file_id, size, suffix in ARCHIVES:
        url = f"https://ndownloader.figshare.com/files/{file_id}"
        with zipfile.ZipFile(RangeArchive(url, size)) as archive:
            for participant in sorted(participants):
                filename = participant + suffix
                matches = [name for name in archive.namelist()
                           if PurePosixPath(name).name == filename and not name.startswith("__MACOSX/")]
                if len(matches) != 1:
                    raise ValueError(f"Ambiguous/missing archive member: {filename}")
                output = ROOT / "trace-inputs" / folder / participant / filename
                output.parent.mkdir(parents=True, exist_ok=True)
                contents = archive.read(matches[0])  # Verifies member CRC.
                if output.exists() and output.read_bytes() != contents:
                    raise FileExistsError(f"Existing trace input differs: {output}")
                output.write_bytes(contents)
                manifest[str(output)] = {"path": str(output), "archive_url": url, "member": matches[0],
                                         "sha256": hashlib.sha256(contents).hexdigest(), "bytes": len(contents)}
                print(f"Retrieved {filename}: {len(contents):,} bytes", flush=True)
    manifest_path.write_text(json.dumps(list(manifest.values()), indent=2), encoding="utf-8")


def verify_features(actual, exported):
    if set(actual) != set(exported):
        raise ValueError("Recalculated feature keys differ from the export")
    for key, value in actual.items():
        expected = exported[key]
        if value is None or expected is None:
            matches = value is expected
        else:
            matches = math.isclose(value, expected, rel_tol=1e-9, abs_tol=1e-10)
        if not matches:
            raise ValueError(f"Recalculated {key}={value!r} differs from export {expected!r}")


def render_example(window, example, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    channels = ("TP9", "AF7", "AF8", "TP10")
    figure, axes = plt.subplots(4, 1, figsize=(11, 8), sharex=True, sharey=True)
    for channel, axis in zip(channels, axes):
        values = window.channel_samples[channel]
        times = [window.start_time_s + i / window.nominal_sample_rate_hz for i in range(len(values))]
        axis.plot(times, values, color="#214d6a", linewidth=0.9)
        axis.set_ylabel(channel + "\nµV")
        axis.grid(alpha=0.25)
        axis.set_xlim(window.start_time_s, window.end_time_s)
    axes[-1].set_xlabel("Session elapsed time (seconds)")
    decision = "FLAG" if example["proposed_decision"] == "artifact" else "NO FLAG"
    figure.suptitle(f"ANALYST ONLY — {decision} (provisional rule, not human label)\n{window.window_id}", fontsize=11)
    notes = [f"{t['channel']} {t['feature']}: {t['value_uv']:.2f} > {t['threshold_uv']:.2f} µV"
             for t in example["triggers"]]
    if not notes:
        notes = ["Neither configured threshold was exceeded on any channel."]
    notes.append("Unfiltered saved samples; common vertical scale across channels; task/rest is only a weak target.")
    figure.text(0.11, 0.025, "\n".join(notes), fontsize=9, va="bottom")
    figure.tight_layout(rect=(0, 0.04 + 0.023 * len(notes), 1, 0.93))
    figure.savefig(output, dpi=130)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Retrieve the two participants' matching public files.")
    args = parser.parse_args()
    report = json.loads((RUN / "report.json").read_text())
    protected_hashes = {name: hashlib.sha256((RUN / name).read_bytes()).hexdigest()
                        for name in ("settings.json", "predictions.json")}
    candidates = report["trace_candidates"]
    participants = {example["participant_id"] for example in candidates}
    if args.download:
        download_examples(participants)
    source = subprocess.check_output(["git", "show", f"{IMPORTER_REF}:eeg_app/public_muse.py"])
    output = RUN / "analyst-traces"
    output.mkdir(exist_ok=False)
    (output / "importer-source.py").write_bytes(source)
    importer = types.ModuleType("eeg_app._trace_example_importer")
    sys.modules[importer.__name__] = importer
    exec(compile(source, f"{IMPORTER_REF}:public_muse.py", "exec"), importer.__dict__)
    from eeg_app.math_pipeline import extract_window_features
    from eeg_app.math_detector import DetectorSettings, predict_window
    settings = DetectorSettings.from_dict(report["settings"])
    export_path = ROOT / "exports/features-2s.jsonl"
    export_bytes = export_path.read_bytes()
    if hashlib.sha256(export_bytes).hexdigest() != report["source_export_sha256"]:
        raise ValueError("Export differs from the Part 3 run")
    records = {r["window_id"]: r for r in map(json.loads, export_bytes.decode().splitlines())}
    windows = {}
    for participant in sorted(participants):
        edf = ROOT / "trace-inputs/sourcedata" / participant / f"{participant}_task-BT_acq-Muse2_eeg.edf"
        mat = ROOT / "trace-inputs/derivatives" / participant / f"{participant}_task-BT_acq-BLP_eeg.mat"
        imported = importer.import_public_muse_recording(edf, mat, window_length_s=2)
        windows.update({window.window_id: window for window in imported.windows})
    checks = []
    links = []
    for index, example in enumerate(candidates):
        window = windows[example["window_id"]]
        reference = records[window.window_id]
        if (not window.is_valid or window.start_time_s != example["start_time_s"]
                or window.end_time_s != example["end_time_s"] or window.weak_target != reference["weak_target"]):
            raise ValueError(f"Window identity/interval/validity mismatch: {window.window_id}")
        recalculated = extract_window_features(window, flatline_tolerance_uv=0.1)
        verify_features(recalculated["features"], reference["features"])
        prediction = predict_window(recalculated, settings, validity_confirmed=True)
        if prediction["decision"] != example["proposed_decision"] or prediction["triggers"] != example["triggers"]:
            raise ValueError(f"Raw-sample prediction differs from saved result: {window.window_id}")
        filename = f"example-{index + 1:02d}.png"
        render_example(window, example, output / filename)
        checked = {**example, "trace_status": "raw_samples_verified", "plot_file": filename,
                   "features_verified": len(recalculated["features"]), "samples_per_channel": len(window.channel_samples['TP9'])}
        checks.append(checked)
        links.append(f'<h2>{html.escape(window.window_id)}</h2><p>{html.escape(example["split"])} / '
                     f'{html.escape(example["weak_target"])} / proposed {html.escape(prediction["decision"])}</p>'
                     f'<img src="{filename}" alt="Four raw EEG channel traces" style="max-width:100%">')
        print(f"Verified {window.window_id}: 24 features and original decision match", flush=True)
    verification = {"importer_commit": IMPORTER_REF, "importer_source_sha256": hashlib.sha256(source).hexdigest(),
                    "flatline_tolerance_uv": 0.1, "source_export_sha256": report["source_export_sha256"],
                    "unit_convention": "Shared public Muse importer microvolt convention",
                    "relative_tolerance": 1e-9, "absolute_tolerance": 1e-10, "examples": checks,
                    "settings_and_predictions_sha256": protected_hashes}
    (output / "verification.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
    (output / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>Analyst trace examples</title>'
                                       '<h1>Analyst only — contains detector predictions</h1>'
                                       '<p>Do not share with blinded reviewers. These examples are not human artifact labels.</p>'
                                       + "".join(links), encoding="utf-8")
    for name, original_hash in protected_hashes.items():
        if hashlib.sha256((RUN / name).read_bytes()).hexdigest() != original_hash:
            raise AssertionError(f"Part 3 {name} changed during trace verification")
    report["trace_backed_examples_complete"] = True
    report["trace_candidates"] = checks
    report["trace_verification_file"] = "analyst-traces/verification.json"
    (RUN / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Four trace-backed examples saved under {output}")


if __name__ == "__main__":
    main()
