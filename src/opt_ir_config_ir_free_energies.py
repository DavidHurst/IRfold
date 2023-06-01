from IUPACpal import find_inverted_repeats, config
import re
import matplotlib.pyplot as plt
import forgi.visual.mplotlib as fvm
import forgi.graph.bulge_graph as fgb
import forgi
import itertools
import RNA
import pandas as pd
from ortools.linear_solver import pywraplp
import random


def shape_state_to_dot_bracket(active_irs, all_irs, seq_len):
    """
    active_irs is list of indicies. A subset of all indices in all_irs, those
    indices that represent an IR being included in the shape e.g. [0,2,5]
    """
    paired_bases = ["." for _ in range(seq_len)]  # Initially none paired

    for ir_idx in active_irs:
        # print(f'    Adding IR#{ir_idx} -> {all_irs[ir_idx]}')
        ir = all_irs[ir_idx]
        lhs = ir[0]
        rhs = ir[1]

        for i in range(lhs[0] - 1, lhs[1]):
            paired_bases[i] = "("

        for j in range(rhs[0] - 1, rhs[1]):
            paired_bases[j] = ")"

    return "".join(paired_bases)


def eval_free_energy(dot_brk_repr, seq, out_fname):
    with open(f"data/{out_fname}.txt", "a") as out_file:
        out_file.write(f"Evaluating shape:\n")
        for i in range(len(dot_brk_repr)):
            out_file.write(f"{i+1:<3}")
        out_file.write("\n")
        for b in dot_brk_repr:
            out_file.write(f"{b:<3}")
        out_file.write("\n")

        free_energy = RNA.eval_structure_simple(seq, dot_brk_repr, 1, out_file)
        out_file.write(f"\n\n")

    return free_energy


def irs_incompatible(ir_a, ir_b):
    # print(f'  ir_a = {ir_a}')
    # print(f'  ir_b = {ir_b}')

    paired_base_idxs_a = [idx for idx in range(ir_a[0][0], ir_a[0][1] + 1)] + [
        idx for idx in range(ir_a[1][0], ir_a[1][1] + 1)
    ]
    paired_base_idxs_b = [idx for idx in range(ir_b[0][0], ir_b[0][1] + 1)] + [
        idx for idx in range(ir_b[1][0], ir_b[1][1] + 1)
    ]
    # print(f'  Paired base idxs in ir_a = {paired_base_idxs_a}')
    # print(f'  Paired base idxs in ir_b = {paired_base_idxs_b}')
    any_overlapping_pairings = any(
        [ir_b_bases in paired_base_idxs_a for ir_b_bases in paired_base_idxs_b]
    )

    return any_overlapping_pairings


