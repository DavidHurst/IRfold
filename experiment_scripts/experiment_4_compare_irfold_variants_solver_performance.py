import random
import sys

from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

DATA_DIR = (Path(__file__).parent.parent / "data").resolve()
EXPERIMENT_4_DATA_DIR = (DATA_DIR / "experiment_4").resolve()

from irfold import (
    IRFoldVal2,
    IRFoldCorX,
)

if __name__ == "__main__":
    n_trials = 10
    for seq_len in (7, 200):
        print(f"Seq. len. :{seq_len}".center(70, "="))
        for _ in range(n_trials):
            seq = "".join(random.choice("ACGU") for _ in range(seq_len))

            fold_params = {
                "sequence": seq,
                "out_dir": EXPERIMENT_4_DATA_DIR,
                "save_performance": True,
            }

            _, _ = IRFoldVal2.fold(**fold_params)

            fold_params.update({"max_n_tuple_sz_to_correct": 2})
            _, _ = IRFoldCorX.fold(**fold_params)

            fold_params.update({"max_n_tuple_sz_to_correct": 3})
            _, _ = IRFoldCorX.fold(**fold_params)

            fold_params.update({"max_n_tuple_sz_to_correct": 4})
            _, _ = IRFoldCorX.fold(**fold_params)
