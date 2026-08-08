import Mathlib.Analysis.Fourier.ZMod

namespace Problem2FiniteFourier

open AddChar

variable {N : ℕ} [NeZero N]

/--
Finite conductor Fourier orthogonality on `ZMod N`.

The discrete Fourier transform of the constant-one function is supported only
at zero frequency. This is the finite-quotient analogue of the
characteristic-function / annihilator-support calculation that appears in
the conductor-level Fourier step of First Proof #2.
-/
theorem dft_const_one_support (k : ZMod N) :
    ZMod.dft (fun _ : ZMod N ↦ (1 : ℂ)) k = if k = 0 then (N : ℂ) else 0 := by
  rw [ZMod.dft_apply]
  simp only [smul_eq_mul, mul_one]
  have h := AddChar.sum_mulShift (R := ZMod N) (R' := ℂ) (-k)
    (ZMod.isPrimitive_stdAddChar N)
  simpa [mul_neg, neg_eq_zero] using h

/-- At every nonzero frequency, the finite conductor Fourier sum vanishes. -/
theorem dft_const_one_eq_zero_of_ne_zero (k : ZMod N) (hk : k ≠ 0) :
    ZMod.dft (fun _ : ZMod N ↦ (1 : ℂ)) k = 0 := by
  rw [dft_const_one_support]
  simp [hk]

/-- At zero frequency, the finite conductor Fourier sum equals the conductor quotient size. -/
theorem dft_const_one_zero :
    ZMod.dft (fun _ : ZMod N ↦ (1 : ℂ)) 0 = (N : ℂ) := by
  rw [dft_const_one_support]
  simp

end Problem2FiniteFourier
