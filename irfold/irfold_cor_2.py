"""Deprecated class, used for testing."""
__all__ = ["IRFoldCor2"]

import itertools
import re

from tqdm import tqdm

from irfold import IRFoldVal2
from typing import Tuple, List
from ortools.sat.python.cp_model import CpModel, IntVar, LinearExpr
from irfold.util import (
    ir_has_valid_gap_size,
    IR,
    irs_to_dot_bracket,
    calc_free_energy,
    irs_incompatible,
)


class IRFoldCor2(IRFoldVal2):
    """Extends IRFold2 by adding solver variables to correct for the additivity of free energy IRs not holding
    consistently"""

    @staticmethod
    def _get_cp_model(
        ir_list: List[IR],
        seq_len: int,
        sequence: str,
        out_dir: str,
        seq_name: str,
        max_n_tuple_sz_to_correct: int = 3,
    ) -> Tuple[CpModel, List[IntVar]]:
        model: CpModel = CpModel()
        n_irs: int = len(ir_list)

        # Create binary indicator variables for IRs
        invalid_gap_ir_idxs: List[int] = [
            i for i in range(n_irs) if not ir_has_valid_gap_size(ir_list[i])
        ]
        ir_indicator_variables = [
            model.NewIntVar(0, 1, f"ir_{i}")
            for i in range(n_irs)
            if i not in invalid_gap_ir_idxs
        ]

        # If 1 or fewer variables, trivial or impossible optimisation problem, will be trivially handled by solver
        if len(ir_indicator_variables) <= 1:
            return model, ir_indicator_variables

        unique_possible_idx_pairs: List[Tuple[int, int]] = list(
            itertools.combinations([i for i in range(n_irs)], 2)
        )
        valid_idx_pairs: List[Tuple[int, int]] = [
            pair
            for pair in unique_possible_idx_pairs
            if pair[0] not in invalid_gap_ir_idxs and pair[1] not in invalid_gap_ir_idxs
        ]
        valid_ir_pairs: List[Tuple[IR, IR]] = [
            (ir_list[i], ir_list[j]) for i, j in valid_idx_pairs
        ]

        incompatible_ir_pair_idxs: List[Tuple[int, int]] = [
            idx_pair
            for ir_pair, idx_pair in zip(valid_ir_pairs, valid_idx_pairs)
            if irs_incompatible([ir_pair[0], ir_pair[1]])
        ]

        # Add XOR between IRs that are incompatible
        for ir_a_idx, ir_b_idx in incompatible_ir_pair_idxs:
            # Search required as some IR variables might not have had variables created as they were invalid so
            # list ordering of variables cannot be relied upon
            ir_a_var: IntVar = [
                var for var in ir_indicator_variables if str(ir_a_idx) in var.Name()
            ][0]
            ir_b_var: IntVar = [
                var for var in ir_indicator_variables if str(ir_b_idx) in var.Name()
            ][0]

            model.Add(ir_a_var + ir_b_var <= 1)

        # Obtain free energies of the IRs that are valid, they comprise the coefficients for ir vars
        ir_indicator_var_coeffs: List[int] = []
        for var in ir_indicator_variables:
            ir_idx: int = int(re.findall(r"-?\d+\.?\d*", var.Name())[0])
            ir_db_repr: str = irs_to_dot_bracket([ir_list[ir_idx]], seq_len)
            ir_free_energy: float = calc_free_energy(
                ir_db_repr, sequence, out_dir, seq_name
            )
            ir_indicator_var_coeffs.append(round(ir_free_energy))

        # Add variable for each IR pair that forms an invalid loop which corrects the pairs additive free energy
        (
            ir_pair_fe_correction_indicator_vars,
            ir_pair_fe_correction_indicator_vars_coeffs,
        ) = IRFoldCor2.__generate_ir_pair_correction_variables_w_coeffs(
            model,
            ir_list,
            seq_len,
            sequence,
            out_dir,
            seq_name,
            valid_idx_pairs,
            valid_ir_pairs,
        )

        # Add constraints that only activate correction variables when the IR pair they represent is active
        for correction_var in ir_pair_fe_correction_indicator_vars:
            # print(f"Adding activate {correction_var.Name()}")
            ir_idxs: List[str] = re.findall(r"-?\d+\.?\d*", correction_var.Name())
            ir_a_idx: int = int(ir_idxs[0])
            ir_b_idx: int = int(ir_idxs[1])

            ir_a_var: IntVar = [
                var for var in ir_indicator_variables if str(ir_a_idx) in var.Name()
            ][0]
            ir_b_var: IntVar = [
                var for var in ir_indicator_variables if str(ir_b_idx) in var.Name()
            ][0]

            # Variable tracks whether both ir_a and ir_b are both 1 i.e. active
            ir_pair_is_active_var = model.NewBoolVar(
                f"ir_{ir_a_idx}_ir_{ir_b_idx}_both_1"
            )
            model.Add(ir_a_var + ir_b_var == 2).OnlyEnforceIf(ir_pair_is_active_var)
            model.Add(ir_a_var + ir_b_var != 2).OnlyEnforceIf(
                ir_pair_is_active_var.Not()
            )

            # Set ir pair's correction variable to 1 only if both ir variables are active, 0 otherwise
            model.Add(correction_var == 1).OnlyEnforceIf(ir_pair_is_active_var)
            model.Add(correction_var == 0).OnlyEnforceIf(ir_pair_is_active_var.Not())

        # Define objective function
        ir_indicators_expr = LinearExpr.WeightedSum(
            ir_indicator_variables, ir_indicator_var_coeffs
        )
        ir_pair_fe_correction_indicators_expr = LinearExpr.WeightedSum(
            ir_pair_fe_correction_indicator_vars,
            ir_pair_fe_correction_indicator_vars_coeffs,
        )
        model.Minimize(
            LinearExpr.Sum([ir_indicators_expr, ir_pair_fe_correction_indicators_expr])
        )

        return model, ir_indicator_variables + ir_pair_fe_correction_indicator_vars

    @staticmethod
    def __generate_ir_pair_correction_variables_w_coeffs(
        model: CpModel,
        ir_list: List[IR],
        seq_len: int,
        sequence: str,
        out_dir: str,
        seq_name: str,
        valid_idx_pairs: List[Tuple[int, int]],
        valid_ir_pairs: List[Tuple[IR, IR]],
    ) -> Tuple[List[IntVar], List[int]]:
        ir_pair_fe_correction_indicator_vars = []
        ir_pair_fe_correction_indicator_vars_coeffs = []
        for (ir_a_idx, ir_b_idx), (ir_a, ir_b) in tqdm(
            zip(valid_idx_pairs, valid_ir_pairs),
            desc="Generating pair correction variables",
        ):
            if irs_incompatible([ir_a, ir_b]):
                continue

            ir_a_db_repr: str = irs_to_dot_bracket([ir_list[ir_a_idx]], seq_len)
            ir_b_db_repr: str = irs_to_dot_bracket([ir_list[ir_b_idx]], seq_len)
            ir_pair_db_repr: str = irs_to_dot_bracket(
                [ir_list[ir_a_idx], ir_list[ir_b_idx]], seq_len
            )

            ir_pair_additive_free_energy: float = round(
                sum(
                    [
                        calc_free_energy(ir_db_repr, sequence, out_dir, seq_name)
                        for ir_db_repr in [ir_a_db_repr, ir_b_db_repr]
                    ]
                ),
                4,
            )
            ir_pair_db_repr_free_energy: float = round(
                calc_free_energy(ir_pair_db_repr, sequence, out_dir, seq_name), 4
            )

            free_energy_difference: float = round(
                ir_pair_additive_free_energy - ir_pair_db_repr_free_energy, 4
            )

            # If additivity assumption does not hold, add correction variable
            # ToDo: Use experiment 1 data to more efficiently add correction variables e.g. those pairs that form invalid loops
            if abs(free_energy_difference) > 0:
                correction_var = model.NewIntVar(
                    0, 1, f"ir_{ir_a_idx}_ir_{ir_b_idx}_fe_corrector"
                )
                ir_pair_fe_correction_indicator_vars.append(correction_var)

                if ir_pair_additive_free_energy > ir_pair_db_repr_free_energy:

                    ir_pair_fe_correction_indicator_vars_coeffs.append(
                        -round(abs(free_energy_difference))
                    )
                else:
                    ir_pair_fe_correction_indicator_vars_coeffs.append(
                        round(abs(free_energy_difference))
                    )

        return (
            ir_pair_fe_correction_indicator_vars,
            ir_pair_fe_correction_indicator_vars_coeffs,
        )