def main():
    # print(help(RNA))
    # print(help(rnastructure))
    # print(help(contrafold))
    # for x in dir(RNA):
    #     print(x)
    # exit()
    random.seed()

    our_shape_preds = []
    our_preds_mfes = []
    rnalib_shape_preds = []
    rnalib_preds_mfes = []
    sequence_lengths = []
    num_irs = []
    num_variables = []
    num_constraints = []
    num_solver_iters = []
    num_b_n_b_nodes = []
    solution_time_msecs = []

    # Generate random RNA sequence and write it to file for IUPACpal to use
    print_info = False
    for s_len in list(range(10, 150, 5)):
        print(f'Sequence length = {s_len}')
        for i in range(40):
            print(f'  Iteration: {i}')
            seq_len = s_len
            seq = "".join(random.choice("ACGU") for _ in range(seq_len))
            seq_fname = "rand_rna"
            seq_energies_fname = f"{seq_fname}_energies"

            with open(f"data/{seq_fname}.fasta", "w") as file:
                file.write(">rand_rna\n")
                file.write(seq)

            if print_info:
                print(f"Seq.: {seq}")
                print(f"Seq. len.: {seq_len}")
                print(f"Seq. file name: {seq_fname}")

            # Prep free energy values file
            with open(f"data/{seq_energies_fname}.txt", "w") as file:
                file.write(f"Energies for seq: {seq}".center(50, "="))
                file.write("\n\n")

            # Find inverted repeats in given sequence
            inverted_repeats = find_inverted_repeats(
                input_file="data/rand_rna.fasta",
                seq_name="rand_rna",
                min_len=2,
                max_len=seq_len,
                max_gap=seq_len-1,
                mismatches=0,
                output_file=f"data/{seq_fname}_irs.txt",
            )

            n_irs = len(inverted_repeats)

            if print_info:
                print(f"Found IRs ({n_irs})".center(50, "="))
                for i, ir in enumerate(inverted_repeats):
                    print(f"IR#{i:<2}: {ir}")

            # Compute free energy of each IR
            free_energies = []
            for i in range(n_irs):
                dot_b = shape_state_to_dot_bracket([i], inverted_repeats, seq_len)
                fe = eval_free_energy(dot_b, seq, seq_energies_fname)
                free_energies.append(fe)

            if print_info:
                print("Free energies of IRs".center(50, "="))
                for i, e_ir in zip([_ for _ in range(n_irs)], free_energies):
                    print(f"IR#{i:<2} = {e_ir:.4f}")

            # Instantiate MIP solver with SCIP backend
            solver = pywraplp.Solver.CreateSolver("SCIP")
            if not solver:
                print("Failed to init solver.")
                return

            # Define variables: binary indicators for each IR
            # (hand crafted for above IUPACpal settings and input for now)
            if print_info:
                print("Variables".center(50, "="))
            variables = []
            for i in range(n_irs):
                variables.append(solver.IntVar(0, 1, f"ir_{i}"))

            # Add varibale which represents how many irs are included, n_irs - # included. Minimse this
            # included_irs_var = solver.IntVar(0, infinity, 'irs_included')

            if print_info:
                print(f"Num variables: {solver.NumVariables()}")
                # for i, v in enumerate(variables):
                #     print(f'Var #{i}: {v.name()}')

                # Define constraints: XOR between those IRs that match the same bases
                print("Constraints".center(50, "="))

            # Find all pairs of IRs that are incompatible with each other i.e.
            # those that match the same bases
            unique_ir_pairs = itertools.combinations([_ for _ in range(n_irs)], 2)
            incompatible_ir_pairs = []
            n_unique_ir_pairs = 0
            for pair in unique_ir_pairs:
                n_unique_ir_pairs += 1
                ir_a = inverted_repeats[pair[0]]
                ir_b = inverted_repeats[pair[1]]
                incompatible = irs_incompatible(ir_a, ir_b)
                if incompatible:
                    incompatible_ir_pairs.append(pair)

            # Add an XOR for all incompatiable IR pairs i.e. ir_i + ir_j <= 1
            for inc_pair in incompatible_ir_pairs:
                ir_a_idx = inc_pair[0]
                ir_b_idx = inc_pair[1]

                # constraint = solver.Constraint(0, 1, f"ir_{ir_a_idx} XOR ir_{ir_b_idx}")
                # constraint.SetCoefficient(variables[ir_a_idx], 1)
                # constraint.SetCoefficient(variables[ir_b_idx], 1)
                solver.Add(variables[ir_a_idx] + variables[ir_b_idx] <= 1)

            # Add constraint that at least one IR is included in any solution
            one_or_more_irs_constr = solver.Add(solver.Sum(variables) >= 1)

            if print_info:
                # print(f'Num possible IR combinations = {n_unique_ir_pairs}, num valid = {n_unique_ir_pairs - len(list(incompatible_ir_pairs))}')
                print(f"Num constraints: {solver.NumConstraints()}")

            # Objective: free energy of current configuration of binary indicators
            # print("Objective".center(50, "="))
            obj_fn = solver.Objective()
            for i in range(n_irs):
                obj_fn.SetCoefficient(variables[i], free_energies[i])
            obj_fn.SetMinimization()

            if print_info:
                print("Solver Solution".center(50, "="))
            status = solver.Solve()

            if status == pywraplp.Solver.OPTIMAL:
                if print_info:
                    print("Objective value =", solver.Objective().Value())
                    for v in variables:
                        print(f'Var. "{v.name()}" opt. val. = {v.solution_value()}')
                    print("Problem solved in %f milliseconds" % solver.wall_time())
                    print("Problem solved in %d iterations" % solver.iterations())
                    print("Problem solved in %d branch-and-bound nodes" % solver.nodes())

                    print()

                    print(f"Dot Bracket: {solution_dot_brk_repr}")
                    print(f"MFE: {solver.Objective().Value():.4f}")

                ir_vars = [int(v.solution_value()) for v in variables]
                included_irs = [i for i, ir_v in enumerate(ir_vars) if ir_v == 1]
                solution_dot_brk_repr = shape_state_to_dot_bracket(
                    included_irs, inverted_repeats, seq_len
                )
                solution_mfe = solver.Objective().Value()
            else:
                if print_info:
                    print("The problem does not have an optimal solution.")
                solution_dot_brk_repr = '-'
                solution_mfe = 10000000

            # RNAlib pred
            opt_dot_brkt = str()
            out = RNA.fold(seq, opt_dot_brkt)
            if print_info:
                print("RNAlib Solution".center(50, "="))
                print(f"Dot Bracket: {out[0]}")
                print(f"MFE: {out[1]:.4f}")

            our_shape_preds.append(solution_dot_brk_repr)
            our_preds_mfes.append(solution_mfe)
            rnalib_shape_preds.append(out[0])
            rnalib_preds_mfes.append(out[1])
            sequence_lengths.append(seq_len)
            num_irs.append(n_irs)
            num_variables.append(solver.NumVariables())
            num_constraints.append(solver.NumConstraints())
            num_solver_iters.append(solver.iterations())
            num_b_n_b_nodes.append(solver.nodes())
            solution_time_msecs.append(solver.wall_time())

    results_df = pd.DataFrame(
        {
            "our_shape_preds": our_shape_preds,
            "our_preds_mfes": our_preds_mfes,
            "rnalib_shape_preds": rnalib_shape_preds,
            "rnalib_preds_mfes": rnalib_preds_mfes,
            "seq_length": sequence_lengths,
            "num_irs": num_irs,
            "num_variables": num_variables,
            "num_constraints": num_constraints,
            "num_solver_iters": num_solver_iters,
            "num_b_n_b_nodes": num_b_n_b_nodes,
            "solution_time_msecs": solution_time_msecs
        }
    )
    results_df.to_csv("performance.csv")


if __name__ == "__main__":
    main()