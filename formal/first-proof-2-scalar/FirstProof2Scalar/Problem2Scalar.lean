import Mathlib

namespace Problem2Scalar

/--
The exponent arithmetic used in the official Proposition 6 calculation:
combining the homogeneity exponent from (19) with the exponent from (20)
produces the s-independent exponent `-n/2` in (17).
-/
theorem exponent_cancellation (s n : ℝ) :
    -(s - (1 / 2 : ℝ)) + (s - (n + 1) / 2) = -n / 2 := by
  ring

/-- At the reference point `s = (n+1)/2`, the exponent in (20) is zero. -/
theorem basepoint_normalization (n : ℝ) :
    ((n + 1) / 2) - (n + 1) / 2 = 0 := by
  ring

/--
Abstract scalar nonvanishing used after the deep representation-theoretic
inputs have supplied a nonzero epsilon factor, a nonzero `|Q|^n` term, and
positive/nonzero Haar volume.
-/
theorem nonzero_scalar_factor
    {epsilonAbs qPower volume : ℝ}
    (hEpsilon : epsilonAbs ≠ 0)
    (hQPower : qPower ≠ 0)
    (hVolume : volume ≠ 0) :
    qPower * volume / epsilonAbs ≠ 0 := by
  exact div_ne_zero (mul_ne_zero hQPower hVolume) hEpsilon

/--
Lean-checked scalar spine corresponding to the three obligations already
checked independently by DSG's Z3 reconstruction audit.

This theorem intentionally does not formalize Kirillov extension,
Godement--Jacquet, Mellin/Fourier analysis, newvector theory, or local
epsilon-factor theory. Those remain explicit external mathematical inputs.
-/
theorem proposition6_scalar_spine
    (s n epsilonAbs qPower volume : ℝ)
    (hEpsilon : epsilonAbs ≠ 0)
    (hQPower : qPower ≠ 0)
    (hVolume : volume ≠ 0) :
    (-(s - (1 / 2 : ℝ)) + (s - (n + 1) / 2) = -n / 2) ∧
      (((n + 1) / 2) - (n + 1) / 2 = 0) ∧
      (qPower * volume / epsilonAbs ≠ 0) := by
  constructor
  · exact exponent_cancellation s n
  constructor
  · exact basepoint_normalization n
  · exact nonzero_scalar_factor hEpsilon hQPower hVolume

end Problem2Scalar
