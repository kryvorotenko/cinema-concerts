"""Core O2.3: 1/2/4 processes x3, profile, one-factor repeat."""
import cProfile
import io
import json
import statistics
import sys
from pathlib import Path
from pstats import Stats

sys.path.insert(0, "/srv" if Path("/srv/app").exists() else str(Path(__file__).resolve().parents[1] / "dpc" / "api"))
from app.compute import calculate  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3_000_000
TOLERANCE = 0.02


def run(chunks):
    series = {}
    for workers in (1, 2, 4):
        samples = []
        for _ in range(3):
            result = calculate(0, 90, N, workers, "midpoint", chunks)
            assert result["error"] < TOLERANCE, result
            samples.append(result["time_s"])
        series[workers] = {"samples_s": [round(x, 4) for x in samples],
                           "median_s": statistics.median(samples),
                           "spread_s": max(samples) - min(samples),
                           "error": result["error"]}
    t1 = series[1]["median_s"]
    for workers in (1, 2, 4):
        series[workers]["speedup"] = t1 / series[workers]["median_s"]
        series[workers]["efficiency"] = series[workers]["speedup"] / workers
    return series


def main():
    baseline = run(4)
    assert baseline[1]["median_s"] >= 1, baseline
    profiler = cProfile.Profile()
    profiler.enable()
    calculate(0, 90, N, 4, "midpoint", 4)
    profiler.disable()
    output = io.StringIO()
    Stats(profiler, stream=output).sort_stats("cumtime").print_stats(12)
    changed = run(1)
    print(json.dumps({"n": N, "a": 0, "b": 90, "method": "midpoint", "order": 2,
                      "tolerance_abs": TOLERANCE, "baseline_chunks_per_worker": 4,
                      "baseline": baseline, "changed_chunks_per_worker": 1,
                      "changed": changed, "profile": output.getvalue()}, indent=2))


if __name__ == "__main__":
    main()
