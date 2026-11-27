import argparse
import json
from pathlib import Path

from geostart.closed_coffee import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Сравнение закрывшихся и работающих кофеен Москвы")
    parser.add_argument("--historical", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--scores", type=Path, default=Path("data/scores/moscow_coffee.parquet"))
    parser.add_argument("--output-dir", type=Path, default=Path(".team/out/c10"))
    arguments = parser.parse_args()
    print(
        json.dumps(
            run(arguments.historical, arguments.current, arguments.scores, arguments.output_dir),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
